"""Tests for template validation."""

import pytest

from gaphor.ui.templatebrowser.template import (
    DiagramTemplate,
    TemplateParameter,
    ParameterType,
)
from gaphor.ui.templatebrowser.validation import (
    TemplateValidator,
    ValidationResult,
    ValidationSeverity,
    validate_parameter_values,
)


class TestValidationResult:
    def test_initial_state(self):
        result = ValidationResult(is_valid=True)
        assert result.is_valid
        assert len(result.issues) == 0

    def test_add_error_invalidates(self):
        result = ValidationResult(is_valid=True)
        result.add_error("Something went wrong")
        assert not result.is_valid
        assert len(result.errors) == 1

    def test_add_warning_keeps_valid(self):
        result = ValidationResult(is_valid=True)
        result.add_warning("This is a warning")
        assert result.is_valid
        assert len(result.warnings) == 1

    def test_merge_results(self):
        result1 = ValidationResult(is_valid=True)
        result1.add_warning("Warning 1")

        result2 = ValidationResult(is_valid=True)
        result2.add_error("Error 1")

        result1.merge(result2)
        assert not result1.is_valid
        assert len(result1.warnings) == 1
        assert len(result1.errors) == 1


class TestTemplateValidator:
    @pytest.fixture
    def validator(self):
        return TemplateValidator()

    @pytest.fixture
    def valid_template(self):
        return DiagramTemplate.create_new(
            name="Valid Template",
            description="A valid template description",
            category_id="uml",
            content="""<?xml version="1.0"?>
<gaphor xmlns="http://gaphor.sourceforge.net/model">
<StyleSheet id="test-1"/>
<Diagram id="test-2"/>
</gaphor>""",
            modeling_language="UML",
        )

    def test_validate_valid_template(self, validator, valid_template):
        result = validator.validate(valid_template)
        assert result.is_valid
        assert len(result.errors) == 0

    def test_validate_missing_name(self, validator):
        template = DiagramTemplate.create_new(
            name="",
            description="Description",
            category_id="uml",
            content="<gaphor><StyleSheet id='1'/></gaphor>",
        )
        result = validator.validate(template)
        assert not result.is_valid
        assert any("name" in e.field for e in result.errors if e.field)

    def test_validate_missing_content(self, validator):
        template = DiagramTemplate.create_new(
            name="Test",
            description="Description",
            category_id="uml",
            content="",
        )
        result = validator.validate(template)
        assert not result.is_valid
        assert any("content" in e.field for e in result.errors if e.field)

    def test_validate_missing_category(self, validator):
        template = DiagramTemplate.create_new(
            name="Test",
            description="Description",
            category_id="",
            content="<gaphor><StyleSheet id='1'/></gaphor>",
        )
        result = validator.validate(template)
        assert not result.is_valid

    def test_validate_invalid_xml_content(self, validator):
        template = DiagramTemplate.create_new(
            name="Test",
            description="Description",
            category_id="uml",
            content="not xml content at all",
        )
        result = validator.validate(template)
        assert not result.is_valid

    def test_validate_missing_description_warning(self, validator):
        template = DiagramTemplate.create_new(
            name="Test",
            description="",
            category_id="uml",
            content="<gaphor><StyleSheet id='1'/></gaphor>",
        )
        result = validator.validate(template)
        assert any("description" in w.field for w in result.warnings if w.field)

    def test_validate_undefined_placeholder(self, validator):
        template = DiagramTemplate.create_new(
            name="Test",
            description="Description",
            category_id="uml",
            content="<gaphor><name>${undefined_param}</name><StyleSheet id='1'/></gaphor>",
        )
        result = validator.validate(template)
        assert any("undefined_param" in w.message for w in result.warnings)

    def test_validate_unused_parameter(self, validator):
        template = DiagramTemplate.create_new(
            name="Test",
            description="Description",
            category_id="uml",
            content="<gaphor><StyleSheet id='1'/></gaphor>",
        )
        template.parameters = [
            TemplateParameter(name="unused", param_type=ParameterType.STRING)
        ]
        result = validator.validate(template)
        assert any("unused" in i.message for i in result.infos)

    def test_validate_duplicate_parameter_names(self, validator):
        template = DiagramTemplate.create_new(
            name="Test",
            description="Description",
            category_id="uml",
            content="<gaphor><StyleSheet id='1'/>${name}</gaphor>",
        )
        template.parameters = [
            TemplateParameter(name="name", param_type=ParameterType.STRING),
            TemplateParameter(name="name", param_type=ParameterType.STRING),
        ]
        result = validator.validate(template)
        assert not result.is_valid
        assert any("duplicate" in e.message.lower() for e in result.errors)

    def test_validate_invalid_parameter_name(self, validator):
        template = DiagramTemplate.create_new(
            name="Test",
            description="Description",
            category_id="uml",
            content="<gaphor><StyleSheet id='1'/></gaphor>",
        )
        template.parameters = [
            TemplateParameter(name="123invalid", param_type=ParameterType.STRING)
        ]
        result = validator.validate(template)
        assert not result.is_valid

    def test_validate_choice_without_choices(self, validator):
        template = DiagramTemplate.create_new(
            name="Test",
            description="Description",
            category_id="uml",
            content="<gaphor><StyleSheet id='1'/></gaphor>",
        )
        template.parameters = [
            TemplateParameter(name="choice_param", param_type=ParameterType.CHOICE, choices=[])
        ]
        result = validator.validate(template)
        assert not result.is_valid

    def test_validate_required_elements(self, validator):
        template = DiagramTemplate.create_new(
            name="Test",
            description="Description",
            category_id="uml",
            content="<gaphor><StyleSheet id='1'/></gaphor>",
        )
        template.required_elements = ["Class", "Package"]
        result = validator.validate(template)
        assert not result.is_valid
        assert any("Class" in e.message for e in result.errors)

    def test_custom_validator(self, validator):
        def my_custom_validator(template):
            result = ValidationResult(is_valid=True)
            if "forbidden" in template.name.lower():
                result.add_error("Template name contains forbidden word")
            return result

        validator.register_validator(my_custom_validator)

        template = DiagramTemplate.create_new(
            name="Forbidden Template",
            description="Description",
            category_id="uml",
            content="<gaphor><StyleSheet id='1'/></gaphor>",
        )
        result = validator.validate(template)
        assert not result.is_valid
        assert any("forbidden" in e.message.lower() for e in result.errors)


class TestValidateParameterValues:
    def test_validate_required_missing(self):
        template = DiagramTemplate.create_new(
            name="Test",
            description="",
            category_id="uml",
            content="",
        )
        template.parameters = [
            TemplateParameter(name="required_param", param_type=ParameterType.STRING, required=True)
        ]
        result = validate_parameter_values(template, {})
        assert not result.is_valid

    def test_validate_all_provided(self):
        template = DiagramTemplate.create_new(
            name="Test",
            description="",
            category_id="uml",
            content="",
        )
        template.parameters = [
            TemplateParameter(name="param1", param_type=ParameterType.STRING, required=True),
            TemplateParameter(name="param2", param_type=ParameterType.INTEGER, required=False),
        ]
        result = validate_parameter_values(template, {"param1": "value", "param2": "42"})
        assert result.is_valid

    def test_validate_invalid_type(self):
        template = DiagramTemplate.create_new(
            name="Test",
            description="",
            category_id="uml",
            content="",
        )
        template.parameters = [
            TemplateParameter(name="count", param_type=ParameterType.INTEGER, required=True)
        ]
        result = validate_parameter_values(template, {"count": "not_a_number"})
        assert not result.is_valid
