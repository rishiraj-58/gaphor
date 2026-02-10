"""Tests for presentation window and presenter notes."""

import pytest

from gaphor.plugins.presentationmode.model import Presentation, Slide, SlideRegion
from gaphor.plugins.presentationmode.tests.conftest import (
    MockDiagram,
    MockElementFactory,
    MockEventManager,
)


class TestPresentation:
    """Tests for Presentation model in presenter context."""

    def test_presentation_navigation(self):
        """Test presentation slide navigation."""
        diagrams = [MockDiagram(f"d{i}", f"Diagram {i}") for i in range(5)]
        presentation = Presentation()
        for d in diagrams:
            presentation.add_slide(Slide(diagram=d))

        assert presentation.current_index == 0
        assert presentation.get_current_slide().diagram.id == "d0"

        presentation.next_slide()
        assert presentation.current_index == 1

        presentation.next_slide()
        presentation.next_slide()
        presentation.next_slide()
        assert presentation.current_index == 4

        presentation.next_slide()
        assert presentation.current_index == 4

        presentation.previous_slide()
        assert presentation.current_index == 3

    def test_presentation_go_to_slide(self):
        """Test jumping to specific slide."""
        diagrams = [MockDiagram(f"d{i}", f"Diagram {i}") for i in range(5)]
        presentation = Presentation()
        for d in diagrams:
            presentation.add_slide(Slide(diagram=d))

        presentation.go_to_slide(3)
        assert presentation.current_index == 3

        presentation.go_to_slide(0)
        assert presentation.current_index == 0

        presentation.go_to_slide(10)
        assert presentation.current_index == 0


class TestSlideWithRegion:
    """Tests for slides with focus regions."""

    def test_slide_without_region(self):
        """Test slide without custom region."""
        diagram = MockDiagram()
        slide = Slide(diagram=diagram)
        assert slide.region is None

    def test_slide_with_region(self):
        """Test slide with custom focus region."""
        diagram = MockDiagram()
        region = SlideRegion(x=100, y=100, width=400, height=300)
        slide = Slide(diagram=diagram, region=region)

        assert slide.region is not None
        assert slide.region.x == 100
        assert slide.region.y == 100
        assert slide.region.width == 400
        assert slide.region.height == 300

    def test_slide_with_notes(self):
        """Test slide with presenter notes."""
        diagram = MockDiagram()
        slide = Slide(
            diagram=diagram,
            title="Introduction",
            notes="Talk about the main concepts here.\n\nMention the key points.",
        )

        assert slide.title == "Introduction"
        assert "main concepts" in slide.notes
        assert slide.notes.count("\n") == 2


class TestPresenterNotesModel:
    """Tests for presenter notes functionality."""

    def test_slide_notes_empty_default(self):
        """Test slide notes are empty by default."""
        slide = Slide(diagram=MockDiagram())
        assert slide.notes == ""

    def test_slide_notes_preserved(self):
        """Test slide notes are preserved through operations."""
        presentation = Presentation()
        slide = Slide(diagram=MockDiagram(), notes="Important note")
        presentation.add_slide(slide)

        retrieved = presentation.get_current_slide()
        assert retrieved.notes == "Important note"

    def test_slide_title_default(self):
        """Test slide title is empty by default."""
        slide = Slide(diagram=MockDiagram())
        assert slide.title == ""


class TestPresentationSlideOrder:
    """Tests for slide ordering."""

    def test_slides_maintain_order(self):
        """Test slides maintain insertion order."""
        presentation = Presentation()
        for i in range(5):
            presentation.add_slide(Slide(diagram=MockDiagram(f"d{i}")))

        for i in range(5):
            presentation.go_to_slide(i)
            assert presentation.get_current_slide().diagram.id == f"d{i}"

    def test_move_slide_up(self):
        """Test moving slide up in order."""
        presentation = Presentation()
        for i in range(3):
            presentation.add_slide(Slide(diagram=MockDiagram(f"d{i}")))

        presentation.move_slide(2, 0)

        assert presentation.slides[0].diagram.id == "d2"
        assert presentation.slides[1].diagram.id == "d0"
        assert presentation.slides[2].diagram.id == "d1"

    def test_move_slide_down(self):
        """Test moving slide down in order."""
        presentation = Presentation()
        for i in range(3):
            presentation.add_slide(Slide(diagram=MockDiagram(f"d{i}")))

        presentation.move_slide(0, 2)

        assert presentation.slides[0].diagram.id == "d1"
        assert presentation.slides[1].diagram.id == "d2"
        assert presentation.slides[2].diagram.id == "d0"

    def test_remove_slide_updates_index(self):
        """Test removing slide updates current index."""
        presentation = Presentation()
        for i in range(3):
            presentation.add_slide(Slide(diagram=MockDiagram(f"d{i}")))

        presentation.go_to_slide(2)
        assert presentation.current_index == 2

        presentation.remove_slide(2)
        assert presentation.current_index == 1

    def test_remove_middle_slide(self):
        """Test removing middle slide."""
        presentation = Presentation()
        for i in range(3):
            presentation.add_slide(Slide(diagram=MockDiagram(f"d{i}")))

        presentation.remove_slide(1)

        assert len(presentation.slides) == 2
        assert presentation.slides[0].diagram.id == "d0"
        assert presentation.slides[1].diagram.id == "d2"


class TestLinkedDiagrams:
    """Tests for linked diagram functionality."""

    def test_slide_linked_diagram_default(self):
        """Test linked diagram is None by default."""
        slide = Slide(diagram=MockDiagram())
        assert slide.linked_diagram_id is None

    def test_slide_with_linked_diagram(self):
        """Test slide with linked diagram."""
        slide = Slide(diagram=MockDiagram("d1"), linked_diagram_id="d2")
        assert slide.linked_diagram_id == "d2"


class TestRevealElements:
    """Tests for element reveal functionality."""

    def test_slide_reveal_elements_default(self):
        """Test reveal elements are empty by default."""
        slide = Slide(diagram=MockDiagram())
        assert slide.reveal_elements == []

    def test_slide_with_reveal_elements(self):
        """Test slide with reveal elements."""
        slide = Slide(
            diagram=MockDiagram(),
            reveal_elements=["elem1", "elem2", "elem3"],
        )
        assert len(slide.reveal_elements) == 3
        assert "elem1" in slide.reveal_elements
