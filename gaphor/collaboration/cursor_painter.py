"""Painter for rendering remote user cursors on diagrams."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from gaphas.painter import Painter

if TYPE_CHECKING:
    from cairo import Context as CairoContext

    from gaphor.collaboration.user import CollaborationUser


class RemoteCursorPainter(Painter):
    """Painter that renders cursors of remote collaborators on the diagram."""

    def __init__(self, get_cursors_func):
        """Initialize the painter.

        Args:
            get_cursors_func: Function that returns list of (user, x, y) tuples
        """
        self._get_cursors = get_cursors_func

    def paint(self, _items, cairo: CairoContext) -> None:
        """Paint all remote user cursors."""
        cursors = self._get_cursors()
        for user, x, y in cursors:
            self._draw_cursor(cairo, user, x, y)

    def _draw_cursor(
        self, cairo: CairoContext, user: CollaborationUser, x: float, y: float
    ) -> None:
        """Draw a single user cursor with label."""
        r, g, b, a = user.color

        cairo.save()
        cairo.translate(x, y)

        # Draw cursor pointer (arrow shape)
        self._draw_arrow(cairo, r, g, b, a)

        # Draw user name label
        self._draw_label(cairo, user.display_name, r, g, b)

        cairo.restore()

    def _draw_arrow(
        self, cairo: CairoContext, r: float, g: float, b: float, a: float
    ) -> None:
        """Draw the cursor arrow."""
        # Arrow dimensions
        length = 18
        width = 12

        cairo.new_path()
        cairo.move_to(0, 0)
        cairo.line_to(0, length)
        cairo.line_to(width * 0.35, length * 0.7)
        cairo.line_to(width * 0.5, length * 1.1)
        cairo.line_to(width * 0.7, length * 1.0)
        cairo.line_to(width * 0.5, length * 0.6)
        cairo.line_to(width, length * 0.5)
        cairo.close_path()

        # Fill
        cairo.set_source_rgba(r, g, b, a)
        cairo.fill_preserve()

        # Stroke
        cairo.set_source_rgba(0, 0, 0, 0.8)
        cairo.set_line_width(1)
        cairo.stroke()

    def _draw_label(
        self, cairo: CairoContext, name: str, r: float, g: float, b: float
    ) -> None:
        """Draw the user name label."""
        cairo.select_font_face("Sans")
        cairo.set_font_size(11)

        # Get text dimensions
        extents = cairo.text_extents(name)
        padding = 4
        label_x = 15
        label_y = 20

        # Draw label background
        cairo.rectangle(
            label_x - padding,
            label_y - extents.height - padding,
            extents.width + padding * 2,
            extents.height + padding * 2,
        )
        cairo.set_source_rgba(r, g, b, 0.9)
        cairo.fill()

        # Draw label text
        cairo.move_to(label_x, label_y)
        cairo.set_source_rgba(1, 1, 1, 1)
        cairo.show_text(name)


class SelectionHighlightPainter(Painter):
    """Painter that highlights items selected by remote users."""

    def __init__(self, get_selections_func):
        """Initialize the painter.

        Args:
            get_selections_func: Function that returns dict of user -> selected_item_ids
        """
        self._get_selections = get_selections_func

    def paint(self, items, cairo: CairoContext) -> None:
        """Paint selection highlights for remote users."""
        selections = self._get_selections()
        item_map = {item.id: item for item in items if hasattr(item, "id")}

        for user, item_ids in selections.items():
            for item_id in item_ids:
                item = item_map.get(item_id)
                if item:
                    self._highlight_item(cairo, item, user.color)

    def _highlight_item(
        self,
        cairo: CairoContext,
        item,
        color: tuple[float, float, float, float],
    ) -> None:
        """Draw a highlight around a selected item."""
        r, g, b, a = color

        bounds = item.bounds
        if not bounds:
            return

        # Draw dashed outline around item
        cairo.save()

        cairo.rectangle(
            bounds.x - 3,
            bounds.y - 3,
            bounds.width + 6,
            bounds.height + 6,
        )

        cairo.set_source_rgba(r, g, b, 0.6)
        cairo.set_line_width(2)
        cairo.set_dash([5, 3])
        cairo.stroke()

        cairo.restore()
