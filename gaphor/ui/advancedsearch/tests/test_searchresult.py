"""Tests for SearchResult and DiagramLocation classes.

These tests don't require GTK and can run in a minimal environment.
"""

import pytest

from gaphor.ui.advancedsearch.searchresult import (
    DiagramLocation,
    SearchResult,
    SearchResultType,
)


class MockElement:
    """Mock element for testing without requiring the full model."""

    def __init__(self, id_value: str, name: str | None = None):
        self._id = id_value
        self.name = name

    @property
    def id(self):
        return self._id


class MockDiagram:
    """Mock diagram for testing."""

    def __init__(self, id_value: str, name: str | None = None):
        self._id = id_value
        self.name = name

    @property
    def id(self):
        return self._id


class TestSearchResultType:
    """Tests for SearchResultType enum."""

    def test_all_types_defined(self):
        """Verify all expected search result types exist."""
        assert SearchResultType.ELEMENT_NAME
        assert SearchResultType.ELEMENT_TYPE
        assert SearchResultType.ATTRIBUTE_NAME
        assert SearchResultType.ATTRIBUTE_VALUE
        assert SearchResultType.RELATIONSHIP_TYPE
        assert SearchResultType.DIAGRAM_NAME

    def test_type_values_are_strings(self):
        """All type values should be strings."""
        for result_type in SearchResultType:
            assert isinstance(result_type.value, str)


class TestDiagramLocation:
    """Tests for DiagramLocation dataclass."""

    def test_creation_with_diagram(self):
        """Test creating a DiagramLocation with a diagram."""
        diagram = MockDiagram("diag-1", "TestDiagram")
        location = DiagramLocation(diagram=diagram)

        assert location.diagram is diagram
        assert location.presentation is None

    def test_creation_with_diagram_and_presentation(self):
        """Test creating a DiagramLocation with diagram and presentation."""
        diagram = MockDiagram("diag-1", "TestDiagram")
        presentation = MockElement("pres-1", "PresentationItem")

        location = DiagramLocation(diagram=diagram, presentation=presentation)

        assert location.diagram is diagram
        assert location.presentation is presentation

    def test_diagram_name_property(self):
        """Test diagram_name property returns correct name."""
        diagram = MockDiagram("diag-1", "MyDiagram")
        location = DiagramLocation(diagram=diagram)

        assert location.diagram_name == "MyDiagram"

    def test_diagram_name_unnamed(self):
        """Test diagram_name for unnamed diagram."""
        diagram = MockDiagram("diag-1", None)
        location = DiagramLocation(diagram=diagram)

        assert location.diagram_name == "<Unnamed Diagram>"

    def test_diagram_name_empty_string(self):
        """Test diagram_name for empty string name."""
        diagram = MockDiagram("diag-1", "")
        location = DiagramLocation(diagram=diagram)

        # Empty string is falsy, should return placeholder
        assert location.diagram_name == "<Unnamed Diagram>"

    def test_diagram_name_none_diagram(self):
        """Test diagram_name when diagram is None."""
        location = DiagramLocation(diagram=None)

        assert location.diagram_name == "<Unknown>"

    def test_diagram_id_property(self):
        """Test diagram_id property."""
        diagram = MockDiagram("diag-123", "TestDiagram")
        location = DiagramLocation(diagram=diagram)

        assert location.diagram_id == "diag-123"

    def test_diagram_id_none_diagram(self):
        """Test diagram_id when diagram is None."""
        location = DiagramLocation(diagram=None)

        assert location.diagram_id == ""


class TestSearchResult:
    """Tests for SearchResult dataclass."""

    def test_creation_minimal(self):
        """Test creating a SearchResult with minimal fields."""
        element = MockElement("elem-1", "TestElement")
        result = SearchResult(
            element=element,
            result_type=SearchResultType.ELEMENT_NAME,
            match_field="name",
            match_value="TestElement",
        )

        assert result.element is element
        assert result.result_type == SearchResultType.ELEMENT_NAME
        assert result.match_field == "name"
        assert result.match_value == "TestElement"
        assert result.relevance_score == 1.0  # default
        assert result.diagram_locations == []  # default

    def test_creation_with_all_fields(self):
        """Test creating a SearchResult with all fields."""
        element = MockElement("elem-1", "TestElement")
        diagram = MockDiagram("diag-1", "TestDiagram")
        location = DiagramLocation(diagram=diagram)

        result = SearchResult(
            element=element,
            result_type=SearchResultType.ATTRIBUTE_VALUE,
            match_field="customerId",
            match_value="12345",
            relevance_score=0.85,
            diagram_locations=[location],
        )

        assert result.relevance_score == 0.85
        assert len(result.diagram_locations) == 1

    def test_element_id_property(self):
        """Test element_id property."""
        element = MockElement("elem-456", "TestElement")
        result = SearchResult(
            element=element,
            result_type=SearchResultType.ELEMENT_NAME,
            match_field="name",
            match_value="TestElement",
        )

        assert result.element_id == "elem-456"

    def test_element_id_none_element(self):
        """Test element_id when element is None."""
        result = SearchResult(
            element=None,
            result_type=SearchResultType.ELEMENT_NAME,
            match_field="name",
            match_value="Test",
        )

        assert result.element_id == ""

    def test_element_name_property(self):
        """Test element_name property."""
        element = MockElement("elem-1", "MyElement")
        result = SearchResult(
            element=element,
            result_type=SearchResultType.ELEMENT_NAME,
            match_field="name",
            match_value="MyElement",
        )

        assert result.element_name == "MyElement"

    def test_element_name_unnamed(self):
        """Test element_name for unnamed element."""
        element = MockElement("elem-1", None)
        result = SearchResult(
            element=element,
            result_type=SearchResultType.ELEMENT_NAME,
            match_field="name",
            match_value="",
        )

        # Should return type name placeholder
        assert "<" in result.element_name
        assert ">" in result.element_name

    def test_element_name_none_element(self):
        """Test element_name when element is None."""
        result = SearchResult(
            element=None,
            result_type=SearchResultType.ELEMENT_NAME,
            match_field="name",
            match_value="Test",
        )

        assert result.element_name == "<None>"

    def test_element_type_name_property(self):
        """Test element_type_name property."""
        element = MockElement("elem-1", "Test")
        result = SearchResult(
            element=element,
            result_type=SearchResultType.ELEMENT_NAME,
            match_field="name",
            match_value="Test",
        )

        assert result.element_type_name == "MockElement"

    def test_element_type_name_none_element(self):
        """Test element_type_name when element is None."""
        result = SearchResult(
            element=None,
            result_type=SearchResultType.ELEMENT_NAME,
            match_field="name",
            match_value="Test",
        )

        assert result.element_type_name == "Unknown"

    def test_description_element_name(self):
        """Test description for ELEMENT_NAME result type."""
        element = MockElement("elem-1", "Test")
        result = SearchResult(
            element=element,
            result_type=SearchResultType.ELEMENT_NAME,
            match_field="name",
            match_value="TestValue",
        )

        assert "Name:" in result.description
        assert "TestValue" in result.description

    def test_description_element_type(self):
        """Test description for ELEMENT_TYPE result type."""
        element = MockElement("elem-1", "Test")
        result = SearchResult(
            element=element,
            result_type=SearchResultType.ELEMENT_TYPE,
            match_field="type",
            match_value="Class",
        )

        assert "Type:" in result.description
        assert "Class" in result.description

    def test_description_attribute_name(self):
        """Test description for ATTRIBUTE_NAME result type."""
        element = MockElement("elem-1", "Test")
        result = SearchResult(
            element=element,
            result_type=SearchResultType.ATTRIBUTE_NAME,
            match_field="customerId",
            match_value="customerId",
        )

        assert "Attribute:" in result.description
        assert "customerId" in result.description

    def test_description_attribute_value(self):
        """Test description for ATTRIBUTE_VALUE result type."""
        element = MockElement("elem-1", "Test")
        result = SearchResult(
            element=element,
            result_type=SearchResultType.ATTRIBUTE_VALUE,
            match_field="customerId",
            match_value="12345",
        )

        assert "customerId:" in result.description
        assert "12345" in result.description

    def test_description_relationship_type(self):
        """Test description for RELATIONSHIP_TYPE result type."""
        element = MockElement("elem-1", "Test")
        result = SearchResult(
            element=element,
            result_type=SearchResultType.RELATIONSHIP_TYPE,
            match_field="relationship_type",
            match_value="Association",
        )

        assert "Relationship:" in result.description
        assert "Association" in result.description

    def test_description_diagram_name(self):
        """Test description for DIAGRAM_NAME result type."""
        element = MockElement("elem-1", "Test")
        result = SearchResult(
            element=element,
            result_type=SearchResultType.DIAGRAM_NAME,
            match_field="name",
            match_value="MainDiagram",
        )

        assert "Diagram:" in result.description
        assert "MainDiagram" in result.description

    def test_location_summary_no_locations(self):
        """Test location_summary with no diagram locations."""
        element = MockElement("elem-1", "Test")
        result = SearchResult(
            element=element,
            result_type=SearchResultType.ELEMENT_NAME,
            match_field="name",
            match_value="Test",
            diagram_locations=[],
        )

        assert result.location_summary == "Not in any diagram"

    def test_location_summary_one_location(self):
        """Test location_summary with one diagram location."""
        element = MockElement("elem-1", "Test")
        diagram = MockDiagram("diag-1", "MyDiagram")
        location = DiagramLocation(diagram=diagram)

        result = SearchResult(
            element=element,
            result_type=SearchResultType.ELEMENT_NAME,
            match_field="name",
            match_value="Test",
            diagram_locations=[location],
        )

        assert "In:" in result.location_summary
        assert "MyDiagram" in result.location_summary

    def test_location_summary_multiple_locations(self):
        """Test location_summary with multiple diagram locations."""
        element = MockElement("elem-1", "Test")
        locations = [
            DiagramLocation(diagram=MockDiagram(f"diag-{i}", f"Diagram{i}"))
            for i in range(5)
        ]

        result = SearchResult(
            element=element,
            result_type=SearchResultType.ELEMENT_NAME,
            match_field="name",
            match_value="Test",
            diagram_locations=locations,
        )

        summary = result.location_summary
        assert "In:" in summary
        assert "(+2 more)" in summary  # 5 - 3 = 2 more

    def test_hash(self):
        """Test that SearchResult is hashable."""
        element = MockElement("elem-1", "Test")
        result = SearchResult(
            element=element,
            result_type=SearchResultType.ELEMENT_NAME,
            match_field="name",
            match_value="Test",
        )

        # Should not raise
        hash_value = hash(result)
        assert isinstance(hash_value, int)

    def test_equality_same(self):
        """Test equality for same results."""
        element = MockElement("elem-1", "Test")
        result1 = SearchResult(
            element=element,
            result_type=SearchResultType.ELEMENT_NAME,
            match_field="name",
            match_value="Test",
        )
        result2 = SearchResult(
            element=element,
            result_type=SearchResultType.ELEMENT_NAME,
            match_field="name",
            match_value="Test",
        )

        assert result1 == result2

    def test_equality_different_type(self):
        """Test equality for different result types."""
        element = MockElement("elem-1", "Test")
        result1 = SearchResult(
            element=element,
            result_type=SearchResultType.ELEMENT_NAME,
            match_field="name",
            match_value="Test",
        )
        result2 = SearchResult(
            element=element,
            result_type=SearchResultType.ELEMENT_TYPE,
            match_field="type",
            match_value="Test",
        )

        assert result1 != result2

    def test_equality_different_element(self):
        """Test equality for different elements."""
        element1 = MockElement("elem-1", "Test")
        element2 = MockElement("elem-2", "Test")
        result1 = SearchResult(
            element=element1,
            result_type=SearchResultType.ELEMENT_NAME,
            match_field="name",
            match_value="Test",
        )
        result2 = SearchResult(
            element=element2,
            result_type=SearchResultType.ELEMENT_NAME,
            match_field="name",
            match_value="Test",
        )

        assert result1 != result2

    def test_equality_non_searchresult(self):
        """Test equality with non-SearchResult object."""
        element = MockElement("elem-1", "Test")
        result = SearchResult(
            element=element,
            result_type=SearchResultType.ELEMENT_NAME,
            match_field="name",
            match_value="Test",
        )

        assert result != "not a search result"
        assert result != None
        assert result != 42

    def test_can_be_used_in_set(self):
        """Test that SearchResult can be used in a set."""
        element = MockElement("elem-1", "Test")
        result1 = SearchResult(
            element=element,
            result_type=SearchResultType.ELEMENT_NAME,
            match_field="name",
            match_value="Test",
        )
        result2 = SearchResult(
            element=element,
            result_type=SearchResultType.ELEMENT_NAME,
            match_field="name",
            match_value="Test",
        )

        result_set = {result1, result2}
        assert len(result_set) == 1  # Duplicates removed

    def test_can_be_used_as_dict_key(self):
        """Test that SearchResult can be used as a dict key."""
        element = MockElement("elem-1", "Test")
        result = SearchResult(
            element=element,
            result_type=SearchResultType.ELEMENT_NAME,
            match_field="name",
            match_value="Test",
        )

        result_dict = {result: "value"}
        assert result_dict[result] == "value"
