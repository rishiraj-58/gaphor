"""Template data model for Gaphor diagram templates.

This module defines the data structures for storing and validating
diagram templates with parametrized placeholders.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path
from typing import Any, TypedDict

log = logging.getLogger(__name__)

# Maximum allowed sizes for various fields to prevent memory issues
MAX_NAME_LENGTH = 256
MAX_DESCRIPTION_LENGTH = 4096
MAX_TEMPLATE_DATA_SIZE = 10 * 1024 * 1024  # 10MB
MAX_PARAMETERS = 100
MAX_PARAMETER_NAME_LENGTH = 128
MAX_PARAMETER_DEFAULT_LENGTH = 1024
MAX_TAGS = 50
MAX_TAG_LENGTH = 64
MAX_THUMBNAIL_SIZE = 512 * 1024  # 512KB

# Pattern for valid parameter placeholder names
PARAMETER_NAME_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
# Pattern for finding placeholders in template data: ${param_name} or {{param_name}}
PLACEHOLDER_PATTERN = re.compile(r"\$\{([a-zA-Z_][a-zA-Z0-9_]*)\}|\{\{([a-zA-Z_][a-zA-Z0-9_]*)\}\}")


class TemplateParameterType(Enum):
    """Types of parameters that can be used in templates."""

    STRING = auto()
    INTEGER = auto()
    FLOAT = auto()
    BOOLEAN = auto()
    CHOICE = auto()
    ELEMENT_NAME = auto()  # Special type for naming UML elements


class TemplateCategory(Enum):
    """Built-in categories for organizing templates."""

    GENERAL = "general"
    CLASS_DIAGRAM = "class_diagram"
    SEQUENCE_DIAGRAM = "sequence_diagram"
    USE_CASE = "use_case"
    ACTIVITY = "activity"
    STATE_MACHINE = "state_machine"
    COMPONENT = "component"
    DEPLOYMENT = "deployment"
    PACKAGE = "package"
    COMPOSITE = "composite"
    COMMUNICATION = "communication"
    TIMING = "timing"
    PROFILE = "profile"
    SYSML = "sysml"
    C4_MODEL = "c4_model"
    RAAML = "raaml"
    CUSTOM = "custom"

    @classmethod
    def from_string(cls, value: str) -> TemplateCategory:
        """Safely convert a string to TemplateCategory with fallback."""
        if not value:
            return cls.GENERAL
        try:
            normalized = value.strip().lower()
            for member in cls:
                if member.value == normalized:
                    return member
            return cls.CUSTOM
        except (ValueError, AttributeError):
            log.warning(f"Unknown template category: {value}, using CUSTOM")
            return cls.CUSTOM


class TemplateValidationError(Enum):
    """Types of validation errors for templates."""

    MISSING_ID = "missing_id"
    INVALID_ID = "invalid_id"
    MISSING_NAME = "missing_name"
    NAME_TOO_LONG = "name_too_long"
    DESCRIPTION_TOO_LONG = "description_too_long"
    MISSING_TEMPLATE_DATA = "missing_template_data"
    TEMPLATE_DATA_TOO_LARGE = "template_data_too_large"
    INVALID_TEMPLATE_DATA = "invalid_template_data"
    INVALID_PARAMETER_NAME = "invalid_parameter_name"
    PARAMETER_NAME_TOO_LONG = "parameter_name_too_long"
    DUPLICATE_PARAMETER = "duplicate_parameter"
    TOO_MANY_PARAMETERS = "too_many_parameters"
    MISSING_REQUIRED_PARAMETER = "missing_required_parameter"
    INVALID_PARAMETER_TYPE = "invalid_parameter_type"
    INVALID_PARAMETER_DEFAULT = "invalid_parameter_default"
    PARAMETER_DEFAULT_TOO_LONG = "parameter_default_too_long"
    UNDEFINED_PLACEHOLDER = "undefined_placeholder"
    UNUSED_PARAMETER = "unused_parameter"
    INVALID_CATEGORY = "invalid_category"
    TOO_MANY_TAGS = "too_many_tags"
    TAG_TOO_LONG = "tag_too_long"
    THUMBNAIL_TOO_LARGE = "thumbnail_too_large"
    INVALID_THUMBNAIL_FORMAT = "invalid_thumbnail_format"
    MISSING_MODELING_LANGUAGE = "missing_modeling_language"
    INVALID_VERSION = "invalid_version"
    CORRUPTED_DATA = "corrupted_data"


@dataclass(frozen=True)
class TemplateValidationResult:
    """Result of template validation."""

    is_valid: bool
    errors: tuple[tuple[TemplateValidationError, str], ...] = field(default_factory=tuple)
    warnings: tuple[tuple[TemplateValidationError, str], ...] = field(default_factory=tuple)

    def __bool__(self) -> bool:
        return self.is_valid

    @classmethod
    def success(cls, warnings: list[tuple[TemplateValidationError, str]] | None = None) -> TemplateValidationResult:
        return cls(is_valid=True, warnings=tuple(warnings or []))

    @classmethod
    def failure(
        cls,
        errors: list[tuple[TemplateValidationError, str]],
        warnings: list[tuple[TemplateValidationError, str]] | None = None,
    ) -> TemplateValidationResult:
        return cls(is_valid=False, errors=tuple(errors), warnings=tuple(warnings or []))


class ParameterChoiceDict(TypedDict, total=False):
    """Type definition for parameter choice options."""

    value: str
    label: str


@dataclass
class TemplateParameter:
    """A parameter that can be used to customize a template."""

    name: str
    param_type: TemplateParameterType = TemplateParameterType.STRING
    label: str = ""
    description: str = ""
    default_value: str = ""
    required: bool = False
    choices: list[ParameterChoiceDict] = field(default_factory=list)
    validation_pattern: str = ""
    min_value: float | None = None
    max_value: float | None = None

    def __post_init__(self):
        if not self.label:
            self.label = self.name.replace("_", " ").title()

    def validate_value(self, value: str | None) -> tuple[bool, str]:
        """Validate a value against this parameter's constraints."""
        if value is None or value == "":
            if self.required:
                return False, f"Parameter '{self.name}' is required"
            return True, ""

        try:
            if self.param_type == TemplateParameterType.INTEGER:
                int_val = int(value)
                if self.min_value is not None and int_val < self.min_value:
                    return False, f"Value must be >= {self.min_value}"
                if self.max_value is not None and int_val > self.max_value:
                    return False, f"Value must be <= {self.max_value}"

            elif self.param_type == TemplateParameterType.FLOAT:
                float_val = float(value)
                if self.min_value is not None and float_val < self.min_value:
                    return False, f"Value must be >= {self.min_value}"
                if self.max_value is not None and float_val > self.max_value:
                    return False, f"Value must be <= {self.max_value}"

            elif self.param_type == TemplateParameterType.BOOLEAN:
                if value.lower() not in ("true", "false", "1", "0", "yes", "no"):
                    return False, "Value must be a boolean"

            elif self.param_type == TemplateParameterType.CHOICE:
                valid_values = [c.get("value", "") for c in self.choices]
                if value not in valid_values:
                    return False, f"Value must be one of: {', '.join(valid_values)}"

            if self.validation_pattern:
                pattern = re.compile(self.validation_pattern)
                if not pattern.match(value):
                    return False, f"Value does not match pattern: {self.validation_pattern}"

        except (ValueError, TypeError) as e:
            return False, f"Invalid value: {e}"

        return True, ""

    def to_dict(self) -> dict[str, Any]:
        """Convert parameter to dictionary for serialization."""
        return {
            "name": self.name,
            "param_type": self.param_type.name,
            "label": self.label,
            "description": self.description,
            "default_value": self.default_value,
            "required": self.required,
            "choices": self.choices,
            "validation_pattern": self.validation_pattern,
            "min_value": self.min_value,
            "max_value": self.max_value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TemplateParameter | None:
        """Create parameter from dictionary with defensive validation."""
        if not isinstance(data, dict):
            log.warning("Parameter data is not a dictionary")
            return None

        name = data.get("name")
        if not name or not isinstance(name, str):
            log.warning("Parameter missing valid name")
            return None

        try:
            param_type_str = data.get("param_type", "STRING")
            if isinstance(param_type_str, str):
                param_type = TemplateParameterType[param_type_str.upper()]
            else:
                param_type = TemplateParameterType.STRING
        except (KeyError, ValueError):
            param_type = TemplateParameterType.STRING

        choices_data = data.get("choices", [])
        if not isinstance(choices_data, list):
            choices_data = []

        min_val = data.get("min_value")
        max_val = data.get("max_value")

        return cls(
            name=str(name)[:MAX_PARAMETER_NAME_LENGTH],
            param_type=param_type,
            label=str(data.get("label", ""))[:MAX_PARAMETER_NAME_LENGTH],
            description=str(data.get("description", ""))[:MAX_DESCRIPTION_LENGTH],
            default_value=str(data.get("default_value", ""))[:MAX_PARAMETER_DEFAULT_LENGTH],
            required=bool(data.get("required", False)),
            choices=[c for c in choices_data if isinstance(c, dict)][:20],
            validation_pattern=str(data.get("validation_pattern", ""))[:256],
            min_value=float(min_val) if min_val is not None else None,
            max_value=float(max_val) if max_val is not None else None,
        )


@dataclass
class DiagramTemplate:
    """A reusable diagram template with parametrized placeholders."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    category: TemplateCategory = TemplateCategory.GENERAL
    modeling_language: str = "UML"
    template_data: str = ""  # The serialized Gaphor model data
    parameters: list[TemplateParameter] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    thumbnail_data: bytes | None = None  # PNG thumbnail
    author: str = ""
    version: str = "1.0.0"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    is_builtin: bool = False
    source_file: Path | None = None

    def __post_init__(self):
        # Ensure timestamps are timezone-aware
        if self.created_at.tzinfo is None:
            self.created_at = self.created_at.replace(tzinfo=timezone.utc)
        if self.updated_at.tzinfo is None:
            self.updated_at = self.updated_at.replace(tzinfo=timezone.utc)

    @property
    def checksum(self) -> str:
        """Compute checksum of template data for integrity verification."""
        data = self.template_data.encode("utf-8") if self.template_data else b""
        return hashlib.sha256(data).hexdigest()[:16]

    def get_placeholders(self) -> set[str]:
        """Extract all placeholder names from the template data."""
        if not self.template_data:
            return set()

        placeholders = set()
        for match in PLACEHOLDER_PATTERN.finditer(self.template_data):
            # Match groups: group(1) is ${...}, group(2) is {{...}}
            name = match.group(1) or match.group(2)
            if name:
                placeholders.add(name)
        return placeholders

    def get_parameter_names(self) -> set[str]:
        """Get all defined parameter names."""
        return {p.name for p in self.parameters}

    def get_required_parameters(self) -> list[TemplateParameter]:
        """Get all required parameters."""
        return [p for p in self.parameters if p.required]

    def validate(self, strict: bool = False) -> TemplateValidationResult:
        """Validate the template structure and content."""
        errors: list[tuple[TemplateValidationError, str]] = []
        warnings: list[tuple[TemplateValidationError, str]] = []

        # Validate ID
        if not self.id:
            errors.append((TemplateValidationError.MISSING_ID, "Template ID is required"))
        elif not isinstance(self.id, str) or len(self.id) > 64:
            errors.append((TemplateValidationError.INVALID_ID, "Template ID must be a string <= 64 chars"))

        # Validate name
        if not self.name or not self.name.strip():
            errors.append((TemplateValidationError.MISSING_NAME, "Template name is required"))
        elif len(self.name) > MAX_NAME_LENGTH:
            errors.append(
                (TemplateValidationError.NAME_TOO_LONG, f"Name exceeds {MAX_NAME_LENGTH} characters")
            )

        # Validate description length
        if self.description and len(self.description) > MAX_DESCRIPTION_LENGTH:
            errors.append(
                (
                    TemplateValidationError.DESCRIPTION_TOO_LONG,
                    f"Description exceeds {MAX_DESCRIPTION_LENGTH} characters",
                )
            )

        # Validate template data
        if not self.template_data:
            errors.append(
                (TemplateValidationError.MISSING_TEMPLATE_DATA, "Template data is required")
            )
        elif len(self.template_data) > MAX_TEMPLATE_DATA_SIZE:
            errors.append(
                (
                    TemplateValidationError.TEMPLATE_DATA_TOO_LARGE,
                    f"Template data exceeds {MAX_TEMPLATE_DATA_SIZE // 1024 // 1024}MB",
                )
            )
        else:
            # Basic XML validation
            if not self.template_data.strip().startswith("<?xml") and not self.template_data.strip().startswith("<gaphor"):
                warnings.append(
                    (
                        TemplateValidationError.INVALID_TEMPLATE_DATA,
                        "Template data may not be valid Gaphor format",
                    )
                )

        # Validate parameters
        if len(self.parameters) > MAX_PARAMETERS:
            errors.append(
                (
                    TemplateValidationError.TOO_MANY_PARAMETERS,
                    f"Too many parameters (max {MAX_PARAMETERS})",
                )
            )

        seen_params: set[str] = set()
        for param in self.parameters:
            if not param.name:
                errors.append(
                    (TemplateValidationError.INVALID_PARAMETER_NAME, "Parameter name is empty")
                )
                continue

            if not PARAMETER_NAME_PATTERN.match(param.name):
                errors.append(
                    (
                        TemplateValidationError.INVALID_PARAMETER_NAME,
                        f"Invalid parameter name: {param.name}",
                    )
                )

            if len(param.name) > MAX_PARAMETER_NAME_LENGTH:
                errors.append(
                    (
                        TemplateValidationError.PARAMETER_NAME_TOO_LONG,
                        f"Parameter name too long: {param.name}",
                    )
                )

            if param.name in seen_params:
                errors.append(
                    (
                        TemplateValidationError.DUPLICATE_PARAMETER,
                        f"Duplicate parameter: {param.name}",
                    )
                )
            seen_params.add(param.name)

            if param.default_value and len(param.default_value) > MAX_PARAMETER_DEFAULT_LENGTH:
                errors.append(
                    (
                        TemplateValidationError.PARAMETER_DEFAULT_TOO_LONG,
                        f"Default value too long for: {param.name}",
                    )
                )

        # Cross-validate placeholders and parameters
        if self.template_data and strict:
            placeholders = self.get_placeholders()
            param_names = self.get_parameter_names()

            # Check for undefined placeholders
            undefined = placeholders - param_names
            for name in undefined:
                errors.append(
                    (
                        TemplateValidationError.UNDEFINED_PLACEHOLDER,
                        f"Placeholder '${{{name}}}' has no matching parameter",
                    )
                )

            # Check for unused parameters (warning only)
            unused = param_names - placeholders
            for name in unused:
                warnings.append(
                    (
                        TemplateValidationError.UNUSED_PARAMETER,
                        f"Parameter '{name}' is not used in template",
                    )
                )

        # Validate tags
        if len(self.tags) > MAX_TAGS:
            errors.append(
                (TemplateValidationError.TOO_MANY_TAGS, f"Too many tags (max {MAX_TAGS})")
            )
        for tag in self.tags:
            if len(tag) > MAX_TAG_LENGTH:
                errors.append(
                    (TemplateValidationError.TAG_TOO_LONG, f"Tag too long: {tag[:20]}...")
                )

        # Validate thumbnail
        if self.thumbnail_data:
            if len(self.thumbnail_data) > MAX_THUMBNAIL_SIZE:
                errors.append(
                    (
                        TemplateValidationError.THUMBNAIL_TOO_LARGE,
                        f"Thumbnail exceeds {MAX_THUMBNAIL_SIZE // 1024}KB",
                    )
                )
            # Check PNG magic bytes
            if not self.thumbnail_data.startswith(b"\x89PNG\r\n\x1a\n"):
                errors.append(
                    (
                        TemplateValidationError.INVALID_THUMBNAIL_FORMAT,
                        "Thumbnail must be PNG format",
                    )
                )

        # Validate modeling language
        if not self.modeling_language:
            warnings.append(
                (
                    TemplateValidationError.MISSING_MODELING_LANGUAGE,
                    "Modeling language not specified",
                )
            )

        if errors:
            return TemplateValidationResult.failure(errors, warnings)
        return TemplateValidationResult.success(warnings)

    def apply_parameters(self, values: dict[str, str]) -> tuple[str, list[str]]:
        """Apply parameter values to the template and return processed data.

        Returns:
            Tuple of (processed_template_data, list_of_errors)
        """
        errors: list[str] = []
        if not self.template_data:
            return "", ["No template data to process"]

        # Validate all provided values
        for param in self.parameters:
            value = values.get(param.name, param.default_value)
            is_valid, error_msg = param.validate_value(value)
            if not is_valid:
                errors.append(error_msg)

        if errors:
            return "", errors

        # Build substitution map with defaults for missing values
        substitutions: dict[str, str] = {}
        for param in self.parameters:
            value = values.get(param.name, param.default_value)
            substitutions[param.name] = value if value else ""

        # Perform substitution
        result = self.template_data
        for name, value in substitutions.items():
            # Replace both ${name} and {{name}} formats
            result = result.replace(f"${{{name}}}", value)
            result = result.replace(f"{{{{{name}}}}}", value)

        return result, []

    def to_dict(self) -> dict[str, Any]:
        """Serialize template to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category.value,
            "modeling_language": self.modeling_language,
            "template_data": self.template_data,
            "parameters": [p.to_dict() for p in self.parameters],
            "tags": self.tags,
            "thumbnail_data": self.thumbnail_data.hex() if self.thumbnail_data else None,
            "author": self.author,
            "version": self.version,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "is_builtin": self.is_builtin,
            "checksum": self.checksum,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DiagramTemplate | None:
        """Deserialize template from dictionary with defensive parsing."""
        if not isinstance(data, dict):
            log.error("Template data is not a dictionary")
            return None

        try:
            template_id = data.get("id")
            if not template_id:
                template_id = str(uuid.uuid4())

            name = data.get("name", "")
            if not name:
                log.warning("Template has no name")

            category = TemplateCategory.from_string(data.get("category", ""))

            # Parse parameters
            params_data = data.get("parameters", [])
            parameters = []
            if isinstance(params_data, list):
                for p_data in params_data[:MAX_PARAMETERS]:
                    param = TemplateParameter.from_dict(p_data)
                    if param:
                        parameters.append(param)

            # Parse tags
            tags_data = data.get("tags", [])
            tags = []
            if isinstance(tags_data, list):
                for tag in tags_data[:MAX_TAGS]:
                    if isinstance(tag, str):
                        tags.append(tag[:MAX_TAG_LENGTH])

            # Parse thumbnail
            thumbnail_data = None
            thumb_hex = data.get("thumbnail_data")
            if thumb_hex and isinstance(thumb_hex, str):
                try:
                    thumbnail_data = bytes.fromhex(thumb_hex)
                except ValueError:
                    log.warning("Invalid thumbnail hex data")

            # Parse timestamps
            created_at = datetime.now(timezone.utc)
            updated_at = datetime.now(timezone.utc)
            try:
                if created_str := data.get("created_at"):
                    created_at = datetime.fromisoformat(str(created_str))
                    if created_at.tzinfo is None:
                        created_at = created_at.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                pass
            try:
                if updated_str := data.get("updated_at"):
                    updated_at = datetime.fromisoformat(str(updated_str))
                    if updated_at.tzinfo is None:
                        updated_at = updated_at.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                pass

            template_data = data.get("template_data", "")
            if not isinstance(template_data, str):
                template_data = ""
            elif len(template_data) > MAX_TEMPLATE_DATA_SIZE:
                log.warning("Template data truncated due to size limit")
                template_data = template_data[:MAX_TEMPLATE_DATA_SIZE]

            return cls(
                id=str(template_id)[:64],
                name=str(name)[:MAX_NAME_LENGTH],
                description=str(data.get("description", ""))[:MAX_DESCRIPTION_LENGTH],
                category=category,
                modeling_language=str(data.get("modeling_language", "UML"))[:32],
                template_data=template_data,
                parameters=parameters,
                tags=tags,
                thumbnail_data=thumbnail_data,
                author=str(data.get("author", ""))[:128],
                version=str(data.get("version", "1.0.0"))[:32],
                created_at=created_at,
                updated_at=updated_at,
                is_builtin=bool(data.get("is_builtin", False)),
            )

        except Exception as e:
            log.error(f"Failed to parse template data: {e}")
            return None

    def to_json(self, indent: int = 2) -> str:
        """Serialize template to JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> DiagramTemplate | None:
        """Deserialize template from JSON string."""
        if not json_str:
            return None
        try:
            data = json.loads(json_str)
            return cls.from_dict(data)
        except json.JSONDecodeError as e:
            log.error(f"Invalid JSON: {e}")
            return None
