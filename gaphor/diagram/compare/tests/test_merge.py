"""Unit tests for the merge-resolution engine (merge.py).

These tests use a lightweight in-memory fake factory that mirrors the
``ElementFactory`` contract (``lookup``, ``create_as``, ``unlink`` removes
from registry) so the full resolution logic is exercised without needing a
running GTK application.  A ``FakeTransaction`` records how many top-level
transactions were opened so the "single undoable step" guarantee is verified.
"""

from __future__ import annotations

from gaphor.diagram.compare.differ import DiffKind, ModelDiff, diff_elements
from gaphor.diagram.compare.merge import MergeResolution, apply_resolutions


# ---------------------------------------------------------------------------
# Lightweight stubs
# ---------------------------------------------------------------------------


class _FakeFactory:
    """Minimal element factory whose unlink() wires back to the registry."""

    def __init__(self):
        self._elems: dict = {}

    def lookup(self, eid):
        return self._elems.get(eid)

    def create_as(self, etype, eid, diagram=None):
        name = etype.__name__ if hasattr(etype, "__name__") else str(etype)
        e = self._make_elem(eid, name)
        self._elems[eid] = e
        return e

    def _make_elem(self, eid, type_name):
        registry = self._elems

        class _El:
            def __init__(s):
                s.id = eid
                s._type = type_name
                s._attrs: dict = {}
                s._refs: dict = {}

            def load(s, name, value):
                if isinstance(value, _El):
                    s._refs.setdefault(name, []).append(value.id)
                else:
                    s._attrs[name] = value

            def postload(s):
                pass

            def unlink(s):
                registry.pop(s.id, None)

        return _El()

    def add(self, eid, type_name):
        """Convenience: add a pre-existing element."""
        e = self._make_elem(eid, type_name)
        self._elems[eid] = e
        return e

    def __iter__(self):
        return iter(list(self._elems.values()))


class _FakeType:
    def __init__(self, name):
        self.__name__ = name


class _FakeML:
    def lookup_element(self, name, ns=None):
        return _FakeType(name)


class _FakeEM:
    pass


class _FakeTransaction:
    """Records how many top-level transactions were opened."""

    opened: int = 0

    def __init__(self, em, context=None):
        pass

    def __enter__(self):
        _FakeTransaction.opened += 1
        return self

    def __exit__(self, *args):
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_parsed(eid, etype, values=None, references=None):
    from gaphor.storage.parser import element as ParsedElement

    e = ParsedElement(id=eid, type=etype)
    e.values = values or {}
    e.references = references or {}
    return e


def _snapshot(factory: _FakeFactory) -> dict:
    """Convert the fake factory contents to a parsed-element dict for diffing."""
    return {e.id: _make_parsed(e.id, e._type, dict(e._attrs)) for e in factory}


# Patch Transaction in the merge module for unit tests.
import gaphor.diagram.compare.merge as _merge_mod

_merge_mod.Transaction = _FakeTransaction  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# "other" resolution – accept incoming change
# ---------------------------------------------------------------------------


def test_accept_added_element_creates_it():
    """Choosing 'other' for an ADDED element should create it in the factory."""
    f = _FakeFactory()
    base = _snapshot(f)
    other = dict(base)
    other["new-xyz"] = _make_parsed("new-xyz", "Diagram", {"name": "NewDiagram"})

    diff = diff_elements(base, other)
    assert len(diff.added) == 1

    count = apply_resolutions(diff, [MergeResolution("new-xyz", "other")], f, _FakeML(), _FakeEM())
    assert count == 1
    assert f.lookup("new-xyz") is not None


def test_accept_removed_element_deletes_it():
    """Choosing 'other' for a REMOVED element should delete it from the factory."""
    f = _FakeFactory()
    f.add("del-me", "Class")
    base = _snapshot(f)
    diff = diff_elements(base, {})
    assert len(diff.removed) == 1

    apply_resolutions(diff, [MergeResolution("del-me", "other")], f, _FakeML(), _FakeEM())
    assert f.lookup("del-me") is None


def test_accept_modified_attribute_updates_value():
    """Choosing 'other' for a MODIFIED element updates the attribute."""
    f = _FakeFactory()
    e = f.add("mod-me", "Class")
    e._attrs["name"] = "OldName"
    base = _snapshot(f)
    other = {"mod-me": _make_parsed("mod-me", "Class", {"name": "NewName"})}

    diff = diff_elements(base, other)
    assert len(diff.modified) == 1

    apply_resolutions(diff, [MergeResolution("mod-me", "other")], f, _FakeML(), _FakeEM())
    assert f.lookup("mod-me")._attrs["name"] == "NewName"


# ---------------------------------------------------------------------------
# "base" resolution – keep current state
# ---------------------------------------------------------------------------


def test_reject_added_element_leaves_factory_unchanged():
    """Choosing 'base' for an ADDED element should not modify the factory."""
    f = _FakeFactory()
    base = _snapshot(f)
    other = dict(base)
    other["reject-me"] = _make_parsed("reject-me", "Package")

    diff = diff_elements(base, other)
    count = apply_resolutions(diff, [MergeResolution("reject-me", "base")], f, _FakeML(), _FakeEM())
    assert count == 0
    assert f.lookup("reject-me") is None


def test_reject_modified_element_leaves_attribute_unchanged():
    f = _FakeFactory()
    e = f.add("keep", "Class")
    e._attrs["name"] = "KeepThis"
    base = _snapshot(f)
    other = {"keep": _make_parsed("keep", "Class", {"name": "DontWant"})}

    diff = diff_elements(base, other)
    apply_resolutions(diff, [MergeResolution("keep", "base")], f, _FakeML(), _FakeEM())
    assert f.lookup("keep")._attrs["name"] == "KeepThis"


# ---------------------------------------------------------------------------
# "skip" resolution – no-op
# ---------------------------------------------------------------------------


def test_skip_resolution_is_noop():
    f = _FakeFactory()
    base = _snapshot(f)
    other = dict(base)
    other["skip-add"] = _make_parsed("skip-add", "Interface")

    diff = diff_elements(base, other)
    count = apply_resolutions(diff, [MergeResolution("skip-add", "skip")], f, _FakeML(), _FakeEM())
    assert count == 0
    assert f.lookup("skip-add") is None


# ---------------------------------------------------------------------------
# Single Transaction wraps ALL mutations (undo guarantee)
# ---------------------------------------------------------------------------


def test_merge_uses_single_transaction():
    """The entire apply_resolutions call must be wrapped in exactly one Transaction."""
    _FakeTransaction.opened = 0
    f = _FakeFactory()
    f.add("e1", "Class")._attrs["name"] = "Old"
    base = _snapshot(f)
    other = {"e1": _make_parsed("e1", "Class", {"name": "New"})}
    diff = diff_elements(base, other)

    apply_resolutions(diff, [MergeResolution("e1", "other")], f, _FakeML(), _FakeEM())
    assert _FakeTransaction.opened == 1


# ---------------------------------------------------------------------------
# Mixed resolutions in one call
# ---------------------------------------------------------------------------


def test_mixed_resolutions_applied_correctly():
    """Accept some, reject others, skip some in one call."""
    _FakeTransaction.opened = 0
    f = _FakeFactory()
    e1 = f.add("e1", "Class")
    e1._attrs["name"] = "OldName"
    e2 = f.add("e2", "Package")
    e2._attrs["name"] = "StayName"
    base = _snapshot(f)
    other = {
        "e1": _make_parsed("e1", "Class", {"name": "NewName"}),
        "e2": _make_parsed("e2", "Package", {"name": "StayName"}),
        "e3": _make_parsed("e3", "Diagram", {"name": "Added"}),
    }

    diff = diff_elements(base, other)
    resolutions = [
        MergeResolution("e1", "other"),
        MergeResolution("e2", "base"),
        MergeResolution("e3", "skip"),
    ]
    count = apply_resolutions(diff, resolutions, f, _FakeML(), _FakeEM())

    assert count == 1  # only e1 was mutated
    assert f.lookup("e1")._attrs["name"] == "NewName"
    assert f.lookup("e2")._attrs["name"] == "StayName"
    assert f.lookup("e3") is None
    # Still exactly one transaction for the whole batch.
    assert _FakeTransaction.opened == 1


# ---------------------------------------------------------------------------
# Empty resolution list
# ---------------------------------------------------------------------------


def test_empty_resolutions_noop():
    f = _FakeFactory()
    count = apply_resolutions(ModelDiff(), [], f, _FakeML(), _FakeEM())
    assert count == 0
