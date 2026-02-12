"""Tests for the template model classes."""

import json
import pytest
from datetime import datetime, timezone

from gaphor.ui.templates.template_model import (
    DiagramTemplate,
    TemplateCategory,
    TemplateParameter,
    TemplateParameterType,
    TemplateValidationError,
    TemplateValidationResult,
    MAX_NAME_LENGTH,
    MAX_DESCRIPTION_LENGTH,
    MAX_PARAMETERS,
    MAX_TEMPLATE_DATA_SIZE,
    PARAMETER_NAME_PATTERN,
)


class TestTemplateCategory:
    """Tests for TemplateCategory enum."""

    def test_from_string_valid_category(self):
        assert TemplateCategory.from_string("general") == TemplateCategory.GENERAL
        assert TemplateCategory.from_string("class_diagram") == TemplateCategory.CLASS_DIAGRAM
        assert TemplateCategory.from_string("sysml") == TemplateCategory.SYSML

    def test_from_string_case_insensitive(self):
        assert TemplateCategory.from_string("GENERAL") == TemplateCategory.CUSTOM
        assert TemplateCategory.from_string("General") == TemplateCategory.CUSTOM

    def test_from_string_empty_returns_general(self):
        assert TemplateCategory.from_string("") == TemplateCategory.GENERAL
        assert TemplateCategory.from_string(None) == TemplateCategory.GENERAL

    def test_from_string_unknown_returns_custom(self):
        assert TemplateCategory.from_string("unknown_category") == TemplateCategory.CUSTOM
        assert TemplateCategory.from_string("foobar") == TemplateCategory.CUSTOM


class TestTemplateParameter:
    """Tests for TemplateParameter class."""

    def test_basic_creation(self):
        param = TemplateParameter(name="test_param")
        assert param.name == "test_param"
        assert param.param_type == TemplateParameterType.STRING
        assert param.label == "Test Param"  # Auto-generated
        assert param.required is False

    def test_custom_label(self):
        param = TemplateParameter(name="my_param", label="My Custom Label")
        assert param.label == "My Custom Label"

    def test_validate_required_missing(self):
        param = TemplateParameter(name="test", required=True)
        is_valid, error = param.validate_value(None)
        assert not is_valid
        assert "required" in error.lower()

        is_valid, error = param.validate_value("")
        assert not is_valid

    def test_validate_required_present(self):
        param = TemplateParameter(name="test", required=True)
        is_valid, error = param.validate_value("some value")
        assert is_valid
        assert error == ""

    def test_validate_integer_type(self):
        param = TemplateParameter(
            name="count",
            param_type=TemplateParameterType.INTEGER,
            min_value=0,
            max_value=100,
        )

        is_valid, _ = param.validate_value("50")
        assert is_valid

        is_valid, error = param.validate_value("-10")
        assert not is_valid
        assert ">=" in error

        is_valid, error = param.validate_value("200")
        assert not is_valid
        assert "<=" in error

        is_valid, error = param.validate_value("not_a_number")
        assert not is_valid

    def test_validate_float_type(self):
        param = TemplateParameter(
            name="ratio",
            param_type=TemplateParameterType.FLOAT,
            min_value=0.0,
            max_value=1.0,
        )

        is_valid, _ = param.validate_value("0.5")
        assert is_valid

        is_valid, _ = param.validate_value("-0.1")
        assert not is_valid

    def test_validate_boolean_type(self):
        param = TemplateParameter(name="enabled", param_type=TemplateParameterType.BOOLEAN)

        for valid in ["true", "false", "True", "False", "1", "0", "yes", "no"]:
            is_valid, _ = param.validate_value(valid)
            assert is_valid, f"Expected '{valid}' to be valid"

        is_valid, _ = param.validate_value("maybe")
        assert not is_valid

    def test_validate_choice_type(self):
        param = TemplateParameter(
            name="visibility",
            param_type=TemplateParameterType.CHOICE,
            choices=[
                {"value": "public", "label": "Public"},
                {"value": "private", "label": "Private"},
            ],
        )

        is_valid, _ = param.validate_value("public")
        assert is_valid

        is_valid, error = param.validate_value("protected")
        assert not is_valid
        assert "public" in error and "private" in error

    def test_validate_pattern(self):
        param = TemplateParameter(
            name="class_name",
            validation_pattern=r"^[A-Z][a-zA-Z0-9]*$",
        )

        is_valid, _ = param.validate_value("MyClass")
        assert is_valid

        is_valid, _ = param.validate_value("myclass")
        assert not is_valid

    def test_to_dict_and_from_dict(self):
        param = TemplateParameter(
            name="test",
            param_type=TemplateParameterType.INTEGER,
            label="Test Label",
            description="A test parameter",
            default_value="42",
            required=True,
            min_value=0,
            max_value=100,
        )

        data = param.to_dict()
        restored = TemplateParameter.from_dict(data)

        assert restored is not None
        assert restored.name == param.name
        assert restored.param_type == param.param_type
        assert restored.label == param.label
        assert restored.default_value == param.default_value
        assert restored.required == param.required
        assert restored.min_value == param.min_value
        assert restored.max_value == param.max_value

    def test_from_dict_invalid_data(self):
        assert TemplateParameter.from_dict(None) is None
        assert TemplateParameter.from_dict("not a dict") is None
        assert TemplateParameter.from_dict({}) is None  # Missing name
        assert TemplateParameter.from_dict({"name": ""}) is None

    def test_from_dict_unknown_type_defaults_to_string(self):
        param = TemplateParameter.from_dict({
            "name": "test",
            "param_type": "UNKNOWN_TYPE",
        })
        assert param is not None
        assert param.param_type == TemplateParameterType.STRING


class TestDiagramTemplate:
    """Tests for DiagramTemplate class."""

    def test_basic_creation(self):
        template = DiagramTemplate(
            name="Test Template",
            template_data="<gaphor>...</gaphor>",
        )

        assert template.id is not None
        assert len(template.id) > 0
        assert template.name == "Test Template"
        assert template.category == TemplateCategory.GENERAL
        assert template.modeling_language == "UML"
        assert template.is_builtin is False

    def test_timestamps_are_timezone_aware(self):
        template = DiagramTemplate(name="Test")
        assert template.created_at.tzinfo is not None
        assert template.updated_at.tzinfo is not None

    def test_checksum(self):
        template1 = DiagramTemplate(
            name="Test",
            template_data="data1",
        )
        template2 = DiagramTemplate(
            name="Test",
            template_data="data1",
        )
        template3 = DiagramTemplate(
            name="Test",
            template_data="data2",
        )

        assert template1.checksum == template2.checksum
        assert template1.checksum != template3.checksum

    def test_get_placeholders(self):
        template = DiagramTemplate(
            name="Test",
            template_data="Class ${class_name} has attribute {{attr_name}} and ${class_name} again",
        )

        placeholders = template.get_placeholders()
        assert placeholders == {"class_name", "attr_name"}

    def test_get_placeholders_empty_template(self):
        template = DiagramTemplate(name="Test", template_data="")
        assert template.get_placeholders() == set()

    def test_apply_parameters(self):
        template = DiagramTemplate(
            name="Test",
            template_data="Class ${name} extends ${parent}",
            parameters=[
                TemplateParameter(name="name", default_value="MyClass"),
                TemplateParameter(name="parent", default_value="BaseClass"),
            ],
        )

        result, errors = template.apply_parameters({"name": "Customer"})
        assert not errors
        assert result == "Class Customer extends BaseClass"

    def test_apply_parameters_both_formats(self):
        template = DiagramTemplate(
            name="Test",
            template_data="Name: ${name}, Type: {{type}}",
            parameters=[
                TemplateParameter(name="name"),
                TemplateParameter(name="type"),
            ],
        )

        result, errors = template.apply_parameters({"name": "Test", "type": "Class"})
        assert not errors
        assert result == "Name: Test, Type: Class"

    def test_apply_parameters_validation_failure(self):
        template = DiagramTemplate(
            name="Test",
            template_data="${count}",
            parameters=[
                TemplateParameter(
                    name="count",
                    param_type=TemplateParameterType.INTEGER,
                    min_value=0,
                ),
            ],
        )

        result, errors = template.apply_parameters({"count": "-5"})
        assert errors
        assert result == ""


class TestDiagramTemplateValidation:
    """Tests for template validation."""

    def test_valid_template(self):
        template = DiagramTemplate(
            name="Valid Template",
            description="A valid template",
            template_data="<?xml version='1.0'?><gaphor></gaphor>",
            parameters=[
                TemplateParameter(name="param1"),
            ],
        )

        result = template.validate()
        assert result.is_valid
        assert len(result.errors) == 0

    def test_missing_name(self):
        template = DiagramTemplate(
            name="",
            template_data="<gaphor></gaphor>",
        )

        result = template.validate()
        assert not result.is_valid
        assert any(e[0] == TemplateValidationError.MISSING_NAME for e in result.errors)

    def test_name_too_long(self):
        template = DiagramTemplate(
            name="X" * (MAX_NAME_LENGTH + 1),
            template_data="<gaphor></gaphor>",
        )

        result = template.validate()
        assert not result.is_valid
        assert any(e[0] == TemplateValidationError.NAME_TOO_LONG for e in result.errors)

    def test_missing_template_data(self):
        template = DiagramTemplate(
            name="Test",
            template_data="",
        )

        result = template.validate()
        assert not result.is_valid
        assert any(
            e[0] == TemplateValidationError.MISSING_TEMPLATE_DATA for e in result.errors
        )

    def test_invalid_parameter_name(self):
        template = DiagramTemplate(
            name="Test",
            template_data="<gaphor></gaphor>",
            parameters=[
                TemplateParameter(name="123invalid"),  # Starts with digit
            ],
        )

        # Need to bypass __post_init__ validation
        template.parameters[0].name = "123invalid"

        result = template.validate()
        assert not result.is_valid
        assert any(
            e[0] == TemplateValidationError.INVALID_PARAMETER_NAME for e in result.errors
        )

    def test_duplicate_parameter(self):
        template = DiagramTemplate(
            name="Test",
            template_data="<gaphor></gaphor>",
            parameters=[
                TemplateParameter(name="param1"),
                TemplateParameter(name="param1"),  # Duplicate
            ],
        )

        result = template.validate()
        assert not result.is_valid
        assert any(
            e[0] == TemplateValidationError.DUPLICATE_PARAMETER for e in result.errors
        )

    def test_too_many_parameters(self):
        template = DiagramTemplate(
            name="Test",
            template_data="<gaphor></gaphor>",
            parameters=[
                TemplateParameter(name=f"param_{i}") for i in range(MAX_PARAMETERS + 1)
            ],
        )

        result = template.validate()
        assert not result.is_valid
        assert any(
            e[0] == TemplateValidationError.TOO_MANY_PARAMETERS for e in result.errors
        )

    def test_strict_validation_undefined_placeholder(self):
        template = DiagramTemplate(
            name="Test",
            template_data="${undefined_param}",
            parameters=[],  # No parameters defined
        )

        result = template.validate(strict=True)
        assert not result.is_valid
        assert any(
            e[0] == TemplateValidationError.UNDEFINED_PLACEHOLDER for e in result.errors
        )

    def test_strict_validation_unused_parameter_warning(self):
        template = DiagramTemplate(
            name="Test",
            template_data="<gaphor></gaphor>",  # No placeholders
            parameters=[
                TemplateParameter(name="unused_param"),
            ],
        )

        result = template.validate(strict=True)
        assert result.is_valid  # Unused parameters are warnings, not errors
        assert any(
            w[0] == TemplateValidationError.UNUSED_PARAMETER for w in result.warnings
        )

    def test_invalid_thumbnail_format(self):
        template = DiagramTemplate(
            name="Test",
            template_data="<gaphor></gaphor>",
            thumbnail_data=b"not a PNG",
        )

        result = template.validate()
        assert not result.is_valid
        assert any(
            e[0] == TemplateValidationError.INVALID_THUMBNAIL_FORMAT for e in result.errors
        )


class TestDiagramTemplateSerialization:
    """Tests for template serialization."""

    def test_to_dict(self):
        template = DiagramTemplate(
            id="test-id-123",
            name="Test Template",
            description="A test template",
            category=TemplateCategory.CLASS_DIAGRAM,
            modeling_language="UML",
            template_data="<gaphor></gaphor>",
            parameters=[
                TemplateParameter(name="param1", default_value="default"),
            ],
            tags=["test", "example"],
            author="Test Author",
            version="1.2.3",
        )

        data = template.to_dict()

        assert data["id"] == "test-id-123"
        assert data["name"] == "Test Template"
        assert data["category"] == "class_diagram"
        assert data["modeling_language"] == "UML"
        assert len(data["parameters"]) == 1
        assert data["tags"] == ["test", "example"]
        assert data["author"] == "Test Author"
        assert data["version"] == "1.2.3"
        assert "checksum" in data

    def test_from_dict(self):
        data = {
            "id": "test-id",
            "name": "Test",
            "description": "Description",
            "category": "class_diagram",
            "modeling_language": "SysML",
            "template_data": "<gaphor/>",
            "parameters": [
                {"name": "p1", "param_type": "STRING"},
            ],
            "tags": ["tag1"],
            "author": "Author",
            "version": "2.0.0",
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-02T00:00:00+00:00",
        }

        template = DiagramTemplate.from_dict(data)

        assert template is not None
        assert template.id == "test-id"
        assert template.name == "Test"
        assert template.category == TemplateCategory.CLASS_DIAGRAM
        assert template.modeling_language == "SysML"
        assert len(template.parameters) == 1
        assert template.parameters[0].name == "p1"

    def test_from_dict_missing_fields_uses_defaults(self):
        data = {
            "name": "Minimal",
            "template_data": "data",
        }

        template = DiagramTemplate.from_dict(data)

        assert template is not None
        assert template.id is not None  # Generated
        assert template.category == TemplateCategory.GENERAL
        assert template.modeling_language == "UML"
        assert template.parameters == []
        assert template.tags == []

    def test_from_dict_invalid_data(self):
        assert DiagramTemplate.from_dict(None) is None
        assert DiagramTemplate.from_dict("not a dict") is None
        assert DiagramTemplate.from_dict([]) is None

    def test_json_round_trip(self):
        original = DiagramTemplate(
            name="Test",
            description="Test description",
            category=TemplateCategory.SYSML,
            template_data="<gaphor>test</gaphor>",
            parameters=[
                TemplateParameter(
                    name="param1",
                    param_type=TemplateParameterType.INTEGER,
                    default_value="42",
                ),
            ],
            tags=["tag1", "tag2"],
        )

        json_str = original.to_json()
        restored = DiagramTemplate.from_json(json_str)

        assert restored is not None
        assert restored.name == original.name
        assert restored.description == original.description
        assert restored.category == original.category
        assert restored.template_data == original.template_data
        assert len(restored.parameters) == len(original.parameters)
        assert restored.parameters[0].name == original.parameters[0].name
        assert restored.tags == original.tags

    def test_from_json_invalid(self):
        assert DiagramTemplate.from_json("") is None
        assert DiagramTemplate.from_json("not json") is None
        assert DiagramTemplate.from_json("null") is None


class TestTemplateValidationResult:
    """Tests for TemplateValidationResult."""

    def test_success(self):
        result = TemplateValidationResult.success()
        assert result.is_valid
        assert bool(result) is True
        assert len(result.errors) == 0

    def test_success_with_warnings(self):
        warnings = [(TemplateValidationError.UNUSED_PARAMETER, "param not used")]
        result = TemplateValidationResult.success(warnings=warnings)
        assert result.is_valid
        assert len(result.warnings) == 1

    def test_failure(self):
        errors = [(TemplateValidationError.MISSING_NAME, "name required")]
        result = TemplateValidationResult.failure(errors)
        assert not result.is_valid
        assert bool(result) is False
        assert len(result.errors) == 1

    def test_immutable(self):
        result = TemplateValidationResult.success()
        with pytest.raises(AttributeError):
            result.is_valid = False


class TestParameterNamePattern:
    """Tests for parameter name validation pattern."""

    def test_valid_names(self):
        valid_names = [
            "param",
            "param1",
            "my_param",
            "_private",
            "CamelCase",
            "mixedCase123",
        ]
        for name in valid_names:
            assert PARAMETER_NAME_PATTERN.match(name), f"Expected '{name}' to be valid"

    def test_invalid_names(self):
        invalid_names = [
            "123start",  # Starts with digit
            "has-dash",  # Contains dash
            "has space",  # Contains space
            "has.dot",  # Contains dot
            "",  # Empty
        ]
        for name in invalid_names:
            assert not PARAMETER_NAME_PATTERN.match(name), f"Expected '{name}' to be invalid"
