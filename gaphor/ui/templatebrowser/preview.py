"""Preview generation for diagram templates."""

from __future__ import annotations

import io
import logging
from typing import TYPE_CHECKING, Optional

import cairo

if TYPE_CHECKING:
    from gaphor.core.modeling import Diagram, ElementFactory
    from gaphor.ui.templatebrowser.template import DiagramTemplate

log = logging.getLogger(__name__)

PREVIEW_WIDTH = 200
PREVIEW_HEIGHT = 150
PREVIEW_PADDING = 8


class TemplatePreviewGenerator:
    def __init__(self, element_factory: Optional[ElementFactory] = None):
        self._element_factory = element_factory

    def generate_thumbnail(
        self,
        template: DiagramTemplate,
        width: int = PREVIEW_WIDTH,
        height: int = PREVIEW_HEIGHT,
    ) -> Optional[bytes]:
        if template.thumbnail_data:
            return template.thumbnail_data

        try:
            return self._render_content_preview(template.content, width, height)
        except Exception as e:
            log.debug(f"Failed to generate thumbnail for template {template.id}: {e}")
            return self._generate_placeholder_thumbnail(template, width, height)

    def _render_content_preview(
        self,
        content: str,
        width: int,
        height: int,
    ) -> Optional[bytes]:
        return self._generate_placeholder_thumbnail(None, width, height)

    def _generate_placeholder_thumbnail(
        self,
        template: Optional[DiagramTemplate],
        width: int,
        height: int,
    ) -> bytes:
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        ctx = cairo.Context(surface)

        ctx.set_source_rgb(0.95, 0.95, 0.95)
        ctx.rectangle(0, 0, width, height)
        ctx.fill()

        ctx.set_source_rgb(0.8, 0.8, 0.8)
        ctx.set_line_width(1)
        ctx.rectangle(0.5, 0.5, width - 1, height - 1)
        ctx.stroke()

        self._draw_placeholder_content(ctx, width, height, template)

        output = io.BytesIO()
        surface.write_to_png(output)
        return output.getvalue()

    def _draw_placeholder_content(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        template: Optional[DiagramTemplate],
    ):
        ctx.set_source_rgb(0.6, 0.6, 0.6)

        box_w = width * 0.3
        box_h = height * 0.2

        positions = [
            (width * 0.2, height * 0.2),
            (width * 0.5, height * 0.2),
            (width * 0.35, height * 0.55),
        ]

        for x, y in positions:
            ctx.rectangle(x - box_w / 2, y - box_h / 2, box_w, box_h)
            ctx.stroke()

        ctx.set_line_width(1)
        ctx.move_to(positions[0][0], positions[0][1] + box_h / 2)
        ctx.line_to(positions[2][0], positions[2][1] - box_h / 2)
        ctx.stroke()

        ctx.move_to(positions[1][0], positions[1][1] + box_h / 2)
        ctx.line_to(positions[2][0], positions[2][1] - box_h / 2)
        ctx.stroke()

    def generate_preview_for_diagram(
        self,
        diagram: Diagram,
        width: int = PREVIEW_WIDTH,
        height: int = PREVIEW_HEIGHT,
    ) -> bytes:
        try:
            from gaphor.diagram.export import render, calc_bounding_box
            from gaphor.diagram.painter import ItemPainter
            from gaphor.core.modeling import StyleSheet

            items = list(diagram.get_all_items())
            if not items:
                return self._generate_placeholder_thumbnail(None, width, height)

            model = diagram.model
            style_sheet = model.style_sheet or StyleSheet()
            item_painter = ItemPainter(compute_style=style_sheet.compute_style)

            bounding_box = calc_bounding_box(items, item_painter)

            scale_x = (width - 2 * PREVIEW_PADDING) / max(bounding_box.width, 1)
            scale_y = (height - 2 * PREVIEW_PADDING) / max(bounding_box.height, 1)
            scale = min(scale_x, scale_y, 1.0)

            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
            ctx = cairo.Context(surface)

            ctx.set_source_rgb(1, 1, 1)
            ctx.paint()

            ctx.translate(PREVIEW_PADDING, PREVIEW_PADDING)
            ctx.scale(scale, scale)
            ctx.translate(-bounding_box.x, -bounding_box.y)

            item_painter.paint(items, ctx)

            output = io.BytesIO()
            surface.write_to_png(output)
            return output.getvalue()

        except Exception as e:
            log.warning(f"Failed to render diagram preview: {e}")
            return self._generate_placeholder_thumbnail(None, width, height)


def get_icon_for_modeling_language(modeling_language: str) -> str:
    icons = {
        "UML": "UML",
        "SysML": "SysML",
        "C4Model": "C4Model",
        "RAAML": "RAAML",
    }
    return icons.get(modeling_language, "org.gaphor.Gaphor")


def get_icon_for_category(category_id: str) -> str:
    icons = {
        "uml": "UML",
        "sysml": "SysML",
        "c4model": "C4Model",
        "raaml": "RAAML",
        "patterns": "emblem-symbolic-link",
        "custom": "folder-symbolic",
    }
    return icons.get(category_id, "folder-symbolic")
