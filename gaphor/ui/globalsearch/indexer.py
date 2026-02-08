"""Search indexer for efficient model searching."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING
from unicodedata import normalize

from gaphor.core import event_handler
from gaphor.core.modeling import (
    Base,
    ElementCreated,
    ElementDeleted,
    ElementUpdated,
    ModelFlushed,
    ModelReady,
)

if TYPE_CHECKING:
    from gaphor.core.modeling import ElementFactory


@dataclass
class IndexEntry:
    element_id: str
    field: str
    value: str
    normalized_value: str


class SearchIndexer:
    def __init__(self, element_factory: ElementFactory, event_manager):
        self.element_factory = element_factory
        self.event_manager = event_manager

        self._name_index: dict[str, set[str]] = defaultdict(set)
        self._type_index: dict[str, set[str]] = defaultdict(set)
        self._value_index: dict[str, set[str]] = defaultdict(set)

        event_manager.subscribe(self._on_element_created)
        event_manager.subscribe(self._on_element_deleted)
        event_manager.subscribe(self._on_element_updated)
        event_manager.subscribe(self._on_model_ready)
        event_manager.subscribe(self._on_model_flushed)

    def shutdown(self):
        self.event_manager.unsubscribe(self._on_element_created)
        self.event_manager.unsubscribe(self._on_element_deleted)
        self.event_manager.unsubscribe(self._on_element_updated)
        self.event_manager.unsubscribe(self._on_model_ready)
        self.event_manager.unsubscribe(self._on_model_flushed)

    def rebuild_index(self):
        self._clear_index()

        for element in self.element_factory.select(None):
            self._index_element(element)

    def _clear_index(self):
        self._name_index.clear()
        self._type_index.clear()
        self._value_index.clear()

    def _index_element(self, element: Base):
        element_id = element.id

        type_name = type(element).__name__.casefold()
        self._type_index[type_name].add(element_id)

        name = getattr(element, "name", None)
        if name:
            normalized_name = normalize("NFC", str(name)).casefold()
            for i in range(1, len(normalized_name) + 1):
                prefix = normalized_name[:i]
                self._name_index[prefix].add(element_id)

        self._index_element_values(element)

    def _index_element_values(self, element: Base):
        element_id = element.id

        for prop in element.__properties__:
            if prop.name.startswith("_"):
                continue

            try:
                value = getattr(element, prop.name, None)
            except Exception:
                continue

            if isinstance(value, str) and value:
                normalized = normalize("NFC", value).casefold()
                for word in normalized.split():
                    if len(word) >= 2:
                        self._value_index[word].add(element_id)

    def _remove_element_from_index(self, element: Base):
        element_id = element.id

        for index in [self._name_index, self._type_index, self._value_index]:
            for key in list(index.keys()):
                index[key].discard(element_id)
                if not index[key]:
                    del index[key]

    def search_by_name_prefix(self, prefix: str) -> set[str]:
        normalized = normalize("NFC", prefix).casefold()
        return self._name_index.get(normalized, set())

    def search_by_type(self, type_name: str) -> set[str]:
        normalized = type_name.casefold()
        return self._type_index.get(normalized, set())

    def search_by_value(self, value: str) -> set[str]:
        normalized = normalize("NFC", value).casefold()

        results = set()
        for word in normalized.split():
            if word in self._value_index:
                if not results:
                    results = self._value_index[word].copy()
                else:
                    results &= self._value_index[word]

        return results

    @event_handler(ElementCreated)
    def _on_element_created(self, event: ElementCreated):
        self._index_element(event.element)

    @event_handler(ElementDeleted)
    def _on_element_deleted(self, event: ElementDeleted):
        self._remove_element_from_index(event.element)

    @event_handler(ElementUpdated)
    def _on_element_updated(self, event: ElementUpdated):
        self._remove_element_from_index(event.element)
        self._index_element(event.element)

    @event_handler(ModelReady)
    def _on_model_ready(self, event: ModelReady):
        self.rebuild_index()

    @event_handler(ModelFlushed)
    def _on_model_flushed(self, event: ModelFlushed):
        self._clear_index()
