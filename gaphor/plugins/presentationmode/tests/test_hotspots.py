"""Tests for hotspot functionality."""

import pytest

from gaphor.plugins.presentationmode.hotspots import Hotspot, HotspotManager


class MockMatrix:
    def __init__(self, scale=1.0, offset_x=0, offset_y=0):
        self._scale = scale
        self._offset_x = offset_x
        self._offset_y = offset_y

    def inverse(self):
        return MockInverseMatrix(self._scale, self._offset_x, self._offset_y)

    def transform_point(self, x, y):
        return (x * self._scale + self._offset_x, y * self._scale + self._offset_y)

    def __getitem__(self, index):
        if index == 0:
            return self._scale
        return 0


class MockInverseMatrix:
    def __init__(self, scale, offset_x, offset_y):
        self._scale = scale
        self._offset_x = offset_x
        self._offset_y = offset_y

    def transform_point(self, x, y):
        return (
            (x - self._offset_x) / self._scale,
            (y - self._offset_y) / self._scale,
        )


def test_hotspot_creation():
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


def test_hotspot_manager_add_hotspot():
    manager = HotspotManager()
    hotspot = Hotspot(x=0, y=0, width=100, height=100, action="navigate")
    manager.add_hotspot(hotspot)
    assert len(manager.hotspots) == 1


def test_hotspot_manager_clear():
    manager = HotspotManager()
    manager.add_hotspot(Hotspot(x=0, y=0, width=100, height=100, action="navigate"))
    manager.add_hotspot(Hotspot(x=100, y=100, width=100, height=100, action="reveal"))
    manager.clear_hotspots()
    assert len(manager.hotspots) == 0


def test_hotspot_manager_check_click_hit():
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


def test_hotspot_manager_check_click_miss():
    manager = HotspotManager()
    hotspot = Hotspot(x=100, y=100, width=50, height=50, action="navigate")
    manager.add_hotspot(hotspot)

    matrix = MockMatrix(scale=1.0)
    result = manager.check_click(10, 10, matrix)

    assert result is False


def test_hotspot_manager_reveal_action():
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


def test_hotspot_manager_is_element_revealed():
    manager = HotspotManager()
    manager.revealed_elements.add("elem-1")

    assert manager.is_element_revealed("elem-1") is True
    assert manager.is_element_revealed("elem-2") is False


def test_hotspot_manager_reset_reveals():
    manager = HotspotManager()
    manager.revealed_elements.add("elem-1")
    manager.revealed_elements.add("elem-2")

    manager.reset_reveals()

    assert len(manager.revealed_elements) == 0


def test_hotspot_manager_get_hotspot_at():
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
