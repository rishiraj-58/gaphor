"""Tests for the model merge module."""

import pytest

from gaphor import UML
from gaphor.core.modeling import Diagram, ElementFactory
from gaphor.services.modelinglanguage import ModelingLanguageService
from gaphor.ui.modelcompare.differ import (
    Change,
    ChangeCategory,
    ChangeType,
    compare_models,
)
from gaphor.ui.modelcompare.merge import (
    MergeConflict,
    MergeResult,
    apply_change,
    can_apply_change,
    create_undo_changes,
    merge_changes,
)


@pytest.fixture
def modeling_language():
    return ModelingLanguageService()


@pytest.fixture
def base_factory():
    return ElementFactory()


@pytest.fixture
def compare_factory():
    return ElementFactory()


def test_can_apply_add_change(base_factory, compare_factory):
    klass = compare_factory.create(UML.Class)
    klass.name = "MyClass"

    change = Change(
        change_type=ChangeType.ADDED,
        category=ChangeCategory.ELEMENT,
        element_id=klass.id,
        element_type="Class",
        element_name="MyClass",
    )

    can_apply, reason = can_apply_change(change, base_factory, compare_factory)
    assert can_apply


def test_cannot_apply_add_if_exists(base_factory, compare_factory):
    klass1 = base_factory.create(UML.Class)
    klass2 = compare_factory.create_as(UML.Class, klass1.id)

    change = Change(
        change_type=ChangeType.ADDED,
        category=ChangeCategory.ELEMENT,
        element_id=klass1.id,
        element_type="Class",
    )

    can_apply, reason = can_apply_change(change, base_factory, compare_factory)
    assert not can_apply
    assert "already exists" in reason


def test_can_apply_remove_change(base_factory, compare_factory):
    klass = base_factory.create(UML.Class)
    klass.name = "MyClass"

    change = Change(
        change_type=ChangeType.REMOVED,
        category=ChangeCategory.ELEMENT,
        element_id=klass.id,
        element_type="Class",
        element_name="MyClass",
    )

    can_apply, reason = can_apply_change(change, base_factory, compare_factory)
    assert can_apply


def test_cannot_remove_nonexistent(base_factory, compare_factory):
    change = Change(
        change_type=ChangeType.REMOVED,
        category=ChangeCategory.ELEMENT,
        element_id="nonexistent",
        element_type="Class",
    )

    can_apply, reason = can_apply_change(change, base_factory, compare_factory)
    assert not can_apply


def test_apply_add_element(base_factory, compare_factory, modeling_language):
    klass = compare_factory.create(UML.Class)
    klass.name = "MyClass"

    change = Change(
        change_type=ChangeType.ADDED,
        category=ChangeCategory.ELEMENT,
        element_id=klass.id,
        element_type="Class",
        element_name="MyClass",
    )

    result = apply_change(change, base_factory, compare_factory, modeling_language)

    assert result
    assert base_factory.lookup(klass.id) is not None


def test_apply_remove_element(base_factory, compare_factory, modeling_language):
    klass = base_factory.create(UML.Class)
    klass.name = "MyClass"

    change = Change(
        change_type=ChangeType.REMOVED,
        category=ChangeCategory.ELEMENT,
        element_id=klass.id,
        element_type="Class",
        element_name="MyClass",
    )

    result = apply_change(change, base_factory, compare_factory, modeling_language)

    assert result
    assert base_factory.lookup(klass.id) is None


def test_apply_modify_property(base_factory, compare_factory, modeling_language):
    klass1 = base_factory.create(UML.Class)
    klass1.name = "OldName"

    klass2 = compare_factory.create_as(UML.Class, klass1.id)
    klass2.name = "NewName"

    change = Change(
        change_type=ChangeType.MODIFIED,
        category=ChangeCategory.PROPERTY,
        element_id=klass1.id,
        element_type="Class",
        property_name="name",
        old_value="OldName",
        new_value="NewName",
    )

    result = apply_change(change, base_factory, compare_factory, modeling_language)

    assert result
    assert klass1.name == "NewName"


def test_merge_changes(base_factory, compare_factory, modeling_language):
    # Create elements in compare factory
    klass = compare_factory.create(UML.Class)
    klass.name = "MyClass"

    pkg = compare_factory.create(UML.Package)
    pkg.name = "MyPackage"

    diff = compare_models(base_factory, compare_factory)

    result = merge_changes(
        diff.changes, base_factory, compare_factory, modeling_language
    )

    assert len(result.applied) > 0
    assert base_factory.lookup(klass.id) is not None
    assert base_factory.lookup(pkg.id) is not None


def test_create_undo_changes():
    changes = [
        Change(
            change_type=ChangeType.ADDED,
            category=ChangeCategory.ELEMENT,
            element_id="123",
            element_type="Class",
        ),
        Change(
            change_type=ChangeType.MODIFIED,
            category=ChangeCategory.PROPERTY,
            element_id="456",
            element_type="Class",
            property_name="name",
            old_value="Old",
            new_value="New",
        ),
    ]

    undo = create_undo_changes(changes)

    # Undo of add is remove
    assert any(
        c.change_type == ChangeType.REMOVED and c.element_id == "123" for c in undo
    )

    # Undo of modify has swapped values
    modify_undo = next(c for c in undo if c.element_id == "456")
    assert modify_undo.old_value == "New"
    assert modify_undo.new_value == "Old"
