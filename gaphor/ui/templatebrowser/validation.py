"""Validation system for diagram templates."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, List, Optional

if TYPE_CHECKING:
    from gaphor.ui.templatebrowser.template import DiagramTemplate, TemplateParameter


class ValidationSeverity(Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class ValidationIssue:
    severity: ValidationSeverity
    message: str
    field: Optional[str] = None
    suggestion: Optional[str] = None


@dataclass
class ValidationResult:
    is_valid: bool
    issues: List[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == ValidationSeverity.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == ValidationSeverity.WARNING]

    @property
    def infos(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == ValidationSeverity.INFO]

    def add_error(self, message: str, field: Optional[str] = None, suggestion: Optional[str] = None):
        self.issues.append(ValidationIssue(ValidationSeverity.ERROR, message, field, suggestion))
        self.is_valid = False

    def add_warning(self, message: str, field: Optional[str] = None, suggestion: Optional[str] = None):
        self.issues.append(ValidationIssue(ValidationSeverity.WARNING, message, field, suggestion))

    def add_info(self, message: str, field: Optional[str] = None, suggestion: Optional[str] = None):
        self.issues.append(ValidationIssue(ValidationSeverity.INFO, message, field, suggestion))

    def merge(self, other: ValidationResult):
        self.issues.extend(other.issues)
        if not other.is_valid:
            self.is_valid = False


class TemplateValidator:
    REQUIRED_XML_ELEMENTS = ["gaphor", "StyleSheet"]
    SUPPORTED_MODELING_LANGUAGES = ["UML", "SysML", "C4Model", "RAAML"]

    def __init__(self):
        self._custom_validators: list[callable] = []

    def register_validator(self, validator: callable):
        self._custom_validators.append(validator)

    def validate(self, template: DiagramTemplate) -> ValidationResult:
        result = ValidationResult(is_valid=True)

        self._validate_metadata(template, result)
        self._validate_content(template, result)
        self._validate_parameters(template, result)
        self._validate_required_elements(template, result)

        for validator in self._custom_validators:
            custom_result = validator(template)
            if custom_result:
                result.merge(custom_result)

        return result

    def _validate_metadata(self, template: DiagramTemplate, result: ValidationResult):
        if not template.name or not template.name.strip():
            result.add_error("Template name is required", "name")

        if len(template.name) > 100:
            result.add_warning(
                "Template name is very long",
                "name",
                "Consider using a shorter name for better display"
            )

        if not template.description or not template.description.strip():
            result.add_warning(
                "Template description is empty",
                "description",
                "Add a description to help users understand the template's purpose"
            )

        if not template.category_id:
            result.add_error("Template must belong to a category", "category_id")

        if template.modeling_language not in self.SUPPORTED_MODELING_LANGUAGES:
            result.add_warning(
                f"Unknown modeling language: {template.modeling_language}",
                "modeling_language",
                f"Supported languages: {', '.join(self.SUPPORTED_MODELING_LANGUAGES)}"
            )

        if not template.id:
            result.add_error("Template ID is required", "id")

    def _validate_content(self, template: DiagramTemplate, result: ValidationResult):
        if not template.content or not template.content.strip():
            result.add_error("Template content is required", "content")
            return

        content = template.content.strip()

        if not content.startswith("<?xml") and not content.startswith("<gaphor"):
            result.add_error(
                "Template content must be valid Gaphor XML format",
                "content",
                "Content should start with XML declaration or <gaphor> element"
            )
            return

        for required_element in self.REQUIRED_XML_ELEMENTS:
            if f"<{required_element}" not in content:
                result.add_warning(
                    f"Template content may be missing required element: {required_element}",
                    "content"
                )

        if "<Diagram" not in content:
            result.add_warning(
                "Template does not contain any diagram definitions",
                "content",
                "Consider adding at least one diagram to the template"
            )

        self._validate_placeholders(template, result)

    def _validate_placeholders(self, template: DiagramTemplate, result: ValidationResult):
        pattern = r'\$\{([a-zA-Z_][a-zA-Z0-9_]*)\}'
        content_params = set(re.findall(pattern, template.content))
        defined_params = {p.name for p in template.parameters}

        undefined = content_params - defined_params
        for param_name in undefined:
            result.add_warning(
                f"Placeholder '${{{param_name}}}' is used but not defined as a parameter",
                "parameters",
                f"Add a parameter definition for '{param_name}'"
            )

        unused = defined_params - content_params
        for param_name in unused:
            result.add_info(
                f"Parameter '{param_name}' is defined but not used in the content",
                "parameters"
            )

    def _validate_parameters(self, template: DiagramTemplate, result: ValidationResult):
        seen_names: set[str] = set()
        for param in template.parameters:
            if param.name in seen_names:
                result.add_error(
                    f"Duplicate parameter name: {param.name}",
                    "parameters"
                )
            seen_names.add(param.name)

            if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', param.name):
                result.add_error(
                    f"Invalid parameter name: {param.name}",
                    "parameters",
                    "Parameter names must start with a letter or underscore"
                )

            from gaphor.ui.templatebrowser.template import ParameterType
            if param.param_type == ParameterType.CHOICE and not param.choices:
                result.add_error(
                    f"Parameter '{param.name}' is a choice type but has no choices defined",
                    "parameters"
                )

    def _validate_required_elements(self, template: DiagramTemplate, result: ValidationResult):
        for element_type in template.required_elements:
            element_pattern = f"<{element_type}"
            if element_pattern not in template.content:
                result.add_error(
                    f"Required element '{element_type}' not found in template content",
                    "required_elements"
                )


def validate_parameter_values(
    template: DiagramTemplate,
    values: dict
) -> ValidationResult:
    result = ValidationResult(is_valid=True)

    for param in template.parameters:
        value = values.get(param.name)
        is_valid, message = param.validate_value(value)
        if not is_valid:
            result.add_error(message, f"parameter.{param.name}")

    return result
