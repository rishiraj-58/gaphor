"""Template service for managing diagram templates in Gaphor.

This module provides the main service interface for creating, managing,
and applying diagram templates with parametrized placeholders.
"""

from __future__ import annotations

import importlib.resources
import io
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from gaphor.abc import Service
from gaphor.core import event_handler
from gaphor.core.modeling import Diagram, ElementFactory
from gaphor.diagram.copypaste import copy_full, paste_full
from gaphor.diagram.export import render
from gaphor.event import SessionCreated

from gaphor.ui.templates.template_model import (
    DiagramTemplate,
    TemplateCategory,
    TemplateParameter,
    TemplateParameterType,
    TemplateValidationError,
    TemplateValidationResult,
)
from gaphor.ui.templates.template_storage import (
    TemplateStorage,
    TemplateStorageError,
    TemplateNotFoundError,
    TemplateCorruptedError,
)

if TYPE_CHECKING:
    from gaphor.core.eventmanager import EventManager
    from gaphor.services.modelinglanguage import ModelingLanguageService

log = logging.getLogger(__name__)

# Maximum thumbnail dimensions
THUMBNAIL_MAX_WIDTH = 256
THUMBNAIL_MAX_HEIGHT = 192


class TemplateCreatedEvent:
    """Event fired when a template is created."""

    def __init__(self, template: DiagramTemplate):
        self.template = template


class TemplateUpdatedEvent:
    """Event fired when a template is updated."""

    def __init__(self, template: DiagramTemplate):
        self.template = template


class TemplateDeletedEvent:
    """Event fired when a template is deleted."""

    def __init__(self, template_id: str):
        self.template_id = template_id


class TemplateAppliedEvent:
    """Event fired when a template is applied to a diagram."""

    def __init__(self, template: DiagramTemplate, diagram: Diagram):
        self.template = template
        self.diagram = diagram


class TemplateService(Service):
    """Service for managing diagram templates."""

    def __init__(
        self,
        event_manager: EventManager,
        element_factory: ElementFactory,
        modeling_language: ModelingLanguageService,
    ):
        self._event_manager = event_manager
        self._element_factory = element_factory
        self._modeling_language = modeling_language
        self._storage: TemplateStorage | None = None
        self._builtin_templates: dict[str, DiagramTemplate] = {}

        event_manager.subscribe(self._on_session_created)

    def shutdown(self) -> None:
        """Shutdown the template service."""
        self._event_manager.unsubscribe(self._on_session_created)
        self._storage = None
        self._builtin_templates.clear()

    @event_handler(SessionCreated)
    def _on_session_created(self, event: SessionCreated) -> None:
        """Initialize storage when a session is created."""
        self._initialize_storage()
        self._load_builtin_templates()

    def _initialize_storage(self) -> None:
        """Initialize the template storage."""
        try:
            self._storage = TemplateStorage()
        except Exception as e:
            log.error(f"Failed to initialize template storage: {e}")
            self._storage = None

    def _load_builtin_templates(self) -> None:
        """Load built-in templates from the templates directory."""
        self._builtin_templates.clear()

        try:
            templates_dir = importlib.resources.files("gaphor") / "templates"

            for resource in templates_dir.iterdir():
                if not resource.name.endswith(".gaphor"):
                    continue

                # Skip example files
                if "example" in resource.name.lower():
                    continue

                try:
                    with resource.open(encoding="utf-8") as f:
                        content = f.read()

                    template = self._create_builtin_template(resource.name, content)
                    if template:
                        self._builtin_templates[template.id] = template

                except Exception as e:
                    log.warning(f"Could not load builtin template {resource.name}: {e}")

        except Exception as e:
            log.warning(f"Could not load builtin templates: {e}")

    def _create_builtin_template(
        self, filename: str, content: str
    ) -> DiagramTemplate | None:
        """Create a builtin template from file content."""
        name = filename.replace(".gaphor", "").replace("-", " ").replace("_", " ").title()
        template_id = f"builtin_{filename.replace('.gaphor', '')}"

        # Determine category and language from filename
        category = TemplateCategory.GENERAL
        modeling_language = "UML"

        if "uml" in filename.lower():
            category = TemplateCategory.CLASS_DIAGRAM
            modeling_language = "UML"
        elif "sysml" in filename.lower():
            category = TemplateCategory.SYSML
            modeling_language = "SysML"
        elif "c4" in filename.lower():
            category = TemplateCategory.C4_MODEL
            modeling_language = "C4Model"
        elif "raaml" in filename.lower():
            category = TemplateCategory.RAAML
            modeling_language = "RAAML"

        return DiagramTemplate(
            id=template_id,
            name=name,
            description=f"Built-in {name} template",
            category=category,
            modeling_language=modeling_language,
            template_data=content,
            is_builtin=True,
            author="Gaphor",
            version="1.0.0",
        )

    @property
    def storage(self) -> TemplateStorage:
        """Get the template storage, initializing if needed."""
        if self._storage is None:
            self._initialize_storage()
        if self._storage is None:
            raise TemplateStorageError("Template storage not available")
        return self._storage

    def get_template(self, template_id: str) -> DiagramTemplate | None:
        """Get a template by ID.

        Checks builtin templates first, then user templates.
        """
        # Check builtin templates
        if template_id in self._builtin_templates:
            return self._builtin_templates[template_id]

        # Check user templates
        try:
            return self.storage.load(template_id)
        except (TemplateNotFoundError, TemplateCorruptedError) as e:
            log.debug(f"Template not found: {template_id}: {e}")
            return None
        except TemplateStorageError as e:
            log.error(f"Error loading template {template_id}: {e}")
            return None

    def list_templates(
        self,
        category: TemplateCategory | None = None,
        modeling_language: str | None = None,
        search_query: str | None = None,
        include_builtin: bool = True,
    ) -> list[dict[str, Any]]:
        """List all available templates with optional filtering."""
        results: list[dict[str, Any]] = []

        # Add builtin templates
        if include_builtin:
            for template in self._builtin_templates.values():
                # Apply filters
                if category and template.category != category:
                    continue
                if modeling_language and template.modeling_language != modeling_language:
                    continue

                if search_query:
                    search_lower = search_query.lower().strip()
                    name_lower = template.name.lower()
                    tags_lower = [t.lower() for t in template.tags]

                    if not (
                        search_lower in name_lower
                        or any(search_lower in tag for tag in tags_lower)
                    ):
                        continue

                results.append({
                    "id": template.id,
                    "name": template.name,
                    "category": template.category.value,
                    "modeling_language": template.modeling_language,
                    "tags": template.tags,
                    "is_builtin": True,
                    "updated_at": template.updated_at.isoformat(),
                })

        # Add user templates
        try:
            user_templates = self.storage.list_templates(
                category=category,
                modeling_language=modeling_language,
                search_query=search_query,
            )
            for t in user_templates:
                t["is_builtin"] = False
                results.append(t)
        except TemplateStorageError as e:
            log.warning(f"Could not list user templates: {e}")

        # Sort by name
        results.sort(key=lambda t: t.get("name", "").lower())
        return results

    def get_categories(self) -> list[tuple[TemplateCategory, int]]:
        """Get all categories with template counts."""
        counts: dict[TemplateCategory, int] = {}

        # Count builtin templates
        for template in self._builtin_templates.values():
            counts[template.category] = counts.get(template.category, 0) + 1

        # Count user templates
        try:
            user_counts = self.storage.get_categories_with_counts()
            for cat_value, count in user_counts.items():
                try:
                    cat = TemplateCategory.from_string(cat_value)
                    counts[cat] = counts.get(cat, 0) + count
                except ValueError:
                    pass
        except TemplateStorageError:
            pass

        # Return sorted list
        return sorted(counts.items(), key=lambda x: x[0].value)

    def create_template(
        self,
        name: str,
        description: str = "",
        category: TemplateCategory = TemplateCategory.GENERAL,
        modeling_language: str | None = None,
        template_data: str = "",
        parameters: list[TemplateParameter] | None = None,
        tags: list[str] | None = None,
        author: str = "",
    ) -> DiagramTemplate:
        """Create a new template."""
        if not modeling_language:
            modeling_language = self._modeling_language.active_modeling_language

        template = DiagramTemplate(
            id=str(uuid4()),
            name=name,
            description=description,
            category=category,
            modeling_language=modeling_language,
            template_data=template_data,
            parameters=parameters or [],
            tags=tags or [],
            author=author,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        validation = template.validate()
        if not validation:
            errors = "; ".join(e[1] for e in validation.errors)
            raise TemplateStorageError(f"Invalid template: {errors}")

        self.storage.save(template)
        self._event_manager.handle(TemplateCreatedEvent(template))
        return template

    def create_template_from_diagram(
        self,
        diagram: Diagram,
        name: str,
        description: str = "",
        category: TemplateCategory | None = None,
        parameters: list[TemplateParameter] | None = None,
        tags: list[str] | None = None,
    ) -> DiagramTemplate:
        """Create a template from an existing diagram."""
        if not diagram:
            raise TemplateStorageError("No diagram provided")

        # Export diagram to Gaphor format
        template_data = self._export_diagram_to_gaphor(diagram)
        if not template_data:
            raise TemplateStorageError("Could not export diagram")

        # Generate thumbnail
        thumbnail_data = self._generate_thumbnail(diagram)

        # Determine category if not provided
        if category is None:
            category = self._infer_category_from_diagram(diagram)

        template = DiagramTemplate(
            id=str(uuid4()),
            name=name,
            description=description,
            category=category,
            modeling_language=diagram.__class__.__modeling_language__ or "UML",
            template_data=template_data,
            parameters=parameters or [],
            tags=tags or [],
            thumbnail_data=thumbnail_data,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        validation = template.validate()
        if not validation:
            # Log warnings but don't fail
            for warning in validation.warnings:
                log.warning(f"Template warning: {warning[1]}")

            if not validation.is_valid:
                errors = "; ".join(e[1] for e in validation.errors)
                raise TemplateStorageError(f"Invalid template: {errors}")

        self.storage.save(template)
        self._event_manager.handle(TemplateCreatedEvent(template))
        return template

    def _export_diagram_to_gaphor(self, diagram: Diagram) -> str:
        """Export a diagram to Gaphor XML format."""
        try:
            from gaphor.storage.save import save
            from gaphor.storage.xmlwriter import XMLWriter

            # Create a minimal element factory with just the diagram elements
            output = io.StringIO()
            writer = XMLWriter(output)

            # Use copy_full to get all diagram data
            items = list(diagram.get_all_items())
            if not items:
                # Empty diagram - create minimal structure
                return f"""<?xml version="1.0" encoding="utf-8"?>
<gaphor xmlns="http://gaphor.sourceforge.net/model" version="3.0">
<Diagram id="{diagram.id}">
<name><val>{diagram.name or 'Template Diagram'}</val></name>
</Diagram>
</gaphor>"""

            # For a full export, we need to serialize the diagram
            # This is a simplified version - in production you'd use the full save logic
            output = io.StringIO()

            # Build XML representation
            output.write('<?xml version="1.0" encoding="utf-8"?>\n')
            output.write('<gaphor xmlns="http://gaphor.sourceforge.net/model" version="3.0">\n')

            # Add diagram
            output.write(f'<Diagram id="{diagram.id}">\n')
            output.write(f'<name><val>{diagram.name or "Template Diagram"}</val></name>\n')
            output.write('</Diagram>\n')

            # Add items (simplified - real implementation would be more complete)
            for item in items:
                if hasattr(item, 'id') and hasattr(item, '__class__'):
                    cls_name = item.__class__.__name__
                    output.write(f'<{cls_name} id="{item.id}">\n')
                    output.write(f'<diagram><ref refid="{diagram.id}"/></diagram>\n')
                    if hasattr(item, 'subject') and item.subject:
                        output.write(f'<subject><ref refid="{item.subject.id}"/></subject>\n')
                    output.write(f'</{cls_name}>\n')

            output.write('</gaphor>')
            return output.getvalue()

        except Exception as e:
            log.error(f"Failed to export diagram: {e}")
            return ""

    def _generate_thumbnail(self, diagram: Diagram) -> bytes | None:
        """Generate a PNG thumbnail for a diagram."""
        try:
            import cairo

            # Create a small surface for the thumbnail
            width = THUMBNAIL_MAX_WIDTH
            height = THUMBNAIL_MAX_HEIGHT

            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
            cr = cairo.Context(surface)

            # Fill with white background
            cr.set_source_rgb(1, 1, 1)
            cr.paint()

            # Render diagram (scaled to fit)
            items = list(diagram.get_all_items())
            if items:
                # Calculate bounding box
                from gaphor.diagram.export import calc_bounding_box
                from gaphor.diagram.painter import ItemPainter

                painter = ItemPainter()
                bbox = calc_bounding_box(items, painter)

                if bbox.width > 0 and bbox.height > 0:
                    # Calculate scale to fit
                    scale_x = (width - 16) / bbox.width
                    scale_y = (height - 16) / bbox.height
                    scale = min(scale_x, scale_y, 1.0)

                    # Center the content
                    cr.translate(8, 8)
                    cr.scale(scale, scale)
                    cr.translate(-bbox.x, -bbox.y)

                    painter.paint(items, cr)

            # Write to PNG bytes
            output = io.BytesIO()
            surface.write_to_png(output)
            return output.getvalue()

        except Exception as e:
            log.warning(f"Could not generate thumbnail: {e}")
            return None

    def _infer_category_from_diagram(self, diagram: Diagram) -> TemplateCategory:
        """Infer the template category from a diagram's type."""
        diagram_type = getattr(diagram, 'diagramType', '') or ''
        type_lower = diagram_type.lower()

        category_map = {
            'cls': TemplateCategory.CLASS_DIAGRAM,
            'class': TemplateCategory.CLASS_DIAGRAM,
            'seq': TemplateCategory.SEQUENCE_DIAGRAM,
            'sd': TemplateCategory.SEQUENCE_DIAGRAM,
            'uc': TemplateCategory.USE_CASE,
            'usecase': TemplateCategory.USE_CASE,
            'act': TemplateCategory.ACTIVITY,
            'activity': TemplateCategory.ACTIVITY,
            'stm': TemplateCategory.STATE_MACHINE,
            'state': TemplateCategory.STATE_MACHINE,
            'cmp': TemplateCategory.COMPONENT,
            'component': TemplateCategory.COMPONENT,
            'dep': TemplateCategory.DEPLOYMENT,
            'deployment': TemplateCategory.DEPLOYMENT,
            'pkg': TemplateCategory.PACKAGE,
            'package': TemplateCategory.PACKAGE,
            'com': TemplateCategory.COMMUNICATION,
            'communication': TemplateCategory.COMMUNICATION,
            'prf': TemplateCategory.PROFILE,
            'profile': TemplateCategory.PROFILE,
            'bdd': TemplateCategory.SYSML,
            'ibd': TemplateCategory.SYSML,
            'req': TemplateCategory.SYSML,
            'c4': TemplateCategory.C4_MODEL,
            'fta': TemplateCategory.RAAML,
            'stpa': TemplateCategory.RAAML,
        }

        for key, category in category_map.items():
            if key in type_lower:
                return category

        return TemplateCategory.GENERAL

    def update_template(
        self,
        template_id: str,
        name: str | None = None,
        description: str | None = None,
        category: TemplateCategory | None = None,
        template_data: str | None = None,
        parameters: list[TemplateParameter] | None = None,
        tags: list[str] | None = None,
    ) -> DiagramTemplate:
        """Update an existing template."""
        template = self.get_template(template_id)
        if template is None:
            raise TemplateNotFoundError(f"Template not found: {template_id}")

        if template.is_builtin:
            raise TemplateStorageError("Cannot modify builtin templates")

        # Update fields
        if name is not None:
            template.name = name
        if description is not None:
            template.description = description
        if category is not None:
            template.category = category
        if template_data is not None:
            template.template_data = template_data
        if parameters is not None:
            template.parameters = parameters
        if tags is not None:
            template.tags = tags

        template.updated_at = datetime.now(timezone.utc)

        validation = template.validate()
        if not validation:
            errors = "; ".join(e[1] for e in validation.errors)
            raise TemplateStorageError(f"Invalid template: {errors}")

        self.storage.save(template)
        self._event_manager.handle(TemplateUpdatedEvent(template))
        return template

    def delete_template(self, template_id: str) -> None:
        """Delete a template."""
        template = self.get_template(template_id)
        if template is None:
            raise TemplateNotFoundError(f"Template not found: {template_id}")

        if template.is_builtin:
            raise TemplateStorageError("Cannot delete builtin templates")

        self.storage.delete(template_id)
        self._event_manager.handle(TemplateDeletedEvent(template_id))

    def apply_template(
        self,
        template_id: str,
        target_diagram: Diagram,
        parameter_values: dict[str, str] | None = None,
    ) -> list[str]:
        """Apply a template to a diagram.

        Returns a list of errors if any occurred during application.
        """
        template = self.get_template(template_id)
        if template is None:
            return [f"Template not found: {template_id}"]

        errors: list[str] = []

        # Validate parameter values
        values = parameter_values or {}
        for param in template.parameters:
            value = values.get(param.name, param.default_value)
            is_valid, error_msg = param.validate_value(value)
            if not is_valid:
                errors.append(error_msg)

        if errors:
            return errors

        # Apply parameter substitutions
        processed_data, apply_errors = template.apply_parameters(values)
        if apply_errors:
            return apply_errors

        # Load the template data and add to diagram
        try:
            self._apply_template_data(processed_data, target_diagram)
        except Exception as e:
            log.error(f"Failed to apply template: {e}")
            return [f"Failed to apply template: {e}"]

        self._event_manager.handle(TemplateAppliedEvent(template, target_diagram))
        return []

    def _apply_template_data(self, template_data: str, target_diagram: Diagram) -> None:
        """Apply template data to a target diagram."""
        # This is a simplified implementation
        # In production, you'd parse the XML and create elements properly
        try:
            from gaphor.storage.parser import GaphorLoader, parse_generator
            from gaphor.storage.load import load_elements_generator

            # Parse the template data
            loader = GaphorLoader()
            data_io = io.StringIO(template_data)

            for _ in parse_generator(data_io, loader):
                pass

            elements = loader.elements

            if not elements:
                log.warning("No elements found in template data")
                return

            # Load elements into the model
            # Note: This is simplified - real implementation would need
            # to properly handle ID remapping and element relationships
            model = target_diagram.model
            modeling_language = self._modeling_language.modeling_language

            for _ in load_elements_generator(
                elements,
                model,
                modeling_language,
                loader.gaphor_version,
            ):
                pass

        except Exception as e:
            log.error(f"Error applying template data: {e}")
            raise

    def validate_template(
        self, template_id: str, strict: bool = False
    ) -> TemplateValidationResult:
        """Validate a template's structure and content."""
        template = self.get_template(template_id)
        if template is None:
            return TemplateValidationResult.failure([
                (TemplateValidationError.MISSING_ID, f"Template not found: {template_id}")
            ])

        return template.validate(strict=strict)

    def export_template(self, template_id: str, export_path: Path) -> None:
        """Export a template to a file."""
        template = self.get_template(template_id)
        if template is None:
            raise TemplateNotFoundError(f"Template not found: {template_id}")

        self.storage.export_template(template_id, export_path)

    def import_template(
        self, import_path: Path, overwrite: bool = False
    ) -> DiagramTemplate:
        """Import a template from a file."""
        return self.storage.import_template(import_path, overwrite=overwrite)

    def duplicate_template(
        self, template_id: str, new_name: str | None = None
    ) -> DiagramTemplate:
        """Create a copy of an existing template."""
        template = self.get_template(template_id)
        if template is None:
            raise TemplateNotFoundError(f"Template not found: {template_id}")

        new_template = DiagramTemplate(
            id=str(uuid4()),
            name=new_name or f"{template.name} (Copy)",
            description=template.description,
            category=template.category,
            modeling_language=template.modeling_language,
            template_data=template.template_data,
            parameters=list(template.parameters),
            tags=list(template.tags),
            thumbnail_data=template.thumbnail_data,
            author=template.author,
            version=template.version,
            is_builtin=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        self.storage.save(new_template)
        self._event_manager.handle(TemplateCreatedEvent(new_template))
        return new_template
