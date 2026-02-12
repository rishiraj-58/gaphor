"""Tests for template storage with atomic writes and search indexing."""

import json
import os
import pytest
from pathlib import Path

from gaphor.ui.templatebrowser.storage import (
    TemplateStorage,
    TemplateStorageError,
    SearchIndex,
    SearchIndexEntry,
    atomic_write,
    atomic_write_bytes,
)
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


class TestAtomicWrite:
    def test_atomic_write_creates_file(self, tmp_path):
        file_path = tmp_path / "test.txt"
        atomic_write(file_path, "hello world")
        
        assert file_path.exists()
        assert file_path.read_text() == "hello world"

    def test_atomic_write_overwrites_existing(self, tmp_path):
        file_path = tmp_path / "test.txt"
        file_path.write_text("old content")
        
        atomic_write(file_path, "new content")
        
        assert file_path.read_text() == "new content"

    def test_atomic_write_creates_parent_dirs(self, tmp_path):
        file_path = tmp_path / "nested" / "dir" / "test.txt"
        atomic_write(file_path, "content")
        
        assert file_path.exists()
        assert file_path.read_text() == "content"

    def test_atomic_write_no_temp_files_left(self, tmp_path):
        file_path = tmp_path / "test.txt"
        atomic_write(file_path, "content")
        
        files = list(tmp_path.iterdir())
        assert len(files) == 1
        assert files[0].name == "test.txt"

    def test_atomic_write_bytes(self, tmp_path):
        file_path = tmp_path / "test.bin"
        data = b'\x00\x01\x02\x03'
        atomic_write_bytes(file_path, data)
        
        assert file_path.exists()
        assert file_path.read_bytes() == data


class TestSearchIndex:
    def test_create_empty_index(self):
        index = SearchIndex()
        assert len(index.entries) == 0
        assert index.version == 1

    def test_add_entry(self, sample_template):
        index = SearchIndex()
        index.add_entry(sample_template)
        
        assert sample_template.id in index.entries
        entry = index.entries[sample_template.id]
        assert entry.name == sample_template.name
        assert entry.tags == sample_template.tags

    def test_remove_entry(self, sample_template):
        index = SearchIndex()
        index.add_entry(sample_template)
        index.remove_entry(sample_template.id)
        
        assert sample_template.id not in index.entries

    def test_search_by_name(self, sample_template):
        index = SearchIndex()
        index.add_entry(sample_template)
        
        results = index.search("test")
        assert sample_template.id in results
        
        results = index.search("nonexistent")
        assert len(results) == 0

    def test_search_by_tag(self, sample_template):
        index = SearchIndex()
        index.add_entry(sample_template)
        
        results = index.search("sample")
        assert sample_template.id in results

    def test_search_with_category_filter(self):
        index = SearchIndex()
        
        template1 = DiagramTemplate.create_new("T1", "", "uml", "<gaphor/>")
        template2 = DiagramTemplate.create_new("T2", "", "sysml", "<gaphor/>")
        
        index.add_entry(template1)
        index.add_entry(template2)
        
        results = index.search("", category_id="uml")
        assert len(results) == 1
        assert template1.id in results

    def test_search_with_language_filter(self):
        index = SearchIndex()
        
        template1 = DiagramTemplate.create_new("T1", "", "uml", "<gaphor/>", "UML")
        template2 = DiagramTemplate.create_new("T2", "", "sysml", "<gaphor/>", "SysML")
        
        index.add_entry(template1)
        index.add_entry(template2)
        
        results = index.search("", modeling_language="SysML")
        assert len(results) == 1
        assert template2.id in results

    def test_get_ids_by_category(self):
        index = SearchIndex()
        
        template1 = DiagramTemplate.create_new("T1", "", "uml", "<gaphor/>")
        template2 = DiagramTemplate.create_new("T2", "", "uml", "<gaphor/>")
        template3 = DiagramTemplate.create_new("T3", "", "sysml", "<gaphor/>")
        
        index.add_entry(template1)
        index.add_entry(template2)
        index.add_entry(template3)
        
        uml_ids = index.get_ids_by_category("uml")
        assert len(uml_ids) == 2
        assert template1.id in uml_ids
        assert template2.id in uml_ids

    def test_to_dict_and_from_dict(self, sample_template):
        index = SearchIndex()
        index.add_entry(sample_template)
        
        data = index.to_dict()
        restored = SearchIndex.from_dict(data)
        
        assert len(restored.entries) == 1
        assert sample_template.id in restored.entries
        assert restored.entries[sample_template.id].name == sample_template.name


class TestTemplateStorage:
    def test_storage_creates_directory(self, storage_path, storage):
        assert storage_path.exists()

    def test_storage_creates_index_file(self, storage_path, storage):
        index_file = storage_path / "search_index.json"
        assert index_file.exists()

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

    def test_save_and_load_template(self, storage, sample_template):
        storage.save_template(sample_template)

        loaded = storage.get_template(sample_template.id)
        assert loaded is not None
        assert loaded.name == sample_template.name
        assert loaded.description == sample_template.description
        assert loaded.tags == sample_template.tags

    def test_save_template_updates_index(self, storage, sample_template, storage_path):
        storage.save_template(sample_template)
        
        index_file = storage_path / "search_index.json"
        index_data = json.loads(index_file.read_text())
        
        assert sample_template.id in index_data["entries"]

    def test_delete_template_updates_index(self, storage, sample_template, storage_path):
        storage.save_template(sample_template)
        storage.delete_template(sample_template.id)
        
        index_file = storage_path / "search_index.json"
        index_data = json.loads(index_file.read_text())
        
        assert sample_template.id not in index_data["entries"]

    def test_search_uses_index(self, storage):
        template1 = DiagramTemplate.create_new(
            name="Observer Pattern",
            description="Observer design pattern",
            category_id="patterns",
            content="<gaphor/>",
        )
        template1.tags = ["behavioral", "design"]

        template2 = DiagramTemplate.create_new(
            name="Factory Pattern",
            description="Factory design pattern",
            category_id="patterns",
            content="<gaphor/>",
        )
        template2.tags = ["creational", "design"]

        storage.save_template(template1)
        storage.save_template(template2)

        results = storage.search_templates("observer")
        assert len(results) == 1
        assert results[0].name == "Observer Pattern"

        results = storage.search_templates("design")
        assert len(results) == 2

    def test_get_template_count_uses_index(self, storage, sample_template):
        storage.save_template(sample_template)
        
        count = storage.get_template_count()
        assert count == 1
        
        count = storage.get_template_count("uml")
        assert count == 1
        
        count = storage.get_template_count("sysml")
        assert count == 0

    def test_delete_category_removes_templates(self, storage, sample_template):
        category = TemplateCategory(id="delete-me", name="To Delete")
        storage.save_category(category)

        sample_template.category_id = "delete-me"
        storage.save_template(sample_template)

        storage.delete_category("delete-me")

        templates = list(storage.list_templates(category_id="delete-me"))
        assert len(templates) == 0

    def test_rebuild_search_index(self, storage, sample_template, storage_path):
        storage.save_template(sample_template)
        
        # Corrupt the index
        index_file = storage_path / "search_index.json"
        index_file.write_text("{}")
        
        # Rebuild
        storage.rebuild_search_index()
        
        # Verify index is restored
        index_data = json.loads(index_file.read_text())
        assert sample_template.id in index_data["entries"]

    def test_verify_index_integrity(self, storage, sample_template):
        storage.save_template(sample_template)
        
        assert storage.verify_index_integrity() is True
        
        # Delete template file without updating index
        template_file = storage.templates_path / f"{sample_template.id}.gaphor-template"
        template_file.unlink()
        
        assert storage.verify_index_integrity() is False

    def test_import_export_with_atomic_writes(self, storage, sample_template, tmp_path):
        storage.save_template(sample_template)

        export_path = tmp_path / "exported.gaphor-template"
        storage.export_template(sample_template.id, export_path)
        
        assert export_path.exists()
        
        # No temp files should remain
        temp_files = list(tmp_path.glob(".tmp_*"))
        assert len(temp_files) == 0

    def test_concurrent_access_safety(self, storage_path):
        """Test that atomic writes are safe for concurrent access."""
        storage1 = TemplateStorage(storage_path)
        storage2 = TemplateStorage(storage_path)
        
        template1 = DiagramTemplate.create_new("T1", "", "uml", "<gaphor/>")
        template2 = DiagramTemplate.create_new("T2", "", "uml", "<gaphor/>")
        
        # Both save at roughly the same time
        storage1.save_template(template1)
        storage2.save_template(template2)
        
        # Both should be saved
        assert storage1.get_template(template1.id) is not None
        assert storage2.get_template(template2.id) is not None


class TestTemplateStorageEdgeCases:
    def test_invalid_template_file_skipped(self, storage_path, storage):
        invalid_file = storage_path / "invalid.gaphor-template"
        invalid_file.write_text("not valid json{{{")

        templates = list(storage.list_templates())
        assert not any(t.name == "invalid" for t in templates)

    def test_missing_index_triggers_rebuild(self, storage_path):
        storage = TemplateStorage(storage_path)
        
        # Save a template
        template = DiagramTemplate.create_new("Test", "", "uml", "<gaphor/>")
        storage.save_template(template)
        
        # Delete index
        index_file = storage_path / "search_index.json"
        index_file.unlink()
        
        # Create new storage - should rebuild index
        storage2 = TemplateStorage(storage_path)
        
        assert index_file.exists()
        results = storage2.search_templates("Test")
        assert len(results) == 1

    def test_corrupted_index_triggers_rebuild(self, storage_path):
        storage = TemplateStorage(storage_path)
        
        template = DiagramTemplate.create_new("Test", "", "uml", "<gaphor/>")
        storage.save_template(template)
        
        # Corrupt index
        index_file = storage_path / "search_index.json"
        index_file.write_text("invalid json")
        
        # Create new storage - should rebuild
        storage2 = TemplateStorage(storage_path)
        
        results = storage2.search_templates("Test")
        assert len(results) == 1

    def test_backup_and_restore_preserves_index(self, storage, sample_template, tmp_path):
        storage.save_template(sample_template)
        backup_path = tmp_path / "backup"

        storage.backup_storage(backup_path)
        
        # Delete original
        storage.delete_template(sample_template.id)
        
        # Restore
        storage.restore_storage(backup_path)
        
        # Index should be valid after restore
        results = storage.search_templates(sample_template.name)
        assert len(results) == 1
