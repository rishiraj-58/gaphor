"""Tests for hotspot functionality."""

import pytest

from gaphor.plugins.presentationmode.hotspots import Hotspot, HotspotManager
from gaphor.plugins.presentationmode.tests.conftest import MockMatrix


class TestHotspot:
    """Tests for Hotspot dataclass."""

    def test_hotspot_creation(self):
        """Test hotspot can be created."""
        hotspot = Hotspot(
            x=100,
            y=100,
            width=50,
            height=50,
            action="navigate",
            target_diagram_id="diagram-1",
        )
        assert hotspot.x == 100
        assert hotspot.y == 100
        assert hotspot.width == 50
        assert hotspot.height == 50
        assert hotspot.action == "navigate"
        assert hotspot.target_diagram_id == "diagram-1"

    def test_hotspot_reveal_action(self):
        """Test hotspot with reveal action."""
        hotspot = Hotspot(
            x=0,
            y=0,
            width=100,
            height=100,
            action="reveal",
            reveal_element_ids=["elem-1", "elem-2"],
        )
        assert hotspot.action == "reveal"
        assert hotspot.reveal_element_ids == ["elem-1", "elem-2"]

    def test_hotspot_tooltip(self):
        """Test hotspot with tooltip."""
        hotspot = Hotspot(
            x=0,
            y=0,
            width=100,
            height=100,
            action="navigate",
            tooltip="Click to navigate",
        )
        assert hotspot.tooltip == "Click to navigate"

    def test_hotspot_defaults(self):
        """Test hotspot default values."""
        hotspot = Hotspot(x=0, y=0, width=10, height=10, action="navigate")
        assert hotspot.target_diagram_id is None
        assert hotspot.reveal_element_ids is None
        assert hotspot.tooltip == ""


class TestHotspotManager:
    """Tests for HotspotManager."""

    def test_manager_creation(self):
        """Test manager can be created."""
        manager = HotspotManager()
        assert manager.hotspots == []
        assert len(manager.revealed_elements) == 0

    def test_add_hotspot(self):
        """Test adding hotspot."""
        manager = HotspotManager()
        hotspot = Hotspot(x=0, y=0, width=100, height=100, action="navigate")
        manager.add_hotspot(hotspot)
        assert len(manager.hotspots) == 1
        assert manager.hotspots[0] == hotspot

    def test_add_multiple_hotspots(self):
        """Test adding multiple hotspots."""
        manager = HotspotManager()
        for i in range(5):
            manager.add_hotspot(
                Hotspot(x=i * 100, y=0, width=50, height=50, action="navigate")
            )
        assert len(manager.hotspots) == 5

    def test_clear_hotspots(self):
        """Test clearing hotspots."""
        manager = HotspotManager()
        manager.add_hotspot(Hotspot(x=0, y=0, width=100, height=100, action="navigate"))
        manager.add_hotspot(Hotspot(x=100, y=100, width=100, height=100, action="reveal"))
        manager.clear_hotspots()
        assert len(manager.hotspots) == 0
        assert len(manager.revealed_elements) == 0

    def test_check_click_hit(self):
        """Test click detection hit."""
        manager = HotspotManager()
        hotspot = Hotspot(
            x=100, y=100, width=50, height=50, action="navigate", target_diagram_id="test"
        )
        manager.add_hotspot(hotspot)

        navigated_to = []
        manager.set_navigate_callback(lambda id: navigated_to.append(id))

        matrix = MockMatrix(scale=1.0)
        result = manager.check_click(125, 125, matrix)

        assert result is True
        assert navigated_to == ["test"]

    def test_check_click_miss(self):
        """Test click detection miss."""
        manager = HotspotManager()
        hotspot = Hotspot(x=100, y=100, width=50, height=50, action="navigate")
        manager.add_hotspot(hotspot)

        matrix = MockMatrix(scale=1.0)
        result = manager.check_click(10, 10, matrix)

        assert result is False

    def test_check_click_edge(self):
        """Test click on hotspot edge."""
        manager = HotspotManager()
        hotspot = Hotspot(
            x=100, y=100, width=50, height=50, action="navigate", target_diagram_id="test"
        )
        manager.add_hotspot(hotspot)

        navigated_to = []
        manager.set_navigate_callback(lambda id: navigated_to.append(id))

        matrix = MockMatrix(scale=1.0)

        result = manager.check_click(100, 100, matrix)
        assert result is True

        navigated_to.clear()
        result = manager.check_click(150, 150, matrix)
        assert result is True

    def test_reveal_action(self):
        """Test reveal action."""
        manager = HotspotManager()
        hotspot = Hotspot(
            x=0,
            y=0,
            width=100,
            height=100,
            action="reveal",
            reveal_element_ids=["elem-1", "elem-2"],
        )
        manager.add_hotspot(hotspot)

        revealed = []
        manager.set_reveal_callback(lambda ids: revealed.extend(ids))

        matrix = MockMatrix(scale=1.0)
        manager.check_click(50, 50, matrix)

        assert "elem-1" in manager.revealed_elements
        assert "elem-2" in manager.revealed_elements
        assert revealed == ["elem-1", "elem-2"]

    def test_is_element_revealed(self):
        """Test element revealed check."""
        manager = HotspotManager()
        manager.revealed_elements.add("elem-1")

        assert manager.is_element_revealed("elem-1") is True
        assert manager.is_element_revealed("elem-2") is False

    def test_reset_reveals(self):
        """Test resetting reveals."""
        manager = HotspotManager()
        manager.revealed_elements.add("elem-1")
        manager.revealed_elements.add("elem-2")

        manager.reset_reveals()

        assert len(manager.revealed_elements) == 0

    def test_get_hotspot_at(self):
        """Test getting hotspot at position."""
        manager = HotspotManager()
        hotspot1 = Hotspot(x=0, y=0, width=50, height=50, action="navigate")
        hotspot2 = Hotspot(x=100, y=100, width=50, height=50, action="reveal")
        manager.add_hotspot(hotspot1)
        manager.add_hotspot(hotspot2)

        matrix = MockMatrix(scale=1.0)

        result = manager.get_hotspot_at(25, 25, matrix)
        assert result == hotspot1

        result = manager.get_hotspot_at(125, 125, matrix)
        assert result == hotspot2

        result = manager.get_hotspot_at(200, 200, matrix)
        assert result is None

    def test_check_click_with_zoom(self):
        """Test click detection with zoomed view."""
        manager = HotspotManager()
        hotspot = Hotspot(
            x=100, y=100, width=50, height=50, action="navigate", target_diagram_id="test"
        )
        manager.add_hotspot(hotspot)

        navigated_to = []
        manager.set_navigate_callback(lambda id: navigated_to.append(id))

        matrix = MockMatrix(scale=2.0, offset_x=100, offset_y=100)

        result = manager.check_click(325, 325, matrix)

        assert result is True

    def test_overlapping_hotspots(self):
        """Test overlapping hotspots (first match wins)."""
        manager = HotspotManager()
        hotspot1 = Hotspot(
            x=0, y=0, width=100, height=100, action="navigate", target_diagram_id="first"
        )
        hotspot2 = Hotspot(
            x=50, y=50, width=100, height=100, action="navigate", target_diagram_id="second"
        )
        manager.add_hotspot(hotspot1)
        manager.add_hotspot(hotspot2)

        navigated_to = []
        manager.set_navigate_callback(lambda id: navigated_to.append(id))

        matrix = MockMatrix(scale=1.0)
        manager.check_click(75, 75, matrix)

        assert navigated_to == ["first"]

    def test_no_callback_set(self):
        """Test action with no callback set."""
        manager = HotspotManager()
        hotspot = Hotspot(
            x=0, y=0, width=100, height=100, action="navigate", target_diagram_id="test"
        )
        manager.add_hotspot(hotspot)

        matrix = MockMatrix(scale=1.0)
        result = manager.check_click(50, 50, matrix)

        assert result is True


class TestHotspotActions:
    """Tests for different hotspot action types."""

    def test_navigate_action(self):
        """Test navigate action."""
        manager = HotspotManager()
        hotspot = Hotspot(
            x=0,
            y=0,
            width=100,
            height=100,
            action="navigate",
            target_diagram_id="target-diagram",
        )
        manager.add_hotspot(hotspot)

        target = []
        manager.set_navigate_callback(lambda id: target.append(id))

        matrix = MockMatrix(scale=1.0)
        manager.check_click(50, 50, matrix)

        assert target == ["target-diagram"]

    def test_reveal_action_multiple_elements(self):
        """Test reveal action with multiple elements."""
        manager = HotspotManager()
        hotspot = Hotspot(
            x=0,
            y=0,
            width=100,
            height=100,
            action="reveal",
            reveal_element_ids=["a", "b", "c", "d"],
        )
        manager.add_hotspot(hotspot)

        matrix = MockMatrix(scale=1.0)
        manager.check_click(50, 50, matrix)

        assert len(manager.revealed_elements) == 4
        for elem in ["a", "b", "c", "d"]:
            assert manager.is_element_revealed(elem)

    def test_link_action(self):
        """Test link action (similar to navigate)."""
        manager = HotspotManager()
        hotspot = Hotspot(
            x=0,
            y=0,
            width=100,
            height=100,
            action="link",
            target_diagram_id="linked-diagram",
        )
        manager.add_hotspot(hotspot)

        target = []
        manager.set_navigate_callback(lambda id: target.append(id))

        matrix = MockMatrix(scale=1.0)
        manager.check_click(50, 50, matrix)

        assert target == ["linked-diagram"]
