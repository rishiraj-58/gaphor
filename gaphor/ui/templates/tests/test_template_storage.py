"""Tests for the template storage system."""

import json
import os
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from gaphor.ui.templates.template_model import (
    DiagramTemplate,
    TemplateCategory,
    TemplateParameter,
)
from gaphor.ui.templates.template_storage import (
    TemplateStorage,
    TemplateStorageError,
    TemplateNotFoundError,
    TemplateCorruptedError,
    TemplateLockError,
    safe_write_file,
    safe_read_file,
    file_lock,
    TEMPLATE_FILE_EXTENSION,
)


@pytest.fixture
def temp_storage_dir():
    """Create a temporary directory for storage tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def storage(temp_storage_dir):
    """Create a TemplateStorage instance with a temporary directory."""
    return TemplateStorage(base_dir=temp_storage_dir)


@pytest.fixture
def sample_template():
    """Create a sample template for testing."""
    return DiagramTemplate(
        id="test-template-001",
        name="Test Template",
        description="A test template",
        category=TemplateCategory.CLASS_DIAGRAM,
        modeling_language="UML",
        template_data="<?xml version='1.0'?><gaphor><test/></gaphor>",
        parameters=[
            TemplateParameter(name="class_name", default_value="MyClass"),
        ],
        tags=["test", "example"],
        author="Test Author",
    )


class TestSafeFileOperations:
    """Tests for safe file operations."""

    def test_safe_write_and_read(self, temp_storage_dir):
        file_path = temp_storage_dir / "test.txt"
        content = "Hello, World!"

        safe_write_file(file_path, content)
        result = safe_read_file(file_path)

        assert result == content

    def test_safe_write_creates_parent_dirs(self, temp_storage_dir):
        file_path = temp_storage_dir / "nested" / "dir" / "test.txt"
        content = "nested content"

        safe_write_file(file_path, content)

        assert file_path.exists()
        assert safe_read_file(file_path) == content

    def test_safe_write_creates_backup(self, temp_storage_dir):
        file_path = temp_storage_dir / "test.txt"
        backup_path = file_path.with_suffix(".txt.backup")

        safe_write_file(file_path, "original")
        safe_write_file(file_path, "updated")

        assert backup_path.exists()
        assert safe_read_file(backup_path) == "original"
        assert safe_read_file(file_path) == "updated"

    def test_safe_write_bytes(self, temp_storage_dir):
        file_path = temp_storage_dir / "test.bin"
        content = b"\x00\x01\x02\x03"

        safe_write_file(file_path, content)

        with open(file_path, "rb") as f:
            assert f.read() == content

    def test_safe_read_nonexistent_file(self, temp_storage_dir):
        result = safe_read_file(temp_storage_dir / "nonexistent.txt")
        assert result is None

    def test_safe_read_encoding_error(self, temp_storage_dir):
        file_path = temp_storage_dir / "binary.txt"
        with open(file_path, "wb") as f:
            f.write(b"\xff\xfe")  # Invalid UTF-8

        result = safe_read_file(file_path, encoding="utf-8")
        assert result is None


class TestFileLock:
    """Tests for file locking."""

    def test_file_lock_basic(self, temp_storage_dir):
        file_path = temp_storage_dir / "lockable.txt"
        file_path.write_text("test")

        with file_lock(file_path, timeout=1.0):
            # Should be able to read/write while holding lock
            file_path.write_text("updated")
            assert file_path.read_text() == "updated"

    def test_file_lock_creates_parent_dirs(self, temp_storage_dir):
        file_path = temp_storage_dir / "nested" / "file.txt"

        with file_lock(file_path, timeout=1.0):
            pass  # Lock should succeed

        assert file_path.parent.exists()

    def test_file_lock_cleanup(self, temp_storage_dir):
        file_path = temp_storage_dir / "test.txt"
        lock_path = file_path.with_suffix(".txt.lock")

        with file_lock(file_path, timeout=1.0):
            pass

        # Lock file should be cleaned up
        assert not lock_path.exists()


class TestTemplateStorage:
    """Tests for TemplateStorage class."""

    def test_storage_creates_directory(self, temp_storage_dir):
        storage = TemplateStorage(base_dir=temp_storage_dir)
        templates_dir = temp_storage_dir / "templates"
        assert templates_dir.exists()

    def test_save_and_load_template(self, storage, sample_template):
        storage.save(sample_template)
        loaded = storage.load(sample_template.id)

        assert loaded.id == sample_template.id
        assert loaded.name == sample_template.name
        assert loaded.description == sample_template.description
        assert loaded.category == sample_template.category
        assert loaded.template_data == sample_template.template_data
        assert len(loaded.parameters) == len(sample_template.parameters)

    def test_save_updates_timestamp(self, storage, sample_template):
        original_updated = sample_template.updated_at
        storage.save(sample_template)
        loaded = storage.load(sample_template.id)

        assert loaded.updated_at >= original_updated

    def test_save_invalid_template_raises(self, storage):
        invalid_template = DiagramTemplate(
            name="",  # Empty name is invalid
            template_data="",
        )

        with pytest.raises(TemplateStorageError):
            storage.save(invalid_template)

    def test_load_nonexistent_raises(self, storage):
        with pytest.raises(TemplateNotFoundError):
            storage.load("nonexistent-id")

    def test_delete_template(self, storage, sample_template):
        storage.save(sample_template)
        assert storage.exists(sample_template.id)

        storage.delete(sample_template.id)
        assert not storage.exists(sample_template.id)

    def test_delete_nonexistent_silent(self, storage):
        # Should not raise
        storage.delete("nonexistent-id")

    def test_delete_creates_backup(self, storage, sample_template, temp_storage_dir):
        storage.save(sample_template)
        storage.delete(sample_template.id)

        templates_dir = temp_storage_dir / "templates"
        backups = list(templates_dir.glob("*.backup"))
        assert len(backups) >= 1

    def test_exists(self, storage, sample_template):
        assert not storage.exists(sample_template.id)

        storage.save(sample_template)
        assert storage.exists(sample_template.id)

    def test_list_templates_empty(self, storage):
        templates = storage.list_templates()
        assert templates == []

    def test_list_templates_with_data(self, storage):
        template1 = DiagramTemplate(
            id="t1",
            name="Template 1",
            category=TemplateCategory.CLASS_DIAGRAM,
            template_data="<gaphor/>",
        )
        template2 = DiagramTemplate(
            id="t2",
            name="Template 2",
            category=TemplateCategory.SEQUENCE_DIAGRAM,
            template_data="<gaphor/>",
        )

        storage.save(template1)
        storage.save(template2)

        templates = storage.list_templates()
        assert len(templates) == 2

    def test_list_templates_filter_by_category(self, storage):
        template1 = DiagramTemplate(
            id="t1",
            name="Class Template",
            category=TemplateCategory.CLASS_DIAGRAM,
            template_data="<gaphor/>",
        )
        template2 = DiagramTemplate(
            id="t2",
            name="Sequence Template",
            category=TemplateCategory.SEQUENCE_DIAGRAM,
            template_data="<gaphor/>",
        )

        storage.save(template1)
        storage.save(template2)

        templates = storage.list_templates(category=TemplateCategory.CLASS_DIAGRAM)
        assert len(templates) == 1
        assert templates[0]["id"] == "t1"

    def test_list_templates_filter_by_language(self, storage):
        template1 = DiagramTemplate(
            id="t1",
            name="UML Template",
            modeling_language="UML",
            template_data="<gaphor/>",
        )
        template2 = DiagramTemplate(
            id="t2",
            name="SysML Template",
            modeling_language="SysML",
            template_data="<gaphor/>",
        )

        storage.save(template1)
        storage.save(template2)

        templates = storage.list_templates(modeling_language="SysML")
        assert len(templates) == 1
        assert templates[0]["id"] == "t2"

    def test_list_templates_search(self, storage):
        template1 = DiagramTemplate(
            id="t1",
            name="Customer Class",
            template_data="<gaphor/>",
        )
        template2 = DiagramTemplate(
            id="t2",
            name="Order Sequence",
            template_data="<gaphor/>",
        )

        storage.save(template1)
        storage.save(template2)

        templates = storage.list_templates(search_query="customer")
        assert len(templates) == 1
        assert templates[0]["id"] == "t1"

    def test_list_templates_search_tags(self, storage):
        template = DiagramTemplate(
            id="t1",
            name="Template",
            template_data="<gaphor/>",
            tags=["design", "pattern"],
        )

        storage.save(template)

        templates = storage.list_templates(search_query="pattern")
        assert len(templates) == 1

    def test_get_categories_with_counts(self, storage):
        templates = [
            DiagramTemplate(
                id=f"t{i}",
                name=f"Template {i}",
                category=TemplateCategory.CLASS_DIAGRAM if i < 3 else TemplateCategory.SEQUENCE_DIAGRAM,
                template_data="<gaphor/>",
            )
            for i in range(5)
        ]

        for t in templates:
            storage.save(t)

        counts = storage.get_categories_with_counts()
        assert counts.get("class_diagram") == 3
        assert counts.get("sequence_diagram") == 2

    def test_export_template(self, storage, sample_template, temp_storage_dir):
        storage.save(sample_template)

        export_path = temp_storage_dir / "exported.json"
        storage.export_template(sample_template.id, export_path)

        assert export_path.exists()

        with open(export_path) as f:
            data = json.load(f)
        assert data["id"] == sample_template.id

    def test_export_nonexistent_raises(self, storage, temp_storage_dir):
        export_path = temp_storage_dir / "exported.json"

        with pytest.raises(TemplateNotFoundError):
            storage.export_template("nonexistent", export_path)

    def test_import_template(self, storage, sample_template, temp_storage_dir):
        import_path = temp_storage_dir / "import.json"
        import_path.write_text(sample_template.to_json())

        imported = storage.import_template(import_path)

        assert imported.id == sample_template.id
        assert imported.name == sample_template.name
        assert storage.exists(sample_template.id)

    def test_import_overwrite(self, storage, sample_template, temp_storage_dir):
        storage.save(sample_template)

        updated = DiagramTemplate(
            id=sample_template.id,
            name="Updated Name",
            template_data="<gaphor>updated</gaphor>",
        )

        import_path = temp_storage_dir / "import.json"
        import_path.write_text(updated.to_json())

        with pytest.raises(TemplateStorageError):
            storage.import_template(import_path, overwrite=False)

        imported = storage.import_template(import_path, overwrite=True)
        assert imported.name == "Updated Name"

    def test_import_nonexistent_file_raises(self, storage, temp_storage_dir):
        with pytest.raises(TemplateNotFoundError):
            storage.import_template(temp_storage_dir / "nonexistent.json")

    def test_import_corrupted_file_raises(self, storage, temp_storage_dir):
        import_path = temp_storage_dir / "corrupted.json"
        import_path.write_text("not valid json {{{")

        with pytest.raises(TemplateCorruptedError):
            storage.import_template(import_path)

    def test_rebuild_index(self, storage, sample_template, temp_storage_dir):
        # Save a template
        storage.save(sample_template)

        # Corrupt the index
        index_path = temp_storage_dir / "templates" / "templates_index.json"
        index_path.write_text("{}")

        # Rebuild
        count = storage.rebuild_index()

        assert count == 1
        templates = storage.list_templates()
        assert len(templates) == 1

    def test_template_id_sanitization(self, storage):
        # Test that potentially dangerous IDs are sanitized
        template = DiagramTemplate(
            id="../../../etc/passwd",
            name="Dangerous",
            template_data="<gaphor/>",
        )

        storage.save(template)

        # The file should be in the templates directory, not elsewhere
        templates_dir = storage._templates_dir
        assert all(
            f.parent == templates_dir
            for f in templates_dir.glob(f"*{TEMPLATE_FILE_EXTENSION}")
        )


class TestTemplateStorageEdgeCases:
    """Tests for edge cases and error handling."""

    def test_concurrent_saves(self, storage):
        """Test that concurrent saves don't corrupt data."""
        import threading

        template = DiagramTemplate(
            id="concurrent-test",
            name="Concurrent",
            template_data="<gaphor/>",
        )

        errors = []

        def save_template(name_suffix):
            try:
                t = DiagramTemplate(
                    id=template.id,
                    name=f"Concurrent {name_suffix}",
                    template_data=f"<gaphor>{name_suffix}</gaphor>",
                )
                storage.save(t)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=save_template, args=(i,))
            for i in range(5)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No errors should have occurred
        assert len(errors) == 0

        # Template should still be loadable
        loaded = storage.load(template.id)
        assert loaded is not None

    def test_empty_template_id_generates_new(self, storage):
        template = DiagramTemplate(
            id="",  # Empty ID
            name="No ID",
            template_data="<gaphor/>",
        )
        # The template model generates IDs automatically
        assert template.id != ""

    def test_very_long_template_data(self, storage, temp_storage_dir):
        large_data = "x" * (1024 * 1024)  # 1MB
        template = DiagramTemplate(
            id="large-template",
            name="Large Template",
            template_data=f"<gaphor>{large_data}</gaphor>",
        )

        storage.save(template)
        loaded = storage.load(template.id)

        assert len(loaded.template_data) == len(template.template_data)

    def test_unicode_in_template(self, storage):
        template = DiagramTemplate(
            id="unicode-test",
            name="日本語テンプレート",  # Japanese
            description="中文描述",  # Chinese
            template_data="<gaphor>🎨 émojis et accénts</gaphor>",
            tags=["標籤", "тег"],  # Chinese and Russian
        )

        storage.save(template)
        loaded = storage.load(template.id)

        assert loaded.name == template.name
        assert loaded.description == template.description
        assert loaded.template_data == template.template_data
        assert loaded.tags == template.tags

    def test_storage_recovers_from_corrupted_index(self, storage, temp_storage_dir):
        # Create a valid template
        template = DiagramTemplate(
            id="recovery-test",
            name="Recovery Test",
            template_data="<gaphor/>",
        )
        storage.save(template)

        # Corrupt the index
        index_path = temp_storage_dir / "templates" / "templates_index.json"
        index_path.write_text("corrupted data")

        # Create new storage instance (simulates restart)
        new_storage = TemplateStorage(base_dir=temp_storage_dir)

        # The template file is still there
        loaded = new_storage.load(template.id)
        assert loaded.name == template.name
