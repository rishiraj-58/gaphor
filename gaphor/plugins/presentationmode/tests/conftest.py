"""Test fixtures for presentation mode tests."""

import pytest


class MockDiagram:
    """Mock diagram for testing."""

    def __init__(self, id: str = "test-diagram-1", name: str = "Test Diagram"):
        self.id = id
        self.name = name


class MockElementFactory:
    """Mock element factory for testing."""

    def __init__(self):
        self._elements: dict[str, object] = {}

    def add_element(self, element):
        self._elements[element.id] = element

    def lookup(self, id: str):
        return self._elements.get(id)

    def select(self, type_or_func=None):
        if type_or_func is None:
            return list(self._elements.values())
        if isinstance(type_or_func, type):
            return [e for e in self._elements.values() if isinstance(e, type_or_func)]
        return [e for e in self._elements.values() if type_or_func(e)]


class MockEventManager:
    """Mock event manager for testing."""

    def __init__(self):
        self.events = []

    def handle(self, event):
        self.events.append(event)

    def subscribe(self, handler):
        pass

    def unsubscribe(self, handler):
        pass


class MockView:
    """Mock view for testing."""

    def __init__(self, width: int = 800, height: int = 600):
        self._width = width
        self._height = height
        self.matrix = MockMatrix()
        self.model = None

    def get_width(self):
        return self._width

    def get_height(self):
        return self._height

    def get_item_bounding_box(self, item):
        return MockBounds(0, 0, 100, 100)


class MockMatrix:
    """Mock matrix for testing."""

    def __init__(self, scale=1.0, offset_x=0.0, offset_y=0.0):
        self._values = [scale, 0, 0, scale, offset_x, offset_y]

    def __getitem__(self, index):
        return self._values[index]

    def set(self, *values):
        self._values = list(values)

    def inverse(self):
        return MockInverseMatrix(self._values[0], self._values[4], self._values[5])

    def transform_point(self, x, y):
        return (
            x * self._values[0] + self._values[4],
            y * self._values[0] + self._values[5],
        )


class MockInverseMatrix:
    """Mock inverse matrix."""

    def __init__(self, scale, offset_x, offset_y):
        self._scale = scale
        self._offset_x = offset_x
        self._offset_y = offset_y

    def transform_point(self, x, y):
        if self._scale == 0:
            return (0, 0)
        return (
            (x - self._offset_x) / self._scale,
            (y - self._offset_y) / self._scale,
        )


class MockBounds:
    """Mock bounding box."""

    def __init__(self, x, y, width, height):
        self.x = x
        self.y = y
        self.width = width
        self.height = height


class MockMainWindow:
    """Mock main window."""

    def __init__(self):
        self.window = None


class MockDiagrams:
    """Mock diagrams service."""

    def __init__(self):
        self._current_diagram = None
        self._current_view = None

    def get_current_diagram(self):
        return self._current_diagram

    def get_current_view(self):
        return self._current_view

    def set_current_diagram(self, diagram):
        self._current_diagram = diagram

    def set_current_view(self, view):
        self._current_view = view


class MockToolsMenu:
    """Mock tools menu."""

    def add_actions(self, provider):
        pass


@pytest.fixture
def mock_diagram():
    """Create a mock diagram."""
    return MockDiagram()


@pytest.fixture
def mock_element_factory():
    """Create a mock element factory."""
    return MockElementFactory()


@pytest.fixture
def mock_event_manager():
    """Create a mock event manager."""
    return MockEventManager()


@pytest.fixture
def mock_view():
    """Create a mock view."""
    return MockView()


@pytest.fixture
def mock_main_window():
    """Create a mock main window."""
    return MockMainWindow()


@pytest.fixture
def mock_diagrams():
    """Create a mock diagrams service."""
    return MockDiagrams()


@pytest.fixture
def mock_tools_menu():
    """Create a mock tools menu."""
    return MockToolsMenu()
