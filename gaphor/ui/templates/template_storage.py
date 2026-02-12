"""Template storage handling for Gaphor templates.

This module provides file-based storage for user templates with
integrity checking, backup management, and safe file operations.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import shutil
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from gaphor.settings import get_config_dir
from gaphor.ui.templates.template_model import (
    DiagramTemplate,
    TemplateCategory,
    MAX_TEMPLATE_DATA_SIZE,
)

log = logging.getLogger(__name__)

TEMPLATES_DIR_NAME = "templates"
TEMPLATES_INDEX_FILE = "templates_index.json"
TEMPLATE_FILE_EXTENSION = ".gaphor-template"
BACKUP_EXTENSION = ".backup"
LOCK_TIMEOUT_SECONDS = 10.0
MAX_BACKUP_COUNT = 5
INDEX_VERSION = 1


class TemplateStorageError(Exception):
    """Base exception for template storage errors."""

    pass


class TemplateNotFoundError(TemplateStorageError):
    """Raised when a template cannot be found."""

    pass


class TemplateLockError(TemplateStorageError):
    """Raised when a template file is locked."""

    pass


class TemplateCorruptedError(TemplateStorageError):
    """Raised when template data is corrupted."""

    pass


@contextmanager
def file_lock(file_path: Path, timeout: float = LOCK_TIMEOUT_SECONDS) -> Iterator[None]:
    """Acquire an exclusive lock on a file with timeout."""
    lock_path = file_path.with_suffix(file_path.suffix + ".lock")
    lock_file = None
    start_time = time.monotonic()

    try:
        # Create parent directory if needed
        lock_path.parent.mkdir(parents=True, exist_ok=True)

        while True:
            try:
                lock_file = open(lock_path, "w")
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (IOError, OSError):
                if lock_file:
                    lock_file.close()
                    lock_file = None

                elapsed = time.monotonic() - start_time
                if elapsed >= timeout:
                    raise TemplateLockError(
                        f"Could not acquire lock on {file_path} within {timeout}s"
                    )
                time.sleep(0.1)

        yield

    finally:
        if lock_file:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                lock_file.close()
            except (IOError, OSError):
                pass

        # Clean up lock file
        try:
            if lock_path.exists():
                lock_path.unlink()
        except (IOError, OSError):
            pass


def safe_write_file(file_path: Path, content: str | bytes, encoding: str = "utf-8") -> None:
    """Write content to file atomically with backup."""
    file_path.parent.mkdir(parents=True, exist_ok=True)

    # Create backup if file exists
    if file_path.exists():
        backup_path = file_path.with_suffix(file_path.suffix + BACKUP_EXTENSION)
        try:
            shutil.copy2(file_path, backup_path)
        except (IOError, OSError) as e:
            log.warning(f"Could not create backup: {e}")

    # Write to temp file first, then rename
    temp_fd = None
    temp_path = None
    try:
        temp_fd, temp_path = tempfile.mkstemp(
            dir=file_path.parent,
            prefix=f".{file_path.stem}_",
            suffix=".tmp",
        )

        if isinstance(content, bytes):
            os.write(temp_fd, content)
        else:
            os.write(temp_fd, content.encode(encoding))

        os.close(temp_fd)
        temp_fd = None

        # Atomic rename
        os.replace(temp_path, file_path)
        temp_path = None

    except Exception:
        # Clean up temp file on error
        if temp_fd is not None:
            try:
                os.close(temp_fd)
            except OSError:
                pass
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass
        raise


def safe_read_file(file_path: Path, encoding: str = "utf-8") -> str | None:
    """Read file content with error handling."""
    if not file_path.exists():
        return None

    try:
        with open(file_path, encoding=encoding) as f:
            return f.read()
    except (IOError, OSError, UnicodeDecodeError) as e:
        log.error(f"Failed to read file {file_path}: {e}")
        return None


class TemplateStorage:
    """File-based storage for diagram templates."""

    def __init__(self, base_dir: Path | None = None):
        """Initialize template storage.

        Args:
            base_dir: Base directory for template storage. Defaults to user config dir.
        """
        self._base_dir = base_dir or get_config_dir()
        self._templates_dir = self._base_dir / TEMPLATES_DIR_NAME
        self._index_path = self._templates_dir / TEMPLATES_INDEX_FILE
        self._index_cache: dict[str, dict] | None = None
        self._index_cache_mtime: float = 0.0

        self._ensure_directories()

    def _ensure_directories(self) -> None:
        """Create necessary directories if they don't exist."""
        try:
            self._templates_dir.mkdir(parents=True, exist_ok=True)
        except (IOError, OSError) as e:
            log.error(f"Failed to create templates directory: {e}")

    def _get_template_path(self, template_id: str) -> Path:
        """Get the file path for a template by ID."""
        # Sanitize ID to prevent path traversal
        safe_id = "".join(c for c in template_id if c.isalnum() or c in "-_")[:64]
        if not safe_id:
            safe_id = "unnamed"
        return self._templates_dir / f"{safe_id}{TEMPLATE_FILE_EXTENSION}"

    def _load_index(self, force_reload: bool = False) -> dict[str, dict]:
        """Load the template index from disk with caching."""
        try:
            if self._index_path.exists():
                mtime = self._index_path.stat().st_mtime
                if (
                    not force_reload
                    and self._index_cache is not None
                    and mtime == self._index_cache_mtime
                ):
                    return self._index_cache
        except (IOError, OSError):
            pass

        index: dict[str, dict] = {"version": INDEX_VERSION, "templates": {}}

        if self._index_path.exists():
            content = safe_read_file(self._index_path)
            if content:
                try:
                    data = json.loads(content)
                    if isinstance(data, dict):
                        index = data
                except json.JSONDecodeError as e:
                    log.error(f"Corrupted index file: {e}")

        self._index_cache = index
        try:
            self._index_cache_mtime = self._index_path.stat().st_mtime
        except (IOError, OSError):
            self._index_cache_mtime = 0.0

        return index

    def _save_index(self, index: dict[str, dict]) -> None:
        """Save the template index to disk."""
        try:
            with file_lock(self._index_path):
                content = json.dumps(index, indent=2, ensure_ascii=False)
                safe_write_file(self._index_path, content)
                self._index_cache = index
                self._index_cache_mtime = self._index_path.stat().st_mtime
        except (IOError, OSError, TemplateLockError) as e:
            log.error(f"Failed to save template index: {e}")
            raise TemplateStorageError(f"Could not save template index: {e}")

    def _update_index_entry(
        self, template: DiagramTemplate, action: str = "save"
    ) -> None:
        """Update a single entry in the index."""
        index = self._load_index(force_reload=True)
        templates = index.setdefault("templates", {})

        if action == "delete":
            templates.pop(template.id, None)
        else:
            templates[template.id] = {
                "name": template.name,
                "category": template.category.value,
                "modeling_language": template.modeling_language,
                "tags": template.tags[:10],  # Store limited tags in index
                "updated_at": template.updated_at.isoformat(),
                "checksum": template.checksum,
            }

        self._save_index(index)

    def save(self, template: DiagramTemplate) -> None:
        """Save a template to storage."""
        if not template.id:
            raise TemplateStorageError("Template must have an ID")

        validation = template.validate()
        if not validation:
            errors = "; ".join(e[1] for e in validation.errors)
            raise TemplateStorageError(f"Invalid template: {errors}")

        file_path = self._get_template_path(template.id)

        try:
            with file_lock(file_path):
                template.updated_at = datetime.now(timezone.utc)
                content = template.to_json()
                safe_write_file(file_path, content)
                self._update_index_entry(template, "save")
        except (IOError, OSError, TemplateLockError) as e:
            log.error(f"Failed to save template {template.id}: {e}")
            raise TemplateStorageError(f"Could not save template: {e}")

    def load(self, template_id: str) -> DiagramTemplate:
        """Load a template from storage by ID."""
        file_path = self._get_template_path(template_id)

        if not file_path.exists():
            raise TemplateNotFoundError(f"Template not found: {template_id}")

        content = safe_read_file(file_path)
        if content is None:
            raise TemplateCorruptedError(f"Could not read template: {template_id}")

        template = DiagramTemplate.from_json(content)
        if template is None:
            raise TemplateCorruptedError(f"Invalid template data: {template_id}")

        template.source_file = file_path
        return template

    def delete(self, template_id: str) -> None:
        """Delete a template from storage."""
        file_path = self._get_template_path(template_id)

        # Load template first to update index
        try:
            template = self.load(template_id)
        except TemplateNotFoundError:
            return  # Already gone

        try:
            with file_lock(file_path):
                # Create backup before deletion
                if file_path.exists():
                    backup_path = file_path.with_suffix(
                        f".deleted_{int(time.time())}{BACKUP_EXTENSION}"
                    )
                    shutil.move(file_path, backup_path)

                    # Clean up old backups
                    self._cleanup_old_backups(template_id)

                self._update_index_entry(template, "delete")
        except (IOError, OSError, TemplateLockError) as e:
            log.error(f"Failed to delete template {template_id}: {e}")
            raise TemplateStorageError(f"Could not delete template: {e}")

    def _cleanup_old_backups(self, template_id: str) -> None:
        """Remove old backup files, keeping only the most recent ones."""
        safe_id = "".join(c for c in template_id if c.isalnum() or c in "-_")[:64]
        pattern = f"{safe_id}*.backup"

        try:
            backups = sorted(
                self._templates_dir.glob(pattern),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )

            for backup in backups[MAX_BACKUP_COUNT:]:
                try:
                    backup.unlink()
                except (IOError, OSError):
                    pass
        except (IOError, OSError) as e:
            log.warning(f"Could not clean up backups: {e}")

    def list_templates(
        self,
        category: TemplateCategory | None = None,
        modeling_language: str | None = None,
        search_query: str | None = None,
    ) -> list[dict]:
        """List templates matching the given criteria.

        Returns list of template summaries from the index.
        """
        index = self._load_index()
        templates = index.get("templates", {})
        results = []

        search_lower = search_query.lower().strip() if search_query else None

        for template_id, info in templates.items():
            # Apply filters
            if category and info.get("category") != category.value:
                continue
            if modeling_language and info.get("modeling_language") != modeling_language:
                continue

            # Apply search
            if search_lower:
                name = info.get("name", "").lower()
                tags = [t.lower() for t in info.get("tags", [])]

                if not (
                    search_lower in name
                    or any(search_lower in tag for tag in tags)
                ):
                    continue

            results.append({"id": template_id, **info})

        # Sort by name
        results.sort(key=lambda t: t.get("name", "").lower())
        return results

    def exists(self, template_id: str) -> bool:
        """Check if a template exists in storage."""
        return self._get_template_path(template_id).exists()

    def get_categories_with_counts(self) -> dict[str, int]:
        """Get all categories with their template counts."""
        index = self._load_index()
        templates = index.get("templates", {})
        counts: dict[str, int] = {}

        for info in templates.values():
            category = info.get("category", TemplateCategory.GENERAL.value)
            counts[category] = counts.get(category, 0) + 1

        return counts

    def export_template(self, template_id: str, export_path: Path) -> None:
        """Export a template to an external file."""
        template = self.load(template_id)
        content = template.to_json()

        try:
            safe_write_file(export_path, content)
        except (IOError, OSError) as e:
            raise TemplateStorageError(f"Could not export template: {e}")

    def import_template(
        self, import_path: Path, overwrite: bool = False
    ) -> DiagramTemplate:
        """Import a template from an external file."""
        if not import_path.exists():
            raise TemplateNotFoundError(f"File not found: {import_path}")

        # Check file size before reading
        try:
            file_size = import_path.stat().st_size
            if file_size > MAX_TEMPLATE_DATA_SIZE * 2:  # Allow some overhead for JSON
                raise TemplateStorageError("Import file too large")
        except (IOError, OSError) as e:
            raise TemplateStorageError(f"Could not read file: {e}")

        content = safe_read_file(import_path)
        if content is None:
            raise TemplateCorruptedError("Could not read import file")

        template = DiagramTemplate.from_json(content)
        if template is None:
            raise TemplateCorruptedError("Invalid template file format")

        # Check for existing template
        if not overwrite and self.exists(template.id):
            raise TemplateStorageError(
                f"Template {template.id} already exists. Use overwrite=True to replace."
            )

        self.save(template)
        return template

    def rebuild_index(self) -> int:
        """Rebuild the index from template files on disk.

        Returns the number of templates indexed.
        """
        index = {"version": INDEX_VERSION, "templates": {}}
        count = 0

        try:
            for file_path in self._templates_dir.glob(f"*{TEMPLATE_FILE_EXTENSION}"):
                try:
                    content = safe_read_file(file_path)
                    if content is None:
                        continue

                    template = DiagramTemplate.from_json(content)
                    if template is None:
                        log.warning(f"Could not parse template: {file_path}")
                        continue

                    index["templates"][template.id] = {
                        "name": template.name,
                        "category": template.category.value,
                        "modeling_language": template.modeling_language,
                        "tags": template.tags[:10],
                        "updated_at": template.updated_at.isoformat(),
                        "checksum": template.checksum,
                    }
                    count += 1

                except Exception as e:
                    log.warning(f"Error processing {file_path}: {e}")

            self._save_index(index)

        except (IOError, OSError) as e:
            log.error(f"Error rebuilding index: {e}")
            raise TemplateStorageError(f"Could not rebuild index: {e}")

        return count
