"""Tests for drawing tools."""

import pytest

from gaphor.plugins.presentationmode.drawing import (
    TOOL_COLORS,
    TOOL_LINE_WIDTHS,
    DrawingState,
    LaserPointerState,
)
from gaphor.plugins.presentationmode.model import DrawingAnnotation


class TestDrawingState:
    """Tests for DrawingState."""

    def test_default_state(self):
        """Test default drawing state."""
        state = DrawingState()
        assert state.enabled is False
        assert state.current_tool == "pen"
        assert state.line_width == 3.0
        assert state.annotations == []
        assert state.current_points == []
        assert state.is_drawing is False

    def test_state_with_custom_values(self):
        """Test state with custom values."""
        state = DrawingState(
            enabled=True,
            current_tool="highlighter",
            color=(0.0, 0.0, 1.0, 0.5),
            line_width=10.0,
        )
        assert state.enabled is True
        assert state.current_tool == "highlighter"
        assert state.color == (0.0, 0.0, 1.0, 0.5)
        assert state.line_width == 10.0


class TestDrawingAnnotation:
    """Tests for DrawingAnnotation."""

    def test_default_annotation(self):
        """Test default annotation values."""
        annotation = DrawingAnnotation()
        assert annotation.points == []
        assert annotation.color == (1.0, 0.0, 0.0, 1.0)
        assert annotation.line_width == 3.0
        assert annotation.tool == "pen"

    def test_annotation_with_points(self):
        """Test annotation with points."""
        points = [(0, 0), (10, 10), (20, 5), (30, 15)]
        annotation = DrawingAnnotation(points=points)
        assert len(annotation.points) == 4
        assert annotation.points[0] == (0, 0)
        assert annotation.points[-1] == (30, 15)

    def test_annotation_with_custom_color(self):
        """Test annotation with custom color."""
        annotation = DrawingAnnotation(color=(0.0, 1.0, 0.0, 1.0))
        assert annotation.color == (0.0, 1.0, 0.0, 1.0)

    def test_annotation_tool_types(self):
        """Test different annotation tool types."""
        for tool in ["pen", "highlighter", "arrow", "rectangle", "ellipse", "line"]:
            annotation = DrawingAnnotation(tool=tool)
            assert annotation.tool == tool


class TestToolColors:
    """Tests for tool color definitions."""

    def test_all_colors_defined(self):
        """Test all expected colors are defined."""
        expected_colors = ["red", "blue", "green", "yellow", "black", "white"]
        for color in expected_colors:
            assert color in TOOL_COLORS

    def test_color_values_valid(self):
        """Test color values are valid RGBA tuples."""
        for name, color in TOOL_COLORS.items():
            assert len(color) == 4, f"Color {name} should have 4 components"
            for component in color:
                assert 0.0 <= component <= 1.0, f"Color {name} component out of range"

    def test_red_is_red(self):
        """Test red color is correct."""
        assert TOOL_COLORS["red"] == (1.0, 0.0, 0.0, 1.0)

    def test_blue_is_blue(self):
        """Test blue color is correct."""
        assert TOOL_COLORS["blue"] == (0.0, 0.0, 1.0, 1.0)

    def test_yellow_is_semi_transparent(self):
        """Test yellow (highlighter) has transparency."""
        r, g, b, a = TOOL_COLORS["yellow"]
        assert a < 1.0


class TestToolLineWidths:
    """Tests for tool line width definitions."""

    def test_all_tools_have_widths(self):
        """Test all expected tools have line widths."""
        expected_tools = ["pen", "highlighter", "arrow", "rectangle", "ellipse"]
        for tool in expected_tools:
            assert tool in TOOL_LINE_WIDTHS

    def test_highlighter_is_wider(self):
        """Test highlighter is wider than pen."""
        assert TOOL_LINE_WIDTHS["highlighter"] > TOOL_LINE_WIDTHS["pen"]

    def test_pen_default_width(self):
        """Test pen default width."""
        assert TOOL_LINE_WIDTHS["pen"] == 3.0

    def test_highlighter_width(self):
        """Test highlighter width for visibility."""
        assert TOOL_LINE_WIDTHS["highlighter"] >= 15.0


class TestLaserPointerState:
    """Tests for LaserPointerState."""

    def test_default_state(self):
        """Test default laser pointer state."""
        state = LaserPointerState()
        assert state.enabled is False
        assert state.x == 0.0
        assert state.y == 0.0
        assert state.visible is False
        assert state.size == 12.0
        assert state.trail == []

    def test_state_with_position(self):
        """Test state with position."""
        state = LaserPointerState()
        state.x = 100.0
        state.y = 200.0
        state.visible = True

        assert state.x == 100.0
        assert state.y == 200.0
        assert state.visible is True

    def test_trail_tracking(self):
        """Test trail point tracking."""
        state = LaserPointerState()
        state.trail.append((10.0, 20.0, 0.5))
        state.trail.append((15.0, 25.0, 0.4))

        assert len(state.trail) == 2
        assert state.trail[0] == (10.0, 20.0, 0.5)

    def test_trail_max_length(self):
        """Test trail has max length setting."""
        state = LaserPointerState()
        assert state.trail_max_length == 20

    def test_custom_color(self):
        """Test custom laser pointer color."""
        state = LaserPointerState(color=(0.0, 1.0, 0.0, 1.0))
        assert state.color == (0.0, 1.0, 0.0, 1.0)

    def test_custom_size(self):
        """Test custom laser pointer size."""
        state = LaserPointerState(size=20.0)
        assert state.size == 20.0


class TestAnnotationManagement:
    """Tests for managing annotations."""

    def test_add_annotation(self):
        """Test adding annotation to state."""
        state = DrawingState()
        annotation = DrawingAnnotation(points=[(0, 0), (10, 10)])
        state.annotations.append(annotation)

        assert len(state.annotations) == 1

    def test_clear_annotations(self):
        """Test clearing all annotations."""
        state = DrawingState()
        state.annotations.append(DrawingAnnotation())
        state.annotations.append(DrawingAnnotation())
        state.annotations.clear()

        assert len(state.annotations) == 0

    def test_undo_annotation(self):
        """Test undoing last annotation."""
        state = DrawingState()
        state.annotations.append(DrawingAnnotation(tool="pen"))
        state.annotations.append(DrawingAnnotation(tool="arrow"))

        state.annotations.pop()

        assert len(state.annotations) == 1
        assert state.annotations[0].tool == "pen"

    def test_annotation_count(self):
        """Test counting annotations."""
        state = DrawingState()
        for i in range(5):
            state.annotations.append(DrawingAnnotation())

        assert len(state.annotations) == 5


class TestDrawingTools:
    """Tests for drawing tool behavior."""

    def test_pen_tool_settings(self):
        """Test pen tool settings."""
        assert TOOL_LINE_WIDTHS["pen"] == 3.0

    def test_highlighter_tool_settings(self):
        """Test highlighter tool settings."""
        assert TOOL_LINE_WIDTHS["highlighter"] == 20.0

    def test_shape_tools_settings(self):
        """Test shape tool line widths."""
        assert TOOL_LINE_WIDTHS["rectangle"] == 2.0
        assert TOOL_LINE_WIDTHS["ellipse"] == 2.0
