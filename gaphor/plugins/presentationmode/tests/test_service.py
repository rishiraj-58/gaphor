"""Tests for presentation mode service."""

import json
import tempfile
from pathlib import Path

import pytest

from gaphor.plugins.presentationmode.model import Presentation, Slide, SlideRegion
from gaphor.plugins.presentationmode.tests.conftest import (
    MockDiagram,
    MockDiagrams,
    MockElementFactory,
    MockEventManager,
    MockMainWindow,
    MockToolsMenu,
    MockView,
)


class TestPresentationModeService:
    """Tests for PresentationModeService."""

    def create_service(self, element_factory=None, event_manager=None, diagrams=None):
        """Create a service instance for testing."""
        from gaphor.plugins.presentationmode.service import PresentationModeService

        return PresentationModeService(
            event_manager=event_manager or MockEventManager(),
            element_factory=element_factory or MockElementFactory(),
            main_window=MockMainWindow(),
            diagrams=diagrams or MockDiagrams(),
            tools_menu=MockToolsMenu(),
        )

    def test_service_creation(self):
        """Test service can be created."""
        service = self.create_service()
        assert service is not None
        assert service.current_presentation is None

    def test_create_presentation_from_empty_factory(self):
        """Test creating presentation with no diagrams."""
        service = self.create_service()
        presentation = service._create_presentation_from_diagrams()
        assert presentation is not None
        assert len(presentation.slides) == 0

    def test_create_presentation_from_diagrams(self):
        """Test creating presentation from diagrams."""
        factory = MockElementFactory()
        factory.add_element(MockDiagram("d1", "Diagram 1"))
        factory.add_element(MockDiagram("d2", "Diagram 2"))

        service = self.create_service(element_factory=factory)
        presentation = service._create_presentation_from_diagrams()

        assert len(presentation.slides) == 2
        assert presentation.slides[0].diagram.name == "Diagram 1"
        assert presentation.slides[1].diagram.name == "Diagram 2"

    def test_capture_view_region(self):
        """Test capturing view region."""
        service = self.create_service()
        view = MockView(800, 600)
        view.matrix.set(1.0, 0, 0, 1.0, -100, -50)

        region = service._capture_view_region(view)

        assert region is not None
        assert region.x == 100
        assert region.y == 50
        assert region.width == 800
        assert region.height == 600

    def test_capture_view_region_with_zoom(self):
        """Test capturing view region with zoom."""
        service = self.create_service()
        view = MockView(800, 600)
        view.matrix.set(2.0, 0, 0, 2.0, -200, -100)

        region = service._capture_view_region(view)

        assert region is not None
        assert region.x == 100
        assert region.y == 50
        assert region.width == 400
        assert region.height == 300

    def test_capture_view_region_none_view(self):
        """Test capturing region with no view."""
        service = self.create_service()
        region = service._capture_view_region(None)
        assert region is None

    def test_capture_view_region_zero_size(self):
        """Test capturing region with zero size view."""
        service = self.create_service()
        view = MockView(0, 0)
        region = service._capture_view_region(view)
        assert region is None

    def test_save_and_load_presentation(self):
        """Test saving and loading a presentation."""
        factory = MockElementFactory()
        diagram1 = MockDiagram("d1", "Diagram 1")
        diagram2 = MockDiagram("d2", "Diagram 2")
        factory.add_element(diagram1)
        factory.add_element(diagram2)

        service = self.create_service(element_factory=factory)

        presentation = Presentation(name="Test Presentation")
        presentation.add_slide(
            Slide(
                diagram=diagram1,
                title="First Slide",
                notes="Some notes",
                region=SlideRegion(x=10, y=20, width=100, height=80),
            )
        )
        presentation.add_slide(
            Slide(
                diagram=diagram2,
                title="Second Slide",
            )
        )
        service.current_presentation = presentation

        with tempfile.NamedTemporaryFile(suffix=".gaphor-pres", delete=False) as f:
            path = Path(f.name)

        try:
            service._save_presentation_to_file(path)

            assert path.exists()

            with open(path, "r") as f:
                data = json.load(f)

            assert data["name"] == "Test Presentation"
            assert len(data["slides"]) == 2
            assert data["slides"][0]["title"] == "First Slide"
            assert data["slides"][0]["notes"] == "Some notes"
            assert data["slides"][0]["region"]["x"] == 10

            loaded = service._load_presentation_from_file(path)

            assert loaded is not None
            assert loaded.name == "Test Presentation"
            assert len(loaded.slides) == 2
            assert loaded.slides[0].title == "First Slide"
            assert loaded.slides[0].region.x == 10

        finally:
            path.unlink(missing_ok=True)

    def test_load_presentation_missing_diagram(self):
        """Test loading presentation with missing diagram."""
        factory = MockElementFactory()
        diagram = MockDiagram("d1", "Existing Diagram")
        factory.add_element(diagram)

        service = self.create_service(element_factory=factory)

        data = {
            "version": "1.0",
            "name": "Test",
            "slides": [
                {"diagram_id": "d1", "title": "Valid"},
                {"diagram_id": "missing", "title": "Invalid"},
            ],
        }

        with tempfile.NamedTemporaryFile(
            suffix=".gaphor-pres", delete=False, mode="w"
        ) as f:
            json.dump(data, f)
            path = Path(f.name)

        try:
            loaded = service._load_presentation_from_file(path)

            assert loaded is not None
            assert len(loaded.slides) == 1
            assert loaded.slides[0].title == "Valid"

        finally:
            path.unlink(missing_ok=True)

    def test_load_invalid_json(self):
        """Test loading invalid JSON file."""
        service = self.create_service()

        with tempfile.NamedTemporaryFile(
            suffix=".gaphor-pres", delete=False, mode="w"
        ) as f:
            f.write("invalid json {{{")
            path = Path(f.name)

        try:
            from gaphor.plugins.presentationmode.errors import PresentationLoadError

            with pytest.raises(PresentationLoadError):
                service._load_presentation_from_file(path)

        finally:
            path.unlink(missing_ok=True)

    def test_shutdown_cleans_up(self):
        """Test shutdown cleans up resources."""
        service = self.create_service()
        service.current_presentation = Presentation()

        service.shutdown()

        assert service.presentation_window is None
        assert service.editor_window is None

    def test_add_current_as_slide_no_diagram(self):
        """Test adding slide when no diagram is open."""
        diagrams = MockDiagrams()
        diagrams.set_current_diagram(None)

        service = self.create_service(diagrams=diagrams)

        service.add_current_as_slide()

        assert service.current_presentation is None

    def test_add_current_as_slide_with_diagram(self):
        """Test adding slide with current diagram."""
        diagrams = MockDiagrams()
        diagram = MockDiagram("d1", "Test Diagram")
        diagrams.set_current_diagram(diagram)
        diagrams.set_current_view(MockView())

        service = self.create_service(diagrams=diagrams)
        service.add_current_as_slide()

        assert service.current_presentation is not None
        assert len(service.current_presentation.slides) == 1
        assert service.current_presentation.slides[0].diagram == diagram


class TestPresentationSerialization:
    """Tests for presentation serialization."""

    def test_slide_region_serialization(self):
        """Test slide region is correctly serialized."""
        region = SlideRegion(x=10.5, y=20.5, width=100.0, height=80.0)
        data = {
            "x": region.x,
            "y": region.y,
            "width": region.width,
            "height": region.height,
        }

        loaded = SlideRegion(**data)
        assert loaded.x == 10.5
        assert loaded.y == 20.5
        assert loaded.width == 100.0
        assert loaded.height == 80.0

    def test_presentation_name_default(self):
        """Test presentation has default name."""
        presentation = Presentation()
        assert presentation.name == "Untitled Presentation"

    def test_presentation_name_custom(self):
        """Test presentation with custom name."""
        presentation = Presentation(name="My Presentation")
        assert presentation.name == "My Presentation"
