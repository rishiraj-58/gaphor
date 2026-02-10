"""Tests for the drawing tools."""

import pytest

from gaphor.plugins.presentation.drawing import DrawingState, DrawingToolHandler
from gaphor.plugins.presentation.model import DrawingToolType


class TestDrawingState:
    def test_default_state(self):
        state = DrawingState()

        assert state.active_tool == DrawingToolType.PEN
        assert state.color == (1.0, 0.0, 0.0, 1.0)
        assert state.line_width == 3.0
        assert not state.is_drawing
        assert state.current_annotation is None


class TestDrawingToolHandler:
    def test_create_handler(self):
        handler = DrawingToolHandler()

        assert handler.state.active_tool == DrawingToolType.PEN
        assert len(handler.annotations) == 0

    def test_set_tool_pen(self):
        handler = DrawingToolHandler()
        handler.set_tool(DrawingToolType.PEN)

        assert handler.state.active_tool == DrawingToolType.PEN
        assert handler.state.line_width == 3.0

    def test_set_tool_highlighter(self):
        handler = DrawingToolHandler()
        handler.set_tool(DrawingToolType.HIGHLIGHTER)

        assert handler.state.active_tool == DrawingToolType.HIGHLIGHTER
        assert handler.state.line_width == 20.0
        assert handler.state.color[3] == 0.4  # Semi-transparent

    def test_set_tool_eraser(self):
        handler = DrawingToolHandler()
        handler.set_tool(DrawingToolType.ERASER)

        assert handler.state.active_tool == DrawingToolType.ERASER
        assert handler.state.line_width == 20.0

    def test_set_color_tuple(self):
        handler = DrawingToolHandler()
        handler.set_color((0.0, 1.0, 0.0, 1.0))

        assert handler.state.color == (0.0, 1.0, 0.0, 1.0)

    def test_set_color_string(self):
        handler = DrawingToolHandler()
        handler.set_color("blue")

        assert handler.state.color == DrawingToolHandler.COLORS["blue"]

    def test_set_color_highlighter_transparency(self):
        handler = DrawingToolHandler()
        handler.set_tool(DrawingToolType.HIGHLIGHTER)
        handler.set_color("red")

        # Highlighter should force semi-transparency
        assert handler.state.color[3] == 0.4

    def test_set_line_width(self):
        handler = DrawingToolHandler()
        handler.set_line_width(10.0)

        assert handler.state.line_width == 10.0

    def test_set_line_width_clamped(self):
        handler = DrawingToolHandler()

        handler.set_line_width(0.5)
        assert handler.state.line_width == 1.0

        handler.set_line_width(100.0)
        assert handler.state.line_width == 50.0

    def test_start_drawing(self):
        handler = DrawingToolHandler()
        handler.start_drawing(100, 200)

        assert handler.state.is_drawing
        assert handler.state.current_annotation is not None
        assert handler.state.current_annotation.points == [(100, 200)]

    def test_continue_drawing_pen(self):
        handler = DrawingToolHandler()
        handler.start_drawing(100, 100)
        handler.continue_drawing(150, 150)
        handler.continue_drawing(200, 200)

        assert len(handler.state.current_annotation.points) == 3

    def test_continue_drawing_rectangle(self):
        handler = DrawingToolHandler()
        handler.set_tool(DrawingToolType.RECTANGLE)
        handler.start_drawing(100, 100)
        handler.continue_drawing(200, 200)

        # Rectangle should only have start and end points
        assert len(handler.state.current_annotation.points) == 2

    def test_end_drawing(self):
        handler = DrawingToolHandler()
        handler.start_drawing(100, 100)
        handler.continue_drawing(150, 150)
        annotation = handler.end_drawing(200, 200)

        assert annotation is not None
        assert not handler.state.is_drawing
        assert handler.state.current_annotation is None
        assert annotation in handler.annotations

    def test_end_drawing_not_started(self):
        handler = DrawingToolHandler()
        result = handler.end_drawing(100, 100)

        assert result is None

    def test_undo(self):
        handler = DrawingToolHandler()
        handler.start_drawing(100, 100)
        handler.end_drawing(200, 200)

        assert len(handler.annotations) == 1

        undone = handler.undo()

        assert undone is not None
        assert len(handler.annotations) == 0

    def test_undo_empty(self):
        handler = DrawingToolHandler()
        result = handler.undo()

        assert result is None

    def test_redo(self):
        handler = DrawingToolHandler()
        handler.start_drawing(100, 100)
        handler.end_drawing(200, 200)
        handler.undo()

        assert len(handler.annotations) == 0

        redone = handler.redo()

        assert redone is not None
        assert len(handler.annotations) == 1

    def test_redo_empty(self):
        handler = DrawingToolHandler()
        result = handler.redo()

        assert result is None

    def test_clear(self):
        handler = DrawingToolHandler()
        handler.start_drawing(100, 100)
        handler.end_drawing(200, 200)
        handler.start_drawing(300, 300)
        handler.end_drawing(400, 400)

        assert len(handler.annotations) == 2

        handler.clear()

        assert len(handler.annotations) == 0

    def test_eraser_removes_annotations(self):
        handler = DrawingToolHandler()

        # Create an annotation
        handler.start_drawing(100, 100)
        handler.continue_drawing(150, 150)
        handler.end_drawing(200, 200)

        assert len(handler.annotations) == 1

        # Switch to eraser and erase near the annotation
        handler.set_tool(DrawingToolType.ERASER)
        handler.start_drawing(100, 100)  # Near a point in the annotation

        # Annotation should be removed
        assert len(handler.annotations) == 0
