"""Tests for presentation model classes."""

import pytest

from gaphor.plugins.presentationmode.model import (
    DrawingAnnotation,
    Presentation,
    Slide,
    SlideRegion,
)


class MockDiagram:
    def __init__(self, id, name="Test Diagram"):
        self.id = id
        self.name = name


def test_slide_region_creation():
    region = SlideRegion(x=10, y=20, width=100, height=200)
    assert region.x == 10
    assert region.y == 20
    assert region.width == 100
    assert region.height == 200


def test_slide_creation():
    diagram = MockDiagram("1")
    slide = Slide(diagram=diagram)
    assert slide.diagram == diagram
    assert slide.region is None
    assert slide.notes == ""
    assert slide.title == ""


def test_slide_with_region():
    diagram = MockDiagram("1")
    region = SlideRegion(x=0, y=0, width=500, height=400)
    slide = Slide(diagram=diagram, region=region, notes="Test notes", title="Test Title")
    assert slide.region == region
    assert slide.notes == "Test notes"
    assert slide.title == "Test Title"


def test_presentation_creation():
    presentation = Presentation(name="My Presentation")
    assert presentation.name == "My Presentation"
    assert presentation.slides == []
    assert presentation.current_index == 0


def test_presentation_add_slide():
    presentation = Presentation()
    diagram = MockDiagram("1")
    slide = Slide(diagram=diagram)
    presentation.add_slide(slide)
    assert len(presentation.slides) == 1
    assert presentation.slides[0] == slide


def test_presentation_remove_slide():
    presentation = Presentation()
    for i in range(3):
        presentation.add_slide(Slide(diagram=MockDiagram(str(i))))

    presentation.remove_slide(1)
    assert len(presentation.slides) == 2
    assert presentation.slides[0].diagram.id == "0"
    assert presentation.slides[1].diagram.id == "2"


def test_presentation_remove_slide_adjusts_current_index():
    presentation = Presentation()
    for i in range(3):
        presentation.add_slide(Slide(diagram=MockDiagram(str(i))))

    presentation.current_index = 2
    presentation.remove_slide(2)
    assert presentation.current_index == 1


def test_presentation_move_slide():
    presentation = Presentation()
    for i in range(3):
        presentation.add_slide(Slide(diagram=MockDiagram(str(i))))

    presentation.move_slide(0, 2)
    assert presentation.slides[0].diagram.id == "1"
    assert presentation.slides[1].diagram.id == "2"
    assert presentation.slides[2].diagram.id == "0"


def test_presentation_get_current_slide():
    presentation = Presentation()
    diagram = MockDiagram("1")
    slide = Slide(diagram=diagram)
    presentation.add_slide(slide)

    assert presentation.get_current_slide() == slide


def test_presentation_get_current_slide_empty():
    presentation = Presentation()
    assert presentation.get_current_slide() is None


def test_presentation_next_slide():
    presentation = Presentation()
    for i in range(3):
        presentation.add_slide(Slide(diagram=MockDiagram(str(i))))

    assert presentation.current_index == 0
    presentation.next_slide()
    assert presentation.current_index == 1
    presentation.next_slide()
    assert presentation.current_index == 2
    presentation.next_slide()
    assert presentation.current_index == 2


def test_presentation_previous_slide():
    presentation = Presentation()
    for i in range(3):
        presentation.add_slide(Slide(diagram=MockDiagram(str(i))))

    presentation.current_index = 2
    presentation.previous_slide()
    assert presentation.current_index == 1
    presentation.previous_slide()
    assert presentation.current_index == 0
    presentation.previous_slide()
    assert presentation.current_index == 0


def test_presentation_go_to_slide():
    presentation = Presentation()
    for i in range(5):
        presentation.add_slide(Slide(diagram=MockDiagram(str(i))))

    presentation.go_to_slide(3)
    assert presentation.current_index == 3

    presentation.go_to_slide(10)
    assert presentation.current_index == 3

    presentation.go_to_slide(-1)
    assert presentation.current_index == 3


def test_drawing_annotation_creation():
    annotation = DrawingAnnotation(
        points=[(0, 0), (10, 10), (20, 20)],
        color=(1.0, 0.0, 0.0, 1.0),
        line_width=5.0,
        tool="pen",
    )
    assert len(annotation.points) == 3
    assert annotation.color == (1.0, 0.0, 0.0, 1.0)
    assert annotation.line_width == 5.0
    assert annotation.tool == "pen"


def test_drawing_annotation_defaults():
    annotation = DrawingAnnotation()
    assert annotation.points == []
    assert annotation.color == (1.0, 0.0, 0.0, 1.0)
    assert annotation.line_width == 3.0
    assert annotation.tool == "pen"
