"""Template browser for creating and managing reusable diagram templates.

This module provides:
- TemplateBrowser: Main UI component for browsing and using templates
- DiagramTemplate: Data class representing a reusable template
- TemplateCategory: Categories for organizing templates
- TemplateParameter: Parameterized placeholders in templates
- TemplateStorage: Persistent storage with atomic writes and indexing
- TemplateValidator: Validation for template content and structure
"""

from gaphor.ui.templatebrowser.templatebrowser import TemplateBrowser
from gaphor.ui.templatebrowser.template import (
    DiagramTemplate,
    TemplateCategory,
    TemplateParameter,
    ParameterType,
)
from gaphor.ui.templatebrowser.storage import (
    TemplateStorage,
    TemplateStorageError,
    StorageLockError,
    StorageCorruptionError,
    AtomicFileWriter,
    FileLock,
    IndexEntry,
    TemplateIndex,
)
from gaphor.ui.templatebrowser.validation import (
    TemplateValidator,
    ValidationResult,
    ValidationIssue,
    ValidationSeverity,
    validate_parameter_values,
)

__all__ = [
    # Main UI
    "TemplateBrowser",
    # Data classes
    "DiagramTemplate",
    "TemplateCategory",
    "TemplateParameter",
    "ParameterType",
    # Storage
    "TemplateStorage",
    "TemplateStorageError",
    "StorageLockError",
    "StorageCorruptionError",
    "AtomicFileWriter",
    "FileLock",
    "IndexEntry",
    "TemplateIndex",
    # Validation
    "TemplateValidator",
    "ValidationResult",
    "ValidationIssue",
    "ValidationSeverity",
    "validate_parameter_values",
]
