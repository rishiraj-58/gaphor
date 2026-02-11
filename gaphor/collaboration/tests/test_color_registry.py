"""Tests for ColorRegistry."""

import pytest

from gaphor.collaboration.color_registry import ColorRegistry, UserColor, _PREBUILT


class TestUserColor:
    def test_namedtuple_fields(self):
        c = UserColor(red=0.22, green=0.53, blue=0.92, css="rgb(56, 135, 235)")
        assert c.red == pytest.approx(0.22)
        assert c.green == pytest.approx(0.53)
        assert c.blue == pytest.approx(0.92)
        assert c.css == "rgb(56, 135, 235)"

    def test_cairo_rgba(self):
        c = UserColor(red=0.5, green=0.6, blue=0.7, css="rgb(127, 153, 178)")
        r, g, b, a = c.cairo_rgba
        assert r == pytest.approx(0.5)
        assert g == pytest.approx(0.6)
        assert b == pytest.approx(0.7)
        assert a == pytest.approx(1.0)

    def test_immutable(self):
        c = UserColor(0.1, 0.2, 0.3, "rgb(25, 51, 76)")
        with pytest.raises(AttributeError):
            c.red = 0.9  # type: ignore[misc]

    def test_css_contains_rgb(self):
        for color in _PREBUILT:
            assert color.css.startswith("rgb(")
            assert color.css.endswith(")")


class TestColorRegistry:
    def test_assign_returns_color(self):
        reg = ColorRegistry()
        color = reg.assign("alice")
        assert isinstance(color, UserColor)

    def test_assign_same_user_returns_same_color(self):
        reg = ColorRegistry()
        c1 = reg.assign("alice")
        c2 = reg.assign("alice")
        assert c1 is c2

    def test_two_different_users_get_different_colors(self):
        reg = ColorRegistry()
        c1 = reg.assign("alice")
        c2 = reg.assign("bob")
        assert c1 is not c2

    def test_all_palette_slots_distinct(self):
        reg = ColorRegistry()
        users = [f"user_{i}" for i in range(12)]
        colors = [reg.assign(u) for u in users]
        # All 12 should be distinct objects (from different palette positions)
        assert len(set(id(c) for c in colors)) == 12

    def test_release_frees_slot(self):
        reg = ColorRegistry()
        first_color = reg.assign("alice")
        reg.release("alice")
        assert reg.get("alice") is None
        # alice's slot is now free, next user should get it
        second_color = reg.assign("charlie")
        assert second_color is first_color

    def test_release_nonexistent_user_is_noop(self):
        reg = ColorRegistry()
        # Should not raise
        reg.release("nobody")

    def test_get_returns_none_for_unknown(self):
        reg = ColorRegistry()
        assert reg.get("ghost") is None

    def test_get_returns_color_after_assign(self):
        reg = ColorRegistry()
        color = reg.assign("alice")
        assert reg.get("alice") is color

    def test_assignments_snapshot(self):
        reg = ColorRegistry()
        reg.assign("alice")
        reg.assign("bob")
        snapshot = reg.assignments
        assert set(snapshot.keys()) == {"alice", "bob"}
        # Snapshot is a copy; mutations do not affect the registry
        snapshot["extra"] = None
        assert "extra" not in reg.assignments

    def test_wrap_around_when_palette_full(self):
        """When more than 12 users join the palette wraps rather than crashing."""
        reg = ColorRegistry()
        for i in range(14):
            color = reg.assign(f"user_{i}")
            assert isinstance(color, UserColor)

    def test_release_then_reassign_different_user(self):
        reg = ColorRegistry()
        reg.assign("alice")
        reg.assign("bob")
        reg.release("alice")
        # Bob keeps his slot; the freed slot is reused for charlie
        charlie_color = reg.assign("charlie")
        bob_color = reg.get("bob")
        assert charlie_color is not bob_color

    def test_css_format_all_prebuilt(self):
        """Every prebuilt colour must parse correctly."""
        for color in _PREBUILT:
            inner = color.css[4:-1]   # strip "rgb(" and ")"
            parts = [int(p.strip()) for p in inner.split(",")]
            assert len(parts) == 3
            for part in parts:
                assert 0 <= part <= 255
