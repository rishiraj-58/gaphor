"""Tests for the search indexer."""

import pytest

from gaphor.UML import uml as UML
from gaphor.ui.globalsearch.indexer import SearchIndexer


@pytest.fixture
def indexer(element_factory, event_manager):
    return SearchIndexer(element_factory, event_manager)


class TestSearchIndexer:
    def test_index_element_by_name(self, element_factory, indexer):
        cls = element_factory.create(UML.Class)
        cls.name = "CustomerService"

        ids = indexer.search_by_name_prefix("customer")
        assert cls.id in ids

    def test_index_element_by_type(self, element_factory, indexer):
        cls = element_factory.create(UML.Class)
        cls.name = "TestClass"

        ids = indexer.search_by_type("class")
        assert cls.id in ids

    def test_index_element_by_value(self, element_factory, indexer):
        cls = element_factory.create(UML.Class)
        cls.name = "TestClass"
        cls.note = "important customer data"

        ids = indexer.search_by_value("important")
        assert cls.id in ids

    def test_index_updates_on_element_created(self, element_factory, indexer):
        # Element is automatically indexed when created
        cls = element_factory.create(UML.Class)
        cls.name = "NewClass"

        ids = indexer.search_by_name_prefix("newc")
        assert cls.id in ids

    def test_index_updates_on_element_deleted(self, element_factory, indexer):
        cls = element_factory.create(UML.Class)
        cls.name = "ToBeDeleted"
        element_id = cls.id

        ids = indexer.search_by_name_prefix("tobedeleted")
        assert element_id in ids

        cls.unlink()

        ids = indexer.search_by_name_prefix("tobedeleted")
        assert element_id not in ids

    def test_index_updates_on_element_changed(self, element_factory, indexer):
        cls = element_factory.create(UML.Class)
        cls.name = "OriginalName"

        ids = indexer.search_by_name_prefix("original")
        assert cls.id in ids

        cls.name = "UpdatedName"

        ids = indexer.search_by_name_prefix("updated")
        assert cls.id in ids

        ids = indexer.search_by_name_prefix("original")
        assert cls.id not in ids

    def test_rebuild_index(self, element_factory, indexer):
        cls1 = element_factory.create(UML.Class)
        cls1.name = "FirstClass"

        cls2 = element_factory.create(UML.Class)
        cls2.name = "SecondClass"

        indexer._clear_index()

        ids = indexer.search_by_name_prefix("first")
        assert len(ids) == 0

        indexer.rebuild_index()

        ids = indexer.search_by_name_prefix("first")
        assert cls1.id in ids

        ids = indexer.search_by_name_prefix("second")
        assert cls2.id in ids

    def test_search_by_value_multiple_words(self, element_factory, indexer):
        cls = element_factory.create(UML.Class)
        cls.name = "TestClass"
        cls.note = "handles customer data processing"

        # Search for single word
        ids = indexer.search_by_value("customer")
        assert cls.id in ids

        # Search for multiple words (intersection)
        ids = indexer.search_by_value("customer processing")
        assert cls.id in ids

    def test_shutdown_unsubscribes_events(self, element_factory, indexer, event_manager):
        indexer.shutdown()

        # After shutdown, creating new elements should not affect the index
        initial_index_size = len(indexer._name_index)

        cls = element_factory.create(UML.Class)
        cls.name = "AfterShutdown"

        # Index should not have been updated
        ids = indexer.search_by_name_prefix("aftershutdown")
        assert cls.id not in ids
