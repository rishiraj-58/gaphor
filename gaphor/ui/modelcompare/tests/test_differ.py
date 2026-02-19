"""Tests for the model differ module."""

import pytest

from gaphor.core.modeling import Diagram, ElementFactory
from gaphor.core.modeling.stylesheet import StyleSheet
from gaphor.diagram.general.simpleitem import Box
from gaphor.UML import Class, Package, Property
from gaphor.ui.modelcompare.differ import (
    ChangeType,
    ElementDiff,
    ModelDiff,
    PropertyChange,
    compute_model_diff,
    format_property_change,
    get_element_display_name,
)


@pytest.fixture
def base_factory(element_factory):
    """The base/current model factory."""
    return element_factory


@pytest.fixture
def compare_factory():
    """The model to compare against."""
    return ElementFactory()


class TestModelDiffer:
    """Tests for the ModelDiffer class."""

    def test_empty_factories_produce_no_diff(self, base_factory, compare_factory):
        diff = compute_model_diff(base_factory, compare_factory)

        assert not diff.has_changes
        assert len(diff.element_diffs) == 0
        assert len(diff.errors) == 0

    def test_identical_elements_produce_no_diff(self, base_factory, compare_factory):
        # Create identical elements in both factories
        pkg = base_factory.create(Package)
        pkg.name = "TestPackage"

        compare_pkg = compare_factory.create_as(Package, pkg.id)
        compare_pkg.name = "TestPackage"

        diff = compute_model_diff(base_factory, compare_factory)

        # Should have no diffs (identical elements)
        modified_diffs = [
            d for d in diff.element_diffs if d.change_type == ChangeType.MODIFIED
        ]
        assert not any(d.property_changes for d in modified_diffs)

    def test_added_element_detected(self, base_factory, compare_factory):
        # Add element only in compare factory
        new_class = compare_factory.create(Class)
        new_class.name = "NewClass"

        diff = compute_model_diff(base_factory, compare_factory)

        assert diff.has_changes
        added = diff.added_elements
        assert len(added) == 1
        assert added[0].element_id == new_class.id
        assert added[0].element_type == "Class"
        assert added[0].change_type == ChangeType.ADDED

    def test_removed_element_detected(self, base_factory, compare_factory):
        # Add element only in base factory
        old_class = base_factory.create(Class)
        old_class.name = "OldClass"

        diff = compute_model_diff(base_factory, compare_factory)

        assert diff.has_changes
        removed = diff.removed_elements
        assert len(removed) == 1
        assert removed[0].element_id == old_class.id
        assert removed[0].element_type == "Class"
        assert removed[0].change_type == ChangeType.REMOVED

    def test_modified_element_detected(self, base_factory, compare_factory):
        # Create same element in both with different names
        base_class = base_factory.create(Class)
        base_class.name = "OriginalName"

        compare_class = compare_factory.create_as(Class, base_class.id)
        compare_class.name = "ModifiedName"

        diff = compute_model_diff(base_factory, compare_factory)

        assert diff.has_changes
        modified = diff.modified_elements
        assert len(modified) == 1
        assert modified[0].element_id == base_class.id
        assert modified[0].change_type == ChangeType.MODIFIED

        # Check property changes
        name_changes = [
            c for c in modified[0].property_changes if c.property_name == "name"
        ]
        assert len(name_changes) == 1
        assert name_changes[0].old_value == "OriginalName"
        assert name_changes[0].new_value == "ModifiedName"

    def test_stylesheet_changes_skipped(self, base_factory, compare_factory):
        # StyleSheets should be skipped to avoid noise
        base_ss = base_factory.create(StyleSheet)
        compare_ss = compare_factory.create(StyleSheet)  # Different ID
        compare_ss.styleSheet = "different style"

        diff = compute_model_diff(base_factory, compare_factory)

        # StyleSheet diffs should be filtered out
        ss_diffs = [d for d in diff.element_diffs if "StyleSheet" in d.element_type]
        assert len(ss_diffs) == 0

    def test_multiple_changes(self, base_factory, compare_factory):
        # Multiple types of changes
        # 1. Added element
        added_class = compare_factory.create(Class)
        added_class.name = "AddedClass"

        # 2. Removed element
        removed_class = base_factory.create(Class)
        removed_class.name = "RemovedClass"

        # 3. Modified element
        base_pkg = base_factory.create(Package)
        base_pkg.name = "OldPackageName"
        compare_pkg = compare_factory.create_as(Package, base_pkg.id)
        compare_pkg.name = "NewPackageName"

        diff = compute_model_diff(base_factory, compare_factory)

        assert diff.has_changes
        assert len(diff.added_elements) == 1
        assert len(diff.removed_elements) == 1
        assert len(diff.modified_elements) == 1

    def test_diagram_diffs_detected(self, base_factory, compare_factory):
        # Add a diagram in compare
        diagram = compare_factory.create(Diagram)
        diagram.name = "NewDiagram"

        diff = compute_model_diff(base_factory, compare_factory)

        diagram_diffs = diff.diagram_diffs
        assert len(diagram_diffs) == 1
        assert diagram_diffs[0].is_diagram

    def test_presentation_diffs_detected(self, base_factory, compare_factory, event_manager):
        from gaphor.core import Transaction

        # Create a diagram with a presentation item
        with Transaction(event_manager):
            base_diagram = base_factory.create(Diagram)
            base_diagram.name = "TestDiagram"
            box = base_diagram.create(Box)

        compare_diagram = compare_factory.create_as(Diagram, base_diagram.id)
        compare_diagram.name = "TestDiagram"

        diff = compute_model_diff(base_factory, compare_factory)

        # Should detect removed presentation
        presentation_diffs = [d for d in diff.element_diffs if d.is_presentation]
        assert len(presentation_diffs) == 1
        assert presentation_diffs[0].change_type == ChangeType.REMOVED

    def test_get_diff_for_element(self, base_factory, compare_factory):
        added_class = compare_factory.create(Class)
        added_class.name = "TestClass"

        diff = compute_model_diff(base_factory, compare_factory)

        found = diff.get_diff_for_element(added_class.id)
        assert found is not None
        assert found.element_id == added_class.id

        not_found = diff.get_diff_for_element("nonexistent-id")
        assert not_found is None

    def test_significant_changes_filter(self, base_factory, compare_factory):
        # Create a change that's significant (name change)
        base_class = base_factory.create(Class)
        base_class.name = "OldName"
        compare_class = compare_factory.create_as(Class, base_class.id)
        compare_class.name = "NewName"

        diff = compute_model_diff(base_factory, compare_factory)

        significant = diff.significant_changes
        assert len(significant) >= 1

    def test_null_factory_raises_error(self, base_factory):
        with pytest.raises(ValueError, match="compare_factory"):
            compute_model_diff(base_factory, None)

        with pytest.raises(ValueError, match="base_factory"):
            compute_model_diff(None, ElementFactory())


class TestPropertyChange:
    """Tests for PropertyChange dataclass."""

    def test_is_reference(self):
        change = PropertyChange(
            property_name="test",
            old_value="ref:12345",
            new_value=None,
            change_type=ChangeType.REMOVED,
        )
        # String starting with 'ref:' is normalized reference, not a Base object
        assert not change.is_reference

    def test_change_type_values(self):
        for change_type in ChangeType:
            change = PropertyChange(
                property_name="test",
                old_value="old",
                new_value="new",
                change_type=change_type,
            )
            assert change.change_type == change_type


class TestModelDiff:
    """Tests for ModelDiff dataclass."""

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

    def test_filter_by_change_type(self):
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
                ElementDiff(
                    element_id="3",
                    element_type="Class",
                    element_name="Modified",
                    change_type=ChangeType.MODIFIED,
                ),
            ],
        )

        assert len(diff.added_elements) == 1
        assert len(diff.removed_elements) == 1
        assert len(diff.modified_elements) == 1


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_get_element_display_name_with_name(self, element_factory):
        cls = element_factory.create(Class)
        cls.name = "MyClass"
        assert get_element_display_name(cls) == "MyClass"

    def test_get_element_display_name_without_name(self, element_factory):
        cls = element_factory.create(Class)
        display = get_element_display_name(cls)
        assert "Class" in display
        assert cls.id[:8] in display

    def test_get_element_display_name_none(self):
        assert get_element_display_name(None) == "<Unknown>"

    def test_format_property_change_added(self):
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

    def test_format_property_change_removed(self):
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

    def test_format_property_change_modified(self):
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


class TestElementDiff:
    """Tests for ElementDiff dataclass."""

    def test_is_diagram(self):
        diff = ElementDiff(
            element_id="1",
            element_type="Diagram",
            element_name="Test",
            change_type=ChangeType.ADDED,
        )
        assert diff.is_diagram

        diff2 = ElementDiff(
            element_id="1",
            element_type="ClassDiagram",
            element_name="Test",
            change_type=ChangeType.ADDED,
        )
        assert diff2.is_diagram

    def test_is_presentation(self):
        diff = ElementDiff(
            element_id="1",
            element_type="ClassItem",
            element_name="Test",
            change_type=ChangeType.ADDED,
        )
        assert diff.is_presentation

        diff2 = ElementDiff(
            element_id="1",
            element_type="Class",
            element_name="Test",
            change_type=ChangeType.ADDED,
        )
        assert not diff2.is_presentation

    def test_has_significant_changes_for_added(self):
        diff = ElementDiff(
            element_id="1",
            element_type="Class",
            element_name="Test",
            change_type=ChangeType.ADDED,
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
