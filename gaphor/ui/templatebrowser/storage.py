"""Storage backend for diagram templates."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Iterator, List, Optional

from gaphor import settings
from gaphor.ui.templatebrowser.template import (
    DiagramTemplate,
    TemplateCategory,
)

log = logging.getLogger(__name__)


class TemplateStorageError(Exception):
    pass


class TemplateStorage:
    TEMPLATES_DIR = "templates"
    CATEGORIES_FILE = "categories.json"
    TEMPLATE_EXTENSION = ".gaphor-template"

    def __init__(self, base_path: Optional[Path] = None):
        self._base_path = base_path or self._default_storage_path()
        self._ensure_storage_exists()

    def _default_storage_path(self) -> Path:
        return settings.get_config_dir() / self.TEMPLATES_DIR

    def _ensure_storage_exists(self):
        self._base_path.mkdir(parents=True, exist_ok=True)
        categories_file = self._base_path / self.CATEGORIES_FILE
        if not categories_file.exists():
            self._save_categories(TemplateCategory.builtin_categories())

    @property
    def templates_path(self) -> Path:
        return self._base_path

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

        for template in self.list_templates(category_id=category_id):
            self.delete_template(template.id)
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
        categories_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

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
        from datetime import datetime
        template.updated_at = datetime.now()

        template_file = self._base_path / f"{template.id}{self.TEMPLATE_EXTENSION}"
        data = template.to_dict()

        if template.thumbnail_data:
            thumb_file = self._base_path / f"{template.id}.png"
            thumb_file.write_bytes(template.thumbnail_data)
            data["has_thumbnail"] = True

        template_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def delete_template(self, template_id: str) -> bool:
        template_file = self._base_path / f"{template_id}{self.TEMPLATE_EXTENSION}"
        thumb_file = self._base_path / f"{template_id}.png"

        if template_file.exists():
            template_file.unlink()
        if thumb_file.exists():
            thumb_file.unlink()
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
            destination.write_text(json.dumps(data, indent=2), encoding="utf-8")
        elif destination.suffix == ".gaphor":
            destination.write_text(template.content, encoding="utf-8")
        else:
            raise TemplateStorageError(f"Unsupported export format: {destination.suffix}")

    def search_templates(
        self,
        query: str,
        category_id: Optional[str] = None,
        modeling_language: Optional[str] = None,
    ) -> List[DiagramTemplate]:
        results = []
        for template in self.list_templates(category_id, modeling_language):
            if template.matches_search(query):
                results.append(template)
        return results

    def get_template_count(self, category_id: Optional[str] = None) -> int:
        return sum(1 for _ in self.list_templates(category_id))

    def backup_storage(self, backup_path: Path):
        shutil.copytree(self._base_path, backup_path)

    def restore_storage(self, backup_path: Path):
        if self._base_path.exists():
            shutil.rmtree(self._base_path)
        shutil.copytree(backup_path, self._base_path)
