"""Storage backend for diagram templates with atomic file operations and indexing."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set

from gaphor import settings
from gaphor.ui.templatebrowser.template import (
    DiagramTemplate,
    TemplateCategory,
)

log = logging.getLogger(__name__)

# Constants
INDEX_FILE = "template_index.json"
INDEX_VERSION = 1
CATEGORIES_FILE = "categories.json"
TEMPLATE_EXTENSION = ".gaphor-template"
LOCK_TIMEOUT = 30.0  # seconds
LOCK_RETRY_INTERVAL = 0.1  # seconds


class TemplateStorageError(Exception):
    """Base exception for template storage errors."""
    pass


class StorageLockError(TemplateStorageError):
    """Raised when unable to acquire storage lock."""
    pass


class StorageCorruptionError(TemplateStorageError):
    """Raised when storage data is corrupted."""
    pass


class IndexEntry:
    """Represents an entry in the search index."""

    def __init__(
        self,
        template_id: str,
        name: str,
        description: str,
        category_id: str,
        modeling_language: str,
        tags: List[str],
        search_text: str,
        file_hash: str,
        last_modified: str,
    ):
        self.template_id = template_id
        self.name = name
        self.description = description
        self.category_id = category_id
        self.modeling_language = modeling_language
        self.tags = tags
        self.search_text = search_text
        self.file_hash = file_hash
        self.last_modified = last_modified

    def to_dict(self) -> Dict[str, Any]:
        return {
            "template_id": self.template_id,
            "name": self.name,
            "description": self.description,
            "category_id": self.category_id,
            "modeling_language": self.modeling_language,
            "tags": self.tags,
            "search_text": self.search_text,
            "file_hash": self.file_hash,
            "last_modified": self.last_modified,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IndexEntry":
        return cls(
            template_id=data["template_id"],
            name=data["name"],
            description=data.get("description", ""),
            category_id=data["category_id"],
            modeling_language=data.get("modeling_language", "UML"),
            tags=data.get("tags", []),
            search_text=data.get("search_text", ""),
            file_hash=data.get("file_hash", ""),
            last_modified=data.get("last_modified", ""),
        )

    @classmethod
    def from_template(cls, template: DiagramTemplate, file_hash: str) -> "IndexEntry":
        return cls(
            template_id=template.id,
            name=template.name,
            description=template.description,
            category_id=template.category_id,
            modeling_language=template.modeling_language,
            tags=list(template.tags),
            search_text=template.get_search_text(),
            file_hash=file_hash,
            last_modified=template.updated_at.isoformat(),
        )


class TemplateIndex:
    """Search index for templates."""

    def __init__(
        self,
        version: int = INDEX_VERSION,
        entries: Optional[Dict[str, IndexEntry]] = None,
        category_counts: Optional[Dict[str, int]] = None,
        last_rebuilt: Optional[str] = None,
    ):
        self.version = version
        self.entries = entries if entries is not None else {}
        self.category_counts = category_counts if category_counts is not None else {}
        self.last_rebuilt = last_rebuilt

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "entries": {k: v.to_dict() for k, v in self.entries.items()},
            "category_counts": self.category_counts,
            "last_rebuilt": self.last_rebuilt,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TemplateIndex":
        version = data.get("version", 0)
        if version != INDEX_VERSION:
            return cls()

        entries = {}
        for k, v in data.get("entries", {}).items():
            try:
                entries[k] = IndexEntry.from_dict(v)
            except (KeyError, TypeError) as e:
                log.warning(f"Skipping corrupted index entry {k}: {e}")

        return cls(
            version=version,
            entries=entries,
            category_counts=data.get("category_counts", {}),
            last_rebuilt=data.get("last_rebuilt"),
        )

    def add_entry(self, entry: IndexEntry):
        old_entry = self.entries.get(entry.template_id)
        if old_entry:
            old_cat = old_entry.category_id
            self.category_counts[old_cat] = max(0, self.category_counts.get(old_cat, 1) - 1)

        self.entries[entry.template_id] = entry
        self.category_counts[entry.category_id] = self.category_counts.get(entry.category_id, 0) + 1

    def remove_entry(self, template_id: str):
        entry = self.entries.pop(template_id, None)
        if entry:
            self.category_counts[entry.category_id] = max(
                0, self.category_counts.get(entry.category_id, 1) - 1
            )

    def search(
        self,
        query: str,
        category_id: Optional[str] = None,
        modeling_language: Optional[str] = None,
    ) -> List[IndexEntry]:
        results = []
        query_lower = query.lower() if query else ""
        query_terms = query_lower.split() if query_lower else []

        for entry in self.entries.values():
            if category_id and entry.category_id != category_id:
                continue
            if modeling_language and entry.modeling_language != modeling_language:
                continue
            if query_terms:
                if not all(term in entry.search_text for term in query_terms):
                    continue
            results.append(entry)

        return results

    def get_count(self, category_id: Optional[str] = None) -> int:
        if category_id:
            return self.category_counts.get(category_id, 0)
        return len(self.entries)


class FileLock:
    """Simple file-based lock for cross-process synchronization."""

    def __init__(self, lock_path: Path, timeout: float = LOCK_TIMEOUT):
        self._lock_path = lock_path
        self._timeout = timeout
        self._acquired = False

    def acquire(self) -> bool:
        start_time = time.monotonic()
        while True:
            try:
                fd = os.open(
                    str(self._lock_path),
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o644
                )
                os.write(fd, f"{os.getpid()}:{threading.get_ident()}".encode())
                os.close(fd)
                self._acquired = True
                return True
            except FileExistsError:
                if self._is_stale_lock():
                    self._break_lock()
                    continue

                elapsed = time.monotonic() - start_time
                if elapsed >= self._timeout:
                    return False
                time.sleep(LOCK_RETRY_INTERVAL)
            except OSError as e:
                log.error(f"Failed to acquire lock: {e}")
                return False

    def release(self):
        if self._acquired:
            try:
                self._lock_path.unlink(missing_ok=True)
            except OSError as e:
                log.warning(f"Failed to release lock: {e}")
            finally:
                self._acquired = False

    def _is_stale_lock(self) -> bool:
        try:
            stat = self._lock_path.stat()
            age = time.time() - stat.st_mtime
            return age > self._timeout * 2
        except OSError:
            return True

    def _break_lock(self):
        try:
            self._lock_path.unlink(missing_ok=True)
            log.warning(f"Broke stale lock at {self._lock_path}")
        except OSError:
            pass

    def __enter__(self):
        if not self.acquire():
            raise StorageLockError(f"Failed to acquire lock: {self._lock_path}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False


class AtomicFileWriter:
    """Writes files atomically using temporary file and rename."""

    def __init__(self, target_path: Path, mode: str = "w", encoding: str = "utf-8"):
        self._target_path = target_path
        self._mode = mode
        self._encoding = encoding if "b" not in mode else None
        self._temp_fd: Optional[int] = None
        self._temp_path: Optional[Path] = None

    def __enter__(self):
        self._target_path.parent.mkdir(parents=True, exist_ok=True)

        self._temp_fd, temp_name = tempfile.mkstemp(
            dir=self._target_path.parent,
            prefix=f".{self._target_path.name}.",
            suffix=".tmp"
        )
        self._temp_path = Path(temp_name)

        if "b" in self._mode:
            self._file = os.fdopen(self._temp_fd, self._mode)
        else:
            self._file = os.fdopen(self._temp_fd, self._mode, encoding=self._encoding)

        self._temp_fd = None
        return self._file

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            self._file.flush()
            os.fsync(self._file.fileno())
            self._file.close()
        except Exception as e:
            log.error(f"Error closing temp file: {e}")
            self._cleanup_temp()
            raise

        if exc_type is not None:
            self._cleanup_temp()
            return False

        try:
            if os.name == 'nt':
                self._target_path.unlink(missing_ok=True)
            os.rename(self._temp_path, self._target_path)

            try:
                parent_fd = os.open(str(self._target_path.parent), os.O_RDONLY)
                os.fsync(parent_fd)
                os.close(parent_fd)
            except OSError:
                pass

        except OSError as e:
            log.error(f"Failed to rename temp file: {e}")
            self._cleanup_temp()
            raise TemplateStorageError(f"Failed to write file: {e}") from e

        return False

    def _cleanup_temp(self):
        if self._temp_fd is not None:
            try:
                os.close(self._temp_fd)
            except OSError:
                pass

        if self._temp_path and self._temp_path.exists():
            try:
                self._temp_path.unlink()
            except OSError:
                pass


def compute_file_hash(content: bytes) -> str:
    """Compute a hash of file content for integrity checking."""
    return hashlib.sha256(content).hexdigest()[:16]


def safe_read_json(path: Path, default: Any = None) -> Any:
    """Safely read JSON file with error handling."""
    if not path.exists():
        return default

    try:
        content = path.read_text(encoding="utf-8")
        if not content.strip():
            return default
        return json.loads(content)
    except json.JSONDecodeError as e:
        log.error(f"Invalid JSON in {path}: {e}")
        return default
    except OSError as e:
        log.error(f"Failed to read {path}: {e}")
        return default


def safe_write_json(path: Path, data: Any, indent: int = 2):
    """Safely write JSON file atomically."""
    content = json.dumps(data, indent=indent, ensure_ascii=False)
    with AtomicFileWriter(path, "w", "utf-8") as f:
        f.write(content)


class TemplateStorage:
    """Thread-safe template storage with atomic operations and indexing."""

    TEMPLATES_DIR = "templates"

    def __init__(self, base_path: Optional[Path] = None):
        self._base_path = base_path or self._default_storage_path()
        self._lock_path = self._base_path / ".lock"
        self._index: Optional[TemplateIndex] = None
        self._index_dirty = False
        self._local_lock = threading.RLock()

        self._ensure_storage_exists()

    def _default_storage_path(self) -> Path:
        return settings.get_config_dir() / self.TEMPLATES_DIR

    def _ensure_storage_exists(self):
        self._base_path.mkdir(parents=True, exist_ok=True)
        categories_file = self._base_path / CATEGORIES_FILE
        if not categories_file.exists():
            self._save_categories_internal(TemplateCategory.builtin_categories())
        self._load_or_rebuild_index()

    @property
    def templates_path(self) -> Path:
        return self._base_path

    @contextmanager
    def _storage_lock(self):
        """Acquire both thread and file locks."""
        with self._local_lock:
            with FileLock(self._lock_path):
                yield

    def _load_or_rebuild_index(self):
        """Load index from file or rebuild if necessary."""
        index_path = self._base_path / INDEX_FILE

        data = safe_read_json(index_path)
        if data and data.get("version") == INDEX_VERSION:
            self._index = TemplateIndex.from_dict(data)
            if self._verify_index():
                return

        log.info("Rebuilding template index...")
        self._rebuild_index()

    def _verify_index(self) -> bool:
        """Verify index integrity against actual files."""
        if not self._index:
            return False

        template_files = set(
            f.stem for f in self._base_path.glob(f"*{TEMPLATE_EXTENSION}")
        )
        indexed_ids = set(self._index.entries.keys())

        if template_files != indexed_ids:
            return False

        for template_id, entry in list(self._index.entries.items())[:10]:
            template_file = self._base_path / f"{template_id}{TEMPLATE_EXTENSION}"
            if template_file.exists():
                try:
                    content = template_file.read_bytes()
                    if compute_file_hash(content) != entry.file_hash:
                        return False
                except OSError:
                    return False

        return True

    def _rebuild_index(self):
        """Rebuild the search index from template files."""
        self._index = TemplateIndex()

        for template_file in self._base_path.glob(f"*{TEMPLATE_EXTENSION}"):
            try:
                content = template_file.read_bytes()
                file_hash = compute_file_hash(content)
                data = json.loads(content.decode("utf-8"))
                template = DiagramTemplate.from_dict(data)
                entry = IndexEntry.from_template(template, file_hash)
                self._index.add_entry(entry)
            except (json.JSONDecodeError, KeyError, OSError) as e:
                log.warning(f"Skipping invalid template {template_file}: {e}")

        self._index.last_rebuilt = datetime.now().isoformat()
        self._save_index()

    def _save_index(self):
        """Save index to file atomically."""
        if not self._index:
            return

        index_path = self._base_path / INDEX_FILE
        safe_write_json(index_path, self._index.to_dict())
        self._index_dirty = False

    def _mark_index_dirty(self):
        """Mark index as needing to be saved."""
        self._index_dirty = True

    def flush_index(self):
        """Force save index if dirty."""
        if self._index_dirty:
            with self._storage_lock():
                self._save_index()

    # Category operations

    def list_categories(self) -> List[TemplateCategory]:
        """List all template categories."""
        categories_file = self._base_path / CATEGORIES_FILE
        data = safe_read_json(categories_file, [])

        if not data:
            return TemplateCategory.builtin_categories()

        try:
            return [
                TemplateCategory(
                    id=c["id"],
                    name=c["name"],
                    description=c.get("description", ""),
                    icon=c.get("icon", "folder-symbolic"),
                    parent_id=c.get("parent_id"),
                )
                for c in data
            ]
        except (KeyError, TypeError) as e:
            log.error(f"Failed to parse categories: {e}")
            return TemplateCategory.builtin_categories()

    def save_category(self, category: TemplateCategory):
        """Save or update a category."""
        with self._storage_lock():
            categories = self.list_categories()
            existing_idx = next(
                (i for i, c in enumerate(categories) if c.id == category.id),
                None
            )
            if existing_idx is not None:
                categories[existing_idx] = category
            else:
                categories.append(category)
            self._save_categories_internal(categories)

    def delete_category(self, category_id: str) -> bool:
        """Delete a category and all its templates."""
        with self._storage_lock():
            categories = self.list_categories()
            categories = [c for c in categories if c.id != category_id]
            self._save_categories_internal(categories)

            for entry in list(self._index.entries.values()):
                if entry.category_id == category_id:
                    self._delete_template_internal(entry.template_id)

            self._save_index()
        return True

    def _save_categories_internal(self, categories: List[TemplateCategory]):
        """Internal method to save categories."""
        categories_file = self._base_path / CATEGORIES_FILE
        data = [
            {
                "id": c.id,
                "name": c.name,
                "description": c.description,
                "icon": c.icon,
                "parent_id": c.parent_id,
            }
            for c in categories
        ]
        safe_write_json(categories_file, data)

    # Template operations

    def list_templates(
        self,
        category_id: Optional[str] = None,
        modeling_language: Optional[str] = None,
    ) -> Iterator[DiagramTemplate]:
        """List templates, optionally filtered by category or language."""
        if not self._index:
            return

        entries = self._index.search("", category_id, modeling_language)
        for entry in entries:
            template = self.get_template(entry.template_id)
            if template:
                yield template

    def get_template(self, template_id: str) -> Optional[DiagramTemplate]:
        """Get a template by ID."""
        template_file = self._base_path / f"{template_id}{TEMPLATE_EXTENSION}"
        if not template_file.exists():
            return None

        try:
            data = safe_read_json(template_file)
            if not data:
                return None

            template = DiagramTemplate.from_dict(data)

            if data.get("has_thumbnail"):
                thumb_file = self._base_path / f"{template_id}.png"
                if thumb_file.exists():
                    try:
                        template.thumbnail_data = thumb_file.read_bytes()
                    except OSError as e:
                        log.warning(f"Failed to read thumbnail: {e}")

            return template

        except (KeyError, ValueError) as e:
            log.error(f"Failed to load template {template_id}: {e}")
            return None

    def save_template(self, template: DiagramTemplate):
        """Save a template atomically."""
        with self._storage_lock():
            template.updated_at = datetime.now()
            template_file = self._base_path / f"{template.id}{TEMPLATE_EXTENSION}"

            data = template.to_dict()
            if template.thumbnail_data:
                data["has_thumbnail"] = True

            content = json.dumps(data, indent=2, ensure_ascii=False)
            content_bytes = content.encode("utf-8")
            file_hash = compute_file_hash(content_bytes)

            with AtomicFileWriter(template_file, "w", "utf-8") as f:
                f.write(content)

            if template.thumbnail_data:
                thumb_file = self._base_path / f"{template.id}.png"
                with AtomicFileWriter(thumb_file, "wb") as f:
                    f.write(template.thumbnail_data)

            entry = IndexEntry.from_template(template, file_hash)
            self._index.add_entry(entry)
            self._save_index()

    def delete_template(self, template_id: str) -> bool:
        """Delete a template."""
        with self._storage_lock():
            return self._delete_template_internal(template_id)

    def _delete_template_internal(self, template_id: str) -> bool:
        """Internal method to delete a template without locking."""
        template_file = self._base_path / f"{template_id}{TEMPLATE_EXTENSION}"
        thumb_file = self._base_path / f"{template_id}.png"

        deleted = False
        if template_file.exists():
            try:
                template_file.unlink()
                deleted = True
            except OSError as e:
                log.error(f"Failed to delete template file: {e}")

        if thumb_file.exists():
            try:
                thumb_file.unlink()
            except OSError as e:
                log.warning(f"Failed to delete thumbnail: {e}")

        if self._index:
            self._index.remove_entry(template_id)
            self._mark_index_dirty()

        return deleted

    # Search operations

    def search_templates(
        self,
        query: str,
        category_id: Optional[str] = None,
        modeling_language: Optional[str] = None,
    ) -> List[DiagramTemplate]:
        """Search templates using the index."""
        if not self._index:
            return []

        entries = self._index.search(query, category_id, modeling_language)
        results = []

        for entry in entries:
            template = self.get_template(entry.template_id)
            if template:
                results.append(template)

        return results

    def get_template_count(self, category_id: Optional[str] = None) -> int:
        """Get template count from index."""
        if not self._index:
            return 0
        return self._index.get_count(category_id)

    # Import/Export operations

    def import_template(self, source_path: Path) -> DiagramTemplate:
        """Import a template from a file."""
        if not source_path.exists():
            raise TemplateStorageError(f"Source file not found: {source_path}")

        try:
            content = source_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise TemplateStorageError(f"Failed to read file: {e}") from e

        if source_path.suffix == TEMPLATE_EXTENSION:
            try:
                data = json.loads(content)
                template = DiagramTemplate.from_dict(data)
            except (json.JSONDecodeError, KeyError) as e:
                raise TemplateStorageError(f"Invalid template file: {e}") from e
        elif source_path.suffix == ".gaphor":
            template = DiagramTemplate.create_new(
                name=source_path.stem,
                description=f"Imported from {source_path.name}",
                category_id="custom",
                content=content,
            )
        else:
            raise TemplateStorageError(f"Unsupported file format: {source_path.suffix}")

        self.save_template(template)
        return template

    def export_template(self, template_id: str, destination: Path):
        """Export a template to a file."""
        template = self.get_template(template_id)
        if not template:
            raise TemplateStorageError(f"Template not found: {template_id}")

        destination.parent.mkdir(parents=True, exist_ok=True)

        if destination.suffix == TEMPLATE_EXTENSION:
            data = template.to_dict()
            content = json.dumps(data, indent=2, ensure_ascii=False)
            with AtomicFileWriter(destination, "w", "utf-8") as f:
                f.write(content)
        elif destination.suffix == ".gaphor":
            with AtomicFileWriter(destination, "w", "utf-8") as f:
                f.write(template.content)
        else:
            raise TemplateStorageError(f"Unsupported export format: {destination.suffix}")

    # Backup operations

    def backup_storage(self, backup_path: Path):
        """Create a backup of the entire storage."""
        with self._storage_lock():
            self.flush_index()

            if backup_path.exists():
                shutil.rmtree(backup_path)

            shutil.copytree(self._base_path, backup_path)

    def restore_storage(self, backup_path: Path):
        """Restore storage from a backup."""
        if not backup_path.exists():
            raise TemplateStorageError(f"Backup not found: {backup_path}")

        with self._storage_lock():
            if self._base_path.exists():
                shutil.rmtree(self._base_path)

            shutil.copytree(backup_path, self._base_path)
            self._load_or_rebuild_index()

    def rebuild_index_if_needed(self):
        """Rebuild index if it's invalid or outdated."""
        with self._storage_lock():
            if not self._verify_index():
                self._rebuild_index()
