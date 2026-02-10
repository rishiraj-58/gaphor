"""Integration tests for presentation mode."""

import json
import tempfile
from pathlib import Path

import pytest

from gaphor.plugins.presentationmode.animator import (
    EasingFunction,
    ViewAnimator,
    ease_in_out_cubic,
)
from gaphor.plugins.presentationmode.drawing import DrawingState, LaserPointerState
from gaphor.plugins.presentationmode.hotspots import Hotspot, HotspotManager
from gaphor.plugins.presentationmode.model import (
    DrawingAnnotation,
    Presentation,
    Slide,
    SlideRegion,
)
from gaphor.plugins.presentationmode.tests.conftest import (
    MockDiagram,
    MockElementFactory,
    MockEventManager,
    MockMatrix,
    MockView,
)


class TestFullPresentationWorkflow:
    """Integration test for complete presentation workflow."""

    def test_create_edit_present_save_load_workflow(self):
        """Test the complete workflow from creation to loading."""
        factory = MockElementFactory()
        diagram1 = MockDiagram("diagram-1", "Architecture Overview")
        diagram2 = MockDiagram("diagram-2", "Component Details")
        diagram3 = MockDiagram("diagram-3", "Sequence Flow")
        factory.add_element(diagram1)
        factory.add_element(diagram2)
        factory.add_element(diagram3)

        presentation = Presentation(name="System Architecture Review")

        slide1 = Slide(
            diagram=diagram1,
            title="Introduction",
            notes="Welcome everyone. Today we'll review the system architecture.",
        )
        presentation.add_slide(slide1)

        slide2 = Slide(
            diagram=diagram2,
            title="Core Components",
            notes="Let's look at the main components:\n- Service Layer\n- Data Layer\n- API Gateway",
            region=SlideRegion(x=100, y=100, width=600, height=400),
        )
        presentation.add_slide(slide2)

        slide3 = Slide(
            diagram=diagram3,
            title="Request Flow",
            notes="Here's how a typical request flows through the system.",
            linked_diagram_id="diagram-1",
        )
        presentation.add_slide(slide3)

        assert len(presentation.slides) == 3
        assert presentation.name == "System Architecture Review"

        slide1.title = "Welcome & Introduction"
        slide1.notes += "\n\nRemember to introduce the team members."

        assert "Welcome & Introduction" == presentation.slides[0].title
        assert "team members" in presentation.slides[0].notes

        assert presentation.current_index == 0
        assert presentation.get_current_slide().title == "Welcome & Introduction"

        presentation.next_slide()
        assert presentation.current_index == 1
        assert presentation.get_current_slide().title == "Core Components"
        assert presentation.get_current_slide().region is not None

        presentation.next_slide()
        assert presentation.current_index == 2

        presentation.previous_slide()
        assert presentation.current_index == 1

        presentation.go_to_slide(0)
        assert presentation.current_index == 0

        with tempfile.NamedTemporaryFile(
            suffix=".gaphor-pres", delete=False, mode="w"
        ) as f:
            path = Path(f.name)

        try:
            data = {
                "version": "1.0",
                "name": presentation.name,
                "slides": [],
            }

            for slide in presentation.slides:
                slide_data = {
                    "diagram_id": slide.diagram.id,
                    "title": slide.title,
                    "notes": slide.notes,
                    "reveal_elements": slide.reveal_elements,
                    "linked_diagram_id": slide.linked_diagram_id,
                }
                if slide.region:
                    slide_data["region"] = {
                        "x": slide.region.x,
                        "y": slide.region.y,
                        "width": slide.region.width,
                        "height": slide.region.height,
                    }
                data["slides"].append(slide_data)

            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            assert path.exists()

            with open(path, "r", encoding="utf-8") as f:
                loaded_data = json.load(f)

            loaded_presentation = Presentation(name=loaded_data.get("name", ""))

            for slide_data in loaded_data.get("slides", []):
                diagram = factory.lookup(slide_data["diagram_id"])
                if diagram:
                    region = None
                    if "region" in slide_data:
                        r = slide_data["region"]
                        region = SlideRegion(
                            x=r["x"], y=r["y"], width=r["width"], height=r["height"]
                        )

                    slide = Slide(
                        diagram=diagram,
                        region=region,
                        title=slide_data.get("title", ""),
                        notes=slide_data.get("notes", ""),
                        linked_diagram_id=slide_data.get("linked_diagram_id"),
                    )
                    loaded_presentation.add_slide(slide)

            assert loaded_presentation.name == "System Architecture Review"
            assert len(loaded_presentation.slides) == 3

            assert loaded_presentation.slides[0].title == "Welcome & Introduction"
            assert "team members" in loaded_presentation.slides[0].notes

            assert loaded_presentation.slides[1].region is not None
            assert loaded_presentation.slides[1].region.x == 100
            assert loaded_presentation.slides[1].region.width == 600

            assert loaded_presentation.slides[2].linked_diagram_id == "diagram-1"

        finally:
            path.unlink(missing_ok=True)


class TestDrawingIntegration:
    """Integration tests for drawing functionality."""

    def test_drawing_session_workflow(self):
        """Test a complete drawing session."""
        state = DrawingState()

        state.enabled = True
        state.current_tool = "pen"
        state.color = (1.0, 0.0, 0.0, 1.0)
        state.line_width = 3.0

        annotation1 = DrawingAnnotation(
            points=[(100, 100), (150, 120), (200, 100)],
            color=state.color,
            line_width=state.line_width,
            tool=state.current_tool,
        )
        state.annotations.append(annotation1)

        state.current_tool = "arrow"
        annotation2 = DrawingAnnotation(
            points=[(250, 150), (350, 150)],
            color=state.color,
            line_width=state.line_width,
            tool="arrow",
        )
        state.annotations.append(annotation2)

        state.current_tool = "highlighter"
        state.color = (1.0, 1.0, 0.0, 0.3)
        state.line_width = 20.0
        annotation3 = DrawingAnnotation(
            points=[(100, 200), (200, 200), (300, 200)],
            color=state.color,
            line_width=state.line_width,
            tool="highlighter",
        )
        state.annotations.append(annotation3)

        assert len(state.annotations) == 3
        assert state.annotations[0].tool == "pen"
        assert state.annotations[1].tool == "arrow"
        assert state.annotations[2].tool == "highlighter"

        state.annotations.pop()
        assert len(state.annotations) == 2

        state.annotations.clear()
        assert len(state.annotations) == 0

        state.enabled = False
        assert state.enabled is False


class TestHotspotIntegration:
    """Integration tests for hotspot functionality."""

    def test_hotspot_navigation_workflow(self):
        """Test hotspot navigation workflow."""
        manager = HotspotManager()

        hotspot1 = Hotspot(
            x=100,
            y=100,
            width=50,
            height=50,
            action="navigate",
            target_diagram_id="diagram-details",
            tooltip="Click to see details",
        )
        manager.add_hotspot(hotspot1)

        hotspot2 = Hotspot(
            x=200,
            y=200,
            width=100,
            height=30,
            action="reveal",
            reveal_element_ids=["elem-1", "elem-2"],
            tooltip="Click to reveal",
        )
        manager.add_hotspot(hotspot2)

        navigated_diagrams = []
        revealed_elements = []

        manager.set_navigate_callback(lambda id: navigated_diagrams.append(id))
        manager.set_reveal_callback(lambda ids: revealed_elements.extend(ids))

        matrix = MockMatrix(scale=1.0)

        result = manager.check_click(125, 125, matrix)
        assert result is True
        assert "diagram-details" in navigated_diagrams

        result = manager.check_click(250, 215, matrix)
        assert result is True
        assert "elem-1" in revealed_elements
        assert "elem-2" in revealed_elements
        assert manager.is_element_revealed("elem-1")
        assert manager.is_element_revealed("elem-2")

        result = manager.check_click(50, 50, matrix)
        assert result is False

        manager.reset_reveals()
        assert not manager.is_element_revealed("elem-1")

        manager.clear_hotspots()
        assert len(manager.hotspots) == 0


class TestAnimationIntegration:
    """Integration tests for animation functionality."""

    def test_animation_easing_progression(self):
        """Test animation easing produces smooth progression."""
        steps = 100
        values = [ease_in_out_cubic(i / steps) for i in range(steps + 1)]

        assert values[0] == 0
        assert values[-1] == 1

        for i in range(1, len(values)):
            assert values[i] >= values[i - 1] - 0.001

        mid = values[50]
        assert 0.4 < mid < 0.6

    def test_region_transition_calculation(self):
        """Test region transition calculations."""
        start_region = SlideRegion(x=0, y=0, width=800, height=600)
        end_region = SlideRegion(x=200, y=150, width=400, height=300)

        for progress in [0.0, 0.25, 0.5, 0.75, 1.0]:
            current_x = start_region.x + (end_region.x - start_region.x) * progress
            current_y = start_region.y + (end_region.y - start_region.y) * progress
            current_w = (
                start_region.width + (end_region.width - start_region.width) * progress
            )
            current_h = (
                start_region.height
                + (end_region.height - start_region.height) * progress
            )

            if progress == 0.0:
                assert current_x == 0
                assert current_y == 0
                assert current_w == 800
            elif progress == 1.0:
                assert current_x == 200
                assert current_y == 150
                assert current_w == 400
            elif progress == 0.5:
                assert current_x == 100
                assert current_y == 75
                assert current_w == 600


class TestLaserPointerIntegration:
    """Integration tests for laser pointer."""

    def test_laser_pointer_tracking(self):
        """Test laser pointer position tracking."""
        state = LaserPointerState()
        state.enabled = True
        state.visible = True

        positions = [(100, 100), (120, 110), (140, 105), (160, 115), (180, 100)]

        for x, y in positions:
            if state.visible:
                state.trail.append((state.x, state.y, 0.5))
                if len(state.trail) > state.trail_max_length:
                    state.trail.pop(0)

            state.x = x
            state.y = y

        assert state.x == 180
        assert state.y == 100
        assert len(state.trail) <= state.trail_max_length

    def test_laser_pointer_trail_fade(self):
        """Test laser pointer trail fading."""
        state = LaserPointerState()

        state.trail = [
            (100, 100, 0.9),
            (110, 110, 0.7),
            (120, 120, 0.5),
            (130, 130, 0.3),
            (140, 140, 0.1),
        ]

        state.trail = [
            (x, y, alpha * 0.9)
            for x, y, alpha in state.trail
            if alpha * 0.9 > 0.05
        ]

        assert len(state.trail) == 4
        assert state.trail[0][2] == 0.81


class TestPresentationEditing:
    """Integration tests for presentation editing."""

    def test_slide_reordering_workflow(self):
        """Test slide reordering workflow."""
        presentation = Presentation()
        for i in range(5):
            presentation.add_slide(
                Slide(diagram=MockDiagram(f"d{i}"), title=f"Slide {i}")
            )

        presentation.move_slide(0, 4)

        assert presentation.slides[0].title == "Slide 1"
        assert presentation.slides[4].title == "Slide 0"

        presentation.move_slide(4, 2)

        assert presentation.slides[2].title == "Slide 0"

        original_order = [s.title for s in presentation.slides]
        presentation.move_slide(2, 2)
        new_order = [s.title for s in presentation.slides]
        assert original_order == new_order

    def test_slide_deletion_with_navigation(self):
        """Test slide deletion during navigation."""
        presentation = Presentation()
        for i in range(5):
            presentation.add_slide(Slide(diagram=MockDiagram(f"d{i}")))

        presentation.go_to_slide(3)
        assert presentation.current_index == 3

        presentation.remove_slide(1)
        assert len(presentation.slides) == 4

        assert presentation.current_index == 2

        presentation.go_to_slide(3)
        presentation.remove_slide(3)
        assert presentation.current_index == 2

    def test_batch_slide_operations(self):
        """Test batch operations on slides."""
        presentation = Presentation()
        diagrams = [MockDiagram(f"d{i}") for i in range(10)]

        for d in diagrams:
            presentation.add_slide(Slide(diagram=d))

        assert len(presentation.slides) == 10

        for i in range(5):
            presentation.slides[i].title = f"Chapter {i + 1}"
            presentation.slides[i].notes = f"Notes for chapter {i + 1}"

        for i in range(5):
            assert presentation.slides[i].title == f"Chapter {i + 1}"

        while len(presentation.slides) > 5:
            presentation.remove_slide(5)

        assert len(presentation.slides) == 5
