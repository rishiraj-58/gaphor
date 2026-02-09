"""Merge changes from one model into another."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from gaphor.core.modeling import Base, Diagram, Presentation
from gaphor.ui.modelcompare.differ import Change, ChangeCategory, ChangeType

if TYPE_CHECKING:
    from gaphor.core.modeling import ElementFactory
    from gaphor.core.modeling.modelinglanguage import ModelingLanguage


@dataclass
class MergeConflict:
    """Represents a conflict when merging changes."""

    change: Change
    reason: str


@dataclass
class MergeResult:
    """Result of a merge operation."""

    applied: list[Change]
    skipped: list[Change]
    conflicts: list[MergeConflict]


def can_apply_change(
    change: Change,
    target_factory: ElementFactory,
    source_factory: ElementFactory,
) -> tuple[bool, str]:
    """Check if a change can be applied.

    Returns:
        Tuple of (can_apply, reason)
    """
    if change.change_type == ChangeType.ADDED:
        if change.category in (ChangeCategory.ELEMENT, ChangeCategory.PRESENTATION):
            # Check if element already exists
            if target_factory.lookup(change.element_id):
                return False, "Element already exists in target"
            # For presentations, check if diagram exists
            if change.category == ChangeCategory.PRESENTATION and change.diagram_id:
                if not target_factory.lookup(change.diagram_id):
                    return False, "Diagram does not exist in target"
        return True, ""

    elif change.change_type == ChangeType.REMOVED:
        if change.category in (ChangeCategory.ELEMENT, ChangeCategory.PRESENTATION):
            # Check if element exists
            if not target_factory.lookup(change.element_id):
                return False, "Element does not exist in target"
        return True, ""

    else:  # MODIFIED
        # Check if element exists
        if not target_factory.lookup(change.element_id):
            return False, "Element does not exist in target"
        return True, ""


def apply_change(
    change: Change,
    target_factory: ElementFactory,
    source_factory: ElementFactory,
    modeling_language: ModelingLanguage,
) -> bool:
    """Apply a single change to the target factory.

    Returns:
        True if the change was applied successfully
    """
    if change.change_type == ChangeType.ADDED:
        return _apply_add(change, target_factory, source_factory, modeling_language)
    elif change.change_type == ChangeType.REMOVED:
        return _apply_remove(change, target_factory)
    else:
        return _apply_modify(change, target_factory, source_factory)


def _apply_add(
    change: Change,
    target_factory: ElementFactory,
    source_factory: ElementFactory,
    modeling_language: ModelingLanguage,
) -> bool:
    """Apply an add change."""
    if change.category in (ChangeCategory.ELEMENT, ChangeCategory.PRESENTATION):
        source_element = source_factory.lookup(change.element_id)
        if not source_element:
            return False

        # Create the element in target
        element_type = type(source_element)

        if isinstance(source_element, Presentation):
            if not change.diagram_id:
                return False
            diagram = target_factory.lookup(change.diagram_id)
            if not isinstance(diagram, Diagram):
                return False
            target_element = target_factory.create_as(
                element_type, change.element_id, diagram=diagram
            )
        else:
            target_element = target_factory.create_as(element_type, change.element_id)

        # Copy properties
        _copy_element_properties(source_element, target_element, target_factory)
        return True

    elif change.category == ChangeCategory.PROPERTY:
        target_element = target_factory.lookup(change.element_id)
        if target_element and change.property_name:
            target_element.load(change.property_name, change.new_value)
            target_element.postload()
            return True

    elif change.category == ChangeCategory.RELATIONSHIP:
        target_element = target_factory.lookup(change.element_id)
        ref_element = target_factory.lookup(change.new_value) if change.new_value else None
        if target_element and ref_element and change.property_name:
            target_element.load(change.property_name, ref_element)
            target_element.postload()
            return True

    return False


def _apply_remove(change: Change, target_factory: ElementFactory) -> bool:
    """Apply a remove change."""
    if change.category in (ChangeCategory.ELEMENT, ChangeCategory.PRESENTATION):
        element = target_factory.lookup(change.element_id)
        if element:
            element.unlink()
            return True

    elif change.category == ChangeCategory.PROPERTY:
        element = target_factory.lookup(change.element_id)
        if element and change.property_name:
            try:
                delattr(element, change.property_name)
                return True
            except AttributeError:
                pass

    elif change.category == ChangeCategory.RELATIONSHIP:
        element = target_factory.lookup(change.element_id)
        ref_element = (
            target_factory.lookup(change.old_value) if change.old_value else None
        )
        if element and change.property_name:
            prop = getattr(type(element), change.property_name, None)
            if prop:
                if hasattr(prop, "upper") and prop.upper == 1:
                    delattr(element, change.property_name)
                elif ref_element:
                    getattr(element, change.property_name).remove(ref_element)
                return True

    return False


def _apply_modify(
    change: Change,
    target_factory: ElementFactory,
    source_factory: ElementFactory,
) -> bool:
    """Apply a modification change."""
    target_element = target_factory.lookup(change.element_id)
    if not target_element or not change.property_name:
        return False

    if change.category == ChangeCategory.PROPERTY:
        target_element.load(change.property_name, change.new_value)
        target_element.postload()
        return True

    elif change.category == ChangeCategory.RELATIONSHIP:
        ref_element = (
            target_factory.lookup(change.new_value) if change.new_value else None
        )
        if ref_element:
            target_element.load(change.property_name, ref_element)
            target_element.postload()
            return True

    return False


def _copy_element_properties(
    source: Base,
    target: Base,
    target_factory: ElementFactory,
):
    """Copy properties from source element to target."""

    def save_and_load(name: str, value):
        if name == "id":
            return
        if isinstance(value, Base):
            # Reference - try to resolve in target
            ref = target_factory.lookup(value.id)
            if ref:
                target.load(name, ref)
        elif hasattr(value, "__iter__") and not isinstance(value, str):
            # Collection
            for item in value:
                if isinstance(item, Base):
                    ref = target_factory.lookup(item.id)
                    if ref:
                        target.load(name, ref)
        else:
            # Simple value
            target.load(name, value)

    source.save(save_and_load)
    target.postload()


def merge_changes(
    changes: Iterable[Change],
    target_factory: ElementFactory,
    source_factory: ElementFactory,
    modeling_language: ModelingLanguage,
) -> MergeResult:
    """Merge a set of changes into the target factory.

    Changes are applied in order: adds first, then modifications, then removals.
    This ordering helps avoid dependency issues.

    Args:
        changes: The changes to apply
        target_factory: The factory to apply changes to
        source_factory: The factory containing the source elements
        modeling_language: The modeling language for element creation

    Returns:
        MergeResult with applied, skipped, and conflicting changes
    """
    result = MergeResult(applied=[], skipped=[], conflicts=[])

    # Sort changes: adds first, then modifications, then removals
    sorted_changes = sorted(
        changes,
        key=lambda c: (
            0 if c.change_type == ChangeType.ADDED else
            1 if c.change_type == ChangeType.MODIFIED else 2,
            # Within adds, elements before properties/relationships
            0 if c.category in (ChangeCategory.ELEMENT, ChangeCategory.PRESENTATION) else 1,
        ),
    )

    for change in sorted_changes:
        can_apply, reason = can_apply_change(change, target_factory, source_factory)
        if not can_apply:
            result.conflicts.append(MergeConflict(change=change, reason=reason))
            continue

        if apply_change(change, target_factory, source_factory, modeling_language):
            result.applied.append(change)
        else:
            result.skipped.append(change)

    return result


def create_undo_changes(changes: Iterable[Change]) -> list[Change]:
    """Create inverse changes for undo support.

    Returns a list of changes that, when applied, will undo the given changes.
    """
    undo_changes: list[Change] = []

    for change in changes:
        if change.change_type == ChangeType.ADDED:
            # Undo add = remove
            undo_changes.append(
                Change(
                    change_type=ChangeType.REMOVED,
                    category=change.category,
                    element_id=change.element_id,
                    element_type=change.element_type,
                    element_name=change.element_name,
                    property_name=change.property_name,
                    old_value=change.new_value,
                    diagram_id=change.diagram_id,
                )
            )
        elif change.change_type == ChangeType.REMOVED:
            # Undo remove = add
            undo_changes.append(
                Change(
                    change_type=ChangeType.ADDED,
                    category=change.category,
                    element_id=change.element_id,
                    element_type=change.element_type,
                    element_name=change.element_name,
                    property_name=change.property_name,
                    new_value=change.old_value,
                    diagram_id=change.diagram_id,
                )
            )
        else:
            # Undo modify = modify with swapped values
            undo_changes.append(
                Change(
                    change_type=ChangeType.MODIFIED,
                    category=change.category,
                    element_id=change.element_id,
                    element_type=change.element_type,
                    element_name=change.element_name,
                    property_name=change.property_name,
                    old_value=change.new_value,
                    new_value=change.old_value,
                    diagram_id=change.diagram_id,
                )
            )

    # Reverse the order for undo (removals become adds, which should come first)
    return list(reversed(undo_changes))
