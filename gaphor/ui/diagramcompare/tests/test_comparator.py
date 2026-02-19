"""Tests for the diagram comparison algorithm."""

import pytest

from gaphor import UML
from gaphor.core.modeling import Diagram, ElementFactory
from gaphor.diagram.general.simpleitem import Box
from gaphor.ui.diagramcompare.comparator import (
    ChangeType,
    DiagramDiff,
    compare_diagrams,
    compare_elements,
)
from gaphor.UML.classes import ClassItem


def test_compare_none_diagrams():
    """Comparing two None diagrams should return empty diff."""
    diff = compare_diagrams(None, None)

    assert not diff.has_changes
    assert not diff.presentation_diffs
    assert not diff.diagram_property_diffs


def test_compare_new_diagram(element_factory, event_manager):
    """Comparing None with a diagram should detect all items as added."""
    from gaphor.core import Transaction

    with Transaction(event_manager):
        diagram = element_factory.create(Diagram)
        diagram.name = "Test Diagram"
        box = diagram.create(Box)

    diff = compare_diagrams(None, diagram)

    assert diff.has_changes
    assert len(diff.added_presentations) == 1
    assert diff.added_presentations[0].change_type == ChangeType.ADDED


def test_compare_removed_diagram(element_factory, event_manager):
    """Comparing a diagram with None should detect all items as removed."""
    from gaphor.core import Transaction

    with Transaction(event_manager):
        diagram = element_factory.create(Diagram)
        box = diagram.create(Box)

    diff = compare_diagrams(diagram, None)

    assert diff.has_changes
    assert len(diff.removed_presentations) == 1
    assert diff.removed_presentations[0].change_type == ChangeType.REMOVED


def test_compare_identical_diagrams(element_factory, event_manager):
    """Comparing identical diagrams should detect no changes."""
    from gaphor.core import Transaction

    with Transaction(event_manager):
        diagram = element_factory.create(Diagram)
        diagram.name = "Test"
        box = diagram.create(Box)

    # Compare diagram with itself
    diff = compare_diagrams(diagram, diagram)

    assert not diff.has_changes


def test_compare_added_presentation(event_manager):
    """Detect when a presentation is added."""
    from gaphor.core import Transaction

    base_factory = ElementFactory()
    compare_factory = ElementFactory()

    with Transaction(event_manager):
        base_diagram = base_factory.create(Diagram)
        base_diagram.name = "Test"
        base_box = base_diagram.create(Box)

    with Transaction(event_manager):
        compare_diagram = compare_factory.create_as(Diagram, base_diagram.id)
        compare_diagram.name = "Test"
        # Create same box
        compare_box = compare_diagram.create_as(Box, base_box.id)
        # Add new box
        new_box = compare_diagram.create(Box)

    diff = compare_diagrams(base_diagram, compare_diagram)

    assert diff.has_changes
    assert len(diff.added_presentations) == 1
    assert diff.added_presentations[0].presentation_id == new_box.id


def test_compare_removed_presentation(event_manager):
    """Detect when a presentation is removed."""
    from gaphor.core import Transaction

    base_factory = ElementFactory()
    compare_factory = ElementFactory()

    with Transaction(event_manager):
        base_diagram = base_factory.create(Diagram)
        base_box1 = base_diagram.create(Box)
        base_box2 = base_diagram.create(Box)

    with Transaction(event_manager):
        compare_diagram = compare_factory.create_as(Diagram, base_diagram.id)
        # Only create one box
        compare_box1 = compare_diagram.create_as(Box, base_box1.id)

    diff = compare_diagrams(base_diagram, compare_diagram)

    assert diff.has_changes
    assert len(diff.removed_presentations) == 1
    assert diff.removed_presentations[0].presentation_id == base_box2.id


def test_compare_modified_presentation(event_manager):
    """Detect when a presentation is modified."""
    from gaphor.core import Transaction

    base_factory = ElementFactory()
    compare_factory = ElementFactory()

    with Transaction(event_manager):
        base_diagram = base_factory.create(Diagram)
        base_box = base_diagram.create(Box)
        base_box.width = 100

    with Transaction(event_manager):
        compare_diagram = compare_factory.create_as(Diagram, base_diagram.id)
        compare_box = compare_diagram.create_as(Box, base_box.id)
        compare_box.width = 200  # Different width

    diff = compare_diagrams(base_diagram, compare_diagram)

    assert diff.has_changes
    assert len(diff.modified_presentations) == 1
    assert diff.modified_presentations[0].presentation_id == base_box.id

    # Check property diff
    prop_diffs = diff.modified_presentations[0].property_diffs
    width_diff = next((p for p in prop_diffs if p.property_name == "width"), None)
    assert width_diff is not None
    assert width_diff.old_value == 100
    assert width_diff.new_value == 200


def test_compare_diagram_name_change(event_manager):
    """Detect when diagram name changes."""
    from gaphor.core import Transaction

    base_factory = ElementFactory()
    compare_factory = ElementFactory()

    with Transaction(event_manager):
        base_diagram = base_factory.create(Diagram)
        base_diagram.name = "Old Name"

    with Transaction(event_manager):
        compare_diagram = compare_factory.create_as(Diagram, base_diagram.id)
        compare_diagram.name = "New Name"

    diff = compare_diagrams(base_diagram, compare_diagram)

    assert diff.has_changes
    assert len(diff.diagram_property_diffs) == 1
    assert diff.diagram_property_diffs[0].property_name == "name"
    assert diff.diagram_property_diffs[0].old_value == "Old Name"
    assert diff.diagram_property_diffs[0].new_value == "New Name"


def test_compare_elements_added(element_factory, event_manager):
    """Test comparing elements where one is added."""
    from gaphor.core import Transaction

    with Transaction(event_manager):
        klass = element_factory.create(UML.Class)
        klass.name = "MyClass"

    diff = compare_elements(None, klass)

    assert diff.change_type == ChangeType.ADDED
    assert diff.element_type == "Class"
    assert diff.element_name == "MyClass"


def test_compare_elements_removed(element_factory, event_manager):
    """Test comparing elements where one is removed."""
    from gaphor.core import Transaction

    with Transaction(event_manager):
        klass = element_factory.create(UML.Class)
        klass.name = "MyClass"

    diff = compare_elements(klass, None)

    assert diff.change_type == ChangeType.REMOVED
    assert diff.element_type == "Class"


def test_compare_elements_modified(event_manager):
    """Test comparing modified elements."""
    from gaphor.core import Transaction

    base_factory = ElementFactory()
    compare_factory = ElementFactory()

    with Transaction(event_manager):
        base_class = base_factory.create(UML.Class)
        base_class.name = "OldName"
        base_class.isAbstract = False

    with Transaction(event_manager):
        compare_class = compare_factory.create_as(UML.Class, base_class.id)
        compare_class.name = "NewName"
        compare_class.isAbstract = True

    diff = compare_elements(base_class, compare_class)

    assert diff.change_type == ChangeType.MODIFIED
    assert len(diff.property_diffs) >= 2

    name_diff = next((p for p in diff.property_diffs if p.property_name == "name"), None)
    assert name_diff is not None
    assert name_diff.old_value == "OldName"
    assert name_diff.new_value == "NewName"


def test_compare_with_subject_changes(event_manager, modeling_language):
    """Test that subject changes are detected in presentations."""
    from gaphor.core import Transaction
    from gaphor.core.modeling.elementdispatcher import ElementDispatcher

    base_factory = ElementFactory(
        None, ElementDispatcher(event_manager, modeling_language)
    )
    compare_factory = ElementFactory(
        None, ElementDispatcher(event_manager, modeling_language)
    )

    with Transaction(event_manager):
        base_diagram = base_factory.create(Diagram)
        base_class = base_factory.create(UML.Class)
        base_class.name = "OldClassName"
        base_item = base_diagram.create(ClassItem, subject=base_class)

    with Transaction(event_manager):
        compare_diagram = compare_factory.create_as(Diagram, base_diagram.id)
        compare_class = compare_factory.create_as(UML.Class, base_class.id)
        compare_class.name = "NewClassName"
        compare_item = compare_diagram.create_as(
            ClassItem, base_item.id, subject=compare_class
        )

    diff = compare_diagrams(base_diagram, compare_diagram)

    # Find the modified presentation
    modified = diff.modified_presentations
    assert len(modified) == 1

    # Check subject diff
    subject_diff = modified[0].subject_diff
    assert subject_diff is not None
    assert subject_diff.change_type == ChangeType.MODIFIED

    name_diff = next(
        (p for p in subject_diff.property_diffs if p.property_name == "name"), None
    )
    assert name_diff is not None
    assert name_diff.old_value == "OldClassName"
    assert name_diff.new_value == "NewClassName"


def test_get_presentation_change_type(event_manager):
    """Test getting change type for a specific presentation."""
    from gaphor.core import Transaction

    base_factory = ElementFactory()
    compare_factory = ElementFactory()

    with Transaction(event_manager):
        base_diagram = base_factory.create(Diagram)
        base_box = base_diagram.create(Box)

    with Transaction(event_manager):
        compare_diagram = compare_factory.create_as(Diagram, base_diagram.id)
        new_box = compare_diagram.create(Box)

    diff = compare_diagrams(base_diagram, compare_diagram)

    assert diff.get_presentation_change_type(base_box.id) == ChangeType.REMOVED
    assert diff.get_presentation_change_type(new_box.id) == ChangeType.ADDED
    assert diff.get_presentation_change_type("nonexistent") is None
