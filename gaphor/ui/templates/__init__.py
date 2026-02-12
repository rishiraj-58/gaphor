"""Template system for Gaphor.

This module provides a template system that allows users to create,
manage, and reuse diagram templates with parametrized placeholders.
"""

from gaphor.ui.templates.template_model import (
    DiagramTemplate,
    TemplateCategory,
    TemplateParameter,
    TemplateParameterType,
    TemplateValidationError,
    TemplateValidationResult,
)
from gaphor.ui.templates.template_service import TemplateService
from gaphor.ui.templates.template_browser import TemplateBrowser

__all__ = [
    "DiagramTemplate",
    "TemplateCategory",
    "TemplateParameter",
    "TemplateParameterType",
    "TemplateValidationError",
    "TemplateValidationResult",
    "TemplateService",
    "TemplateBrowser",
]
