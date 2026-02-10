"""Clickable hotspots for presentation mode navigation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from gi.repository import Gdk, Gtk

if TYPE_CHECKING:
    from gaphor.core.modeling import Diagram


@dataclass
class Hotspot:
    """A clickable region that triggers navigation or reveals information."""

    x: float
    y: float
    width: float
    height: float
    action: str  # "navigate", "reveal", "link"
    target_diagram_id: str | None = None
    reveal_element_ids: list[str] | None = None
    tooltip: str = ""


class HotspotManager:
    """Manages clickable hotspots in presentation mode."""

    def __init__(self):
        self.hotspots: list[Hotspot] = []
        self.revealed_elements: set[str] = set()
        self._on_navigate: Callable[[str], None] | None = None
        self._on_reveal: Callable[[list[str]], None] | None = None

    def set_navigate_callback(self, callback: Callable[[str], None]) -> None:
        """Set callback for diagram navigation."""
        self._on_navigate = callback

    def set_reveal_callback(self, callback: Callable[[list[str]], None]) -> None:
        """Set callback for revealing elements."""
        self._on_reveal = callback

    def add_hotspot(self, hotspot: Hotspot) -> None:
        """Add a hotspot."""
        self.hotspots.append(hotspot)

    def clear_hotspots(self) -> None:
        """Clear all hotspots."""
        self.hotspots.clear()
        self.revealed_elements.clear()

    def check_click(self, x: float, y: float, view_matrix) -> bool:
        """Check if a click hits any hotspot and trigger its action.

        Returns True if a hotspot was activated.
        """
        diagram_x, diagram_y = view_matrix.inverse().transform_point(x, y)

        for hotspot in self.hotspots:
            if self._point_in_hotspot(diagram_x, diagram_y, hotspot):
                self._activate_hotspot(hotspot)
                return True

        return False

    def _point_in_hotspot(self, x: float, y: float, hotspot: Hotspot) -> bool:
        """Check if a point is within a hotspot region."""
        return (
            hotspot.x <= x <= hotspot.x + hotspot.width
            and hotspot.y <= y <= hotspot.y + hotspot.height
        )

    def _activate_hotspot(self, hotspot: Hotspot) -> None:
        """Activate a hotspot based on its action type."""
        if hotspot.action == "navigate" and hotspot.target_diagram_id:
            if self._on_navigate:
                self._on_navigate(hotspot.target_diagram_id)

        elif hotspot.action == "reveal" and hotspot.reveal_element_ids:
            self.revealed_elements.update(hotspot.reveal_element_ids)
            if self._on_reveal:
                self._on_reveal(hotspot.reveal_element_ids)

        elif hotspot.action == "link" and hotspot.target_diagram_id:
            if self._on_navigate:
                self._on_navigate(hotspot.target_diagram_id)

    def get_hotspot_at(self, x: float, y: float, view_matrix) -> Hotspot | None:
        """Get the hotspot at a specific position, if any."""
        diagram_x, diagram_y = view_matrix.inverse().transform_point(x, y)

        for hotspot in self.hotspots:
            if self._point_in_hotspot(diagram_x, diagram_y, hotspot):
                return hotspot

        return None

    def is_element_revealed(self, element_id: str) -> bool:
        """Check if an element has been revealed."""
        return element_id in self.revealed_elements

    def reset_reveals(self) -> None:
        """Reset all revealed elements."""
        self.revealed_elements.clear()


class HotspotOverlay(Gtk.DrawingArea):
    """Visual overlay showing hotspot regions."""

    def __init__(self, hotspot_manager: HotspotManager):
        super().__init__()
        self.hotspot_manager = hotspot_manager
        self.view_matrix = None
        self.show_hotspots = False
        self.hovered_hotspot: Hotspot | None = None

        self.set_draw_func(self._on_draw)

        motion = Gtk.EventControllerMotion.new()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", self._on_leave)
        self.add_controller(motion)

        click = Gtk.GestureClick.new()
        click.connect("pressed", self._on_click)
        self.add_controller(click)

    def set_view_matrix(self, matrix) -> None:
        """Update the view matrix for coordinate transformation."""
        self.view_matrix = matrix
        self.queue_draw()

    def toggle_hotspot_visibility(self) -> None:
        """Toggle whether hotspots are visually highlighted."""
        self.show_hotspots = not self.show_hotspots
        self.queue_draw()

    def _on_motion(self, controller, x, y):
        if self.view_matrix is None:
            return

        hotspot = self.hotspot_manager.get_hotspot_at(x, y, self.view_matrix)

        if hotspot != self.hovered_hotspot:
            self.hovered_hotspot = hotspot
            if hotspot:
                self.set_cursor(Gdk.Cursor.new_from_name("pointer"))
            else:
                self.set_cursor(None)
            self.queue_draw()

    def _on_leave(self, controller):
        if self.hovered_hotspot:
            self.hovered_hotspot = None
            self.set_cursor(None)
            self.queue_draw()

    def _on_click(self, gesture, n_press, x, y):
        if self.view_matrix is None:
            return

        self.hotspot_manager.check_click(x, y, self.view_matrix)

    def _on_draw(self, area, cr, width, height):
        if not self.show_hotspots or self.view_matrix is None:
            if self.hovered_hotspot:
                self._draw_hotspot_highlight(cr, self.hovered_hotspot)
            return

        for hotspot in self.hotspot_manager.hotspots:
            self._draw_hotspot(cr, hotspot)

        if self.hovered_hotspot:
            self._draw_hotspot_highlight(cr, self.hovered_hotspot)

    def _draw_hotspot(self, cr, hotspot: Hotspot) -> None:
        """Draw a hotspot indicator."""
        x, y = self.view_matrix.transform_point(hotspot.x, hotspot.y)
        w = hotspot.width * self.view_matrix[0]
        h = hotspot.height * self.view_matrix[0]

        if hotspot.action == "navigate":
            cr.set_source_rgba(0.0, 0.5, 1.0, 0.2)
        elif hotspot.action == "reveal":
            cr.set_source_rgba(0.0, 1.0, 0.5, 0.2)
        else:
            cr.set_source_rgba(1.0, 0.5, 0.0, 0.2)

        cr.rectangle(x, y, w, h)
        cr.fill()

        cr.set_source_rgba(0.0, 0.0, 0.0, 0.5)
        cr.set_line_width(1)
        cr.rectangle(x, y, w, h)
        cr.stroke()

    def _draw_hotspot_highlight(self, cr, hotspot: Hotspot) -> None:
        """Draw a highlighted hotspot."""
        x, y = self.view_matrix.transform_point(hotspot.x, hotspot.y)
        w = hotspot.width * self.view_matrix[0]
        h = hotspot.height * self.view_matrix[0]

        cr.set_source_rgba(1.0, 1.0, 0.0, 0.3)
        cr.rectangle(x, y, w, h)
        cr.fill()

        cr.set_source_rgba(1.0, 0.8, 0.0, 0.8)
        cr.set_line_width(2)
        cr.rectangle(x, y, w, h)
        cr.stroke()
