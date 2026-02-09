# ruff: noqa: F401
"""Diagram-level diff/merge subsystem.

Public surface:
  - ``ModelDiff``       – pure-Python diff result (no GTK dependency)
  - ``DiffKind``        – enum of change kinds (ADDED, REMOVED, MODIFIED, UNCHANGED)
  - ``ElementDiff``     – one record per element in the diff
  - ``diff_elements``   – produce a ``ModelDiff`` from two parsed element dicts
"""

from gaphor.diagram.compare.differ import DiffKind, ElementDiff, ModelDiff, diff_elements
