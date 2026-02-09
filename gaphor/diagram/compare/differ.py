"""Pure-Python diff engine for Gaphor model elements.

Works directly on the ``dict[str, element]`` returned by
``gaphor.storage.parser.parse()``.  No GTK imports – this layer is
intentionally UI-free so it can be unit-tested without a display.

Algorithm
---------
Each parsed ``element`` carries:
  * ``element.id``         – stable identifier
  * ``element.type``       – class name (e.g. "Class", "ClassItem", "Diagram")
  * ``element.values``     – ``dict[str, str]`` of scalar attributes
  * ``element.references`` – ``dict[str, str | list[str]]`` of associations

We diff the two sides by:
  1. Partitioning element ids into (only-in-base, only-in-other, in-both).
  2. For elements in both, comparing values and references attribute-by-attribute.
  3. Rolling up individual attribute deltas into per-element ``ElementDiff``
     records that carry both the categorisation (ADDED/REMOVED/MODIFIED) and the
     full diff detail needed by the UI layer.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

from gaphor.storage.parser import element as ParsedElement


class DiffKind(enum.Enum):
    """Classification of a single element's diff status."""

    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    UNCHANGED = "unchanged"


@dataclass
class AttributeDelta:
    """A single scalar attribute change on one element."""

    name: str
    base_value: str | None
    other_value: str | None


@dataclass
class RefDelta:
    """A single reference / association change on one element."""

    name: str
    # Both sides stored as sorted lists for deterministic comparison.
    base_refs: list[str] = field(default_factory=list)
    other_refs: list[str] = field(default_factory=list)


@dataclass
class ElementDiff:
    """Full diff record for one model element."""

    element_id: str
    element_type: str
    kind: DiffKind

    # Only populated when kind is ADDED or MODIFIED.
    other_values: dict[str, str] = field(default_factory=dict)
    other_references: dict[str, str | list[str]] = field(default_factory=dict)

    # Only populated when kind is REMOVED or MODIFIED (the baseline state).
    base_values: dict[str, str] = field(default_factory=dict)
    base_references: dict[str, str | list[str]] = field(default_factory=dict)

    # Granular deltas – only populated when kind == MODIFIED.
    attribute_deltas: list[AttributeDelta] = field(default_factory=list)
    ref_deltas: list[RefDelta] = field(default_factory=list)

    # Human-readable label (element name if available, else type).
    label: str = ""

    def __post_init__(self):
        if not self.label:
            self.label = self._infer_label()

    def _infer_label(self) -> str:
        """Best-effort human label without loading actual model objects."""
        # "name" is the most common scalar; fall back to the element type.
        name = (self.other_values or self.base_values).get("name")
        if name:
            return f"{self.element_type} \u201c{name}\u201d"
        return self.element_type


@dataclass
class ModelDiff:
    """Aggregated diff result comparing two full models."""

    diffs: list[ElementDiff] = field(default_factory=list)

    # Quick-access buckets.
    added: list[ElementDiff] = field(default_factory=list)
    removed: list[ElementDiff] = field(default_factory=list)
    modified: list[ElementDiff] = field(default_factory=list)
    unchanged: list[ElementDiff] = field(default_factory=list)

    def by_kind(self, kind: DiffKind) -> list[ElementDiff]:
        return [d for d in self.diffs if d.kind == kind]

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.modified)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalise_refs(raw: str | list[str]) -> list[str]:
    """Return a sorted list of ref-ids regardless of multiplicity."""
    if isinstance(raw, list):
        return sorted(raw)
    return [raw]


def _element_label(elem: ParsedElement) -> str:
    name = elem.values.get("name")
    if name:
        return f"{elem.type} \u201c{name}\u201d"
    return elem.type


def _diff_pair(
    eid: str,
    base: ParsedElement,
    other: ParsedElement,
) -> ElementDiff:
    """Build an ``ElementDiff`` for an element present in both sides."""
    attr_deltas: list[AttributeDelta] = []
    ref_deltas: list[RefDelta] = []

    # --- scalar attributes ---
    all_val_keys = set(base.values) | set(other.values)
    for key in sorted(all_val_keys):
        bv = base.values.get(key)
        ov = other.values.get(key)
        if bv != ov:
            attr_deltas.append(AttributeDelta(name=key, base_value=bv, other_value=ov))

    # --- references / associations ---
    all_ref_keys = set(base.references) | set(other.references)
    for key in sorted(all_ref_keys):
        br = _normalise_refs(base.references[key]) if key in base.references else []
        or_ = _normalise_refs(other.references[key]) if key in other.references else []
        if br != or_:
            ref_deltas.append(RefDelta(name=key, base_refs=br, other_refs=or_))

    if attr_deltas or ref_deltas:
        kind = DiffKind.MODIFIED
    else:
        kind = DiffKind.UNCHANGED

    return ElementDiff(
        element_id=eid,
        element_type=base.type,
        kind=kind,
        base_values=dict(base.values),
        base_references=dict(base.references),
        other_values=dict(other.values),
        other_references=dict(other.references),
        attribute_deltas=attr_deltas,
        ref_deltas=ref_deltas,
        label=_element_label(other if kind == DiffKind.MODIFIED else base),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def diff_elements(
    base_elements: dict[str, ParsedElement],
    other_elements: dict[str, ParsedElement],
) -> ModelDiff:
    """Compare two sets of parsed elements and return a :class:`ModelDiff`.

    Parameters
    ----------
    base_elements:
        The "left" / base parse result from :func:`gaphor.storage.parser.parse`.
    other_elements:
        The "right" / other parse result.

    Returns
    -------
    ModelDiff
        Fully populated diff with per-element records.
    """
    base_ids = set(base_elements)
    other_ids = set(other_elements)

    result = ModelDiff()

    # Removed: in base but not in other.
    for eid in sorted(base_ids - other_ids):
        elem = base_elements[eid]
        diff = ElementDiff(
            element_id=eid,
            element_type=elem.type,
            kind=DiffKind.REMOVED,
            base_values=dict(elem.values),
            base_references=dict(elem.references),
            label=_element_label(elem),
        )
        result.diffs.append(diff)
        result.removed.append(diff)

    # Added: in other but not in base.
    for eid in sorted(other_ids - base_ids):
        elem = other_elements[eid]
        diff = ElementDiff(
            element_id=eid,
            element_type=elem.type,
            kind=DiffKind.ADDED,
            other_values=dict(elem.values),
            other_references=dict(elem.references),
            label=_element_label(elem),
        )
        result.diffs.append(diff)
        result.added.append(diff)

    # Common: in both – may be modified or unchanged.
    for eid in sorted(base_ids & other_ids):
        diff = _diff_pair(eid, base_elements[eid], other_elements[eid])
        result.diffs.append(diff)
        if diff.kind == DiffKind.MODIFIED:
            result.modified.append(diff)
        else:
            result.unchanged.append(diff)

    return result
