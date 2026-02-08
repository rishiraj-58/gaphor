"""Test fixtures for global search tests."""

import pytest

from gaphor.core.eventmanager import EventManager
from gaphor.core.modeling import ElementFactory
from gaphor.core.modeling.elementdispatcher import ElementDispatcher


@pytest.fixture
def event_manager():
    return EventManager()


@pytest.fixture
def element_dispatcher(event_manager):
    return ElementDispatcher(event_manager)


@pytest.fixture
def element_factory(event_manager, element_dispatcher):
    return ElementFactory(event_manager, element_dispatcher)
