"""Tests for template storage with atomic operations and indexing."""

import json
import os
import threading
import time
import pytest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from gaphor.ui.templatebrowser.storage import (
    TemplateStorage,
    TemplateStorageError,
    StorageLockError,
    AtomicFileWriter,
    FileLock,
    compute_file_hash,
    safe_read_json,
    safe_write_json,
    IndexEntry,
    TemplateIndex,
    INDEX_FILE,
    CATEGORIES_FILE,
    TEMPLATE_EXTENSION,
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


class TestAtomicFileWriter:
    def test_atomic_write_success(self, tmp_path):
        target = tmp_path / "test.txt"
        content = "Hello, World!"

        with AtomicFileWriter(target, "w", "utf-8") as f:
            f.write(content)

        assert target.exists()
        assert target.read_text() == content

    def test_atomic_write_binary(self, tmp_path):
        target = tmp_path / "test.bin"
        content = b"\x00\x01\x02\x03"

        with AtomicFileWriter(target, "wb") as f:
            f.write(content)

        assert target.exists()
        assert target.read_bytes() == content

    def test_atomic_write_rollback_on_exception(self, tmp_path):
        target = tmp_path / "test.txt"
        target.write_text("original")

        try:
            with AtomicFileWriter(target, "w", "utf-8") as f:
                f.write("new content")
                raise ValueError("Intentional error")
        except ValueError:
            pass

        assert target.read_text() == "original"

    def test_atomic_write_creates_parent_dirs(self, tmp_path):
        target = tmp_path / "deep" / "nested" / "dir" / "test.txt"

        with AtomicFileWriter(target, "w", "utf-8") as f:
            f.write("content")

        assert target.exists()

    def test_atomic_write_no_partial_content(self, tmp_path):
        target = tmp_path / "test.txt"
        large_content = "x" * 100000

        temp_files_before = list(tmp_path.glob(".*"))

        with AtomicFileWriter(target, "w", "utf-8") as f:
            f.write(large_content)

        temp_files_after = list(tmp_path.glob(".*"))
        assert len(temp_files_after) == len(temp_files_before)


class TestFileLock:
    def test_lock_acquire_release(self, tmp_path):
        lock_path = tmp_path / ".lock"
        lock = FileLock(lock_path, timeout=1.0)

        assert lock.acquire()
        assert lock_path.exists()

        lock.release()
        assert not lock_path.exists()

    def test_lock_context_manager(self, tmp_path):
        lock_path = tmp_path / ".lock"

        with FileLock(lock_path, timeout=1.0):
            assert lock_path.exists()

        assert not lock_path.exists()

    def test_lock_prevents_concurrent_access(self, tmp_path):
        lock_path = tmp_path / ".lock"
        acquired = []

        def try_acquire(lock_id):
            lock = FileLock(lock_path, timeout=0.5)
            if lock.acquire():
                acquired.append(lock_id)
                time.sleep(0.3)
                lock.release()

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(try_acquire, i) for i in range(3)]
            for f in futures:
                f.result()

        assert len(acquired) <= 3

    def test_stale_lock_detection(self, tmp_path):
        lock_path = tmp_path / ".lock"

        lock_path.write_text("stale_process")
        old_time = time.time() - 120
        os.utime(lock_path, (old_time, old_time))

        lock = FileLock(lock_path, timeout=1.0)
        assert lock.acquire()
        lock.release()


class TestIndexEntry:
    def test_from_template(self, sample_template):
        file_hash = "abc123"
        entry = IndexEntry.from_template(sample_template, file_hash)

        assert entry.template_id == sample_template.id
        assert entry.name == sample_template.name
        assert entry.category_id == sample_template.category_id
        assert entry.file_hash == file_hash
        assert "test" in entry.search_text

    def test_to_dict_from_dict_roundtrip(self, sample_template):
        entry = IndexEntry.from_template(sample_template, "hash123")
        data = entry.to_dict()
        restored = IndexEntry.from_dict(data)

        assert restored.template_id == entry.template_id
        assert restored.name == entry.name
        assert restored.file_hash == entry.file_hash


class TestTemplateIndex:
    def test_add_entry(self, sample_template):
        index = TemplateIndex()
        entry = IndexEntry.from_template(sample_template, "hash")

        index.add_entry(entry)

        assert sample_template.id in index.entries
        assert index.category_counts.get("uml", 0) == 1

    def test_remove_entry(self, sample_template):
        index = TemplateIndex()
        entry = IndexEntry.from_template(sample_template, "hash")
        index.add_entry(entry)

        index.remove_entry(sample_template.id)

        assert sample_template.id not in index.entries
        assert index.category_counts.get("uml", 0) == 0

    def test_search_by_query(self):
        index = TemplateIndex()

        t1 = DiagramTemplate.create_new("Observer Pattern", "observer", "patterns", "")
        t2 = DiagramTemplate.create_new("Factory Pattern", "factory", "patterns", "")
        t3 = DiagramTemplate.create_new("Class Diagram", "class", "uml", "")

        index.add_entry(IndexEntry.from_template(t1, "h1"))
        index.add_entry(IndexEntry.from_template(t2, "h2"))
        index.add_entry(IndexEntry.from_template(t3, "h3"))

        results = index.search("pattern")
        assert len(results) == 2

        results = index.search("observer")
        assert len(results) == 1
        assert results[0].name == "Observer Pattern"

    def test_search_by_category(self):
        index = TemplateIndex()

        t1 = DiagramTemplate.create_new("T1", "", "uml", "")
        t2 = DiagramTemplate.create_new("T2", "", "sysml", "")

        index.add_entry(IndexEntry.from_template(t1, "h1"))
        index.add_entry(IndexEntry.from_template(t2, "h2"))

        results = index.search("", category_id="uml")
        assert len(results) == 1
        assert results[0].category_id == "uml"

    def test_search_by_language(self):
        index = TemplateIndex()

        t1 = DiagramTemplate.create_new("T1", "", "uml", "", modeling_language="UML")
        t2 = DiagramTemplate.create_new("T2", "", "sysml", "", modeling_language="SysML")

        index.add_entry(IndexEntry.from_template(t1, "h1"))
        index.add_entry(IndexEntry.from_template(t2, "h2"))

        results = index.search("", modeling_language="SysML")
        assert len(results) == 1
        assert results[0].modeling_language == "SysML"

    def test_get_count(self):
        index = TemplateIndex()

        t1 = DiagramTemplate.create_new("T1", "", "uml", "")
        t2 = DiagramTemplate.create_new("T2", "", "uml", "")
        t3 = DiagramTemplate.create_new("T3", "", "sysml", "")

        index.add_entry(IndexEntry.from_template(t1, "h1"))
        index.add_entry(IndexEntry.from_template(t2, "h2"))
        index.add_entry(IndexEntry.from_template(t3, "h3"))

        assert index.get_count() == 3
        assert index.get_count("uml") == 2
        assert index.get_count("sysml") == 1
        assert index.get_count("nonexistent") == 0


class TestTemplateStorage:
    def test_storage_creates_directory(self, storage_path, storage):
        assert storage_path.exists()
        assert (storage_path / CATEGORIES_FILE).exists()

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

    def test_template_indexed_after_save(self, storage, sample_template):
        storage.save_template(sample_template)

        assert storage._index is not None
        assert sample_template.id in storage._index.entries

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

    def test_delete_template(self, storage, sample_template):
        storage.save_template(sample_template)
        assert storage.get_template(sample_template.id) is not None

        storage.delete_template(sample_template.id)
        assert storage.get_template(sample_template.id) is None
        assert sample_template.id not in storage._index.entries

    def test_search_templates_uses_index(self, storage):
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

    def test_get_template_count_from_index(self, storage):
        initial_count = storage.get_template_count()

        template1 = DiagramTemplate.create_new("T1", "", "uml", "<gaphor/>")
        template2 = DiagramTemplate.create_new("T2", "", "sysml", "<gaphor/>")
        storage.save_template(template1)
        storage.save_template(template2)

        assert storage.get_template_count() == initial_count + 2
        assert storage.get_template_count("uml") == 1
        assert storage.get_template_count("sysml") == 1

    def test_index_persisted_to_file(self, storage_path, sample_template):
        storage1 = TemplateStorage(storage_path)
        storage1.save_template(sample_template)
        storage1.flush_index()

        storage2 = TemplateStorage(storage_path)
        assert sample_template.id in storage2._index.entries

    def test_index_rebuilt_if_corrupted(self, storage_path, sample_template):
        storage1 = TemplateStorage(storage_path)
        storage1.save_template(sample_template)
        storage1.flush_index()

        index_file = storage_path / INDEX_FILE
        index_file.write_text("corrupted data")

        storage2 = TemplateStorage(storage_path)
        assert storage2._index is not None
        assert sample_template.id in storage2._index.entries

    def test_concurrent_saves(self, storage):
        results = []
        errors = []

        def save_template(idx):
            try:
                template = DiagramTemplate.create_new(
                    name=f"Template {idx}",
                    description="",
                    category_id="uml",
                    content=f"<gaphor id='{idx}'/>",
                )
                storage.save_template(template)
                results.append(template.id)
            except Exception as e:
                errors.append(e)

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(save_template, i) for i in range(10)]
            for f in futures:
                f.result()

        assert len(errors) == 0
        assert len(results) == 10
        assert storage.get_template_count() == 10


class TestSafeJsonOperations:
    def test_safe_read_json_missing_file(self, tmp_path):
        result = safe_read_json(tmp_path / "nonexistent.json", {"default": True})
        assert result == {"default": True}

    def test_safe_read_json_empty_file(self, tmp_path):
        empty_file = tmp_path / "empty.json"
        empty_file.write_text("")

        result = safe_read_json(empty_file, {"default": True})
        assert result == {"default": True}

    def test_safe_read_json_invalid_json(self, tmp_path):
        invalid_file = tmp_path / "invalid.json"
        invalid_file.write_text("{invalid json")

        result = safe_read_json(invalid_file, {"default": True})
        assert result == {"default": True}

    def test_safe_read_json_valid(self, tmp_path):
        valid_file = tmp_path / "valid.json"
        valid_file.write_text('{"key": "value"}')

        result = safe_read_json(valid_file)
        assert result == {"key": "value"}

    def test_safe_write_json_atomic(self, tmp_path):
        target = tmp_path / "output.json"
        data = {"key": "value", "number": 42}

        safe_write_json(target, data)

        assert target.exists()
        loaded = json.loads(target.read_text())
        assert loaded == data


class TestImportExport:
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
        assert content == sample_template.content


class TestBackupRestore:
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
