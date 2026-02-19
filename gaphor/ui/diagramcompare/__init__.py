"""Diagram comparison feature for Gaphor.

This module provides functionality to compare different versions of diagrams
and models, highlighting differences in a split-screen view.
"""

from gaphor.ui.diagramcompare.comparator import (
    DiagramDiff,
    ElementDiff,
    compare_diagrams,
    compare_elements,
)
from gaphor.ui.diagramcompare.compareview import DiagramCompareView

__all__ = [
    "DiagramDiff",
    "ElementDiff",
    "compare_diagrams",
    "compare_elements",
    "DiagramCompareView",
]
