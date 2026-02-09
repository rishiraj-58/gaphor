"""Tests for the model differ module."""

import pytest

from gaphor import UML
from gaphor.core.modeling import Diagram, ElementFactory
from gaphor.ui.modelcompare.differ import (
    Change,
    ChangeCategory,
    ChangeType,
    DiffResult,
    compare_models,
)


@pytest.fixture
def base_factory():
    return ElementFactory()


@pytest.fixture
def compare_factory():
    return ElementFactory()


def test_empty_models_have_no_changes(base_factory, compare_factory):
    result = compare_models(base_factory, compare_factory)

    assert result.changes == []
    assert len(result.added) == 0
    assert len(result.removed) == 0
    assert len(result.modified) == 0


def test_detect_added_element(base_factory, compare_factory):
    # Add an element to compare_factory only
    klass = compare_factory.create(UML.Class)
    klass.name = "MyClass"

    result = compare_models(base_factory, compare_factory)

    assert len(result.added) == 1
    assert result.added[0].element_id == klass.id
    assert result.added[0].element_type == "Class"
    assert result.added[0].change_type == ChangeType.ADDED


def test_detect_removed_element(base_factory, compare_factory):
    # Add an element to base_factory only
    klass = base_factory.create(UML.Class)
    klass.name = "MyClass"

    result = compare_models(base_factory, compare_factory)

    assert len(result.removed) == 1
    assert result.removed[0].element_id == klass.id
    assert result.removed[0].element_type == "Class"
    assert result.removed[0].change_type == ChangeType.REMOVED


def test_detect_modified_property(base_factory, compare_factory):
    # Create same element in both factories with different property
    klass1 = base_factory.create(UML.Class)
    klass2 = compare_factory.create_as(UML.Class, klass1.id)

    klass1.name = "OldName"
    klass2.name = "NewName"

    result = compare_models(base_factory, compare_factory)

    assert len(result.modified) == 1
    change = result.modified[0]
    assert change.element_id == klass1.id
    assert change.property_name == "name"
    assert change.old_value == "OldName"
    assert change.new_value == "NewName"


def test_detect_added_relationship(base_factory, compare_factory):
    # Create elements in both factories
    klass1 = base_factory.create(UML.Class)
    klass1.name = "MyClass"

    klass2 = compare_factory.create_as(UML.Class, klass1.id)
    klass2.name = "MyClass"

    # Add attribute only in compare
    attr = compare_factory.create(UML.Property)
    attr.name = "myAttr"
    klass2.ownedAttribute = attr

    result = compare_models(base_factory, compare_factory)

    # Should detect the new attribute element and the relationship
    added_elements = [c for c in result.added if c.category == ChangeCategory.ELEMENT]
    added_rels = [c for c in result.added if c.category == ChangeCategory.RELATIONSHIP]

    assert len(added_elements) == 1
    assert added_elements[0].element_type == "Property"


def test_changes_for_element(base_factory, compare_factory):
    klass1 = base_factory.create(UML.Class)
    klass2 = compare_factory.create_as(UML.Class, klass1.id)

    klass1.name = "OldName"
    klass1.isAbstract = False

    klass2.name = "NewName"
    klass2.isAbstract = True

    result = compare_models(base_factory, compare_factory)

    element_changes = result.changes_for_element(klass1.id)
    assert len(element_changes) >= 2  # name and isAbstract changes


def test_diff_result_changes_by_type(base_factory, compare_factory):
    klass = compare_factory.create(UML.Class)
    klass.name = "MyClass"

    pkg = compare_factory.create(UML.Package)
    pkg.name = "MyPackage"

    result = compare_models(base_factory, compare_factory)

    by_type = result.changes_by_type()
    assert "Class" in by_type
    assert "Package" in by_type


def test_change_description_added():
    change = Change(
        change_type=ChangeType.ADDED,
        category=ChangeCategory.ELEMENT,
        element_id="123",
        element_type="Class",
        element_name="MyClass",
    )

    assert "Added" in change.description
    assert "Class" in change.description
    assert "MyClass" in change.description


def test_change_description_removed():
    change = Change(
        change_type=ChangeType.REMOVED,
        category=ChangeCategory.ELEMENT,
        element_id="123",
        element_type="Class",
        element_name="MyClass",
    )

    assert "Removed" in change.description


def test_change_description_modified():
    change = Change(
        change_type=ChangeType.MODIFIED,
        category=ChangeCategory.PROPERTY,
        element_id="123",
        element_type="Class",
        element_name="MyClass",
        property_name="name",
        old_value="OldName",
        new_value="NewName",
    )

    assert "Changed" in change.description
    assert "name" in change.description
