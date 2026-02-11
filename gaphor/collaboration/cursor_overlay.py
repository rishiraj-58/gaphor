"""Remote cursor overlay painter.

Draws a small labelled crosshair on the diagram canvas for every
remote collaborator that is currently editing the same diagram.  The
overlay integrates with Gaphor's existing ``PainterChain`` in
``DiagramPage`` and never touches the model.

Visual design
-------------
Each remote cursor consists of:

1. A 14×14 arrow pointer (drawn with Cairo path commands) filled with
   the peer's assigned colour.
2. A rounded-rectangle name badge immediately to the lower-right of the
   arrow tip, containing the peer's ``display_name`` in white text.
3. A 1 px white outline around both shapes to ensure visibility on both
   light and dark diagram backgrounds.

The overlay operates entirely in *diagram coordinates* (the same space
used by ``Presentation`` items) so it follows any pan/zoom applied to
the ``GtkView``.  Stale cursors (no update for ``STALE_TIMEOUT_S``
seconds) are automatically hidden.

Integration with ``DiagramPage``
---------------------------------
``DiagramPage.update_drawing_style()`` already assembles a
``PainterChain``.  The ``CursorOverlayPainter`` must be appended *last*
to the chain so that cursors appear on top of all diagram items.  The
``CollaborationService`` does this when it attaches to a ``DiagramPage``.
"""

from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Avoid hard GTK import at module level for test environments without a display
    pass

# Number of seconds without a cursor update before the overlay is hidden.
STALE_TIMEOUT_S: float = 5.0

# Font size for the name badge label (Cairo units = diagram points).
_LABEL_FONT_SIZE: float = 11.0
# Padding inside the name badge.
_LABEL_PAD_X: float = 5.0
_LABEL_PAD_Y: float = 3.0
# Corner radius of the name badge.
_BADGE_RADIUS: float = 4.0


class CursorOverlayPainter:
    """A painter that draws remote collaborator cursors on top of the diagram.

    Must be appended to the ``PainterChain`` in
    ``DiagramPage.update_drawing_style()``.

    Parameters
    ----------
    cursor_provider:
        A callable that returns an iterable of
        ``(user_id, display_name, color_css, x, y, last_seen)`` tuples.
        ``CollaborationService`` supplies this by delegating to its
        ``CollaborationClient.peers`` property.
    """

    def __init__(self, cursor_provider) -> None:
        self._cursor_provider = cursor_provider

    # ------------------------------------------------------------------
    # gaphas Painter protocol
    # ------------------------------------------------------------------

    def paint(self, _items, cr) -> None:
        """Called by gaphas on every redraw pass.

        *cr* is a ``cairo.Context`` already set up in diagram coordinates.
        """
        now = time.monotonic()
        for peer_data in self._cursor_provider():
            user_id, display_name, color_css, x, y, last_seen = peer_data
            if now - last_seen > STALE_TIMEOUT_S:
                continue   # cursor is stale – don't draw it
            r, g, b = _parse_css_rgb(color_css)
            _draw_cursor(cr, x, y, r, g, b, display_name)


# ---------------------------------------------------------------------------
# Low-level drawing helpers
# ---------------------------------------------------------------------------

def _draw_cursor(
    cr,
    x: float,
    y: float,
    r: float,
    g: float,
    b: float,
    label: str,
) -> None:
    """Draw a single remote cursor at diagram position *(x, y)*."""
    cr.save()
    try:
        cr.translate(x, y)
        _draw_arrow(cr, r, g, b)
        _draw_badge(cr, r, g, b, label)
    finally:
        cr.restore()


def _draw_arrow(cr, r: float, g: float, b: float) -> None:
    """Draw a 14 × 14 pointer arrow starting at the origin (0, 0)."""
    # The arrow points towards the upper-left; the tip is at (0, 0).
    # Vertices chosen so the arrow is clearly directional and legible.
    cr.new_path()
    cr.move_to(0.0, 0.0)
    cr.line_to(0.0, 14.0)
    cr.line_to(3.5, 10.5)
    cr.line_to(7.0, 17.5)
    cr.line_to(9.0, 16.5)
    cr.line_to(5.5, 9.5)
    cr.line_to(10.5, 9.5)
    cr.close_path()

    # Fill with the peer's colour
    cr.set_source_rgba(r, g, b, 0.90)
    cr.fill_preserve()

    # White 1 px outline
    cr.set_source_rgba(1.0, 1.0, 1.0, 0.95)
    cr.set_line_width(1.0)
    cr.stroke()


def _draw_badge(cr, r: float, g: float, b: float, label: str) -> None:
    """Draw the name badge below and to the right of the arrow tip."""
    if not label:
        return

    cr.set_font_size(_LABEL_FONT_SIZE)
    extents = cr.text_extents(label)
    text_w: float = extents.width
    text_h: float = extents.height

    badge_w = text_w + 2 * _LABEL_PAD_X
    badge_h = text_h + 2 * _LABEL_PAD_Y

    # Offset the badge from the arrow tip
    bx = 12.0
    by = 12.0

    # Draw rounded rectangle
    _rounded_rect(cr, bx, by, badge_w, badge_h, _BADGE_RADIUS)
    cr.set_source_rgba(r, g, b, 0.90)
    cr.fill_preserve()
    cr.set_source_rgba(1.0, 1.0, 1.0, 0.95)
    cr.set_line_width(0.8)
    cr.stroke()

    # Draw label text in white
    cr.set_source_rgba(1.0, 1.0, 1.0, 1.0)
    cr.move_to(
        bx + _LABEL_PAD_X - extents.x_bearing,
        by + _LABEL_PAD_Y - extents.y_bearing,
    )
    cr.show_text(label)


def _rounded_rect(
    cr, x: float, y: float, w: float, h: float, radius: float
) -> None:
    """Trace a rounded rectangle path (does not stroke/fill)."""
    cr.new_path()
    cr.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
    cr.arc(x + w - radius, y + radius, radius, 3 * math.pi / 2, 0)
    cr.arc(x + w - radius, y + h - radius, radius, 0, math.pi / 2)
    cr.arc(x + radius, y + h - radius, radius, math.pi / 2, math.pi)
    cr.close_path()


def _parse_css_rgb(css: str) -> tuple[float, float, float]:
    """Parse ``"rgb(r, g, b)"`` into float components in ``[0.0, 1.0]``.

    Falls back to a neutral grey on any parse error so the overlay
    degrades gracefully rather than raising.
    """
    try:
        inner = css[css.index("(") + 1: css.index(")")]
        parts = [int(p.strip()) for p in inner.split(",")]
        return parts[0] / 255.0, parts[1] / 255.0, parts[2] / 255.0
    except Exception:
        return 0.5, 0.5, 0.5
