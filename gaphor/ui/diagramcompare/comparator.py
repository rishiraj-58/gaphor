"""Diagram and model comparison algorithm.

Compares two versions of a diagram/model and detects differences in:
- Element properties (name, type, etc.)
- Relationships and references
- Presentation items (positions, sizes, styles)
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from gaphor.core.modeling import Base, Diagram, Presentation
from gaphor.core.modeling.collection import collection

if TYPE_CHECKING:
    from gaphor.core.modeling import ElementFactory


class ChangeType(Enum):
    """Types of changes that can be detected."""

    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    UNCHANGED = "unchanged"


@dataclass
class PropertyDiff:
    """Represents a difference in a single property."""

    property_name: str
    old_value: Any
    new_value: Any
    change_type: ChangeType

    @property
    def display_old(self) -> str:
        """Format old value for display."""
        return self._format_value(self.old_value)

    @property
    def display_new(self) -> str:
        """Format new value for display."""
        return self._format_value(self.new_value)

    def _format_value(self, value: Any) -> str:
        if value is None:
            return "<None>"
        if isinstance(value, Base):
            name = getattr(value, "name", None)
            return f"{type(value).__name__}({name or value.id[:8]})"
        if isinstance(value, collection):
            items = [self._format_value(v) for v in value]
            return f"[{', '.join(items)}]"
        return str(value)


@dataclass
class ElementDiff:
    """Represents differences for a single element."""

    element_id: str
    element_type: str
    element_name: str | None
    change_type: ChangeType
    base_element: Base | None = None
    compare_element: Base | None = None
    property_diffs: list[PropertyDiff] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        """Check if there are any actual changes."""
        return self.change_type != ChangeType.UNCHANGED or bool(self.property_diffs)

    @property
    def display_name(self) -> str:
        """Get a display-friendly name for the element."""
        if self.element_name:
            return f"{self.element_type} '{self.element_name}'"
        return f"{self.element_type} ({self.element_id[:8]})"


@dataclass
class PresentationDiff:
    """Represents differences in presentation items."""

    presentation_id: str
    presentation_type: str
    change_type: ChangeType
    base_presentation: Presentation | None = None
    compare_presentation: Presentation | None = None
    property_diffs: list[PropertyDiff] = field(default_factory=list)
    subject_diff: ElementDiff | None = None

    @property
    def has_changes(self) -> bool:
        return self.change_type != ChangeType.UNCHANGED or bool(self.property_diffs)


@dataclass
class DiagramDiff:
    """Represents the complete diff between two diagrams."""

    base_diagram: Diagram | None
    compare_diagram: Diagram | None
    diagram_property_diffs: list[PropertyDiff] = field(default_factory=list)
    presentation_diffs: list[PresentationDiff] = field(default_factory=list)
    element_diffs: list[ElementDiff] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return (
            bool(self.diagram_property_diffs)
            or any(p.has_changes for p in self.presentation_diffs)
            or any(e.has_changes for e in self.element_diffs)
        )

    @property
    def added_presentations(self) -> list[PresentationDiff]:
        return [p for p in self.presentation_diffs if p.change_type == ChangeType.ADDED]

    @property
    def removed_presentations(self) -> list[PresentationDiff]:
        return [
            p for p in self.presentation_diffs if p.change_type == ChangeType.REMOVED
        ]

    @property
    def modified_presentations(self) -> list[PresentationDiff]:
        return [
            p
            for p in self.presentation_diffs
            if p.change_type == ChangeType.MODIFIED or p.property_diffs
        ]

    def get_presentation_change_type(self, presentation_id: str) -> ChangeType | None:
        """Get the change type for a specific presentation."""
        for p in self.presentation_diffs:
            if p.presentation_id == presentation_id:
                return p.change_type
        return None


def compare_diagrams(
    base_diagram: Diagram | None, compare_diagram: Diagram | None
) -> DiagramDiff:
    """Compare two diagrams and return their differences.

    Args:
        base_diagram: The original/base version of the diagram
        compare_diagram: The version to compare against

    Returns:
        DiagramDiff containing all detected differences
    """
    diff = DiagramDiff(base_diagram=base_diagram, compare_diagram=compare_diagram)

    if base_diagram is None and compare_diagram is None:
        return diff

    if base_diagram is None:
        # Everything in compare_diagram is new
        assert compare_diagram is not None
        for pres in compare_diagram.ownedPresentation:
            diff.presentation_diffs.append(
                _create_presentation_diff(None, pres, ChangeType.ADDED)
            )
        return diff

    if compare_diagram is None:
        # Everything in base_diagram was removed
        for pres in base_diagram.ownedPresentation:
            diff.presentation_diffs.append(
                _create_presentation_diff(pres, None, ChangeType.REMOVED)
            )
        return diff

    # Compare diagram-level properties
    diff.diagram_property_diffs = _compare_element_properties(
        base_diagram, compare_diagram, _diagram_property_names()
    )

    # Build maps of presentations by ID
    base_presentations = {p.id: p for p in base_diagram.ownedPresentation}
    compare_presentations = {p.id: p for p in compare_diagram.ownedPresentation}

    base_ids = set(base_presentations.keys())
    compare_ids = set(compare_presentations.keys())

    # Find added presentations
    for pid in compare_ids - base_ids:
        diff.presentation_diffs.append(
            _create_presentation_diff(None, compare_presentations[pid], ChangeType.ADDED)
        )

    # Find removed presentations
    for pid in base_ids - compare_ids:
        diff.presentation_diffs.append(
            _create_presentation_diff(base_presentations[pid], None, ChangeType.REMOVED)
        )

    # Find modified presentations
    for pid in base_ids & compare_ids:
        base_pres = base_presentations[pid]
        compare_pres = compare_presentations[pid]
        pres_diff = _compare_presentations(base_pres, compare_pres)
        if pres_diff.has_changes:
            diff.presentation_diffs.append(pres_diff)

    return diff


def compare_elements(base_element: Base | None, compare_element: Base | None) -> ElementDiff:
    """Compare two elements and return their differences.

    Args:
        base_element: The original/base version of the element
        compare_element: The version to compare against

    Returns:
        ElementDiff containing all detected differences
    """
    if base_element is None and compare_element is None:
        raise ValueError("At least one element must be provided")

    element = base_element or compare_element
    assert element is not None

    element_id = element.id
    element_type = type(element).__name__
    element_name = getattr(element, "name", None)

    if base_element is None:
        return ElementDiff(
            element_id=element_id,
            element_type=element_type,
            element_name=element_name,
            change_type=ChangeType.ADDED,
            compare_element=compare_element,
        )

    if compare_element is None:
        return ElementDiff(
            element_id=element_id,
            element_type=element_type,
            element_name=element_name,
            change_type=ChangeType.REMOVED,
            base_element=base_element,
        )

    # Both elements exist - compare their properties
    property_diffs = _compare_element_properties(
        base_element, compare_element, _element_property_names(base_element)
    )

    change_type = ChangeType.MODIFIED if property_diffs else ChangeType.UNCHANGED

    return ElementDiff(
        element_id=element_id,
        element_type=element_type,
        element_name=element_name,
        change_type=change_type,
        base_element=base_element,
        compare_element=compare_element,
        property_diffs=property_diffs,
    )


def _compare_presentations(
    base_pres: Presentation, compare_pres: Presentation
) -> PresentationDiff:
    """Compare two presentation items."""
    property_diffs = _compare_element_properties(
        base_pres, compare_pres, _presentation_property_names()
    )

    # Compare subjects if they exist
    subject_diff = None
    base_subject = base_pres.subject
    compare_subject = compare_pres.subject

    if base_subject is not None or compare_subject is not None:
        if base_subject is None:
            subject_diff = ElementDiff(
                element_id=compare_subject.id,  # type: ignore
                element_type=type(compare_subject).__name__,  # type: ignore
                element_name=getattr(compare_subject, "name", None),
                change_type=ChangeType.ADDED,
                compare_element=compare_subject,
            )
        elif compare_subject is None:
            subject_diff = ElementDiff(
                element_id=base_subject.id,
                element_type=type(base_subject).__name__,
                element_name=getattr(base_subject, "name", None),
                change_type=ChangeType.REMOVED,
                base_element=base_subject,
            )
        elif base_subject.id != compare_subject.id:
            subject_diff = ElementDiff(
                element_id=compare_subject.id,
                element_type=type(compare_subject).__name__,
                element_name=getattr(compare_subject, "name", None),
                change_type=ChangeType.MODIFIED,
                base_element=base_subject,
                compare_element=compare_subject,
            )
        else:
            # Same subject - compare its properties
            subject_prop_diffs = _compare_element_properties(
                base_subject, compare_subject, _element_property_names(base_subject)
            )
            if subject_prop_diffs:
                subject_diff = ElementDiff(
                    element_id=base_subject.id,
                    element_type=type(base_subject).__name__,
                    element_name=getattr(base_subject, "name", None),
                    change_type=ChangeType.MODIFIED,
                    base_element=base_subject,
                    compare_element=compare_subject,
                    property_diffs=subject_prop_diffs,
                )

    change_type = ChangeType.UNCHANGED
    if property_diffs or subject_diff:
        change_type = ChangeType.MODIFIED

    return PresentationDiff(
        presentation_id=base_pres.id,
        presentation_type=type(base_pres).__name__,
        change_type=change_type,
        base_presentation=base_pres,
        compare_presentation=compare_pres,
        property_diffs=property_diffs,
        subject_diff=subject_diff,
    )


def _create_presentation_diff(
    base_pres: Presentation | None,
    compare_pres: Presentation | None,
    change_type: ChangeType,
) -> PresentationDiff:
    """Create a PresentationDiff for added or removed presentations."""
    pres = base_pres or compare_pres
    assert pres is not None

    subject_diff = None
    if pres.subject:
        subject_diff = ElementDiff(
            element_id=pres.subject.id,
            element_type=type(pres.subject).__name__,
            element_name=getattr(pres.subject, "name", None),
            change_type=change_type,
            base_element=pres.subject if base_pres else None,
            compare_element=pres.subject if compare_pres else None,
        )

    return PresentationDiff(
        presentation_id=pres.id,
        presentation_type=type(pres).__name__,
        change_type=change_type,
        base_presentation=base_pres,
        compare_presentation=compare_pres,
        subject_diff=subject_diff,
    )


def _compare_element_properties(
    base: Base, compare: Base, property_names: Iterable[str]
) -> list[PropertyDiff]:
    """Compare specific properties between two elements."""
    diffs: list[PropertyDiff] = []

    for prop_name in property_names:
        base_value = getattr(base, prop_name, None)
        compare_value = getattr(compare, prop_name, None)

        if not _values_equal(base_value, compare_value):
            diffs.append(
                PropertyDiff(
                    property_name=prop_name,
                    old_value=base_value,
                    new_value=compare_value,
                    change_type=ChangeType.MODIFIED,
                )
            )

    return diffs


def _values_equal(val1: Any, val2: Any) -> bool:
    """Check if two values are equal, handling special cases."""
    if val1 is None and val2 is None:
        return True
    if val1 is None or val2 is None:
        return False

    # Handle Base elements - compare by ID
    if isinstance(val1, Base) and isinstance(val2, Base):
        return val1.id == val2.id

    # Handle collections
    if isinstance(val1, collection) and isinstance(val2, collection):
        ids1 = {v.id for v in val1 if isinstance(v, Base)}
        ids2 = {v.id for v in val2 if isinstance(v, Base)}
        return ids1 == ids2

    # Handle tuples and lists (for matrix, points, etc.)
    if isinstance(val1, (tuple, list)) and isinstance(val2, (tuple, list)):
        if len(val1) != len(val2):
            return False
        return all(_values_equal(v1, v2) for v1, v2 in zip(val1, val2))

    # Handle floats with tolerance
    if isinstance(val1, float) and isinstance(val2, float):
        return abs(val1 - val2) < 0.001

    return val1 == val2


def _diagram_property_names() -> list[str]:
    """Get list of diagram properties to compare."""
    return ["name", "diagramType"]


def _presentation_property_names() -> list[str]:
    """Get list of presentation properties to compare."""
    return [
        "matrix",
        "width",
        "height",
        "points",
        "orthogonal",
        "horizontal",
    ]


def _element_property_names(element: Base) -> Iterator[str]:
    """Get list of element properties to compare."""
    # Skip internal properties and relationships that are handled separately
    skip_props = {
        "id",
        "presentation",
        "diagram",
        "ownedPresentation",
        "ownedDiagram",
        "parent",
        "children",
        "model",
    }

    # Prioritize common properties first for better display order
    priority_props = ["name", "visibility", "isAbstract", "isStatic", "isFinal", "type"]
    
    seen = set()
    for prop_name in priority_props:
        if hasattr(element, prop_name) and prop_name not in skip_props:
            seen.add(prop_name)
            yield prop_name

    for prop in element.__properties__:
        if prop.name not in skip_props and prop.name not in seen:
            yield prop.name
