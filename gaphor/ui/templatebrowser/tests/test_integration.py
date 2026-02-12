"""Integration tests for the template browser system."""

import pytest
from pathlib import Path

from gaphor.ui.templatebrowser.template import (
    DiagramTemplate,
    TemplateCategory,
    TemplateParameter,
    ParameterType,
)
from gaphor.ui.templatebrowser.validation import TemplateValidator, validate_parameter_values
from gaphor.ui.templatebrowser.storage import TemplateStorage


@pytest.fixture
def storage(tmp_path):
    return TemplateStorage(tmp_path / "templates")


@pytest.fixture
def validator():
    return TemplateValidator()


class TestTemplateWorkflow:
    """Test the complete workflow of creating, validating, storing, and using templates."""

    def test_create_validate_save_use_template(self, storage, validator):
        # Create a parameterized template
        template = DiagramTemplate.create_new(
            name="Class Diagram Template",
            description="A template for creating class diagrams with configurable name",
            category_id="uml",
            content="""<?xml version="1.0" encoding="utf-8"?>
<gaphor xmlns="http://gaphor.sourceforge.net/model" version="3.0">
<StyleSheet id="style-1">
<styleSheet><val>diagram { }</val></styleSheet>
</StyleSheet>
<Package id="pkg-1">
<name><val>${package_name}</val></name>
</Package>
<Class id="class-1">
<name><val>${class_name}</val></name>
</Class>
<Diagram id="diagram-1">
<name><val>${diagram_name}</val></name>
</Diagram>
</gaphor>""",
            modeling_language="UML",
        )

        # Extract and define parameters
        template.parameters = template.extract_parameters()
        assert len(template.parameters) == 3
        
        param_names = {p.name for p in template.parameters}
        assert "package_name" in param_names
        assert "class_name" in param_names
        assert "diagram_name" in param_names

        # Add defaults
        for param in template.parameters:
            if param.name == "package_name":
                param.default_value = "MyPackage"
            elif param.name == "class_name":
                param.default_value = "MyClass"
            elif param.name == "diagram_name":
                param.default_value = "Class Diagram"

        template.tags = ["class", "uml", "starter"]

        # Validate the template
        result = validator.validate(template)
        assert result.is_valid, f"Validation failed: {[e.message for e in result.errors]}"

        # Save the template
        storage.save_template(template)

        # Load it back
        loaded = storage.get_template(template.id)
        assert loaded is not None
        assert loaded.name == template.name
        assert len(loaded.parameters) == 3

        # Search for it
        results = storage.search_templates("class")
        assert len(results) == 1
        assert results[0].id == template.id

        # Apply parameters
        values = {
            "package_name": "CustomerService",
            "class_name": "Customer",
            "diagram_name": "Customer Class Diagram",
        }
        
        # Validate parameter values
        param_result = validate_parameter_values(loaded, values)
        assert param_result.is_valid

        # Apply parameters to content
        applied = loaded.apply_parameters(values)
        assert "CustomerService" in applied
        assert "Customer" in applied
        assert "Customer Class Diagram" in applied

    def test_category_management(self, storage):
        # Create a custom category
        category = TemplateCategory(
            id="design-patterns",
            name="Design Patterns",
            description="Common design pattern templates",
            icon="emblem-symbolic",
        )
        storage.save_category(category)

        # Verify it was saved
        categories = storage.list_categories()
        found = next((c for c in categories if c.id == "design-patterns"), None)
        assert found is not None
        assert found.name == "Design Patterns"

        # Create templates in the category
        template1 = DiagramTemplate.create_new(
            name="Singleton Pattern",
            description="Thread-safe singleton implementation",
            category_id="design-patterns",
            content="<gaphor><StyleSheet id='1'/></gaphor>",
        )
        template2 = DiagramTemplate.create_new(
            name="Factory Pattern",
            description="Abstract factory implementation",
            category_id="design-patterns",
            content="<gaphor><StyleSheet id='1'/></gaphor>",
        )
        storage.save_template(template1)
        storage.save_template(template2)

        # Verify templates are in category
        templates = list(storage.list_templates(category_id="design-patterns"))
        assert len(templates) == 2

        # Delete category and verify templates are removed
        storage.delete_category("design-patterns")
        templates = list(storage.list_templates(category_id="design-patterns"))
        assert len(templates) == 0

    def test_template_with_choice_parameters(self, storage, validator):
        template = DiagramTemplate.create_new(
            name="Visibility Template",
            description="Template with visibility choice",
            category_id="uml",
            content="<gaphor><StyleSheet id='1'/><visibility>${visibility}</visibility></gaphor>",
        )
        template.parameters = [
            TemplateParameter(
                name="visibility",
                param_type=ParameterType.CHOICE,
                choices=["public", "private", "protected", "package"],
                default_value="public",
            )
        ]

        # Validate
        result = validator.validate(template)
        assert result.is_valid

        # Save and load
        storage.save_template(template)
        loaded = storage.get_template(template.id)
        
        assert loaded.parameters[0].param_type == ParameterType.CHOICE
        assert loaded.parameters[0].choices == ["public", "private", "protected", "package"]

        # Apply valid value
        applied = loaded.apply_parameters({"visibility": "private"})
        assert "<visibility>private</visibility>" in applied

        # Validate invalid choice
        param_result = validate_parameter_values(loaded, {"visibility": "invalid"})
        assert not param_result.is_valid

    def test_template_import_export(self, storage, tmp_path):
        # Create and save a template
        original = DiagramTemplate.create_new(
            name="Export Test",
            description="Template for export testing",
            category_id="custom",
            content="<gaphor><StyleSheet id='1'/></gaphor>",
        )
        original.tags = ["test", "export"]
        storage.save_template(original)

        # Export as gaphor-template
        export_path = tmp_path / "exported.gaphor-template"
        storage.export_template(original.id, export_path)
        assert export_path.exists()

        # Create new storage and import
        new_storage = TemplateStorage(tmp_path / "new_templates")
        imported = new_storage.import_template(export_path)
        
        assert imported.name == original.name
        assert imported.description == original.description
        assert imported.tags == original.tags

    def test_search_and_filter(self, storage):
        # Create templates with different properties
        templates = [
            DiagramTemplate.create_new(
                name="UML Class Diagram",
                description="Standard class diagram",
                category_id="uml",
                content="<gaphor><StyleSheet id='1'/></gaphor>",
                modeling_language="UML",
            ),
            DiagramTemplate.create_new(
                name="SysML Block Diagram",
                description="Block definition diagram",
                category_id="sysml",
                content="<gaphor><StyleSheet id='1'/></gaphor>",
                modeling_language="SysML",
            ),
            DiagramTemplate.create_new(
                name="UML Sequence Diagram",
                description="Sequence diagram for interactions",
                category_id="uml",
                content="<gaphor><StyleSheet id='1'/></gaphor>",
                modeling_language="UML",
            ),
        ]
        
        templates[0].tags = ["class", "structure"]
        templates[1].tags = ["block", "structure"]
        templates[2].tags = ["sequence", "behavior"]

        for t in templates:
            storage.save_template(t)

        # Search by name
        results = storage.search_templates("class")
        assert len(results) == 1
        assert results[0].name == "UML Class Diagram"

        # Search by tag
        results = storage.search_templates("structure")
        assert len(results) == 2

        # Filter by category
        uml_templates = list(storage.list_templates(category_id="uml"))
        assert len(uml_templates) == 2

        # Filter by language
        sysml_templates = list(storage.list_templates(modeling_language="SysML"))
        assert len(sysml_templates) == 1
        assert sysml_templates[0].name == "SysML Block Diagram"

        # Combined search and filter
        results = storage.search_templates("diagram", category_id="uml")
        assert len(results) == 2
