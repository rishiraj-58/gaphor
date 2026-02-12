"""Template browser for creating and managing reusable diagram templates."""

from gaphor.ui.templatebrowser.templatebrowser import TemplateBrowser
from gaphor.ui.templatebrowser.template import (
    DiagramTemplate,
    TemplateCategory,
    TemplateParameter,
    ParameterType,
)
from gaphor.ui.templatebrowser.storage import TemplateStorage
from gaphor.ui.templatebrowser.validation import TemplateValidator, ValidationResult

__all__ = [
    "TemplateBrowser",
    "DiagramTemplate",
    "TemplateCategory",
    "TemplateParameter",
    "ParameterType",
    "TemplateStorage",
    "TemplateValidator",
    "ValidationResult",
]
