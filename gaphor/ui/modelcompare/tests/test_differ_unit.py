"""Unit tests for the differ module that don't require GTK."""

import pytest

from gaphor.ui.modelcompare.differ import (
    ChangeType,
    ElementDiff,
    ModelDiff,
    PropertyChange,
    format_property_change,
    get_element_display_name,
    _format_value,
)


class TestChangeType:
    """Tests for the ChangeType enum."""

    def test_all_change_types_defined(self):
        assert ChangeType.ADDED is not None
        assert ChangeType.REMOVED is not None
        assert ChangeType.MODIFIED is not None
        assert ChangeType.UNCHANGED is not None


class TestPropertyChange:
    """Tests for PropertyChange dataclass."""

    def test_create_property_change(self):
        change = PropertyChange(
            property_name="name",
            old_value="old",
            new_value="new",
            change_type=ChangeType.MODIFIED,
        )
        assert change.property_name == "name"
        assert change.old_value == "old"
        assert change.new_value == "new"
        assert change.change_type == ChangeType.MODIFIED

    def test_is_reference_with_string(self):
        change = PropertyChange(
            property_name="test",
            old_value="ref:12345",
            new_value=None,
            change_type=ChangeType.REMOVED,
        )
        # Strings are not Base objects
        assert not change.is_reference

    def test_is_collection_with_tuple(self):
        change = PropertyChange(
            property_name="test",
            old_value=("ref:1", "ref:2"),
            new_value=None,
            change_type=ChangeType.REMOVED,
        )
        # Tuples are not collection objects
        assert not change.is_collection

    def test_frozen_dataclass(self):
        change = PropertyChange(
            property_name="name",
            old_value="old",
            new_value="new",
            change_type=ChangeType.MODIFIED,
        )
        # PropertyChange is frozen
        with pytest.raises(AttributeError):
            change.property_name = "other"


class TestElementDiff:
    """Tests for ElementDiff dataclass."""

    def test_create_element_diff(self):
        diff = ElementDiff(
            element_id="test-id",
            element_type="Class",
            element_name="TestClass",
            change_type=ChangeType.ADDED,
        )
        assert diff.element_id == "test-id"
        assert diff.element_type == "Class"
        assert diff.element_name == "TestClass"
        assert diff.change_type == ChangeType.ADDED
        assert diff.property_changes == []

    def test_is_diagram_with_diagram_type(self):
        diff = ElementDiff(
            element_id="1",
            element_type="Diagram",
            element_name="Test",
            change_type=ChangeType.ADDED,
        )
        assert diff.is_diagram

    def test_is_diagram_with_specific_diagram_type(self):
        diff = ElementDiff(
            element_id="1",
            element_type="ClassDiagram",
            element_name="Test",
            change_type=ChangeType.ADDED,
        )
        assert diff.is_diagram

    def test_is_not_diagram(self):
        diff = ElementDiff(
            element_id="1",
            element_type="Class",
            element_name="Test",
            change_type=ChangeType.ADDED,
        )
        assert not diff.is_diagram

    def test_is_presentation_with_item_suffix(self):
        diff = ElementDiff(
            element_id="1",
            element_type="ClassItem",
            element_name="Test",
            change_type=ChangeType.ADDED,
        )
        assert diff.is_presentation

    def test_is_not_presentation(self):
        diff = ElementDiff(
            element_id="1",
            element_type="Class",
            element_name="Test",
            change_type=ChangeType.ADDED,
        )
        assert not diff.is_presentation

    def test_has_significant_changes_for_added(self):
        diff = ElementDiff(
            element_id="1",
            element_type="Class",
            element_name="Test",
            change_type=ChangeType.ADDED,
        )
        assert diff.has_significant_changes

    def test_has_significant_changes_for_removed(self):
        diff = ElementDiff(
            element_id="1",
            element_type="Class",
            element_name="Test",
            change_type=ChangeType.REMOVED,
        )
        assert diff.has_significant_changes

    def test_has_significant_changes_for_name_change(self):
        diff = ElementDiff(
            element_id="1",
            element_type="Class",
            element_name="Test",
            change_type=ChangeType.MODIFIED,
            property_changes=[
                PropertyChange(
                    property_name="name",
                    old_value="Old",
                    new_value="New",
                    change_type=ChangeType.MODIFIED,
                )
            ],
        )
        assert diff.has_significant_changes

    def test_has_significant_changes_for_visibility_change(self):
        diff = ElementDiff(
            element_id="1",
            element_type="Property",
            element_name="Test",
            change_type=ChangeType.MODIFIED,
            property_changes=[
                PropertyChange(
                    property_name="visibility",
                    old_value="public",
                    new_value="private",
                    change_type=ChangeType.MODIFIED,
                )
            ],
        )
        assert diff.has_significant_changes

    def test_no_significant_changes_for_position_only(self):
        diff = ElementDiff(
            element_id="1",
            element_type="ClassItem",
            element_name="Test",
            change_type=ChangeType.MODIFIED,
            property_changes=[
                PropertyChange(
                    property_name="matrix",
                    old_value="(1, 0, 0, 1, 0, 0)",
                    new_value="(1, 0, 0, 1, 10, 10)",
                    change_type=ChangeType.MODIFIED,
                )
            ],
        )
        assert not diff.has_significant_changes

    def test_no_significant_changes_for_width_height_only(self):
        diff = ElementDiff(
            element_id="1",
            element_type="ClassItem",
            element_name="Test",
            change_type=ChangeType.MODIFIED,
            property_changes=[
                PropertyChange(
                    property_name="width",
                    old_value=100,
                    new_value=120,
                    change_type=ChangeType.MODIFIED,
                ),
                PropertyChange(
                    property_name="height",
                    old_value=50,
                    new_value=60,
                    change_type=ChangeType.MODIFIED,
                ),
            ],
        )
        assert not diff.has_significant_changes


class TestModelDiff:
    """Tests for ModelDiff dataclass."""

    def test_create_empty_diff(self):
        diff = ModelDiff(base_model_path=None, compare_model_path=None)
        assert not diff.has_changes
        assert diff.element_diffs == []
        assert diff.errors == []

    def test_create_diff_with_paths(self):
        diff = ModelDiff(
            base_model_path="/path/to/base.gaphor",
            compare_model_path="/path/to/compare.gaphor",
        )
        assert diff.base_model_path == "/path/to/base.gaphor"
        assert diff.compare_model_path == "/path/to/compare.gaphor"

    def test_has_changes_empty(self):
        diff = ModelDiff(base_model_path=None, compare_model_path=None)
        assert not diff.has_changes

    def test_has_changes_with_diffs(self):
        diff = ModelDiff(
            base_model_path=None,
            compare_model_path=None,
            element_diffs=[
                ElementDiff(
                    element_id="test",
                    element_type="Class",
                    element_name="Test",
                    change_type=ChangeType.ADDED,
                )
            ],
        )
        assert diff.has_changes

    def test_added_elements_filter(self):
        diff = ModelDiff(
            base_model_path=None,
            compare_model_path=None,
            element_diffs=[
                ElementDiff(
                    element_id="1",
                    element_type="Class",
                    element_name="Added",
                    change_type=ChangeType.ADDED,
                ),
                ElementDiff(
                    element_id="2",
                    element_type="Class",
                    element_name="Removed",
                    change_type=ChangeType.REMOVED,
                ),
            ],
        )
        added = diff.added_elements
        assert len(added) == 1
        assert added[0].element_id == "1"

    def test_removed_elements_filter(self):
        diff = ModelDiff(
            base_model_path=None,
            compare_model_path=None,
            element_diffs=[
                ElementDiff(
                    element_id="1",
                    element_type="Class",
                    element_name="Added",
                    change_type=ChangeType.ADDED,
                ),
                ElementDiff(
                    element_id="2",
                    element_type="Class",
                    element_name="Removed",
                    change_type=ChangeType.REMOVED,
                ),
            ],
        )
        removed = diff.removed_elements
        assert len(removed) == 1
        assert removed[0].element_id == "2"

    def test_modified_elements_filter(self):
        diff = ModelDiff(
            base_model_path=None,
            compare_model_path=None,
            element_diffs=[
                ElementDiff(
                    element_id="1",
                    element_type="Class",
                    element_name="Modified",
                    change_type=ChangeType.MODIFIED,
                ),
                ElementDiff(
                    element_id="2",
                    element_type="Class",
                    element_name="Added",
                    change_type=ChangeType.ADDED,
                ),
            ],
        )
        modified = diff.modified_elements
        assert len(modified) == 1
        assert modified[0].element_id == "1"

    def test_diagram_diffs_filter(self):
        diff = ModelDiff(
            base_model_path=None,
            compare_model_path=None,
            element_diffs=[
                ElementDiff(
                    element_id="1",
                    element_type="Diagram",
                    element_name="TestDiagram",
                    change_type=ChangeType.ADDED,
                ),
                ElementDiff(
                    element_id="2",
                    element_type="Class",
                    element_name="TestClass",
                    change_type=ChangeType.ADDED,
                ),
            ],
        )
        diagram_diffs = diff.diagram_diffs
        assert len(diagram_diffs) == 1
        assert diagram_diffs[0].element_type == "Diagram"

    def test_significant_changes_filter(self):
        diff = ModelDiff(
            base_model_path=None,
            compare_model_path=None,
            element_diffs=[
                ElementDiff(
                    element_id="1",
                    element_type="Class",
                    element_name="Test",
                    change_type=ChangeType.ADDED,  # Significant
                ),
                ElementDiff(
                    element_id="2",
                    element_type="ClassItem",
                    element_name="Test",
                    change_type=ChangeType.MODIFIED,
                    property_changes=[
                        PropertyChange(
                            property_name="matrix",
                            old_value="old",
                            new_value="new",
                            change_type=ChangeType.MODIFIED,
                        )
                    ],  # Not significant (position only)
                ),
            ],
        )
        significant = diff.significant_changes
        assert len(significant) == 1
        assert significant[0].element_id == "1"

    def test_get_diff_for_element_found(self):
        diff = ModelDiff(
            base_model_path=None,
            compare_model_path=None,
            element_diffs=[
                ElementDiff(
                    element_id="target-id",
                    element_type="Class",
                    element_name="Test",
                    change_type=ChangeType.ADDED,
                ),
            ],
        )
        found = diff.get_diff_for_element("target-id")
        assert found is not None
        assert found.element_id == "target-id"

    def test_get_diff_for_element_not_found(self):
        diff = ModelDiff(
            base_model_path=None,
            compare_model_path=None,
            element_diffs=[
                ElementDiff(
                    element_id="other-id",
                    element_type="Class",
                    element_name="Test",
                    change_type=ChangeType.ADDED,
                ),
            ],
        )
        found = diff.get_diff_for_element("nonexistent-id")
        assert found is None

    def test_get_diff_for_element_with_none(self):
        diff = ModelDiff(base_model_path=None, compare_model_path=None)
        assert diff.get_diff_for_element(None) is None

    def test_get_diff_for_element_with_empty_string(self):
        diff = ModelDiff(base_model_path=None, compare_model_path=None)
        assert diff.get_diff_for_element("") is None


class TestFormatPropertyChange:
    """Tests for format_property_change function."""

    def test_format_added_property(self):
        change = PropertyChange(
            property_name="name",
            old_value=None,
            new_value="NewValue",
            change_type=ChangeType.ADDED,
        )
        formatted = format_property_change(change)
        assert "+" in formatted
        assert "name" in formatted
        assert "NewValue" in formatted

    def test_format_removed_property(self):
        change = PropertyChange(
            property_name="name",
            old_value="OldValue",
            new_value=None,
            change_type=ChangeType.REMOVED,
        )
        formatted = format_property_change(change)
        assert "-" in formatted
        assert "name" in formatted
        assert "OldValue" in formatted

    def test_format_modified_property(self):
        change = PropertyChange(
            property_name="name",
            old_value="OldValue",
            new_value="NewValue",
            change_type=ChangeType.MODIFIED,
        )
        formatted = format_property_change(change)
        assert "~" in formatted
        assert "name" in formatted
        assert "→" in formatted
        assert "OldValue" in formatted or "<" in formatted
        assert "NewValue" in formatted or ">" in formatted


class TestGetElementDisplayName:
    """Tests for get_element_display_name function."""

    def test_with_none(self):
        assert get_element_display_name(None) == "<Unknown>"


class TestFormatValue:
    """Tests for _format_value function."""

    def test_format_none(self):
        assert _format_value(None) == "<none>"

    def test_format_reference(self):
        result = _format_value("ref:12345678-abcd")
        assert "[1234" in result

    def test_format_short_tuple(self):
        result = _format_value((1, 2, 3))
        assert "1" in result
        assert "2" in result
        assert "3" in result

    def test_format_long_tuple(self):
        result = _format_value((1, 2, 3, 4, 5))
        assert "items" in result

    def test_format_long_string(self):
        long_string = "x" * 100
        result = _format_value(long_string)
        assert len(result) < len(long_string)
        assert "..." in result

    def test_format_short_string(self):
        short_string = "hello"
        result = _format_value(short_string)
        assert result == "hello"

    def test_format_number(self):
        assert _format_value(42) == "42"
