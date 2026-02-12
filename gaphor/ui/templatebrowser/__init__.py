"""Template browser for creating and managing reusable diagram templates.

This module provides:
- DiagramTemplate: Data structure for templates with parameterized placeholders
- TemplateCategory: Categories for organizing templates
- TemplateParameter: Parameter definitions with validation
- TemplateStorage: Persistent storage with atomic writes and search indexing
- TemplateValidator: Validation for template content and parameters
- TemplateBrowser: GTK UI for browsing and using templates
"""

from gaphor.ui.templatebrowser.template import (
    DiagramTemplate,
    TemplateCategory,
    TemplateParameter,
    ParameterType,
)
from gaphor.ui.templatebrowser.storage import (
    TemplateStorage,
    TemplateStorageError,
    SearchIndex,
    atomic_write,
    atomic_write_bytes,
)
from gaphor.ui.templatebrowser.validation import (
    TemplateValidator,
    ValidationResult,
    ValidationIssue,
    ValidationSeverity,
    validate_parameter_values,
)
from gaphor.ui.templatebrowser.templatebrowser import TemplateBrowser

__all__ = [
    # Template data structures
    "DiagramTemplate",
    "TemplateCategory",
    "TemplateParameter",
    "ParameterType",
    # Storage
    "TemplateStorage",
    "TemplateStorageError",
    "SearchIndex",
    "atomic_write",
    "atomic_write_bytes",
    # Validation
    "TemplateValidator",
    "ValidationResult",
    "ValidationIssue",
    "ValidationSeverity",
    "validate_parameter_values",
    # UI
    "TemplateBrowser",
]
