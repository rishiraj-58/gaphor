"""Tests for the advanced search engine."""

import pytest

from gaphor import UML
from gaphor.core.modeling import Diagram
from gaphor.ui.advancedsearch.searchengine import (
    AdvancedSearchEngine,
    SearchScope,
)
from gaphor.ui.advancedsearch.searchresult import SearchResultType


@pytest.fixture
def search_engine(element_factory):
    """Create a search engine instance."""
    return AdvancedSearchEngine(element_factory)


@pytest.fixture
def sample_model(element_factory):
    """Create a sample model with various elements for testing."""
    # Create a class with attributes
    cls1 = element_factory.create(UML.Class)
    cls1.name = "CustomerClass"

    attr1 = element_factory.create(UML.Property)
    attr1.name = "customerId"
    cls1.ownedAttribute = attr1

    # Create another class
    cls2 = element_factory.create(UML.Class)
    cls2.name = "OrderClass"

    # Create an association
    assoc = element_factory.create(UML.Association)
    assoc.name = "CustomerOrderAssociation"

    # Create a diagram
    diagram = element_factory.create(Diagram)
    diagram.name = "MainDiagram"

    # Create a package
    pkg = element_factory.create(UML.Package)
    pkg.name = "CorePackage"

    return {
        "class1": cls1,
        "class2": cls2,
        "attribute": attr1,
        "association": assoc,
        "diagram": diagram,
        "package": pkg,
    }


class TestAdvancedSearchEngine:
    """Tests for AdvancedSearchEngine class."""

    def test_search_engine_creation(self, element_factory):
        """Test that search engine can be created."""
        engine = AdvancedSearchEngine(element_factory)
        assert engine is not None

    def test_search_engine_requires_factory(self):
        """Test that search engine requires an element factory."""
        with pytest.raises(ValueError):
            AdvancedSearchEngine(None)

    def test_search_empty_query_returns_empty(self, search_engine):
        """Test that empty query returns no results."""
        results = search_engine.search("")
        assert results == []

    def test_search_whitespace_query_returns_empty(self, search_engine):
        """Test that whitespace-only query returns no results."""
        results = search_engine.search("   ")
        assert results == []

    def test_search_by_element_name(self, search_engine, sample_model):
        """Test searching by element name."""
        results = search_engine.search("Customer")
        assert len(results) > 0

        # Should find CustomerClass
        names = [r.element_name for r in results]
        assert any("Customer" in name for name in names)

    def test_search_case_insensitive(self, search_engine, sample_model):
        """Test that search is case-insensitive."""
        results_lower = search_engine.search("customer")
        results_upper = search_engine.search("CUSTOMER")

        # Both should find the same elements
        assert len(results_lower) == len(results_upper)

    def test_search_by_element_type(self, search_engine, sample_model):
        """Test searching by element type."""
        results = search_engine.search(
            "Class",
            include_names=False,
            include_types=True,
            include_attributes=False,
            include_relationships=False,
        )

        # Should find Class type matches
        type_results = [r for r in results if r.result_type == SearchResultType.ELEMENT_TYPE]
        assert len(type_results) > 0

    def test_search_by_attribute_name(self, search_engine, sample_model):
        """Test searching by attribute name."""
        results = search_engine.search("customerId")

        # Should find the attribute
        assert len(results) > 0
        names = [r.match_value for r in results]
        assert any("customerId" in str(name) for name in names)

    def test_search_relationship_type(self, search_engine, sample_model):
        """Test searching for relationship types."""
        results = search_engine.search(
            "Association",
            include_names=True,
            include_types=True,
            include_attributes=False,
            include_relationships=True,
        )

        assert len(results) > 0

    def test_search_diagram_name(self, search_engine, sample_model):
        """Test searching by diagram name."""
        results = search_engine.search("MainDiagram")

        assert len(results) > 0
        diagram_results = [
            r for r in results if r.result_type == SearchResultType.DIAGRAM_NAME
        ]
        assert len(diagram_results) > 0

    def test_search_filter_by_names_only(self, search_engine, sample_model):
        """Test filtering to search names only."""
        results = search_engine.search(
            "Customer",
            include_names=True,
            include_types=False,
            include_attributes=False,
            include_relationships=False,
        )

        for result in results:
            assert result.result_type in (
                SearchResultType.ELEMENT_NAME,
                SearchResultType.DIAGRAM_NAME,
            )

    def test_search_filter_by_types_only(self, search_engine, sample_model):
        """Test filtering to search types only."""
        results = search_engine.search(
            "Class",
            include_names=False,
            include_types=True,
            include_attributes=False,
            include_relationships=False,
        )

        for result in results:
            assert result.result_type == SearchResultType.ELEMENT_TYPE

    def test_search_results_have_relevance_score(self, search_engine, sample_model):
        """Test that search results include relevance scores."""
        results = search_engine.search("Customer")

        for result in results:
            assert 0.0 <= result.relevance_score <= 1.0

    def test_search_results_sorted_by_relevance(self, search_engine, sample_model):
        """Test that results are sorted by relevance (descending)."""
        results = search_engine.search("Customer")

        if len(results) > 1:
            for i in range(len(results) - 1):
                assert results[i].relevance_score >= results[i + 1].relevance_score

    def test_search_by_type_method(self, search_engine, sample_model):
        """Test the search_by_type method."""
        results = search_engine.search_by_type("Class")

        assert len(results) > 0
        for result in results:
            assert result.result_type == SearchResultType.ELEMENT_TYPE
            assert result.match_value == "Class"

    def test_search_relationships_of_type(self, search_engine, sample_model):
        """Test the search_relationships_of_type method."""
        results = search_engine.search_relationships_of_type("Association")

        assert len(results) > 0
        for result in results:
            assert result.result_type == SearchResultType.RELATIONSHIP_TYPE

    def test_cache_invalidation(self, search_engine, element_factory, sample_model):
        """Test that cache can be invalidated."""
        # Search once to build cache
        search_engine.search("Customer")

        # Invalidate cache
        search_engine.invalidate_cache()

        # Create a new element
        new_class = element_factory.create(UML.Class)
        new_class.name = "NewCustomerRelated"

        # Invalidate again (simulating event handler)
        search_engine.invalidate_cache()

        # Search should find the new element
        results = search_engine.search("NewCustomer")
        names = [r.element_name for r in results]
        assert any("NewCustomer" in name for name in names)


class TestSearchResult:
    """Tests for SearchResult dataclass."""

    def test_search_result_element_name(self, element_factory):
        """Test that search result provides element name."""
        from gaphor.ui.advancedsearch.searchresult import SearchResult

        cls = element_factory.create(UML.Class)
        cls.name = "TestClass"

        result = SearchResult(
            element=cls,
            result_type=SearchResultType.ELEMENT_NAME,
            match_field="name",
            match_value="TestClass",
        )

        assert result.element_name == "TestClass"

    def test_search_result_element_type_name(self, element_factory):
        """Test that search result provides element type name."""
        from gaphor.ui.advancedsearch.searchresult import SearchResult

        cls = element_factory.create(UML.Class)
        cls.name = "TestClass"

        result = SearchResult(
            element=cls,
            result_type=SearchResultType.ELEMENT_NAME,
            match_field="name",
            match_value="TestClass",
        )

        assert result.element_type_name == "Class"

    def test_search_result_description(self, element_factory):
        """Test search result description generation."""
        from gaphor.ui.advancedsearch.searchresult import SearchResult

        cls = element_factory.create(UML.Class)
        cls.name = "TestClass"

        result = SearchResult(
            element=cls,
            result_type=SearchResultType.ELEMENT_NAME,
            match_field="name",
            match_value="TestClass",
        )

        assert "TestClass" in result.description

    def test_search_result_equality(self, element_factory):
        """Test search result equality comparison."""
        from gaphor.ui.advancedsearch.searchresult import SearchResult

        cls = element_factory.create(UML.Class)
        cls.name = "TestClass"

        result1 = SearchResult(
            element=cls,
            result_type=SearchResultType.ELEMENT_NAME,
            match_field="name",
            match_value="TestClass",
        )

        result2 = SearchResult(
            element=cls,
            result_type=SearchResultType.ELEMENT_NAME,
            match_field="name",
            match_value="TestClass",
        )

        assert result1 == result2

    def test_search_result_hash(self, element_factory):
        """Test search result can be hashed."""
        from gaphor.ui.advancedsearch.searchresult import SearchResult

        cls = element_factory.create(UML.Class)
        cls.name = "TestClass"

        result = SearchResult(
            element=cls,
            result_type=SearchResultType.ELEMENT_NAME,
            match_field="name",
            match_value="TestClass",
        )

        # Should be hashable
        result_set = {result}
        assert result in result_set


class TestDiagramLocation:
    """Tests for DiagramLocation dataclass."""

    def test_diagram_location_name(self, element_factory):
        """Test that diagram location provides diagram name."""
        from gaphor.ui.advancedsearch.searchresult import DiagramLocation

        diagram = element_factory.create(Diagram)
        diagram.name = "TestDiagram"

        location = DiagramLocation(diagram=diagram)

        assert location.diagram_name == "TestDiagram"

    def test_diagram_location_id(self, element_factory):
        """Test that diagram location provides diagram ID."""
        from gaphor.ui.advancedsearch.searchresult import DiagramLocation

        diagram = element_factory.create(Diagram)
        diagram.name = "TestDiagram"

        location = DiagramLocation(diagram=diagram)

        assert location.diagram_id == diagram.id

    def test_diagram_location_unnamed_diagram(self, element_factory):
        """Test handling of unnamed diagrams."""
        from gaphor.ui.advancedsearch.searchresult import DiagramLocation

        diagram = element_factory.create(Diagram)
        # Don't set a name

        location = DiagramLocation(diagram=diagram)

        assert location.diagram_name == "<Unnamed Diagram>"


class TestSearchScope:
    """Tests for search scope functionality."""

    def test_global_scope_searches_all(self, search_engine, sample_model):
        """Test that global scope searches all elements."""
        results = search_engine.search("Class", scope=SearchScope.GLOBAL)

        # Should find classes regardless of diagram
        assert len(results) > 0

    def test_current_diagram_scope_no_diagram(self, search_engine, sample_model):
        """Test current diagram scope with no diagram provided."""
        results = search_engine.search(
            "Class", scope=SearchScope.CURRENT_DIAGRAM, current_diagram=None
        )

        # Should fall back to global search
        assert len(results) > 0
