"""Unit tests for the pure-Python diff engine (differ.py).

All tests use ``gaphor.storage.parser.element`` objects constructed
directly – no ElementFactory or GTK needed.
"""

from __future__ import annotations

import pytest

from gaphor.storage.parser import element as ParsedElement
from gaphor.diagram.compare.differ import (
    AttributeDelta,
    DiffKind,
    ModelDiff,
    RefDelta,
    diff_elements,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_elem(
    eid: str,
    etype: str,
    values: dict | None = None,
    references: dict | None = None,
) -> ParsedElement:
    """Build a minimal ParsedElement for testing."""
    e = ParsedElement(id=eid, type=etype)
    e.values = values or {}
    e.references = references or {}
    return e


def base_dict(*elems: ParsedElement) -> dict:
    return {e.id: e for e in elems}


# ---------------------------------------------------------------------------
# Empty / identical models
# ---------------------------------------------------------------------------


def test_both_empty():
    diff = diff_elements({}, {})
    assert not diff.has_changes
    assert diff.diffs == []


def test_identical_single_element():
    e = make_elem("1", "Class", {"name": "Foo"})
    diff = diff_elements(base_dict(e), base_dict(e))
    assert not diff.has_changes
    assert len(diff.unchanged) == 1


def test_identical_two_elements():
    a = make_elem("1", "Class", {"name": "A"})
    b = make_elem("2", "Package", {"name": "P"})
    diff = diff_elements(base_dict(a, b), base_dict(a, b))
    assert len(diff.unchanged) == 2
    assert not diff.has_changes


# ---------------------------------------------------------------------------
# Added elements
# ---------------------------------------------------------------------------


def test_added_element():
    base = {}
    other = base_dict(make_elem("42", "Class", {"name": "NewClass"}))
    diff = diff_elements(base, other)
    assert len(diff.added) == 1
    assert diff.added[0].element_id == "42"
    assert diff.added[0].kind == DiffKind.ADDED
    assert diff.added[0].element_type == "Class"
    assert diff.added[0].label == "Class \u201cNewClass\u201d"


def test_added_element_without_name():
    base = {}
    other = base_dict(make_elem("99", "Association"))
    diff = diff_elements(base, other)
    assert diff.added[0].label == "Association"


def test_multiple_added_elements():
    base = {}
    other = base_dict(
        make_elem("1", "Class", {"name": "A"}),
        make_elem("2", "Interface", {"name": "I"}),
    )
    diff = diff_elements(base, other)
    assert len(diff.added) == 2
    assert {d.element_type for d in diff.added} == {"Class", "Interface"}


# ---------------------------------------------------------------------------
# Removed elements
# ---------------------------------------------------------------------------


def test_removed_element():
    base = base_dict(make_elem("10", "Diagram", {"name": "D1"}))
    other = {}
    diff = diff_elements(base, other)
    assert len(diff.removed) == 1
    assert diff.removed[0].element_id == "10"
    assert diff.removed[0].kind == DiffKind.REMOVED
    assert diff.removed[0].label == "Diagram \u201cD1\u201d"


def test_multiple_removed_elements():
    base = base_dict(
        make_elem("a", "Class"),
        make_elem("b", "Package"),
    )
    diff = diff_elements(base, {})
    assert len(diff.removed) == 2


# ---------------------------------------------------------------------------
# Modified elements – attribute deltas
# ---------------------------------------------------------------------------


def test_modified_scalar_attribute():
    base = base_dict(make_elem("5", "Class", {"name": "OldName"}))
    other = base_dict(make_elem("5", "Class", {"name": "NewName"}))
    diff = diff_elements(base, other)
    assert len(diff.modified) == 1
    m = diff.modified[0]
    assert m.kind == DiffKind.MODIFIED
    assert len(m.attribute_deltas) == 1
    delta = m.attribute_deltas[0]
    assert delta.name == "name"
    assert delta.base_value == "OldName"
    assert delta.other_value == "NewName"


def test_modified_attribute_added_on_other_side():
    """Attribute present in other but missing in base."""
    base = base_dict(make_elem("7", "Class", {}))
    other = base_dict(make_elem("7", "Class", {"visibility": "public"}))
    diff = diff_elements(base, other)
    assert diff.modified[0].attribute_deltas[0] == AttributeDelta(
        name="visibility", base_value=None, other_value="public"
    )


def test_modified_attribute_removed_on_other_side():
    """Attribute present in base but missing in other."""
    base = base_dict(make_elem("8", "Class", {"note": "todo"}))
    other = base_dict(make_elem("8", "Class", {}))
    diff = diff_elements(base, other)
    assert diff.modified[0].attribute_deltas[0] == AttributeDelta(
        name="note", base_value="todo", other_value=None
    )


def test_multiple_attribute_deltas():
    base = base_dict(make_elem("9", "Class", {"name": "X", "visibility": "private"}))
    other = base_dict(make_elem("9", "Class", {"name": "Y", "visibility": "public"}))
    diff = diff_elements(base, other)
    deltas = {d.name: d for d in diff.modified[0].attribute_deltas}
    assert deltas["name"].base_value == "X"
    assert deltas["name"].other_value == "Y"
    assert deltas["visibility"].base_value == "private"
    assert deltas["visibility"].other_value == "public"


# ---------------------------------------------------------------------------
# Modified elements – reference deltas
# ---------------------------------------------------------------------------


def test_modified_single_ref_changed():
    base = base_dict(make_elem("e1", "GeneralizationItem", references={"subject": "s1"}))
    other = base_dict(make_elem("e1", "GeneralizationItem", references={"subject": "s2"}))
    diff = diff_elements(base, other)
    assert diff.modified[0].ref_deltas[0] == RefDelta(
        name="subject", base_refs=["s1"], other_refs=["s2"]
    )


def test_modified_multi_ref_element_added():
    base = base_dict(make_elem("c1", "Class", references={"ownedAttribute": ["p1", "p2"]}))
    other = base_dict(
        make_elem("c1", "Class", references={"ownedAttribute": ["p1", "p2", "p3"]})
    )
    diff = diff_elements(base, other)
    rd = diff.modified[0].ref_deltas[0]
    assert rd.name == "ownedAttribute"
    assert sorted(rd.base_refs) == ["p1", "p2"]
    assert sorted(rd.other_refs) == ["p1", "p2", "p3"]


def test_modified_multi_ref_element_removed():
    base = base_dict(make_elem("c2", "Class", references={"ownedAttribute": ["p1", "p2"]}))
    other = base_dict(make_elem("c2", "Class", references={"ownedAttribute": ["p1"]}))
    diff = diff_elements(base, other)
    rd = diff.modified[0].ref_deltas[0]
    assert sorted(rd.base_refs) == ["p1", "p2"]
    assert sorted(rd.other_refs) == ["p1"]


def test_unchanged_when_only_ref_order_differs():
    """Reference order differences in multi-valued associations must NOT produce a delta
    because the diff normalises both sides to sorted lists."""
    base = base_dict(make_elem("x1", "Package", references={"nestedPackage": ["b", "a"]}))
    other = base_dict(make_elem("x1", "Package", references={"nestedPackage": ["a", "b"]}))
    diff = diff_elements(base, other)
    # Both sides normalise to ["a", "b"] → unchanged
    assert len(diff.unchanged) == 1
    assert not diff.modified


# ---------------------------------------------------------------------------
# Mixed scenarios
# ---------------------------------------------------------------------------


def test_mixed_add_remove_modify():
    base = base_dict(
        make_elem("keep", "Package", {"name": "P"}),
        make_elem("gone", "Class", {"name": "Deleted"}),
        make_elem("change", "Interface", {"name": "Old"}),
    )
    other = base_dict(
        make_elem("keep", "Package", {"name": "P"}),
        make_elem("new", "Diagram", {"name": "Fresh"}),
        make_elem("change", "Interface", {"name": "New"}),
    )
    diff = diff_elements(base, other)
    assert len(diff.added) == 1
    assert diff.added[0].element_id == "new"
    assert len(diff.removed) == 1
    assert diff.removed[0].element_id == "gone"
    assert len(diff.modified) == 1
    assert diff.modified[0].element_id == "change"
    assert len(diff.unchanged) == 1
    assert diff.unchanged[0].element_id == "keep"


# ---------------------------------------------------------------------------
# ModelDiff helpers
# ---------------------------------------------------------------------------


def test_model_diff_has_changes_property():
    diff = diff_elements({}, {})
    assert not diff.has_changes

    base = base_dict(make_elem("z", "Class"))
    diff2 = diff_elements(base, {})
    assert diff2.has_changes


def test_model_diff_by_kind():
    base = base_dict(make_elem("a", "Class"))
    other = base_dict(make_elem("b", "Package"))
    diff = diff_elements(base, other)
    assert diff.by_kind(DiffKind.ADDED) == diff.added
    assert diff.by_kind(DiffKind.REMOVED) == diff.removed
    assert diff.by_kind(DiffKind.MODIFIED) == diff.modified
    assert diff.by_kind(DiffKind.UNCHANGED) == diff.unchanged
