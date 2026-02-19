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
