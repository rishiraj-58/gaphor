"""Storage backend for diagram templates with atomic writes and search indexing."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator, List, Optional, Set

from gaphor import settings
from gaphor.ui.templatebrowser.template import (
    DiagramTemplate,
    TemplateCategory,
)

log = logging.getLogger(__name__)


class TemplateStorageError(Exception):
    pass


@dataclass
class SearchIndexEntry:
    template_id: str
    name: str
    description: str
    tags: List[str]
    category_id: str
    modeling_language: str
    updated_at: str
    content_hash: str

    def matches(self, query: str) -> bool:
        if not query:
            return True
        query_lower = query.lower()
        search_text = f"{self.name} {self.description} {' '.join(self.tags)}".lower()
        return all(term in search_text for term in query_lower.split())


@dataclass
class SearchIndex:
    entries: dict = field(default_factory=dict)
    version: int = 1
    last_updated: str = ""

    def add_entry(self, template: DiagramTemplate):
        content_hash = hashlib.md5(template.content.encode()).hexdigest()
        self.entries[template.id] = SearchIndexEntry(
            template_id=template.id,
            name=template.name,
            description=template.description,
            tags=template.tags,
            category_id=template.category_id,
            modeling_language=template.modeling_language,
            updated_at=template.updated_at.isoformat(),
            content_hash=content_hash,
        )
        self.last_updated = datetime.now().isoformat()

    def remove_entry(self, template_id: str):
        if template_id in self.entries:
            del self.entries[template_id]
            self.last_updated = datetime.now().isoformat()

    def search(
        self,
        query: str,
        category_id: Optional[str] = None,
        modeling_language: Optional[str] = None,
    ) -> List[str]:
        results = []
        for entry in self.entries.values():
            if category_id and entry.category_id != category_id:
                continue
            if modeling_language and entry.modeling_language != modeling_language:
                continue
            if entry.matches(query):
                results.append(entry.template_id)
        return results

    def get_ids_by_category(self, category_id: str) -> List[str]:
        return [
            entry.template_id
            for entry in self.entries.values()
            if entry.category_id == category_id
        ]

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "last_updated": self.last_updated,
            "entries": {
                tid: {
                    "template_id": e.template_id,
                    "name": e.name,
                    "description": e.description,
                    "tags": e.tags,
                    "category_id": e.category_id,
                    "modeling_language": e.modeling_language,
                    "updated_at": e.updated_at,
                    "content_hash": e.content_hash,
                }
                for tid, e in self.entries.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> SearchIndex:
        index = cls()
        index.version = data.get("version", 1)
        index.last_updated = data.get("last_updated", "")
        for tid, entry_data in data.get("entries", {}).items():
            index.entries[tid] = SearchIndexEntry(
                template_id=entry_data["template_id"],
                name=entry_data["name"],
                description=entry_data["description"],
                tags=entry_data.get("tags", []),
                category_id=entry_data["category_id"],
                modeling_language=entry_data.get("modeling_language", "UML"),
                updated_at=entry_data.get("updated_at", ""),
                content_hash=entry_data.get("content_hash", ""),
            )
        return index


def atomic_write(path: Path, content: str, encoding: str = "utf-8"):
    """Write content to a file atomically using a temporary file and rename."""
    dir_path = path.parent
    dir_path.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=str(dir_path), prefix=".tmp_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())

        tmp_file = Path(tmp_path)
        tmp_file.replace(path)

        # Sync the directory to ensure the rename is persisted
        dir_fd = os.open(str(dir_path), os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def atomic_write_bytes(path: Path, content: bytes):
    """Write binary content to a file atomically."""
    dir_path = path.parent
    dir_path.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=str(dir_path), prefix=".tmp_", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())

        tmp_file = Path(tmp_path)
        tmp_file.replace(path)

        dir_fd = os.open(str(dir_path), os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


class TemplateStorage:
    TEMPLATES_DIR = "templates"
    CATEGORIES_FILE = "categories.json"
    INDEX_FILE = "search_index.json"
    TEMPLATE_EXTENSION = ".gaphor-template"
    INDEX_VERSION = 1

    def __init__(self, base_path: Optional[Path] = None):
        self._base_path = base_path or self._default_storage_path()
        self._index: Optional[SearchIndex] = None
        self._ensure_storage_exists()

    def _default_storage_path(self) -> Path:
        return settings.get_config_dir() / self.TEMPLATES_DIR

    def _ensure_storage_exists(self):
        self._base_path.mkdir(parents=True, exist_ok=True)
        categories_file = self._base_path / self.CATEGORIES_FILE
        if not categories_file.exists():
            self._save_categories(TemplateCategory.builtin_categories())
        self._load_or_rebuild_index()

    @property
    def templates_path(self) -> Path:
        return self._base_path

    def _load_or_rebuild_index(self):
        index_file = self._base_path / self.INDEX_FILE
        if index_file.exists():
            try:
                data = json.loads(index_file.read_text(encoding="utf-8"))
                self._index = SearchIndex.from_dict(data)
                if self._index.version != self.INDEX_VERSION:
                    log.info("Index version mismatch, rebuilding...")
                    self._rebuild_index()
                return
            except (json.JSONDecodeError, KeyError) as e:
                log.warning(f"Failed to load search index: {e}")

        self._rebuild_index()

    def _rebuild_index(self):
        log.info("Rebuilding template search index...")
        self._index = SearchIndex()
        self._index.version = self.INDEX_VERSION

        for template_file in self._base_path.glob(f"*{self.TEMPLATE_EXTENSION}"):
            try:
                template = self._load_template_file(template_file)
                self._index.add_entry(template)
            except TemplateStorageError as e:
                log.warning(f"Skipping invalid template {template_file}: {e}")

        self._save_index()

    def _save_index(self):
        if self._index is None:
            return
        index_file = self._base_path / self.INDEX_FILE
        content = json.dumps(self._index.to_dict(), indent=2)
        atomic_write(index_file, content)

    def list_categories(self) -> List[TemplateCategory]:
        categories_file = self._base_path / self.CATEGORIES_FILE
        if not categories_file.exists():
            return TemplateCategory.builtin_categories()

        try:
            data = json.loads(categories_file.read_text(encoding="utf-8"))
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
        except (json.JSONDecodeError, KeyError) as e:
            log.error(f"Failed to load categories: {e}")
            return TemplateCategory.builtin_categories()

    def save_category(self, category: TemplateCategory):
        categories = self.list_categories()
        existing_idx = next(
            (i for i, c in enumerate(categories) if c.id == category.id),
            None
        )
        if existing_idx is not None:
            categories[existing_idx] = category
        else:
            categories.append(category)
        self._save_categories(categories)

    def delete_category(self, category_id: str) -> bool:
        categories = self.list_categories()
        categories = [c for c in categories if c.id != category_id]
        self._save_categories(categories)

        # Delete all templates in category
        if self._index:
            template_ids = self._index.get_ids_by_category(category_id)
            for tid in template_ids:
                self.delete_template(tid)
        return True

    def _save_categories(self, categories: List[TemplateCategory]):
        categories_file = self._base_path / self.CATEGORIES_FILE
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
        atomic_write(categories_file, json.dumps(data, indent=2))

    def list_templates(
        self,
        category_id: Optional[str] = None,
        modeling_language: Optional[str] = None,
    ) -> Iterator[DiagramTemplate]:
        for template_file in self._base_path.glob(f"*{self.TEMPLATE_EXTENSION}"):
            try:
                template = self._load_template_file(template_file)
                if category_id and template.category_id != category_id:
                    continue
                if modeling_language and template.modeling_language != modeling_language:
                    continue
                yield template
            except TemplateStorageError as e:
                log.warning(f"Skipping invalid template file {template_file}: {e}")

    def get_template(self, template_id: str) -> Optional[DiagramTemplate]:
        template_file = self._base_path / f"{template_id}{self.TEMPLATE_EXTENSION}"
        if not template_file.exists():
            return None
        return self._load_template_file(template_file)

    def save_template(self, template: DiagramTemplate):
        template.updated_at = datetime.now()

        template_file = self._base_path / f"{template.id}{self.TEMPLATE_EXTENSION}"
        data = template.to_dict()

        if template.thumbnail_data:
            thumb_file = self._base_path / f"{template.id}.png"
            atomic_write_bytes(thumb_file, template.thumbnail_data)
            data["has_thumbnail"] = True

        atomic_write(template_file, json.dumps(data, indent=2))

        # Update search index
        if self._index:
            self._index.add_entry(template)
            self._save_index()

    def delete_template(self, template_id: str) -> bool:
        template_file = self._base_path / f"{template_id}{self.TEMPLATE_EXTENSION}"
        thumb_file = self._base_path / f"{template_id}.png"

        if template_file.exists():
            template_file.unlink()
        if thumb_file.exists():
            thumb_file.unlink()

        # Update search index
        if self._index:
            self._index.remove_entry(template_id)
            self._save_index()

        return True

    def _load_template_file(self, path: Path) -> DiagramTemplate:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            template = DiagramTemplate.from_dict(data)

            if data.get("has_thumbnail"):
                thumb_file = path.with_suffix(".png")
                if thumb_file.exists():
                    template.thumbnail_data = thumb_file.read_bytes()

            return template
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            raise TemplateStorageError(f"Invalid template file: {e}") from e

    def import_template(self, source_path: Path) -> DiagramTemplate:
        if source_path.suffix == self.TEMPLATE_EXTENSION:
            template = self._load_template_file(source_path)
        elif source_path.suffix == ".gaphor":
            template = self._import_from_gaphor_file(source_path)
        else:
            raise TemplateStorageError(f"Unsupported file format: {source_path.suffix}")

        self.save_template(template)
        return template

    def _import_from_gaphor_file(self, path: Path) -> DiagramTemplate:
        content = path.read_text(encoding="utf-8")
        return DiagramTemplate.create_new(
            name=path.stem,
            description=f"Imported from {path.name}",
            category_id="custom",
            content=content,
        )

    def export_template(self, template_id: str, destination: Path):
        template = self.get_template(template_id)
        if not template:
            raise TemplateStorageError(f"Template not found: {template_id}")

        if destination.suffix == self.TEMPLATE_EXTENSION:
            data = template.to_dict()
            atomic_write(destination, json.dumps(data, indent=2))
        elif destination.suffix == ".gaphor":
            atomic_write(destination, template.content)
        else:
            raise TemplateStorageError(f"Unsupported export format: {destination.suffix}")

    def search_templates(
        self,
        query: str,
        category_id: Optional[str] = None,
        modeling_language: Optional[str] = None,
    ) -> List[DiagramTemplate]:
        if self._index:
            template_ids = self._index.search(query, category_id, modeling_language)
            results = []
            for tid in template_ids:
                template = self.get_template(tid)
                if template:
                    results.append(template)
            return results

        # Fallback to scanning all templates
        results = []
        for template in self.list_templates(category_id, modeling_language):
            if template.matches_search(query):
                results.append(template)
        return results

    def get_template_count(self, category_id: Optional[str] = None) -> int:
        if self._index and category_id:
            return len(self._index.get_ids_by_category(category_id))
        elif self._index:
            return len(self._index.entries)
        return sum(1 for _ in self.list_templates(category_id))

    def backup_storage(self, backup_path: Path):
        shutil.copytree(self._base_path, backup_path)

    def restore_storage(self, backup_path: Path):
        if self._base_path.exists():
            shutil.rmtree(self._base_path)
        shutil.copytree(backup_path, self._base_path)
        self._load_or_rebuild_index()

    def rebuild_search_index(self):
        """Force rebuild of the search index."""
        self._rebuild_index()

    def verify_index_integrity(self) -> bool:
        """Verify the search index matches actual template files."""
        if not self._index:
            return False

        # Check all indexed templates exist
        indexed_ids = set(self._index.entries.keys())
        actual_ids: Set[str] = set()

        for template_file in self._base_path.glob(f"*{self.TEMPLATE_EXTENSION}"):
            template_id = template_file.stem
            actual_ids.add(template_id)

        if indexed_ids != actual_ids:
            log.warning(f"Index mismatch: indexed={len(indexed_ids)}, actual={len(actual_ids)}")
            return False

        return True
