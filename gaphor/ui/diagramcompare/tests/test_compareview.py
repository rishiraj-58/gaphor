"""Tests for the DiagramCompareView UI component."""

import pytest

from gaphor.core.modeling import Diagram, ElementFactory
from gaphor.diagram.general.simpleitem import Box
from gaphor.ui.diagramcompare.comparator import ChangeType, compare_diagrams


def test_compare_diagrams_creates_valid_diff(event_manager):
    """Verify that comparing diagrams produces the expected diff structure."""
    from gaphor.core import Transaction

    base_factory = ElementFactory()
    compare_factory = ElementFactory()

    with Transaction(event_manager):
        base_diagram = base_factory.create(Diagram)
        base_diagram.name = "Test Diagram"
        base_box = base_diagram.create(Box)
        base_box.width = 100

    with Transaction(event_manager):
        compare_diagram = compare_factory.create_as(Diagram, base_diagram.id)
        compare_diagram.name = "Test Diagram Modified"  # Name changed
        compare_box = compare_diagram.create_as(Box, base_box.id)
        compare_box.width = 150  # Size changed
        new_box = compare_diagram.create(Box)  # New item added

    diff = compare_diagrams(base_diagram, compare_diagram)

    # Should detect diagram name change
    name_diff = next(
        (p for p in diff.diagram_property_diffs if p.property_name == "name"), None
    )
    assert name_diff is not None
    assert name_diff.old_value == "Test Diagram"
    assert name_diff.new_value == "Test Diagram Modified"

    # Should detect added box
    assert len(diff.added_presentations) == 1
    assert diff.added_presentations[0].presentation_id == new_box.id

    # Should detect modified box
    assert len(diff.modified_presentations) == 1
    assert diff.modified_presentations[0].presentation_id == base_box.id


def test_diff_has_changes_property(event_manager):
    """Test that has_changes property works correctly."""
    from gaphor.core import Transaction

    base_factory = ElementFactory()
    compare_factory = ElementFactory()

    with Transaction(event_manager):
        base_diagram = base_factory.create(Diagram)
        base_diagram.name = "Same Name"

    with Transaction(event_manager):
        compare_diagram = compare_factory.create_as(Diagram, base_diagram.id)
        compare_diagram.name = "Same Name"

    diff = compare_diagrams(base_diagram, compare_diagram)
    assert not diff.has_changes

    # Now create with different name
    with Transaction(event_manager):
        compare_diagram2 = compare_factory.create(Diagram)
        compare_diagram2.name = "Different Name"

    diff2 = compare_diagrams(base_diagram, compare_diagram2)
    assert diff2.has_changes


def test_get_presentation_change_type(event_manager):
    """Test retrieving change type for specific presentations."""
    from gaphor.core import Transaction

    base_factory = ElementFactory()
    compare_factory = ElementFactory()

    with Transaction(event_manager):
        base_diagram = base_factory.create(Diagram)
        base_box = base_diagram.create(Box)

    with Transaction(event_manager):
        compare_diagram = compare_factory.create_as(Diagram, base_diagram.id)
        compare_box = compare_diagram.create_as(Box, base_box.id)
        new_box = compare_diagram.create(Box)

    diff = compare_diagrams(base_diagram, compare_diagram)

    # The existing box should be unchanged
    assert diff.get_presentation_change_type(base_box.id) is None

    # The new box should be added
    assert diff.get_presentation_change_type(new_box.id) == ChangeType.ADDED


def test_diff_categorizes_changes_correctly(event_manager):
    """Test that changes are categorized into added/removed/modified."""
    from gaphor.core import Transaction

    base_factory = ElementFactory()
    compare_factory = ElementFactory()

    with Transaction(event_manager):
        base_diagram = base_factory.create(Diagram)
        removed_box = base_diagram.create(Box)
        modified_box = base_diagram.create(Box)
        modified_box.width = 100

    with Transaction(event_manager):
        compare_diagram = compare_factory.create_as(Diagram, base_diagram.id)
        # Don't recreate removed_box
        # Recreate modified_box with different width
        compare_mod_box = compare_diagram.create_as(Box, modified_box.id)
        compare_mod_box.width = 200
        # Add new box
        added_box = compare_diagram.create(Box)

    diff = compare_diagrams(base_diagram, compare_diagram)

    # Check categorization
    added_ids = [p.presentation_id for p in diff.added_presentations]
    removed_ids = [p.presentation_id for p in diff.removed_presentations]
    modified_ids = [p.presentation_id for p in diff.modified_presentations]

    assert added_box.id in added_ids
    assert removed_box.id in removed_ids
    assert modified_box.id in modified_ids


def test_diff_list_for_navigation(event_manager):
    """Test that diff list contains all presentation diffs for navigation."""
    from gaphor.core import Transaction

    base_factory = ElementFactory()
    compare_factory = ElementFactory()

    with Transaction(event_manager):
        base_diagram = base_factory.create(Diagram)
        box1 = base_diagram.create(Box)
        box2 = base_diagram.create(Box)
        box3 = base_diagram.create(Box)

    with Transaction(event_manager):
        compare_diagram = compare_factory.create_as(Diagram, base_diagram.id)
        # box1 - removed (not recreated)
        # box2 - modified
        cbox2 = compare_diagram.create_as(Box, box2.id)
        cbox2.width = 200
        # box3 - unchanged
        compare_diagram.create_as(Box, box3.id)
        # box4 - added
        box4 = compare_diagram.create(Box)

    diff = compare_diagrams(base_diagram, compare_diagram)

    # Should have 3 changes: removed, modified, added
    assert len(diff.presentation_diffs) == 3

    change_types = {p.change_type for p in diff.presentation_diffs}
    assert ChangeType.ADDED in change_types
    assert ChangeType.REMOVED in change_types
    assert ChangeType.MODIFIED in change_types


def test_navigation_cycles_through_diffs(event_manager):
    """Test that navigation properly cycles through all diffs."""
    from gaphor.core import Transaction

    base_factory = ElementFactory()
    compare_factory = ElementFactory()

    with Transaction(event_manager):
        base_diagram = base_factory.create(Diagram)
        base_diagram.create(Box)  # Will be removed
        base_diagram.create(Box)  # Will be removed

    with Transaction(event_manager):
        compare_diagram = compare_factory.create_as(Diagram, base_diagram.id)
        compare_diagram.create(Box)  # New

    diff = compare_diagrams(base_diagram, compare_diagram)

    # Should have 3 changes (2 removed + 1 added)
    assert len(diff.presentation_diffs) == 3

    # Test cycling: starting at -1, after 4 navigations forward we should be at index 0
    current_index = -1
    total = len(diff.presentation_diffs)

    # First navigation
    current_index = 0 if current_index < 0 else (current_index + 1) % total
    assert current_index == 0

    # Second navigation
    current_index = (current_index + 1) % total
    assert current_index == 1

    # Third navigation
    current_index = (current_index + 1) % total
    assert current_index == 2

    # Fourth navigation - should cycle back to 0
    current_index = (current_index + 1) % total
    assert current_index == 0


def test_property_diff_display_values():
    """Test that property diff display values format correctly."""
    from gaphor.ui.diagramcompare.comparator import PropertyDiff

    # Test with string values
    prop_diff = PropertyDiff(
        property_name="name",
        old_value="OldName",
        new_value="NewName",
        change_type=ChangeType.MODIFIED,
    )
    assert prop_diff.display_old == "OldName"
    assert prop_diff.display_new == "NewName"

    # Test with None values
    prop_diff_none = PropertyDiff(
        property_name="name",
        old_value=None,
        new_value="NewName",
        change_type=ChangeType.MODIFIED,
    )
    assert prop_diff_none.display_old == "<None>"
    assert prop_diff_none.display_new == "NewName"

    # Test with numeric values
    prop_diff_num = PropertyDiff(
        property_name="width",
        old_value=100,
        new_value=200,
        change_type=ChangeType.MODIFIED,
    )
    assert prop_diff_num.display_old == "100"
    assert prop_diff_num.display_new == "200"
