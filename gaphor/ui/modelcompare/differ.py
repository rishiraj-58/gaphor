"""Model diffing algorithm for comparing Gaphor model versions.

This module provides the core diffing logic for detecting changes between
two versions of a Gaphor model file. It detects:
- Added/removed elements
- Modified element properties (names, attributes, values)
- Modified relationships between elements
- Presentation changes (positions, sizes, visual properties)
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from enum import Enum, auto
from operator import setitem
from typing import Any, TypeVar

from gaphor.core.modeling import Base, Diagram, ElementFactory, Presentation
from gaphor.core.modeling.collection import collection
from gaphor.core.modeling.stylesheet import StyleSheet

log = logging.getLogger(__name__)

T = TypeVar("T", bound=Base)


class ChangeType(Enum):
    """Types of changes that can be detected between model versions."""

    ADDED = auto()
    REMOVED = auto()
    MODIFIED = auto()
    UNCHANGED = auto()


@dataclass(frozen=True)
class PropertyChange:
    """Represents a change in a single property of an element."""

    property_name: str
    old_value: Any
    new_value: Any
    change_type: ChangeType

    @property
    def is_reference(self) -> bool:
        """Check if the property value is a reference to another element."""
        return isinstance(self.old_value, Base) or isinstance(self.new_value, Base)

    @property
    def is_collection(self) -> bool:
        """Check if the property value is a collection."""
        return isinstance(self.old_value, collection) or isinstance(
            self.new_value, collection
        )


@dataclass
class ElementDiff:
    """Represents all changes detected for a single element."""

    element_id: str
    element_type: str
    element_name: str | None
    change_type: ChangeType
    property_changes: list[PropertyChange] = field(default_factory=list)
    base_element: Base | None = None
    compare_element: Base | None = None

    @property
    def is_diagram(self) -> bool:
        """Check if this diff is for a Diagram element."""
        return self.element_type == "Diagram" or "Diagram" in self.element_type

    @property
    def is_presentation(self) -> bool:
        """Check if this diff is for a Presentation element."""
        return "Item" in self.element_type

    @property
    def has_significant_changes(self) -> bool:
        """Check if there are meaningful changes beyond positioning."""
        if self.change_type in (ChangeType.ADDED, ChangeType.REMOVED):
            return True

        significant_props = {
            "name",
            "subject",
            "type",
            "value",
            "visibility",
            "isAbstract",
            "body",
            "guard",
            "specification",
        }

        for change in self.property_changes:
            prop_lower = change.property_name.lower()
            if any(sig in prop_lower for sig in significant_props):
                return True
            # Skip position/visual changes for significance check
            if prop_lower not in ("matrix", "width", "height", "points"):
                return True

        return False


@dataclass
class ModelDiff:
    """Complete diff result between two model versions."""

    base_model_path: str | None
    compare_model_path: str | None
    element_diffs: list[ElementDiff] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        """Check if any changes were detected."""
        return len(self.element_diffs) > 0

    @property
    def added_elements(self) -> list[ElementDiff]:
        """Get all elements that were added."""
        return [d for d in self.element_diffs if d.change_type == ChangeType.ADDED]

    @property
    def removed_elements(self) -> list[ElementDiff]:
        """Get all elements that were removed."""
        return [d for d in self.element_diffs if d.change_type == ChangeType.REMOVED]

    @property
    def modified_elements(self) -> list[ElementDiff]:
        """Get all elements that were modified."""
        return [d for d in self.element_diffs if d.change_type == ChangeType.MODIFIED]

    @property
    def diagram_diffs(self) -> list[ElementDiff]:
        """Get diffs for diagram elements only."""
        return [d for d in self.element_diffs if d.is_diagram]

    @property
    def significant_changes(self) -> list[ElementDiff]:
        """Get only significant changes (excluding minor visual adjustments)."""
        return [d for d in self.element_diffs if d.has_significant_changes]

    def get_diff_for_element(self, element_id: str) -> ElementDiff | None:
        """Find diff for a specific element by ID."""
        if not element_id:
            return None
        for diff in self.element_diffs:
            if diff.element_id == element_id:
                return diff
        return None


class ModelDiffer:
    """Compares two Gaphor model versions and produces a diff."""

    def __init__(
        self,
        base_factory: ElementFactory,
        compare_factory: ElementFactory,
        base_path: str | None = None,
        compare_path: str | None = None,
    ):
        if base_factory is None:
            raise ValueError("base_factory cannot be None")
        if compare_factory is None:
            raise ValueError("compare_factory cannot be None")

        self._base_factory = base_factory
        self._compare_factory = compare_factory
        self._base_path = base_path
        self._compare_path = compare_path
        self._errors: list[str] = []

    def compute_diff(self) -> ModelDiff:
        """Compute the complete diff between the two models."""
        result = ModelDiff(
            base_model_path=self._base_path,
            compare_model_path=self._compare_path,
        )

        try:
            base_keys = set(self._safe_keys(self._base_factory))
            compare_keys = set(self._safe_keys(self._compare_factory))

            # Find removed elements (in base but not in compare)
            for key in base_keys.difference(compare_keys):
                diff = self._create_removed_diff(key)
                if diff:
                    result.element_diffs.append(diff)

            # Find added elements (in compare but not in base)
            for key in compare_keys.difference(base_keys):
                diff = self._create_added_diff(key)
                if diff:
                    result.element_diffs.append(diff)

            # Find modified elements (in both)
            for key in base_keys.intersection(compare_keys):
                diff = self._create_modified_diff(key)
                if diff and diff.property_changes:
                    result.element_diffs.append(diff)

        except Exception as e:
            log.exception("Error computing model diff")
            self._errors.append(f"Error computing diff: {e}")

        result.errors = self._errors.copy()
        return result

    def _safe_keys(self, factory: ElementFactory) -> Iterator[str]:
        """Safely iterate over factory keys with error handling."""
        try:
            yield from factory.keys()
        except Exception as e:
            log.warning("Error iterating factory keys: %s", e)
            self._errors.append(f"Error reading model keys: {e}")

    def _safe_lookup(self, factory: ElementFactory, key: str) -> Base | None:
        """Safely lookup an element with error handling."""
        try:
            return factory.lookup(key)
        except Exception as e:
            log.warning("Error looking up element %s: %s", key, e)
            return None

    def _get_element_name(self, element: Base | None) -> str | None:
        """Safely extract element name."""
        if element is None:
            return None
        try:
            return getattr(element, "name", None)
        except Exception:
            return None

    def _get_element_type(self, element: Base | None) -> str:
        """Get the type name of an element."""
        if element is None:
            return "Unknown"
        try:
            return type(element).__name__
        except Exception:
            return "Unknown"

    def _is_style_sheet(self, element: Base | None) -> bool:
        """Check if element is a StyleSheet."""
        if element is None:
            return False
        try:
            return isinstance(element, StyleSheet)
        except Exception:
            return False

    def _create_removed_diff(self, element_id: str) -> ElementDiff | None:
        """Create a diff for a removed element."""
        element = self._safe_lookup(self._base_factory, element_id)
        if element is None:
            return None

        # Skip stylesheets - they have special handling
        if self._is_style_sheet(element):
            return None

        return ElementDiff(
            element_id=element_id,
            element_type=self._get_element_type(element),
            element_name=self._get_element_name(element),
            change_type=ChangeType.REMOVED,
            base_element=element,
            compare_element=None,
        )

    def _create_added_diff(self, element_id: str) -> ElementDiff | None:
        """Create a diff for an added element."""
        element = self._safe_lookup(self._compare_factory, element_id)
        if element is None:
            return None

        # Skip stylesheets - they have special handling
        if self._is_style_sheet(element):
            return None

        # Get all properties as changes
        property_changes = self._extract_added_properties(element)

        return ElementDiff(
            element_id=element_id,
            element_type=self._get_element_type(element),
            element_name=self._get_element_name(element),
            change_type=ChangeType.ADDED,
            property_changes=property_changes,
            base_element=None,
            compare_element=element,
        )

    def _create_modified_diff(self, element_id: str) -> ElementDiff | None:
        """Create a diff for a modified element."""
        base_element = self._safe_lookup(self._base_factory, element_id)
        compare_element = self._safe_lookup(self._compare_factory, element_id)

        if base_element is None or compare_element is None:
            return None

        # Type mismatch is a serious error
        if type(base_element) is not type(compare_element):
            self._errors.append(
                f"Type mismatch for element {element_id}: "
                f"{self._get_element_type(base_element)} vs "
                f"{self._get_element_type(compare_element)}"
            )
            return None

        # Skip stylesheets
        if self._is_style_sheet(base_element):
            return None

        property_changes = self._compare_properties(base_element, compare_element)

        return ElementDiff(
            element_id=element_id,
            element_type=self._get_element_type(base_element),
            element_name=self._get_element_name(compare_element)
            or self._get_element_name(base_element),
            change_type=ChangeType.MODIFIED,
            property_changes=property_changes,
            base_element=base_element,
            compare_element=compare_element,
        )

    def _extract_added_properties(self, element: Base) -> list[PropertyChange]:
        """Extract all properties from a newly added element."""
        changes: list[PropertyChange] = []

        values: dict[str, Any] = {}
        try:
            element.save(lambda n, v: setitem(values, n, v))
        except Exception as e:
            log.warning("Error saving element properties: %s", e)
            return changes

        for name, value in values.items():
            if name == "id":
                continue
            changes.append(
                PropertyChange(
                    property_name=name,
                    old_value=None,
                    new_value=self._normalize_value(value),
                    change_type=ChangeType.ADDED,
                )
            )

        return changes

    def _compare_properties(
        self, base: Base, compare: Base
    ) -> list[PropertyChange]:
        """Compare properties between two elements."""
        changes: list[PropertyChange] = []

        base_values: dict[str, Any] = {}
        compare_values: dict[str, Any] = {}

        try:
            base.save(lambda n, v: setitem(base_values, n, v))
        except Exception as e:
            log.warning("Error saving base element properties: %s", e)

        try:
            compare.save(lambda n, v: setitem(compare_values, n, v))
        except Exception as e:
            log.warning("Error saving compare element properties: %s", e)

        all_props = set(base_values.keys()) | set(compare_values.keys())

        for name in all_props:
            if name == "id":
                continue

            base_value = base_values.get(name)
            compare_value = compare_values.get(name)

            # Normalize values for comparison
            base_norm = self._normalize_value(base_value)
            compare_norm = self._normalize_value(compare_value)

            if not self._values_equal(base_norm, compare_norm):
                change_type = self._determine_change_type(base_value, compare_value)
                changes.append(
                    PropertyChange(
                        property_name=name,
                        old_value=base_norm,
                        new_value=compare_norm,
                        change_type=change_type,
                    )
                )

        return changes

    def _normalize_value(self, value: Any) -> Any:
        """Normalize a value for comparison."""
        if value is None:
            return None
        if isinstance(value, Base):
            return f"ref:{value.id}"
        if isinstance(value, collection):
            return tuple(sorted(f"ref:{v.id}" for v in value))
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return value

    def _values_equal(self, v1: Any, v2: Any) -> bool:
        """Check if two normalized values are equal."""
        if v1 is None and v2 is None:
            return True
        if v1 is None or v2 is None:
            return False

        try:
            # Handle floating point comparison for matrix values
            if isinstance(v1, tuple) and isinstance(v2, tuple):
                if len(v1) != len(v2):
                    return False
                for a, b in zip(v1, v2):
                    if isinstance(a, float) and isinstance(b, float):
                        if abs(a - b) > 1e-6:
                            return False
                    elif a != b:
                        return False
                return True
            return v1 == v2
        except Exception:
            return str(v1) == str(v2)

    def _determine_change_type(
        self, old_value: Any, new_value: Any
    ) -> ChangeType:
        """Determine the type of change based on old and new values."""
        if old_value is None and new_value is not None:
            return ChangeType.ADDED
        if old_value is not None and new_value is None:
            return ChangeType.REMOVED
        return ChangeType.MODIFIED


def compute_model_diff(
    base_factory: ElementFactory,
    compare_factory: ElementFactory,
    base_path: str | None = None,
    compare_path: str | None = None,
) -> ModelDiff:
    """Compute the diff between two model element factories.

    Args:
        base_factory: The base/current model's element factory
        compare_factory: The model to compare against
        base_path: Optional path to base model file
        compare_path: Optional path to compare model file

    Returns:
        ModelDiff containing all detected changes
    """
    if base_factory is None:
        raise ValueError("base_factory is required")
    if compare_factory is None:
        raise ValueError("compare_factory is required")

    differ = ModelDiffer(base_factory, compare_factory, base_path, compare_path)
    return differ.compute_diff()


def get_element_display_name(element: Base | None) -> str:
    """Get a human-readable display name for an element."""
    if element is None:
        return "<Unknown>"

    try:
        name = getattr(element, "name", None)
        if name:
            return str(name)
        return f"{type(element).__name__} ({element.id[:8]}...)"
    except Exception:
        return "<Error>"


def format_property_change(change: PropertyChange) -> str:
    """Format a property change for display."""
    old_display = _format_value(change.old_value)
    new_display = _format_value(change.new_value)

    if change.change_type == ChangeType.ADDED:
        return f"+ {change.property_name}: {new_display}"
    elif change.change_type == ChangeType.REMOVED:
        return f"- {change.property_name}: {old_display}"
    else:
        return f"~ {change.property_name}: {old_display} → {new_display}"


def _format_value(value: Any) -> str:
    """Format a value for display."""
    if value is None:
        return "<none>"
    if isinstance(value, str) and value.startswith("ref:"):
        return f"[{value[4:8]}...]"
    if isinstance(value, tuple):
        if len(value) > 3:
            return f"({len(value)} items)"
        return str(value)
    if isinstance(value, str) and len(value) > 50:
        return f"{value[:47]}..."
    return str(value)
