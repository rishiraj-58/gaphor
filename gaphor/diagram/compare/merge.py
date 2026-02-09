"""Merge-resolution engine.

Given a :class:`~gaphor.diagram.compare.differ.ModelDiff` produced by
``diff_elements(base, other)`` and a mapping of per-element resolutions
chosen by the user, this module applies the selected changes to the *live*
``ElementFactory`` inside a single ``Transaction`` so that the entire merge
is undoable as one step.

Resolution choices
------------------
For each ``ElementDiff`` the caller supplies one of:

``"base"``
    Keep the element as it is in the currently loaded model.  No-op for
    REMOVED elements (they are already absent); ADDED elements are deleted.

``"other"``
    Accept the incoming change: apply add / remove / all attribute and
    reference mutations from the other side.

``"skip"``
    Leave the element untouched (same as "base" but semantically
    distinct – user explicitly deferred the decision).

The apply step re-uses the existing
:func:`gaphor.core.changeset.apply.apply_change` machinery wherever
possible and falls back to direct ``element.load()`` calls for attribute/ref
mutations, mirroring how the storage loader works.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from gaphor.core.changeset.apply import apply_change, applicable
from gaphor.core.modeling import (
    ElementChange,
    ElementFactory,
    RefChange,
    ValueChange,
)
from gaphor.core.modeling.modelinglanguage import ModelingLanguage
from gaphor.diagram.compare.differ import DiffKind, ElementDiff, ModelDiff
from gaphor.transaction import Transaction

log = logging.getLogger(__name__)


@dataclass
class MergeResolution:
    """Resolution for a single element's diff."""

    element_id: str
    choice: str  # "base" | "other" | "skip"


class ConflictError(Exception):
    """Raised when a resolution is impossible (e.g. type mismatch)."""


def apply_resolutions(
    diff: ModelDiff,
    resolutions: list[MergeResolution],
    element_factory: ElementFactory,
    modeling_language: ModelingLanguage,
    event_manager,
) -> int:
    """Apply user-chosen resolutions in a single undoable transaction.

    Parameters
    ----------
    diff:
        The diff object produced by :func:`~gaphor.diagram.compare.differ.diff_elements`.
    resolutions:
        One ``MergeResolution`` per element the user resolved.  Elements
        without a resolution are left untouched.
    element_factory:
        The live factory whose state will be mutated.
    modeling_language:
        Used to look up element types for creation.
    event_manager:
        Needed to wrap mutations in a ``Transaction``.

    Returns
    -------
    int
        Number of elements actually mutated.
    """
    # Index diffs by element_id for fast lookup.
    diff_by_id = {d.element_id: d for d in diff.diffs}
    applied = 0

    with Transaction(event_manager):
        for resolution in resolutions:
            eid = resolution.element_id
            choice = resolution.choice
            element_diff = diff_by_id.get(eid)
            if element_diff is None or choice == "skip":
                continue

            try:
                did_change = _apply_one(
                    element_diff, choice, element_factory, modeling_language
                )
            except Exception as exc:
                log.error(
                    "Failed to apply resolution '%s' for element %s: %s",
                    choice,
                    eid,
                    exc,
                )
                raise

            if did_change:
                applied += 1

    return applied


def _apply_one(
    diff: ElementDiff,
    choice: str,
    element_factory: ElementFactory,
    modeling_language: ModelingLanguage,
) -> bool:
    """Apply a single resolution.  Returns True if any mutation occurred."""
    kind = diff.kind

    if choice == "base":
        # Nothing to do for UNCHANGED / REMOVED (already removed or same).
        # For ADDED we need to delete it from the live model.
        if kind == DiffKind.ADDED:
            if element := element_factory.lookup(diff.element_id):
                element.unlink()
                return True
        return False

    if choice == "other":
        if kind == DiffKind.REMOVED:
            # The element was deleted in the other version; remove it.
            if element := element_factory.lookup(diff.element_id):
                element.unlink()
                return True
            return False

        if kind == DiffKind.ADDED:
            # The element is new in the other version; create it.
            return _create_element(diff, element_factory, modeling_language)

        if kind == DiffKind.MODIFIED:
            # Apply individual attribute and reference deltas.
            return _apply_deltas(diff, element_factory)

        # UNCHANGED – "other" is the same as base, no-op.
        return False

    raise ValueError(f"Unknown resolution choice '{choice}'")


def _create_element(
    diff: ElementDiff,
    element_factory: ElementFactory,
    modeling_language: ModelingLanguage,
) -> bool:
    """Create an element that exists in `other` but not in `base`."""
    element_type = modeling_language.lookup_element(diff.element_type)
    if element_type is None:
        log.warning("Cannot create unknown element type '%s'", diff.element_type)
        return False

    diagram_id = diff.other_references.get("diagram")
    diagram = element_factory.lookup(diagram_id) if diagram_id else None

    try:
        element = element_factory.create_as(
            element_type, diff.element_id, diagram=diagram
        )
    except Exception as exc:
        log.error("create_as failed for %s: %s", diff.element_id, exc)
        return False

    # Load scalar attributes.
    for name, value in diff.other_values.items():
        if name == "id":
            continue
        try:
            element.load(name, value)
        except AttributeError:
            log.debug("Attribute '%s' not found on %s, skipping", name, diff.element_type)

    # Load references (single and multi).
    for name, ref_or_refs in diff.other_references.items():
        if name == "diagram":
            continue
        refs = ref_or_refs if isinstance(ref_or_refs, list) else [ref_or_refs]
        for ref_id in refs:
            if ref_elem := element_factory.lookup(ref_id):
                try:
                    element.load(name, ref_elem)
                except AttributeError:
                    log.debug("Ref '%s' not found on %s, skipping", name, diff.element_type)

    try:
        element.postload()
    except Exception:
        pass  # postload is best-effort

    return True


def _apply_deltas(
    diff: ElementDiff,
    element_factory: ElementFactory,
) -> bool:
    """Apply attribute and reference deltas to an existing element."""
    element = element_factory.lookup(diff.element_id)
    if element is None:
        log.warning("Element %s not found for delta application", diff.element_id)
        return False

    mutated = False

    for delta in diff.attribute_deltas:
        try:
            element.load(delta.name, delta.other_value)
            mutated = True
        except AttributeError:
            log.debug(
                "Attribute '%s' not settable on %s", delta.name, type(element).__name__
            )

    for rdelta in diff.ref_deltas:
        # Ids to add (in other but not in base).
        added_ids = set(rdelta.other_refs) - set(rdelta.base_refs)
        # Ids to remove (in base but not in other).
        removed_ids = set(rdelta.base_refs) - set(rdelta.other_refs)

        for ref_id in added_ids:
            if ref_elem := element_factory.lookup(ref_id):
                try:
                    element.load(rdelta.name, ref_elem)
                    mutated = True
                except AttributeError:
                    log.debug("Ref add '%s' failed on %s", rdelta.name, type(element).__name__)

        for ref_id in removed_ids:
            if ref_elem := element_factory.lookup(ref_id):
                prop = getattr(type(element), rdelta.name, None)
                if prop is None:
                    continue
                try:
                    if prop.upper == 1:
                        setattr(element, rdelta.name, None)
                    else:
                        getattr(element, rdelta.name).remove(ref_elem)
                    mutated = True
                except (AttributeError, ValueError) as exc:
                    log.debug("Ref remove '%s' failed: %s", rdelta.name, exc)

    if mutated:
        try:
            element.postload()
        except Exception:
            pass

    return mutated
