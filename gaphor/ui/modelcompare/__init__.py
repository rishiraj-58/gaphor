"""Model comparison and merge module for Gaphor.

This module provides functionality to compare and merge different versions
of Gaphor models, similar to Git's diff and merge capabilities.

Main components:
- differ: Compares two models and detects changes
- organize: Organizes changes into a tree structure for display
- merge: Applies selected changes to merge models
- comparedialog: UI service for model comparison
- diagramcompare: Visual diagram comparison view
"""

from gaphor.ui.modelcompare.differ import (
    Change,
    ChangeCategory,
    ChangeType,
    DiffResult,
    compare_models,
)
from gaphor.ui.modelcompare.merge import (
    MergeConflict,
    MergeResult,
    merge_changes,
)

__all__ = [
    "Change",
    "ChangeCategory",
    "ChangeType",
    "DiffResult",
    "MergeConflict",
    "MergeResult",
    "compare_models",
    "merge_changes",
]
