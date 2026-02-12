"""Tests for the template data structures."""

import pytest
from datetime import datetime

from gaphor.ui.templatebrowser.template import (
    DiagramTemplate,
    TemplateCategory,
    TemplateParameter,
    ParameterType,
)


class TestTemplateParameter:
    def test_create_string_parameter(self):
        param = TemplateParameter(
            name="class_name",
            param_type=ParameterType.STRING,
            description="Name of the class",
        )
        assert param.name == "class_name"
        assert param.param_type == ParameterType.STRING
        assert param.required is True
        assert param.placeholder_pattern == "${class_name}"

    def test_validate_required_string_parameter(self):
        param = TemplateParameter(
            name="name",
            param_type=ParameterType.STRING,
            required=True,
        )
        is_valid, msg = param.validate_value(None)
        assert not is_valid
        assert "required" in msg.lower()

        is_valid, msg = param.validate_value("")
        assert not is_valid

        is_valid, msg = param.validate_value("MyClass")
        assert is_valid

    def test_validate_optional_parameter(self):
        param = TemplateParameter(
            name="desc",
            param_type=ParameterType.STRING,
            required=False,
        )
        is_valid, msg = param.validate_value(None)
        assert is_valid

        is_valid, msg = param.validate_value("")
        assert is_valid

    def test_validate_integer_parameter(self):
        param = TemplateParameter(
            name="count",
            param_type=ParameterType.INTEGER,
        )
        is_valid, _ = param.validate_value(42)
        assert is_valid

        is_valid, _ = param.validate_value("42")
        assert is_valid

        is_valid, msg = param.validate_value("not_a_number")
        assert not is_valid
        assert "integer" in msg.lower()

    def test_validate_boolean_parameter(self):
        param = TemplateParameter(
            name="is_abstract",
            param_type=ParameterType.BOOLEAN,
        )
        is_valid, _ = param.validate_value(True)
        assert is_valid

        is_valid, _ = param.validate_value("true")
        assert is_valid

        is_valid, _ = param.validate_value("false")
        assert is_valid

    def test_validate_choice_parameter(self):
        param = TemplateParameter(
            name="visibility",
            param_type=ParameterType.CHOICE,
            choices=["public", "private", "protected"],
        )
        is_valid, _ = param.validate_value("public")
        assert is_valid

        is_valid, msg = param.validate_value("invalid")
        assert not is_valid
        assert "public" in msg


class TestTemplateCategory:
    def test_create_category(self):
        category = TemplateCategory(
            id="uml-class",
            name="UML Class Diagrams",
            description="Templates for UML class diagrams",
        )
        assert category.id == "uml-class"
        assert category.name == "UML Class Diagrams"
        assert category.parent_id is None

    def test_builtin_categories(self):
        categories = TemplateCategory.builtin_categories()
        assert len(categories) > 0

        category_ids = {c.id for c in categories}
        assert "uml" in category_ids
        assert "sysml" in category_ids
        assert "custom" in category_ids


class TestDiagramTemplate:
    def test_create_new_template(self):
        template = DiagramTemplate.create_new(
            name="Simple Class",
            description="A simple class template",
            category_id="uml",
            content="<gaphor>...</gaphor>",
        )
        assert template.name == "Simple Class"
        assert template.id is not None
        assert template.category_id == "uml"
        assert template.modeling_language == "UML"

    def test_extract_parameters_from_content(self):
        template = DiagramTemplate.create_new(
            name="Test",
            description="Test",
            category_id="uml",
            content='<name>${class_name}</name><desc>${description}</desc><name>${class_name}</name>',
        )
        params = template.extract_parameters()
        param_names = [p.name for p in params]

        assert "class_name" in param_names
        assert "description" in param_names
        assert len(param_names) == 2

    def test_apply_parameters(self):
        param = TemplateParameter(
            name="class_name",
            param_type=ParameterType.STRING,
        )
        template = DiagramTemplate.create_new(
            name="Test",
            description="Test",
            category_id="uml",
            content="<Class name='${class_name}'/>",
        )
        template.parameters = [param]

        result = template.apply_parameters({"class_name": "MyClass"})
        assert result == "<Class name='MyClass'/>"

    def test_apply_parameters_with_default(self):
        param = TemplateParameter(
            name="class_name",
            param_type=ParameterType.STRING,
            default_value="DefaultClass",
        )
        template = DiagramTemplate.create_new(
            name="Test",
            description="Test",
            category_id="uml",
            content="<Class name='${class_name}'/>",
        )
        template.parameters = [param]

        result = template.apply_parameters({})
        assert result == "<Class name='DefaultClass'/>"

    def test_matches_search(self):
        template = DiagramTemplate.create_new(
            name="Observer Pattern",
            description="Implementation of the Observer design pattern",
            category_id="patterns",
            content="<gaphor/>",
        )
        template.tags = ["design", "behavioral"]

        assert template.matches_search("observer")
        assert template.matches_search("pattern")
        assert template.matches_search("design behavioral")
        assert not template.matches_search("singleton")

    def test_to_dict_and_from_dict(self):
        original = DiagramTemplate.create_new(
            name="Test Template",
            description="A test",
            category_id="custom",
            content="<gaphor>content</gaphor>",
        )
        original.tags = ["test", "example"]
        original.parameters = [
            TemplateParameter(
                name="param1",
                param_type=ParameterType.STRING,
                default_value="default",
            )
        ]

        data = original.to_dict()
        restored = DiagramTemplate.from_dict(data)

        assert restored.id == original.id
        assert restored.name == original.name
        assert restored.description == original.description
        assert restored.tags == original.tags
        assert len(restored.parameters) == 1
        assert restored.parameters[0].name == "param1"
        assert restored.parameters[0].default_value == "default"

    def test_get_search_text(self):
        template = DiagramTemplate.create_new(
            name="MyTemplate",
            description="A description",
            category_id="uml",
            content="",
        )
        template.tags = ["tag1", "tag2"]

        search_text = template.get_search_text()
        assert "mytemplate" in search_text
        assert "description" in search_text
        assert "tag1" in search_text
        assert "tag2" in search_text
