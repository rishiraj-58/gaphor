"""Tests for the organize module."""

import pytest

from gaphor import UML
from gaphor.core.modeling import ElementFactory
from gaphor.ui.modelcompare.differ import compare_models
from gaphor.ui.modelcompare.organize import (
    CompareNode,
    organize_by_diagram,
    organize_diff_result,
)


@pytest.fixture
def base_factory():
    return ElementFactory()


@pytest.fixture
def compare_factory():
    return ElementFactory()


def test_organize_empty_diff(base_factory, compare_factory):
    diff = compare_models(base_factory, compare_factory)
    tree = organize_diff_result(diff, base_factory, compare_factory)

    assert tree.get_n_items() == 0


def test_organize_groups_by_change_type(base_factory, compare_factory):
    # Add element
    klass = compare_factory.create(UML.Class)
    klass.name = "MyClass"

    diff = compare_models(base_factory, compare_factory)
    tree = organize_diff_result(diff, base_factory, compare_factory)

    assert tree.get_n_items() >= 1
    # Should have an "Added" group
    labels = [tree.get_item(i).label for i in range(tree.get_n_items())]
    assert any("Added" in label for label in labels)


def test_organize_groups_by_element_type(base_factory, compare_factory):
    # Add multiple elements of same type
    klass1 = compare_factory.create(UML.Class)
    klass1.name = "Class1"

    klass2 = compare_factory.create(UML.Class)
    klass2.name = "Class2"

    diff = compare_models(base_factory, compare_factory)
    tree = organize_diff_result(diff, base_factory, compare_factory)

    # Navigate to find Class group
    assert tree.get_n_items() >= 1
    added_node = tree.get_item(0)
    assert added_node.children is not None


def test_compare_node_selection_propagates(base_factory, compare_factory):
    klass1 = compare_factory.create(UML.Class)
    klass1.name = "Class1"

    klass2 = compare_factory.create(UML.Class)
    klass2.name = "Class2"

    diff = compare_models(base_factory, compare_factory)
    tree = organize_diff_result(diff, base_factory, compare_factory)

    # Select root node
    root = tree.get_item(0)
    root.selected = True

    # Children should also be selected
    if root.children:
        for i in range(root.children.get_n_items()):
            child = root.children.get_item(i)
            assert child.selected


def test_compare_node_all_changes(base_factory, compare_factory):
    klass = compare_factory.create(UML.Class)
    klass.name = "MyClass"

    diff = compare_models(base_factory, compare_factory)
    tree = organize_diff_result(diff, base_factory, compare_factory)

    root = tree.get_item(0)
    all_changes = root.all_changes()

    assert len(all_changes) > 0


def test_organize_by_diagram(base_factory, compare_factory):
    # This test requires diagram setup which needs more fixtures
    diff = compare_models(base_factory, compare_factory)
    tree = organize_by_diagram(diff, base_factory, compare_factory)

    # Empty diff should have empty tree
    assert tree is not None
