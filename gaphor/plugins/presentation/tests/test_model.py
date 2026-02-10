"""Tests for the presentation data model."""

import json

import pytest

from gaphor.plugins.presentation.model import (
    DrawingAnnotation,
    DrawingToolType,
    Hotspot,
    HotspotAction,
    Presentation,
    Slide,
    ViewRegion,
)


class TestViewRegion:
    def test_create_view_region(self):
        region = ViewRegion(x=10, y=20, width=800, height=600, zoom=1.5)

        assert region.x == 10
        assert region.y == 20
        assert region.width == 800
        assert region.height == 600
        assert region.zoom == 1.5

    def test_view_region_default_zoom(self):
        region = ViewRegion(x=0, y=0, width=100, height=100)

        assert region.zoom == 1.0

    def test_view_region_to_dict(self):
        region = ViewRegion(x=10, y=20, width=800, height=600, zoom=2.0)
        data = region.to_dict()

        assert data == {
            "x": 10,
            "y": 20,
            "width": 800,
            "height": 600,
            "zoom": 2.0,
        }

    def test_view_region_from_dict(self):
        data = {"x": 50, "y": 100, "width": 1920, "height": 1080, "zoom": 0.5}
        region = ViewRegion.from_dict(data)

        assert region.x == 50
        assert region.y == 100
        assert region.width == 1920
        assert region.height == 1080
        assert region.zoom == 0.5

    def test_view_region_from_dict_with_defaults(self):
        region = ViewRegion.from_dict({})

        assert region.x == 0
        assert region.y == 0
        assert region.width == 800
        assert region.height == 600
        assert region.zoom == 1.0


class TestHotspot:
    def test_create_hotspot(self):
        hotspot = Hotspot(
            x=100,
            y=200,
            width=50,
            height=50,
            action=HotspotAction.NAVIGATE_SLIDE,
            target="slide-123",
            tooltip="Go to next slide",
        )

        assert hotspot.x == 100
        assert hotspot.y == 200
        assert hotspot.action == HotspotAction.NAVIGATE_SLIDE
        assert hotspot.target == "slide-123"

    def test_hotspot_contains_point(self):
        hotspot = Hotspot(x=100, y=100, width=50, height=50)

        assert hotspot.contains_point(125, 125)
        assert hotspot.contains_point(100, 100)
        assert hotspot.contains_point(150, 150)
        assert not hotspot.contains_point(99, 100)
        assert not hotspot.contains_point(151, 100)

    def test_hotspot_to_dict(self):
        hotspot = Hotspot(
            id="test-id",
            x=10,
            y=20,
            width=30,
            height=40,
            action=HotspotAction.EXTERNAL_LINK,
            target="https://example.com",
            tooltip="Visit website",
            visible=False,
        )
        data = hotspot.to_dict()

        assert data["id"] == "test-id"
        assert data["x"] == 10
        assert data["action"] == "external_link"
        assert data["visible"] is False

    def test_hotspot_from_dict(self):
        data = {
            "id": "hot-1",
            "x": 50,
            "y": 60,
            "width": 70,
            "height": 80,
            "action": "reveal_layer",
            "target": "layer-details",
            "tooltip": "",
            "visible": True,
        }
        hotspot = Hotspot.from_dict(data)

        assert hotspot.id == "hot-1"
        assert hotspot.action == HotspotAction.REVEAL_LAYER
        assert hotspot.target == "layer-details"


class TestDrawingAnnotation:
    def test_create_annotation(self):
        annotation = DrawingAnnotation(
            tool=DrawingToolType.PEN,
            color=(1.0, 0.0, 0.0, 1.0),
            line_width=3.0,
            points=[(10, 10), (20, 20), (30, 15)],
        )

        assert annotation.tool == DrawingToolType.PEN
        assert len(annotation.points) == 3

    def test_annotation_to_dict(self):
        annotation = DrawingAnnotation(
            id="ann-1",
            tool=DrawingToolType.HIGHLIGHTER,
            color=(1.0, 1.0, 0.0, 0.5),
            line_width=20.0,
            points=[(0, 0), (100, 100)],
        )
        data = annotation.to_dict()

        assert data["tool"] == "highlighter"
        assert data["color"] == [1.0, 1.0, 0.0, 0.5]
        assert data["line_width"] == 20.0

    def test_annotation_from_dict(self):
        data = {
            "id": "ann-2",
            "tool": "arrow",
            "color": [0.0, 0.0, 1.0, 1.0],
            "line_width": 5.0,
            "points": [(50, 50), (150, 150)],
            "text": "",
        }
        annotation = DrawingAnnotation.from_dict(data)

        assert annotation.tool == DrawingToolType.ARROW
        assert annotation.color == (0.0, 0.0, 1.0, 1.0)


class TestSlide:
    def test_create_slide(self):
        slide = Slide(
            title="Introduction",
            diagram_id="diagram-123",
            notes="Welcome to the presentation",
        )

        assert slide.title == "Introduction"
        assert slide.diagram_id == "diagram-123"
        assert slide.notes == "Welcome to the presentation"
        assert slide.hotspots == []
        assert slide.annotations == []

    def test_slide_with_region(self):
        region = ViewRegion(x=100, y=200, width=800, height=600, zoom=1.5)
        slide = Slide(title="Test", region=region)

        assert slide.region.x == 100
        assert slide.region.zoom == 1.5

    def test_slide_to_dict(self):
        slide = Slide(
            id="slide-1",
            title="Overview",
            diagram_id="diag-1",
            notes="This is the overview",
            transition_duration=0.8,
        )
        data = slide.to_dict()

        assert data["id"] == "slide-1"
        assert data["title"] == "Overview"
        assert data["transition_duration"] == 0.8
        assert "region" in data
        assert "hotspots" in data

    def test_slide_from_dict(self):
        data = {
            "id": "slide-2",
            "title": "Details",
            "diagram_id": "diag-2",
            "region": {"x": 0, "y": 0, "width": 1024, "height": 768, "zoom": 2.0},
            "notes": "Detailed view",
            "hotspots": [],
            "annotations": [],
            "transition_duration": 1.0,
            "visible_layers": ["layer1"],
        }
        slide = Slide.from_dict(data)

        assert slide.title == "Details"
        assert slide.region.width == 1024
        assert slide.transition_duration == 1.0
        assert slide.visible_layers == ["layer1"]


class TestPresentation:
    def test_create_presentation(self):
        presentation = Presentation(title="My Presentation")

        assert presentation.title == "My Presentation"
        assert presentation.slides == []
        assert presentation.default_transition_duration == 0.5

    def test_add_slide(self):
        presentation = Presentation()
        slide = presentation.add_slide()

        assert len(presentation.slides) == 1
        assert slide in presentation.slides

    def test_add_existing_slide(self):
        presentation = Presentation()
        slide = Slide(title="Test Slide")
        result = presentation.add_slide(slide)

        assert result is slide
        assert slide in presentation.slides

    def test_remove_slide(self):
        presentation = Presentation()
        slide = presentation.add_slide()
        slide_id = slide.id

        result = presentation.remove_slide(slide_id)

        assert result is True
        assert len(presentation.slides) == 0

    def test_remove_nonexistent_slide(self):
        presentation = Presentation()

        result = presentation.remove_slide("nonexistent")

        assert result is False

    def test_get_slide(self):
        presentation = Presentation()
        slide = presentation.add_slide(Slide(title="Found"))

        result = presentation.get_slide(slide.id)

        assert result is slide

    def test_get_slide_nonexistent(self):
        presentation = Presentation()

        result = presentation.get_slide("nonexistent")

        assert result is None

    def test_get_slide_index(self):
        presentation = Presentation()
        presentation.add_slide(Slide(title="First"))
        slide2 = presentation.add_slide(Slide(title="Second"))
        presentation.add_slide(Slide(title="Third"))

        index = presentation.get_slide_index(slide2.id)

        assert index == 1

    def test_get_slide_index_nonexistent(self):
        presentation = Presentation()

        index = presentation.get_slide_index("nonexistent")

        assert index == -1

    def test_move_slide(self):
        presentation = Presentation()
        slide1 = presentation.add_slide(Slide(title="First"))
        slide2 = presentation.add_slide(Slide(title="Second"))
        slide3 = presentation.add_slide(Slide(title="Third"))

        result = presentation.move_slide(slide3.id, 0)

        assert result is True
        assert presentation.slides[0] is slide3
        assert presentation.slides[1] is slide1
        assert presentation.slides[2] is slide2

    def test_presentation_to_json(self):
        presentation = Presentation(title="JSON Test")
        presentation.add_slide(Slide(title="Slide 1"))

        json_str = presentation.to_json()
        data = json.loads(json_str)

        assert data["title"] == "JSON Test"
        assert len(data["slides"]) == 1

    def test_presentation_from_json(self):
        json_str = """{
            "id": "pres-1",
            "title": "Loaded Presentation",
            "slides": [
                {
                    "id": "s1",
                    "title": "First Slide",
                    "diagram_id": "d1",
                    "region": {"x": 0, "y": 0, "width": 800, "height": 600, "zoom": 1},
                    "notes": "",
                    "hotspots": [],
                    "annotations": [],
                    "transition_duration": 0.5,
                    "visible_layers": []
                }
            ],
            "default_transition_duration": 0.5,
            "show_hotspot_indicators": true,
            "loop_presentation": false
        }"""

        presentation = Presentation.from_json(json_str)

        assert presentation.title == "Loaded Presentation"
        assert len(presentation.slides) == 1
        assert presentation.slides[0].title == "First Slide"

    def test_presentation_roundtrip(self):
        original = Presentation(title="Roundtrip Test")
        original.show_hotspot_indicators = False
        original.loop_presentation = True

        slide = Slide(
            title="Test Slide",
            diagram_id="diagram-123",
            notes="Test notes",
            transition_duration=1.5,
        )
        slide.hotspots.append(
            Hotspot(
                x=10,
                y=20,
                action=HotspotAction.SHOW_TOOLTIP,
                tooltip="Hello",
            )
        )
        original.add_slide(slide)

        json_str = original.to_json()
        loaded = Presentation.from_json(json_str)

        assert loaded.title == original.title
        assert loaded.show_hotspot_indicators == original.show_hotspot_indicators
        assert loaded.loop_presentation == original.loop_presentation
        assert len(loaded.slides) == 1
        assert loaded.slides[0].title == slide.title
        assert loaded.slides[0].notes == slide.notes
        assert len(loaded.slides[0].hotspots) == 1
        assert loaded.slides[0].hotspots[0].tooltip == "Hello"
