"""Tests for the search engine."""

import pytest

from gaphor.UML import uml as UML
from gaphor.ui.globalsearch.engine import (
    SearchCategory,
    SearchEngine,
    SearchResult,
    SearchScope,
)


@pytest.fixture
def search_engine(element_factory):
    return SearchEngine(element_factory, modeling_language=None)


class TestSearchEngine:
    def test_search_by_name(self, element_factory, search_engine):
        cls = element_factory.create(UML.Class)
        cls.name = "CustomerService"

        results = search_engine.search("customer")

        assert len(results) == 1
        assert results[0].element is cls
        assert results[0].match_category == SearchCategory.NAME
        assert results[0].match_value == "CustomerService"

    def test_search_by_name_case_insensitive(self, element_factory, search_engine):
        cls = element_factory.create(UML.Class)
        cls.name = "CustomerService"

        results = search_engine.search("CUSTOMER")

        assert len(results) == 1
        assert results[0].element is cls

    def test_search_by_type(self, element_factory, search_engine):
        element_factory.create(UML.Class)
        element_factory.create(UML.Interface)
        element_factory.create(UML.Package)

        results = search_engine.search("class", search_names=False, search_types=True)

        class_results = [r for r in results if r.match_category == SearchCategory.TYPE]
        assert len(class_results) >= 1

    def test_search_by_attribute_value(self, element_factory, search_engine):
        cls = element_factory.create(UML.Class)
        cls.name = "TestClass"
        cls.note = "This is a special note about customers"

        results = search_engine.search(
            "special", search_names=False, search_attributes=True
        )

        assert len(results) >= 1
        note_results = [
            r
            for r in results
            if r.match_category == SearchCategory.ATTRIBUTE_VALUE
            and r.match_field == "note"
        ]
        assert len(note_results) == 1

    def test_search_returns_diagram_locations(self, element_factory, search_engine):
        diagram = element_factory.create(UML.Diagram)
        diagram.name = "Main Diagram"

        cls = element_factory.create(UML.Class)
        cls.name = "MyClass"

        # Create a presentation for the class in the diagram
        from gaphor.UML.classes.klass import ClassItem

        item = diagram.create(ClassItem, subject=cls)

        results = search_engine.search("MyClass")

        assert len(results) == 1
        assert len(results[0].diagram_locations) == 1
        assert results[0].diagram_locations[0].diagram is diagram

    def test_search_empty_query_returns_empty(self, search_engine):
        results = search_engine.search("")
        assert len(results) == 0

        results = search_engine.search("   ")
        assert len(results) == 0

    def test_search_respects_max_results(self, element_factory, search_engine):
        for i in range(20):
            cls = element_factory.create(UML.Class)
            cls.name = f"TestClass{i}"

        results = search_engine.search("TestClass", max_results=5)

        assert len(results) == 5

    def test_search_relationship_type(self, element_factory, search_engine):
        cls1 = element_factory.create(UML.Class)
        cls1.name = "Parent"

        cls2 = element_factory.create(UML.Class)
        cls2.name = "Child"

        gen = element_factory.create(UML.Generalization)
        gen.general = cls1
        gen.specific = cls2

        results = search_engine.search(
            "generalization", search_names=False, search_relationships=True
        )

        rel_results = [
            r for r in results if r.match_category == SearchCategory.RELATIONSHIP
        ]
        assert len(rel_results) >= 1

    def test_search_current_diagram_scope(self, element_factory, search_engine):
        diagram1 = element_factory.create(UML.Diagram)
        diagram1.name = "Diagram 1"

        diagram2 = element_factory.create(UML.Diagram)
        diagram2.name = "Diagram 2"

        cls1 = element_factory.create(UML.Class)
        cls1.name = "ClassInDiagram1"

        cls2 = element_factory.create(UML.Class)
        cls2.name = "ClassInDiagram2"

        from gaphor.UML.classes.klass import ClassItem

        diagram1.create(ClassItem, subject=cls1)
        diagram2.create(ClassItem, subject=cls2)

        results = search_engine.search(
            "Class", scope=SearchScope.CURRENT_DIAGRAM, current_diagram=diagram1
        )

        assert len(results) == 1
        assert results[0].element is cls1

    def test_search_result_relevance_ordering(self, element_factory, search_engine):
        cls_exact = element_factory.create(UML.Class)
        cls_exact.name = "customer"

        cls_starts = element_factory.create(UML.Class)
        cls_starts.name = "customerService"

        cls_contains = element_factory.create(UML.Class)
        cls_contains.name = "bigCustomerData"

        results = search_engine.search("customer")

        # Exact match should be first
        names = [r.element_name for r in results]
        assert names[0] == "customer"


class TestSearchResult:
    def test_search_result_properties(self, element_factory):
        cls = element_factory.create(UML.Class)
        cls.name = "TestClass"

        result = SearchResult(
            element=cls,
            match_category=SearchCategory.NAME,
            match_field="name",
            match_value="TestClass",
        )

        assert result.element_name == "TestClass"
        assert result.element_type == "Class"
        assert result.element_id == cls.id

    def test_search_result_unnamed_element(self, element_factory):
        cls = element_factory.create(UML.Class)

        result = SearchResult(
            element=cls,
            match_category=SearchCategory.TYPE,
            match_field="type",
            match_value="Class",
        )

        assert result.element_name == "<Class>"

    def test_search_result_equality(self, element_factory):
        cls = element_factory.create(UML.Class)
        cls.name = "TestClass"

        result1 = SearchResult(
            element=cls,
            match_category=SearchCategory.NAME,
            match_field="name",
            match_value="TestClass",
        )

        result2 = SearchResult(
            element=cls,
            match_category=SearchCategory.NAME,
            match_field="name",
            match_value="TestClass",
        )

        assert result1 == result2
        assert hash(result1) == hash(result2)

    def test_search_result_different_category(self, element_factory):
        cls = element_factory.create(UML.Class)
        cls.name = "TestClass"

        result1 = SearchResult(
            element=cls,
            match_category=SearchCategory.NAME,
            match_field="name",
            match_value="TestClass",
        )

        result2 = SearchResult(
            element=cls,
            match_category=SearchCategory.TYPE,
            match_field="type",
            match_value="Class",
        )

        assert result1 != result2
