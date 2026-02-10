"""Drawing tools for presentation mode annotations."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import cairo
from gi.repository import Gdk, Gtk

if TYPE_CHECKING:
    from gaphor.plugins.presentationmode.model import DrawingAnnotation


@dataclass
class DrawingState:
    """Current state of the drawing tools."""

    enabled: bool = False
    current_tool: str = "pen"
    color: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 1.0)
    line_width: float = 3.0
    annotations: list[DrawingAnnotation] = field(default_factory=list)
    current_points: list[tuple[float, float]] = field(default_factory=list)
    is_drawing: bool = False


TOOL_COLORS = {
    "red": (1.0, 0.0, 0.0, 1.0),
    "blue": (0.0, 0.0, 1.0, 1.0),
    "green": (0.0, 0.6, 0.0, 1.0),
    "yellow": (1.0, 1.0, 0.0, 0.5),
    "black": (0.0, 0.0, 0.0, 1.0),
    "white": (1.0, 1.0, 1.0, 1.0),
}

TOOL_LINE_WIDTHS = {
    "pen": 3.0,
    "highlighter": 20.0,
    "arrow": 3.0,
    "rectangle": 2.0,
    "ellipse": 2.0,
}


class DrawingOverlay(Gtk.DrawingArea):
    """Overlay widget for drawing annotations during presentation."""

    def __init__(self):
        super().__init__()
        self.state = DrawingState()
        self.set_draw_func(self._on_draw)

        click = Gtk.GestureClick.new()
        click.connect("pressed", self._on_press)
        click.connect("released", self._on_release)
        self.add_controller(click)

        motion = Gtk.EventControllerMotion.new()
        motion.connect("motion", self._on_motion)
        self.add_controller(motion)

        self._press_x = 0.0
        self._press_y = 0.0

    def set_tool(self, tool: str) -> None:
        """Set the current drawing tool."""
        self.state.current_tool = tool
        self.state.line_width = TOOL_LINE_WIDTHS.get(tool, 3.0)
        if tool == "highlighter":
            r, g, b, _ = self.state.color
            self.state.color = (r, g, b, 0.3)

    def set_color(self, color_name: str) -> None:
        """Set the current drawing color."""
        if color_name in TOOL_COLORS:
            self.state.color = TOOL_COLORS[color_name]
            if self.state.current_tool == "highlighter":
                r, g, b, _ = self.state.color
                self.state.color = (r, g, b, 0.3)

    def clear_annotations(self) -> None:
        """Clear all annotations."""
        self.state.annotations.clear()
        self.queue_draw()

    def undo_last(self) -> None:
        """Undo the last annotation."""
        if self.state.annotations:
            self.state.annotations.pop()
            self.queue_draw()

    def _on_press(self, gesture, n_press, x, y):
        if not self.state.enabled:
            return

        self._press_x = x
        self._press_y = y
        self.state.is_drawing = True
        self.state.current_points = [(x, y)]

    def _on_motion(self, controller, x, y):
        if not self.state.enabled or not self.state.is_drawing:
            return

        tool = self.state.current_tool
        if tool in ("pen", "highlighter"):
            self.state.current_points.append((x, y))
            self.queue_draw()

    def _on_release(self, gesture, n_press, x, y):
        if not self.state.enabled or not self.state.is_drawing:
            return

        self.state.is_drawing = False
        tool = self.state.current_tool

        if tool in ("rectangle", "ellipse", "arrow"):
            self.state.current_points = [(self._press_x, self._press_y), (x, y)]

        if self.state.current_points:
            from gaphor.plugins.presentationmode.model import DrawingAnnotation

            annotation = DrawingAnnotation(
                points=list(self.state.current_points),
                color=self.state.color,
                line_width=self.state.line_width,
                tool=tool,
            )
            self.state.annotations.append(annotation)
            self.state.current_points.clear()
            self.queue_draw()

    def _on_draw(self, area, cr, width, height):
        for annotation in self.state.annotations:
            self._draw_annotation(cr, annotation)

        if self.state.is_drawing and self.state.current_points:
            from gaphor.plugins.presentationmode.model import DrawingAnnotation

            current = DrawingAnnotation(
                points=list(self.state.current_points),
                color=self.state.color,
                line_width=self.state.line_width,
                tool=self.state.current_tool,
            )
            self._draw_annotation(cr, current)

    def _draw_annotation(self, cr: cairo.Context, annotation: DrawingAnnotation) -> None:
        if not annotation.points:
            return

        cr.set_source_rgba(*annotation.color)
        cr.set_line_width(annotation.line_width)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)

        tool = annotation.tool
        points = annotation.points

        if tool in ("pen", "highlighter"):
            self._draw_freehand(cr, points)
        elif tool == "arrow":
            self._draw_arrow(cr, points)
        elif tool == "rectangle":
            self._draw_rectangle(cr, points)
        elif tool == "ellipse":
            self._draw_ellipse(cr, points)

    def _draw_freehand(self, cr: cairo.Context, points: list[tuple[float, float]]) -> None:
        if len(points) < 2:
            return

        cr.move_to(points[0][0], points[0][1])
        for x, y in points[1:]:
            cr.line_to(x, y)
        cr.stroke()

    def _draw_arrow(self, cr: cairo.Context, points: list[tuple[float, float]]) -> None:
        if len(points) < 2:
            return

        x1, y1 = points[0]
        x2, y2 = points[-1]

        cr.move_to(x1, y1)
        cr.line_to(x2, y2)
        cr.stroke()

        angle = math.atan2(y2 - y1, x2 - x1)
        arrow_length = 15
        arrow_angle = math.pi / 6

        ax1 = x2 - arrow_length * math.cos(angle - arrow_angle)
        ay1 = y2 - arrow_length * math.sin(angle - arrow_angle)
        ax2 = x2 - arrow_length * math.cos(angle + arrow_angle)
        ay2 = y2 - arrow_length * math.sin(angle + arrow_angle)

        cr.move_to(x2, y2)
        cr.line_to(ax1, ay1)
        cr.move_to(x2, y2)
        cr.line_to(ax2, ay2)
        cr.stroke()

    def _draw_rectangle(self, cr: cairo.Context, points: list[tuple[float, float]]) -> None:
        if len(points) < 2:
            return

        x1, y1 = points[0]
        x2, y2 = points[-1]

        width = x2 - x1
        height = y2 - y1

        cr.rectangle(x1, y1, width, height)
        cr.stroke()

    def _draw_ellipse(self, cr: cairo.Context, points: list[tuple[float, float]]) -> None:
        if len(points) < 2:
            return

        x1, y1 = points[0]
        x2, y2 = points[-1]

        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        rx = abs(x2 - x1) / 2
        ry = abs(y2 - y1) / 2

        if rx > 0 and ry > 0:
            cr.save()
            cr.translate(cx, cy)
            cr.scale(rx, ry)
            cr.arc(0, 0, 1, 0, 2 * math.pi)
            cr.restore()
            cr.stroke()
