"""Drawing tools for presentation annotations.

Provides tools for drawing during presentations, including pen, highlighter,
arrows, shapes, and text annotations.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from gi.repository import Gdk, Gtk

from gaphor.plugins.presentation.model import DrawingAnnotation, DrawingToolType

if TYPE_CHECKING:
    from cairo import Context as CairoContext


@dataclass
class DrawingState:
    """Current state of the drawing tool."""

    active_tool: DrawingToolType = DrawingToolType.PEN
    color: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 1.0)
    line_width: float = 3.0
    is_drawing: bool = False
    current_annotation: DrawingAnnotation | None = None


class DrawingToolHandler:
    """Handles drawing tool operations on the presentation canvas."""

    # Predefined colors for quick selection
    COLORS = {
        "red": (1.0, 0.0, 0.0, 1.0),
        "green": (0.0, 0.8, 0.0, 1.0),
        "blue": (0.0, 0.4, 1.0, 1.0),
        "yellow": (1.0, 0.9, 0.0, 0.7),  # Semi-transparent for highlighter
        "orange": (1.0, 0.5, 0.0, 1.0),
        "purple": (0.6, 0.2, 0.8, 1.0),
        "black": (0.0, 0.0, 0.0, 1.0),
        "white": (1.0, 1.0, 1.0, 1.0),
    }

    def __init__(self):
        self.state = DrawingState()
        self.annotations: list[DrawingAnnotation] = []
        self._undo_stack: list[DrawingAnnotation] = []
        self._start_point: tuple[float, float] | None = None

    def set_tool(self, tool: DrawingToolType) -> None:
        """Set the active drawing tool."""
        self.state.active_tool = tool
        if tool == DrawingToolType.HIGHLIGHTER:
            self.state.line_width = 20.0
            color = list(self.state.color)
            color[3] = 0.4
            self.state.color = tuple(color)
        elif tool == DrawingToolType.ERASER:
            self.state.line_width = 20.0
        else:
            if self.state.color[3] < 1.0:
                color = list(self.state.color)
                color[3] = 1.0
                self.state.color = tuple(color)
            if tool == DrawingToolType.PEN:
                self.state.line_width = 3.0

    def set_color(self, color: tuple[float, float, float, float] | str) -> None:
        """Set the drawing color."""
        if isinstance(color, str):
            color = self.COLORS.get(color, self.COLORS["red"])

        if self.state.active_tool == DrawingToolType.HIGHLIGHTER:
            color = (*color[:3], 0.4)

        self.state.color = color

    def set_line_width(self, width: float) -> None:
        """Set the line width."""
        self.state.line_width = max(1.0, min(50.0, width))

    def start_drawing(self, x: float, y: float) -> None:
        """Start a new drawing stroke."""
        if self.state.active_tool == DrawingToolType.ERASER:
            self._erase_at_point(x, y)
            self.state.is_drawing = True
            return

        self.state.is_drawing = True
        self._start_point = (x, y)
        self.state.current_annotation = DrawingAnnotation(
            tool=self.state.active_tool,
            color=self.state.color,
            line_width=self.state.line_width,
            points=[(x, y)],
        )

    def continue_drawing(self, x: float, y: float) -> None:
        """Continue the current drawing stroke."""
        if not self.state.is_drawing:
            return

        if self.state.active_tool == DrawingToolType.ERASER:
            self._erase_at_point(x, y)
            return

        if self.state.current_annotation is None:
            return

        tool = self.state.active_tool

        if tool in (DrawingToolType.PEN, DrawingToolType.HIGHLIGHTER):
            self.state.current_annotation.points.append((x, y))
        elif tool in (
            DrawingToolType.RECTANGLE,
            DrawingToolType.ELLIPSE,
            DrawingToolType.ARROW,
        ):
            if self._start_point:
                self.state.current_annotation.points = [self._start_point, (x, y)]

    def end_drawing(self, x: float, y: float) -> DrawingAnnotation | None:
        """End the current drawing stroke."""
        if not self.state.is_drawing:
            return None

        self.state.is_drawing = False

        if self.state.active_tool == DrawingToolType.ERASER:
            return None

        if self.state.current_annotation is None:
            return None

        if self.state.active_tool in (
            DrawingToolType.RECTANGLE,
            DrawingToolType.ELLIPSE,
            DrawingToolType.ARROW,
        ):
            if self._start_point:
                self.state.current_annotation.points = [self._start_point, (x, y)]

        annotation = self.state.current_annotation
        self.annotations.append(annotation)
        self._undo_stack.clear()
        self.state.current_annotation = None
        self._start_point = None
        return annotation

    def _erase_at_point(self, x: float, y: float, radius: float = 20.0) -> None:
        """Erase annotations near a point."""
        to_remove = []
        for annotation in self.annotations:
            for px, py in annotation.points:
                distance = math.sqrt((px - x) ** 2 + (py - y) ** 2)
                if distance < radius:
                    to_remove.append(annotation)
                    break

        for annotation in to_remove:
            self.annotations.remove(annotation)
            self._undo_stack.append(annotation)

    def undo(self) -> DrawingAnnotation | None:
        """Undo the last drawing action."""
        if self.annotations:
            annotation = self.annotations.pop()
            self._undo_stack.append(annotation)
            return annotation
        return None

    def redo(self) -> DrawingAnnotation | None:
        """Redo the last undone action."""
        if self._undo_stack:
            annotation = self._undo_stack.pop()
            self.annotations.append(annotation)
            return annotation
        return None

    def clear(self) -> None:
        """Clear all annotations."""
        self._undo_stack.extend(self.annotations)
        self.annotations.clear()

    def draw(self, cr: CairoContext, scale: float = 1.0) -> None:
        """Draw all annotations and the current annotation."""
        for annotation in self.annotations:
            self._draw_annotation(cr, annotation, scale)

        if self.state.current_annotation:
            self._draw_annotation(cr, self.state.current_annotation, scale)

    def _draw_annotation(
        self, cr: CairoContext, annotation: DrawingAnnotation, scale: float
    ) -> None:
        """Draw a single annotation."""
        if not annotation.points:
            return

        cr.save()
        cr.set_source_rgba(*annotation.color)
        cr.set_line_width(annotation.line_width * scale)
        cr.set_line_cap(1)  # CAIRO_LINE_CAP_ROUND
        cr.set_line_join(1)  # CAIRO_LINE_JOIN_ROUND

        tool = annotation.tool

        if tool in (DrawingToolType.PEN, DrawingToolType.HIGHLIGHTER):
            self._draw_freeform(cr, annotation.points)
        elif tool == DrawingToolType.ARROW:
            self._draw_arrow(cr, annotation.points, scale)
        elif tool == DrawingToolType.RECTANGLE:
            self._draw_rectangle(cr, annotation.points)
        elif tool == DrawingToolType.ELLIPSE:
            self._draw_ellipse(cr, annotation.points)
        elif tool == DrawingToolType.TEXT:
            self._draw_text(cr, annotation)

        cr.restore()

    def _draw_freeform(
        self, cr: CairoContext, points: list[tuple[float, float]]
    ) -> None:
        """Draw a freeform line."""
        if len(points) < 2:
            return

        cr.move_to(*points[0])
        for point in points[1:]:
            cr.line_to(*point)
        cr.stroke()

    def _draw_arrow(
        self, cr: CairoContext, points: list[tuple[float, float]], scale: float
    ) -> None:
        """Draw an arrow."""
        if len(points) < 2:
            return

        x1, y1 = points[0]
        x2, y2 = points[-1]

        cr.move_to(x1, y1)
        cr.line_to(x2, y2)
        cr.stroke()

        angle = math.atan2(y2 - y1, x2 - x1)
        arrow_length = 15 * scale
        arrow_angle = math.pi / 6

        cr.move_to(x2, y2)
        cr.line_to(
            x2 - arrow_length * math.cos(angle - arrow_angle),
            y2 - arrow_length * math.sin(angle - arrow_angle),
        )
        cr.move_to(x2, y2)
        cr.line_to(
            x2 - arrow_length * math.cos(angle + arrow_angle),
            y2 - arrow_length * math.sin(angle + arrow_angle),
        )
        cr.stroke()

    def _draw_rectangle(
        self, cr: CairoContext, points: list[tuple[float, float]]
    ) -> None:
        """Draw a rectangle."""
        if len(points) < 2:
            return

        x1, y1 = points[0]
        x2, y2 = points[-1]
        cr.rectangle(x1, y1, x2 - x1, y2 - y1)
        cr.stroke()

    def _draw_ellipse(
        self, cr: CairoContext, points: list[tuple[float, float]]
    ) -> None:
        """Draw an ellipse."""
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

    def _draw_text(self, cr: CairoContext, annotation: DrawingAnnotation) -> None:
        """Draw text annotation."""
        if not annotation.points or not annotation.text:
            return

        x, y = annotation.points[0]
        cr.move_to(x, y)
        cr.show_text(annotation.text)


def draw_laser_pointer(
    cr: CairoContext,
    points: list[tuple[float, float, float]],
    color: tuple[float, float, float] = (1.0, 0.0, 0.0),
    max_radius: float = 8.0,
) -> None:
    """Draw a laser pointer trail with fading effect.

    Args:
        cr: Cairo context
        points: List of (x, y, alpha) tuples
        color: RGB color tuple
        max_radius: Maximum radius of the pointer
    """
    for i, (x, y, alpha) in enumerate(points):
        radius = max_radius * alpha
        cr.set_source_rgba(*color, alpha * 0.8)
        cr.arc(x, y, radius, 0, 2 * math.pi)
        cr.fill()

        if i > 0 and alpha > 0.1:
            prev_x, prev_y, prev_alpha = points[i - 1]
            avg_alpha = (alpha + prev_alpha) / 2
            cr.set_source_rgba(*color, avg_alpha * 0.3)
            cr.set_line_width(max_radius * avg_alpha)
            cr.move_to(prev_x, prev_y)
            cr.line_to(x, y)
            cr.stroke()
