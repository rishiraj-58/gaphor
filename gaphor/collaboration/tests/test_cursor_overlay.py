"""Tests for CursorOverlayPainter and cursor drawing helpers."""

import time
import math
import pytest

from gaphor.collaboration.cursor_overlay import (
    STALE_TIMEOUT_S,
    CursorOverlayPainter,
    _parse_css_rgb,
    _rounded_rect,
)


# ---------------------------------------------------------------------------
# _parse_css_rgb
# ---------------------------------------------------------------------------

class TestParseCssRgb:
    def test_valid_colour(self):
        r, g, b = _parse_css_rgb("rgb(56, 135, 235)")
        assert r == pytest.approx(56 / 255.0)
        assert g == pytest.approx(135 / 255.0)
        assert b == pytest.approx(235 / 255.0)

    def test_zero_components(self):
        r, g, b = _parse_css_rgb("rgb(0, 0, 0)")
        assert r == pytest.approx(0.0)
        assert g == pytest.approx(0.0)
        assert b == pytest.approx(0.0)

    def test_max_components(self):
        r, g, b = _parse_css_rgb("rgb(255, 255, 255)")
        assert r == pytest.approx(1.0)
        assert g == pytest.approx(1.0)
        assert b == pytest.approx(1.0)

    def test_components_in_range(self):
        for css in ["rgb(0, 0, 0)", "rgb(128, 64, 32)", "rgb(255, 255, 255)"]:
            r, g, b = _parse_css_rgb(css)
            for c in (r, g, b):
                assert 0.0 <= c <= 1.0

    def test_malformed_returns_grey(self):
        r, g, b = _parse_css_rgb("not-a-colour")
        assert r == pytest.approx(0.5)
        assert g == pytest.approx(0.5)
        assert b == pytest.approx(0.5)

    def test_empty_string_returns_grey(self):
        r, g, b = _parse_css_rgb("")
        assert (r, g, b) == (0.5, 0.5, 0.5)


# ---------------------------------------------------------------------------
# Stub Cairo context for overlay painting tests
# ---------------------------------------------------------------------------

class _RecordingCairo:
    """Minimal Cairo context stub that records all draw calls."""

    def __init__(self):
        self.calls = []
        self._source = None
        self._line_width = None

    def save(self):           self.calls.append(("save",))
    def restore(self):        self.calls.append(("restore",))
    def translate(self, x, y): self.calls.append(("translate", x, y))
    def new_path(self):       self.calls.append(("new_path",))
    def move_to(self, x, y): self.calls.append(("move_to", x, y))
    def line_to(self, x, y): self.calls.append(("line_to", x, y))
    def arc(self, cx, cy, r, a1, a2): self.calls.append(("arc", cx, cy, r, a1, a2))
    def close_path(self):     self.calls.append(("close_path",))
    def fill_preserve(self):  self.calls.append(("fill_preserve",))
    def fill(self):           self.calls.append(("fill",))
    def stroke(self):         self.calls.append(("stroke",))
    def show_text(self, t):   self.calls.append(("show_text", t))

    def set_source_rgba(self, r, g, b, a):
        self._source = (r, g, b, a)
        self.calls.append(("set_source_rgba", r, g, b, a))

    def set_line_width(self, w):
        self._line_width = w
        self.calls.append(("set_line_width", w))

    def set_font_size(self, s):
        self.calls.append(("set_font_size", s))

    def text_extents(self, t):
        """Return a stub with enough attributes for badge drawing."""
        class _Extents:
            width = len(t) * 7.0
            height = 12.0
            x_bearing = 0.0
            y_bearing = -9.0
        return _Extents()


# ---------------------------------------------------------------------------
# CursorOverlayPainter
# ---------------------------------------------------------------------------

class TestCursorOverlayPainter:
    def _fresh_peer(self, uid="alice", name="Alice", color="rgb(56, 135, 235)",
                    x=10.0, y=20.0, offset=0.0):
        return (uid, name, color, x, y, time.monotonic() - offset)

    def test_active_cursor_is_drawn(self):
        peer = self._fresh_peer()
        painter = CursorOverlayPainter(cursor_provider=lambda: [peer])
        cr = _RecordingCairo()
        painter.paint([], cr)

        # At minimum we expect save/restore and at least one translate
        calls = {c[0] for c in cr.calls}
        assert "save" in calls
        assert "restore" in calls
        assert "translate" in calls

    def test_stale_cursor_not_drawn(self):
        # Make a peer that was last seen well past the stale timeout
        stale_peer = self._fresh_peer(offset=STALE_TIMEOUT_S + 1.0)
        painter = CursorOverlayPainter(cursor_provider=lambda: [stale_peer])
        cr = _RecordingCairo()
        painter.paint([], cr)
        # Nothing at all should be drawn for a stale cursor
        assert cr.calls == []

    def test_mixed_fresh_and_stale(self):
        fresh = self._fresh_peer(uid="alice")
        stale = self._fresh_peer(uid="bob", offset=STALE_TIMEOUT_S + 10.0)
        painter = CursorOverlayPainter(cursor_provider=lambda: [fresh, stale])
        cr = _RecordingCairo()
        painter.paint([], cr)
        # Only alice's cursor should produce drawing calls
        translates = [c for c in cr.calls if c[0] == "translate"]
        # Fresh peer triggers a translate for the arrow
        assert len(translates) >= 1

    def test_empty_provider_draws_nothing(self):
        painter = CursorOverlayPainter(cursor_provider=lambda: [])
        cr = _RecordingCairo()
        painter.paint([], cr)
        assert cr.calls == []

    def test_colour_applied_to_drawing(self):
        peer = self._fresh_peer(color="rgb(255, 0, 0)")
        painter = CursorOverlayPainter(cursor_provider=lambda: [peer])
        cr = _RecordingCairo()
        painter.paint([], cr)
        rgba_calls = [c for c in cr.calls if c[0] == "set_source_rgba"]
        # At least one fill call with the red colour
        assert any(
            c[1] == pytest.approx(1.0) and c[2] == pytest.approx(0.0) and c[3] == pytest.approx(0.0)
            for c in rgba_calls
        )

    def test_name_badge_text_shown(self):
        peer = self._fresh_peer(name="Alice Wonderland")
        painter = CursorOverlayPainter(cursor_provider=lambda: [peer])
        cr = _RecordingCairo()
        painter.paint([], cr)
        texts = [c[1] for c in cr.calls if c[0] == "show_text"]
        assert "Alice Wonderland" in texts

    def test_multiple_peers_drawn(self):
        peers = [self._fresh_peer(uid=f"u{i}", name=f"User{i}") for i in range(4)]
        painter = CursorOverlayPainter(cursor_provider=lambda: peers)
        cr = _RecordingCairo()
        painter.paint([], cr)
        texts = [c[1] for c in cr.calls if c[0] == "show_text"]
        for i in range(4):
            assert f"User{i}" in texts

    def test_cursor_at_origin(self):
        peer = self._fresh_peer(x=0.0, y=0.0)
        painter = CursorOverlayPainter(cursor_provider=lambda: [peer])
        cr = _RecordingCairo()
        painter.paint([], cr)
        # translate to (0, 0) should still result in draw calls
        assert any(c[0] == "translate" for c in cr.calls)


# ---------------------------------------------------------------------------
# _rounded_rect (path-tracing helper)
# ---------------------------------------------------------------------------

class TestRoundedRect:
    def test_traces_four_arcs(self):
        cr = _RecordingCairo()
        _rounded_rect(cr, 10.0, 20.0, 100.0, 50.0, 5.0)
        arc_calls = [c for c in cr.calls if c[0] == "arc"]
        assert len(arc_calls) == 4

    def test_closes_path(self):
        cr = _RecordingCairo()
        _rounded_rect(cr, 0.0, 0.0, 40.0, 30.0, 4.0)
        assert any(c[0] == "close_path" for c in cr.calls)

    def test_arc_radius_correct(self):
        cr = _RecordingCairo()
        radius = 7.0
        _rounded_rect(cr, 5.0, 5.0, 80.0, 40.0, radius)
        arc_calls = [c for c in cr.calls if c[0] == "arc"]
        for arc in arc_calls:
            # arc tuple: ("arc", cx, cy, r, a1, a2)
            assert arc[3] == pytest.approx(radius)

    def test_arc_angles_span_full_circle(self):
        cr = _RecordingCairo()
        _rounded_rect(cr, 0.0, 0.0, 60.0, 30.0, 3.0)
        arc_calls = [c for c in cr.calls if c[0] == "arc"]
        start_angles = {c[4] for c in arc_calls}
        end_angles   = {c[5] for c in arc_calls}
        # All four quadrant starting angles should be represented
        expected_starts = {math.pi, 3 * math.pi / 2, 0.0, math.pi / 2}
        assert start_angles == pytest.approx(expected_starts, abs=1e-9)
