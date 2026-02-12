"""Tests for template storage."""

import json
import pytest
from pathlib import Path

from gaphor.ui.templatebrowser.storage import TemplateStorage, TemplateStorageError
from gaphor.ui.templatebrowser.template import (
    DiagramTemplate,
    TemplateCategory,
    TemplateParameter,
    ParameterType,
)


@pytest.fixture
def storage_path(tmp_path):
    return tmp_path / "templates"


@pytest.fixture
def storage(storage_path):
    return TemplateStorage(storage_path)


@pytest.fixture
def sample_template():
    template = DiagramTemplate.create_new(
        name="Test Template",
        description="A test template",
        category_id="uml",
        content="<gaphor><StyleSheet id='1'/></gaphor>",
    )
    template.tags = ["test", "sample"]
    return template


class TestTemplateStorage:
    def test_storage_creates_directory(self, storage_path, storage):
        assert storage_path.exists()

    def test_list_categories_returns_builtins(self, storage):
        categories = storage.list_categories()
        assert len(categories) > 0
        assert any(c.id == "uml" for c in categories)

    def test_save_and_load_category(self, storage):
        category = TemplateCategory(
            id="my-category",
            name="My Category",
            description="Custom category",
        )
        storage.save_category(category)

        categories = storage.list_categories()
        loaded = next((c for c in categories if c.id == "my-category"), None)
        assert loaded is not None
        assert loaded.name == "My Category"

    def test_update_category(self, storage):
        category = TemplateCategory(id="update-me", name="Original Name")
        storage.save_category(category)

        category.name = "Updated Name"
        storage.save_category(category)

        categories = storage.list_categories()
        loaded = next(c for c in categories if c.id == "update-me")
        assert loaded.name == "Updated Name"

    def test_delete_category(self, storage, sample_template):
        category = TemplateCategory(id="delete-me", name="To Delete")
        storage.save_category(category)

        sample_template.category_id = "delete-me"
        storage.save_template(sample_template)

        storage.delete_category("delete-me")

        categories = storage.list_categories()
        assert not any(c.id == "delete-me" for c in categories)

        templates = list(storage.list_templates(category_id="delete-me"))
        assert len(templates) == 0

    def test_save_and_load_template(self, storage, sample_template):
        storage.save_template(sample_template)

        loaded = storage.get_template(sample_template.id)
        assert loaded is not None
        assert loaded.name == sample_template.name
        assert loaded.description == sample_template.description
        assert loaded.tags == sample_template.tags

    def test_list_templates(self, storage, sample_template):
        storage.save_template(sample_template)

        templates = list(storage.list_templates())
        assert len(templates) >= 1
        assert any(t.id == sample_template.id for t in templates)

    def test_list_templates_by_category(self, storage):
        template1 = DiagramTemplate.create_new(
            name="UML Template",
            description="",
            category_id="uml",
            content="<gaphor/>",
        )
        template2 = DiagramTemplate.create_new(
            name="SysML Template",
            description="",
            category_id="sysml",
            content="<gaphor/>",
        )
        storage.save_template(template1)
        storage.save_template(template2)

        uml_templates = list(storage.list_templates(category_id="uml"))
        assert len(uml_templates) == 1
        assert uml_templates[0].name == "UML Template"

    def test_list_templates_by_language(self, storage):
        template1 = DiagramTemplate.create_new(
            name="Template 1",
            description="",
            category_id="uml",
            content="<gaphor/>",
            modeling_language="UML",
        )
        template2 = DiagramTemplate.create_new(
            name="Template 2",
            description="",
            category_id="sysml",
            content="<gaphor/>",
            modeling_language="SysML",
        )
        storage.save_template(template1)
        storage.save_template(template2)

        uml_templates = list(storage.list_templates(modeling_language="UML"))
        assert all(t.modeling_language == "UML" for t in uml_templates)

    def test_delete_template(self, storage, sample_template):
        storage.save_template(sample_template)
        assert storage.get_template(sample_template.id) is not None

        storage.delete_template(sample_template.id)
        assert storage.get_template(sample_template.id) is None

    def test_search_templates(self, storage):
        template1 = DiagramTemplate.create_new(
            name="Observer Pattern",
            description="Implementation of observer pattern",
            category_id="patterns",
            content="<gaphor/>",
        )
        template1.tags = ["behavioral", "design"]

        template2 = DiagramTemplate.create_new(
            name="Factory Pattern",
            description="Implementation of factory pattern",
            category_id="patterns",
            content="<gaphor/>",
        )
        template2.tags = ["creational", "design"]

        storage.save_template(template1)
        storage.save_template(template2)

        results = storage.search_templates("observer")
        assert len(results) == 1
        assert results[0].name == "Observer Pattern"

        results = storage.search_templates("pattern")
        assert len(results) == 2

        results = storage.search_templates("behavioral")
        assert len(results) == 1

    def test_get_template_count(self, storage):
        initial_count = storage.get_template_count()

        template1 = DiagramTemplate.create_new("T1", "", "uml", "<gaphor/>")
        template2 = DiagramTemplate.create_new("T2", "", "sysml", "<gaphor/>")
        storage.save_template(template1)
        storage.save_template(template2)

        assert storage.get_template_count() == initial_count + 2
        assert storage.get_template_count("uml") == 1
        assert storage.get_template_count("sysml") == 1

    def test_save_template_with_parameters(self, storage):
        template = DiagramTemplate.create_new(
            name="Parameterized",
            description="",
            category_id="uml",
            content="<gaphor>${name}</gaphor>",
        )
        template.parameters = [
            TemplateParameter(
                name="name",
                param_type=ParameterType.STRING,
                default_value="MyClass",
            ),
            TemplateParameter(
                name="count",
                param_type=ParameterType.INTEGER,
                required=False,
            ),
        ]
        storage.save_template(template)

        loaded = storage.get_template(template.id)
        assert len(loaded.parameters) == 2
        assert loaded.parameters[0].name == "name"
        assert loaded.parameters[0].default_value == "MyClass"

    def test_import_from_gaphor_file(self, storage, tmp_path):
        gaphor_file = tmp_path / "test.gaphor"
        gaphor_file.write_text("<gaphor>imported content</gaphor>")

        template = storage.import_template(gaphor_file)
        assert template.name == "test"
        assert "imported content" in template.content
        assert template.category_id == "custom"

    def test_export_template(self, storage, sample_template, tmp_path):
        storage.save_template(sample_template)

        export_path = tmp_path / "exported.gaphor-template"
        storage.export_template(sample_template.id, export_path)

        assert export_path.exists()
        data = json.loads(export_path.read_text())
        assert data["name"] == sample_template.name

    def test_export_as_gaphor(self, storage, sample_template, tmp_path):
        storage.save_template(sample_template)

        export_path = tmp_path / "exported.gaphor"
        storage.export_template(sample_template.id, export_path)

        assert export_path.exists()
        content = export_path.read_text()
        assert sample_template.content == content

    def test_export_nonexistent_template(self, storage, tmp_path):
        with pytest.raises(TemplateStorageError):
            storage.export_template("nonexistent-id", tmp_path / "out.gaphor")

    def test_backup_and_restore(self, storage, sample_template, tmp_path):
        storage.save_template(sample_template)
        backup_path = tmp_path / "backup"

        storage.backup_storage(backup_path)
        assert backup_path.exists()

        storage.delete_template(sample_template.id)
        assert storage.get_template(sample_template.id) is None

        storage.restore_storage(backup_path)
        restored = storage.get_template(sample_template.id)
        assert restored is not None
        assert restored.name == sample_template.name


class TestTemplateStorageEdgeCases:
    def test_invalid_template_file_skipped(self, storage_path, storage):
        invalid_file = storage_path / "invalid.gaphor-template"
        invalid_file.write_text("not valid json{{{")

        templates = list(storage.list_templates())
        assert not any(t.name == "invalid" for t in templates)

    def test_missing_categories_file(self, storage_path):
        categories_file = storage_path / "categories.json"
        if categories_file.exists():
            categories_file.unlink()

        storage = TemplateStorage(storage_path)
        categories = storage.list_categories()
        assert len(categories) > 0

    def test_corrupted_categories_file(self, storage_path):
        storage_path.mkdir(parents=True, exist_ok=True)
        categories_file = storage_path / "categories.json"
        categories_file.write_text("invalid json")

        storage = TemplateStorage(storage_path)
        categories = storage.list_categories()
        assert len(categories) > 0

    def test_unsupported_import_format(self, storage, tmp_path):
        bad_file = tmp_path / "test.txt"
        bad_file.write_text("content")

        with pytest.raises(TemplateStorageError):
            storage.import_template(bad_file)

    def test_unsupported_export_format(self, storage, sample_template, tmp_path):
        storage.save_template(sample_template)

        with pytest.raises(TemplateStorageError):
            storage.export_template(sample_template.id, tmp_path / "out.txt")
