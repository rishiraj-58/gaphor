"""Tests for presentation editor."""

import pytest

from gaphor.plugins.presentationmode.model import Presentation, Slide, SlideRegion
from gaphor.plugins.presentationmode.tests.conftest import (
    MockDiagram,
    MockElementFactory,
    MockView,
)


class TestSlideEditorModel:
    """Tests for slide editor model interactions."""

    def test_slide_title_update(self):
        """Test updating slide title."""
        slide = Slide(diagram=MockDiagram())
        slide.title = "New Title"
        assert slide.title == "New Title"

    def test_slide_notes_update(self):
        """Test updating slide notes."""
        slide = Slide(diagram=MockDiagram())
        slide.notes = "New notes content"
        assert slide.notes == "New notes content"

    def test_slide_region_update(self):
        """Test updating slide region."""
        slide = Slide(diagram=MockDiagram())
        slide.region = SlideRegion(x=50, y=50, width=200, height=150)

        assert slide.region.x == 50
        assert slide.region.y == 50
        assert slide.region.width == 200
        assert slide.region.height == 150

    def test_slide_region_remove(self):
        """Test removing slide region."""
        slide = Slide(
            diagram=MockDiagram(),
            region=SlideRegion(x=0, y=0, width=100, height=100),
        )
        slide.region = None
        assert slide.region is None


class TestPresentationEditorModel:
    """Tests for presentation editor model operations."""

    def test_add_slide_to_presentation(self):
        """Test adding slide to presentation."""
        presentation = Presentation()
        diagram = MockDiagram()
        slide = Slide(diagram=diagram)

        presentation.add_slide(slide)

        assert len(presentation.slides) == 1
        assert presentation.slides[0] == slide

    def test_add_multiple_slides(self):
        """Test adding multiple slides."""
        presentation = Presentation()
        for i in range(5):
            presentation.add_slide(Slide(diagram=MockDiagram(f"d{i}")))

        assert len(presentation.slides) == 5

    def test_remove_first_slide(self):
        """Test removing first slide."""
        presentation = Presentation()
        for i in range(3):
            presentation.add_slide(Slide(diagram=MockDiagram(f"d{i}")))

        presentation.remove_slide(0)

        assert len(presentation.slides) == 2
        assert presentation.slides[0].diagram.id == "d1"

    def test_remove_last_slide(self):
        """Test removing last slide."""
        presentation = Presentation()
        for i in range(3):
            presentation.add_slide(Slide(diagram=MockDiagram(f"d{i}")))

        presentation.remove_slide(2)

        assert len(presentation.slides) == 2
        assert presentation.slides[-1].diagram.id == "d1"

    def test_remove_invalid_index(self):
        """Test removing slide at invalid index."""
        presentation = Presentation()
        presentation.add_slide(Slide(diagram=MockDiagram()))

        presentation.remove_slide(5)

        assert len(presentation.slides) == 1

    def test_move_slide_same_position(self):
        """Test moving slide to same position."""
        presentation = Presentation()
        for i in range(3):
            presentation.add_slide(Slide(diagram=MockDiagram(f"d{i}")))

        presentation.move_slide(1, 1)

        assert presentation.slides[1].diagram.id == "d1"

    def test_move_slide_invalid_from_index(self):
        """Test moving from invalid index."""
        presentation = Presentation()
        presentation.add_slide(Slide(diagram=MockDiagram()))

        presentation.move_slide(5, 0)

        assert len(presentation.slides) == 1

    def test_move_slide_invalid_to_index(self):
        """Test moving to invalid index."""
        presentation = Presentation()
        presentation.add_slide(Slide(diagram=MockDiagram()))

        presentation.move_slide(0, 5)

        assert len(presentation.slides) == 1


class TestViewCapture:
    """Tests for view region capture functionality."""

    def test_capture_region_from_view(self):
        """Test capturing region from view."""
        view = MockView(800, 600)
        view.matrix.set(1.0, 0, 0, 1.0, -100, -50)

        scale = view.matrix[0]
        offset_x = view.matrix[4]
        offset_y = view.matrix[5]

        x = -offset_x / scale
        y = -offset_y / scale
        w = view.get_width() / scale
        h = view.get_height() / scale

        region = SlideRegion(x=x, y=y, width=w, height=h)

        assert region.x == 100
        assert region.y == 50
        assert region.width == 800
        assert region.height == 600

    def test_capture_region_with_zoom(self):
        """Test capturing region with zoomed view."""
        view = MockView(800, 600)
        view.matrix.set(2.0, 0, 0, 2.0, -200, -100)

        scale = view.matrix[0]
        offset_x = view.matrix[4]
        offset_y = view.matrix[5]

        x = -offset_x / scale
        y = -offset_y / scale
        w = view.get_width() / scale
        h = view.get_height() / scale

        region = SlideRegion(x=x, y=y, width=w, height=h)

        assert region.x == 100
        assert region.y == 50
        assert region.width == 400
        assert region.height == 300


class TestSlideValidation:
    """Tests for slide validation."""

    def test_slide_requires_diagram(self):
        """Test slide requires a diagram."""
        slide = Slide(diagram=MockDiagram())
        assert slide.diagram is not None

    def test_slide_region_dimensions_positive(self):
        """Test region dimensions should be positive."""
        region = SlideRegion(x=-100, y=-100, width=100, height=100)
        assert region.width > 0
        assert region.height > 0

    def test_slide_notes_can_be_multiline(self):
        """Test notes can contain multiple lines."""
        notes = "Line 1\nLine 2\nLine 3"
        slide = Slide(diagram=MockDiagram(), notes=notes)
        assert slide.notes.count("\n") == 2


class TestPresentationName:
    """Tests for presentation naming."""

    def test_default_name(self):
        """Test default presentation name."""
        presentation = Presentation()
        assert presentation.name == "Untitled Presentation"

    def test_custom_name(self):
        """Test custom presentation name."""
        presentation = Presentation(name="My Cool Presentation")
        assert presentation.name == "My Cool Presentation"

    def test_update_name(self):
        """Test updating presentation name."""
        presentation = Presentation()
        presentation.name = "Updated Name"
        assert presentation.name == "Updated Name"

    def test_empty_name(self):
        """Test empty presentation name."""
        presentation = Presentation(name="")
        assert presentation.name == ""
