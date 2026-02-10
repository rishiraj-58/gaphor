"""Drawing tools for presentation mode annotations."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import cairo
from gi.repository import Gdk, GLib, Gtk

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


@dataclass
class LaserPointerState:
    """State for the laser pointer."""

    enabled: bool = False
    x: float = 0.0
    y: float = 0.0
    visible: bool = False
    color: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 1.0)
    size: float = 12.0
    trail: list[tuple[float, float, float]] = field(default_factory=list)
    trail_max_length: int = 20


TOOL_COLORS = {
    "red": (1.0, 0.0, 0.0, 1.0),
    "blue": (0.0, 0.0, 1.0, 1.0),
    "green": (0.0, 0.6, 0.0, 1.0),
    "yellow": (1.0, 1.0, 0.0, 0.5),
    "black": (0.0, 0.0, 0.0, 1.0),
    "white": (1.0, 1.0, 1.0, 1.0),
    "orange": (1.0, 0.5, 0.0, 1.0),
    "purple": (0.5, 0.0, 0.5, 1.0),
    "cyan": (0.0, 1.0, 1.0, 1.0),
}

TOOL_LINE_WIDTHS = {
    "pen": 3.0,
    "highlighter": 20.0,
    "arrow": 3.0,
    "rectangle": 2.0,
    "ellipse": 2.0,
    "line": 2.0,
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

        drag = Gtk.GestureDrag.new()
        drag.connect("drag-update", self._on_drag_update)
        self.add_controller(drag)

        self._press_x = 0.0
        self._press_y = 0.0

    def set_tool(self, tool: str) -> None:
        """Set the current drawing tool."""
        self.state.current_tool = tool
        self.state.line_width = TOOL_LINE_WIDTHS.get(tool, 3.0)
        if tool == "highlighter":
            r, g, b, _ = self.state.color
            self.state.color = (r, g, b, 0.3)
        else:
            r, g, b, a = self.state.color
            if a < 1.0 and tool != "highlighter":
                self.state.color = (r, g, b, 1.0)

    def set_color(self, color_name: str) -> None:
        """Set the current drawing color."""
        if color_name in TOOL_COLORS:
            self.state.color = TOOL_COLORS[color_name]
            if self.state.current_tool == "highlighter":
                r, g, b, _ = self.state.color
                self.state.color = (r, g, b, 0.3)

    def set_line_width(self, width: float) -> None:
        """Set the current line width."""
        self.state.line_width = width

    def clear_annotations(self) -> None:
        """Clear all annotations."""
        self.state.annotations.clear()
        self.queue_draw()

    def undo_last(self) -> None:
        """Undo the last annotation."""
        if self.state.annotations:
            self.state.annotations.pop()
            self.queue_draw()

    def get_annotation_count(self) -> int:
        """Get the number of annotations."""
        return len(self.state.annotations)

    def _on_press(self, gesture, n_press, x, y):
        if not self.state.enabled:
            return

        self._press_x = x
        self._press_y = y
        self.state.is_drawing = True
        self.state.current_points = [(x, y)]

    def _on_drag_update(self, gesture, offset_x, offset_y):
        if not self.state.enabled or not self.state.is_drawing:
            return

        x = self._press_x + offset_x
        y = self._press_y + offset_y

        tool = self.state.current_tool
        if tool in ("pen", "highlighter"):
            self.state.current_points.append((x, y))
            self.queue_draw()

    def _on_release(self, gesture, n_press, x, y):
        if not self.state.enabled or not self.state.is_drawing:
            return

        self.state.is_drawing = False
        tool = self.state.current_tool

        if tool in ("rectangle", "ellipse", "arrow", "line"):
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
        elif tool == "line":
            self._draw_line(cr, points)

    def _draw_freehand(self, cr: cairo.Context, points: list[tuple[float, float]]) -> None:
        if len(points) < 2:
            return

        cr.move_to(points[0][0], points[0][1])
        for x, y in points[1:]:
            cr.line_to(x, y)
        cr.stroke()

    def _draw_line(self, cr: cairo.Context, points: list[tuple[float, float]]) -> None:
        if len(points) < 2:
            return

        x1, y1 = points[0]
        x2, y2 = points[-1]
        cr.move_to(x1, y1)
        cr.line_to(x2, y2)
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


class LaserPointerOverlay(Gtk.DrawingArea):
    """Overlay for laser pointer functionality."""

    def __init__(self):
        super().__init__()
        self.state = LaserPointerState()
        self.set_draw_func(self._on_draw)

        motion = Gtk.EventControllerMotion.new()
        motion.connect("motion", self._on_motion)
        motion.connect("enter", self._on_enter)
        motion.connect("leave", self._on_leave)
        self.add_controller(motion)

        self._pulse_phase = 0.0
        self._pulse_timer: int | None = None

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable the laser pointer."""
        self.state.enabled = enabled
        if enabled:
            self._start_animation()
        else:
            self._stop_animation()
            self.state.visible = False
            self.state.trail.clear()
        self.queue_draw()

    def set_color(self, color_name: str) -> None:
        """Set the laser pointer color."""
        if color_name in TOOL_COLORS:
            self.state.color = TOOL_COLORS[color_name]

    def set_size(self, size: float) -> None:
        """Set the laser pointer size."""
        self.state.size = size

    def _start_animation(self) -> None:
        """Start the pulse animation."""
        if self._pulse_timer is None:
            self._pulse_timer = GLib.timeout_add(30, self._animate_pulse)

    def _stop_animation(self) -> None:
        """Stop the pulse animation."""
        if self._pulse_timer is not None:
            GLib.source_remove(self._pulse_timer)
            self._pulse_timer = None

    def _animate_pulse(self) -> bool:
        """Animate the laser pointer pulse."""
        self._pulse_phase += 0.15
        if self._pulse_phase > 2 * math.pi:
            self._pulse_phase -= 2 * math.pi

        if len(self.state.trail) > 0:
            self.state.trail = [
                (x, y, alpha * 0.9) for x, y, alpha in self.state.trail if alpha > 0.1
            ]

        self.queue_draw()
        return self.state.enabled

    def _on_motion(self, controller, x, y):
        if not self.state.enabled:
            return

        if self.state.visible:
            self.state.trail.append((self.state.x, self.state.y, 0.5))
            if len(self.state.trail) > self.state.trail_max_length:
                self.state.trail.pop(0)

        self.state.x = x
        self.state.y = y
        self.queue_draw()

    def _on_enter(self, controller, x, y):
        if self.state.enabled:
            self.state.visible = True
            self.state.x = x
            self.state.y = y
            self.queue_draw()

    def _on_leave(self, controller):
        self.state.visible = False
        self.state.trail.clear()
        self.queue_draw()

    def _on_draw(self, area, cr, width, height):
        if not self.state.enabled or not self.state.visible:
            return

        r, g, b, a = self.state.color
        x, y = self.state.x, self.state.y
        base_size = self.state.size

        for tx, ty, alpha in self.state.trail:
            trail_size = base_size * 0.3 * alpha
            cr.set_source_rgba(r, g, b, alpha * 0.3)
            cr.arc(tx, ty, trail_size, 0, 2 * math.pi)
            cr.fill()

        pulse = 0.2 * math.sin(self._pulse_phase) + 1.0

        glow_size = base_size * 2.5 * pulse
        gradient = cairo.RadialGradient(x, y, 0, x, y, glow_size)
        gradient.add_color_stop_rgba(0, r, g, b, 0.4)
        gradient.add_color_stop_rgba(0.5, r, g, b, 0.1)
        gradient.add_color_stop_rgba(1, r, g, b, 0)
        cr.set_source(gradient)
        cr.arc(x, y, glow_size, 0, 2 * math.pi)
        cr.fill()

        outer_size = base_size * pulse
        gradient = cairo.RadialGradient(x, y, 0, x, y, outer_size)
        gradient.add_color_stop_rgba(0, 1, 1, 1, 1)
        gradient.add_color_stop_rgba(0.3, r, g, b, 1)
        gradient.add_color_stop_rgba(1, r * 0.5, g * 0.5, b * 0.5, 0.8)
        cr.set_source(gradient)
        cr.arc(x, y, outer_size, 0, 2 * math.pi)
        cr.fill()

        inner_size = base_size * 0.3
        cr.set_source_rgba(1, 1, 1, 0.9)
        cr.arc(x, y, inner_size, 0, 2 * math.pi)
        cr.fill()
