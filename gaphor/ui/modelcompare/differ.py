"""Model difference detection algorithm.

Compares two Gaphor models and detects changes in elements, properties,
and relationships.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from gaphor.core.modeling import Base, Diagram, Presentation
from gaphor.core.modeling.collection import collection

if TYPE_CHECKING:
    from gaphor.core.modeling import ElementFactory


class ChangeType(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"


class ChangeCategory(StrEnum):
    ELEMENT = "element"
    PROPERTY = "property"
    RELATIONSHIP = "relationship"
    PRESENTATION = "presentation"


@dataclass
class Change:
    """Represents a single change between two model versions."""

    change_type: ChangeType
    category: ChangeCategory
    element_id: str
    element_type: str
    element_name: str | None = None
    property_name: str | None = None
    old_value: Any = None
    new_value: Any = None
    parent_id: str | None = None
    diagram_id: str | None = None

    @property
    def description(self) -> str:
        name = self.element_name or self.element_type
        if self.change_type == ChangeType.ADDED:
            if self.category == ChangeCategory.ELEMENT:
                return f"Added {self.element_type} '{name}'"
            elif self.category == ChangeCategory.PRESENTATION:
                return f"Added {self.element_type} presentation"
            elif self.category == ChangeCategory.PROPERTY:
                return f"Set {self.property_name} to '{self.new_value}'"
            else:
                return f"Added {self.property_name} relationship"
        elif self.change_type == ChangeType.REMOVED:
            if self.category == ChangeCategory.ELEMENT:
                return f"Removed {self.element_type} '{name}'"
            elif self.category == ChangeCategory.PRESENTATION:
                return f"Removed {self.element_type} presentation"
            elif self.category == ChangeCategory.PROPERTY:
                return f"Cleared {self.property_name}"
            else:
                return f"Removed {self.property_name} relationship"
        else:
            return f"Changed {self.property_name}: '{self.old_value}' → '{self.new_value}'"


@dataclass
class DiffResult:
    """Contains all differences between two models."""

    changes: list[Change] = field(default_factory=list)
    base_factory: ElementFactory | None = None
    compare_factory: ElementFactory | None = None

    @property
    def added(self) -> list[Change]:
        return [c for c in self.changes if c.change_type == ChangeType.ADDED]

    @property
    def removed(self) -> list[Change]:
        return [c for c in self.changes if c.change_type == ChangeType.REMOVED]

    @property
    def modified(self) -> list[Change]:
        return [c for c in self.changes if c.change_type == ChangeType.MODIFIED]

    @property
    def elements(self) -> list[Change]:
        return [c for c in self.changes if c.category == ChangeCategory.ELEMENT]

    @property
    def properties(self) -> list[Change]:
        return [c for c in self.changes if c.category == ChangeCategory.PROPERTY]

    @property
    def relationships(self) -> list[Change]:
        return [c for c in self.changes if c.category == ChangeCategory.RELATIONSHIP]

    @property
    def presentations(self) -> list[Change]:
        return [c for c in self.changes if c.category == ChangeCategory.PRESENTATION]

    def changes_for_element(self, element_id: str) -> list[Change]:
        return [c for c in self.changes if c.element_id == element_id]

    def changes_for_diagram(self, diagram_id: str) -> list[Change]:
        return [c for c in self.changes if c.diagram_id == diagram_id]

    def changes_by_type(self) -> dict[str, list[Change]]:
        result: dict[str, list[Change]] = {}
        for change in self.changes:
            if change.element_type not in result:
                result[change.element_type] = []
            result[change.element_type].append(change)
        return result


def compare_models(
    base_factory: ElementFactory,
    compare_factory: ElementFactory,
) -> DiffResult:
    """Compare two model element factories and return the differences.

    Args:
        base_factory: The base/original model factory
        compare_factory: The model factory to compare against

    Returns:
        DiffResult containing all detected changes
    """
    result = DiffResult(
        base_factory=base_factory,
        compare_factory=compare_factory,
    )

    base_ids = set(base_factory.keys())
    compare_ids = set(compare_factory.keys())

    # Find added elements
    for element_id in compare_ids - base_ids:
        element = compare_factory.lookup(element_id)
        if element:
            result.changes.extend(_element_added(element))

    # Find removed elements
    for element_id in base_ids - compare_ids:
        element = base_factory.lookup(element_id)
        if element:
            result.changes.extend(_element_removed(element))

    # Find modified elements
    for element_id in base_ids & compare_ids:
        base_element = base_factory.lookup(element_id)
        compare_element = compare_factory.lookup(element_id)
        if base_element and compare_element:
            result.changes.extend(_element_modified(base_element, compare_element))

    return result


def _get_element_name(element: Base) -> str | None:
    return getattr(element, "name", None)


def _get_diagram_id(element: Base) -> str | None:
    if isinstance(element, Presentation) and element.diagram:
        return element.diagram.id
    return None


def _element_added(element: Base) -> Iterator[Change]:
    category = (
        ChangeCategory.PRESENTATION
        if isinstance(element, Presentation)
        else ChangeCategory.ELEMENT
    )
    yield Change(
        change_type=ChangeType.ADDED,
        category=category,
        element_id=element.id,
        element_type=type(element).__name__,
        element_name=_get_element_name(element),
        diagram_id=_get_diagram_id(element),
    )


def _element_removed(element: Base) -> Iterator[Change]:
    category = (
        ChangeCategory.PRESENTATION
        if isinstance(element, Presentation)
        else ChangeCategory.ELEMENT
    )
    yield Change(
        change_type=ChangeType.REMOVED,
        category=category,
        element_id=element.id,
        element_type=type(element).__name__,
        element_name=_get_element_name(element),
        diagram_id=_get_diagram_id(element),
    )


def _element_modified(base: Base, compare: Base) -> Iterator[Change]:
    """Compare two elements of the same type and yield property changes."""
    base_props = _get_properties(base)
    compare_props = _get_properties(compare)

    all_props = set(base_props.keys()) | set(compare_props.keys())

    for prop_name in all_props:
        if prop_name == "id":
            continue

        base_value = base_props.get(prop_name)
        compare_value = compare_props.get(prop_name)

        if base_value != compare_value:
            yield from _property_changed(
                base, prop_name, base_value, compare_value
            )


def _get_properties(element: Base) -> dict[str, Any]:
    """Extract all property values from an element."""
    props: dict[str, Any] = {}

    def save_prop(name: str, value: Any):
        if isinstance(value, Base):
            props[name] = value.id
        elif isinstance(value, collection):
            props[name] = frozenset(v.id for v in value)
        else:
            props[name] = value

    element.save(save_prop)
    return props


def _property_changed(
    element: Base,
    prop_name: str,
    old_value: Any,
    new_value: Any,
) -> Iterator[Change]:
    """Generate change records for a property modification."""
    element_type = type(element).__name__

    # Determine if this is a relationship or a simple property
    if isinstance(old_value, frozenset) or isinstance(new_value, frozenset):
        # Collection property - track additions and removals
        old_set = old_value if isinstance(old_value, frozenset) else frozenset()
        new_set = new_value if isinstance(new_value, frozenset) else frozenset()

        for added_id in new_set - old_set:
            yield Change(
                change_type=ChangeType.ADDED,
                category=ChangeCategory.RELATIONSHIP,
                element_id=element.id,
                element_type=element_type,
                element_name=_get_element_name(element),
                property_name=prop_name,
                new_value=added_id,
                diagram_id=_get_diagram_id(element),
            )

        for removed_id in old_set - new_set:
            yield Change(
                change_type=ChangeType.REMOVED,
                category=ChangeCategory.RELATIONSHIP,
                element_id=element.id,
                element_type=element_type,
                element_name=_get_element_name(element),
                property_name=prop_name,
                old_value=removed_id,
                diagram_id=_get_diagram_id(element),
            )
    elif isinstance(old_value, str) and isinstance(new_value, str):
        # Reference change
        if old_value != new_value:
            yield Change(
                change_type=ChangeType.MODIFIED,
                category=ChangeCategory.RELATIONSHIP,
                element_id=element.id,
                element_type=element_type,
                element_name=_get_element_name(element),
                property_name=prop_name,
                old_value=old_value,
                new_value=new_value,
                diagram_id=_get_diagram_id(element),
            )
    else:
        # Simple property change
        if old_value is None and new_value is not None:
            yield Change(
                change_type=ChangeType.ADDED,
                category=ChangeCategory.PROPERTY,
                element_id=element.id,
                element_type=element_type,
                element_name=_get_element_name(element),
                property_name=prop_name,
                new_value=new_value,
                diagram_id=_get_diagram_id(element),
            )
        elif old_value is not None and new_value is None:
            yield Change(
                change_type=ChangeType.REMOVED,
                category=ChangeCategory.PROPERTY,
                element_id=element.id,
                element_type=element_type,
                element_name=_get_element_name(element),
                property_name=prop_name,
                old_value=old_value,
                diagram_id=_get_diagram_id(element),
            )
        else:
            yield Change(
                change_type=ChangeType.MODIFIED,
                category=ChangeCategory.PROPERTY,
                element_id=element.id,
                element_type=element_type,
                element_name=_get_element_name(element),
                property_name=prop_name,
                old_value=old_value,
                new_value=new_value,
                diagram_id=_get_diagram_id(element),
            )
