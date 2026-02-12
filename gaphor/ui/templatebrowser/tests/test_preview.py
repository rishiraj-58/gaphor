"""Tests for template preview generation."""

import pytest

from gaphor.ui.templatebrowser.preview import (
    TemplatePreviewGenerator,
    get_icon_for_category,
    get_icon_for_modeling_language,
    PREVIEW_WIDTH,
    PREVIEW_HEIGHT,
)
from gaphor.ui.templatebrowser.template import DiagramTemplate


@pytest.fixture
def preview_generator():
    return TemplatePreviewGenerator()


@pytest.fixture
def sample_template():
    return DiagramTemplate.create_new(
        name="Test",
        description="Test template",
        category_id="uml",
        content="<gaphor/>",
        modeling_language="UML",
    )


class TestTemplatePreviewGenerator:
    def test_generate_placeholder_thumbnail(self, preview_generator, sample_template):
        thumb = preview_generator.generate_thumbnail(sample_template)
        assert thumb is not None
        assert isinstance(thumb, bytes)
        assert len(thumb) > 0

    def test_generate_thumbnail_with_custom_size(self, preview_generator, sample_template):
        thumb = preview_generator.generate_thumbnail(sample_template, width=100, height=75)
        assert thumb is not None
        assert isinstance(thumb, bytes)

    def test_use_cached_thumbnail(self, preview_generator, sample_template):
        cached_data = b"cached thumbnail data"
        sample_template.thumbnail_data = cached_data

        result = preview_generator.generate_thumbnail(sample_template)
        assert result == cached_data

    def test_placeholder_is_valid_png(self, preview_generator, sample_template):
        thumb = preview_generator.generate_thumbnail(sample_template)
        png_header = b'\x89PNG\r\n\x1a\n'
        assert thumb[:8] == png_header


class TestIconHelpers:
    def test_get_icon_for_modeling_language_uml(self):
        assert get_icon_for_modeling_language("UML") == "UML"

    def test_get_icon_for_modeling_language_sysml(self):
        assert get_icon_for_modeling_language("SysML") == "SysML"

    def test_get_icon_for_modeling_language_c4model(self):
        assert get_icon_for_modeling_language("C4Model") == "C4Model"

    def test_get_icon_for_modeling_language_unknown(self):
        icon = get_icon_for_modeling_language("Unknown")
        assert icon == "org.gaphor.Gaphor"

    def test_get_icon_for_category_uml(self):
        assert get_icon_for_category("uml") == "UML"

    def test_get_icon_for_category_custom(self):
        assert get_icon_for_category("custom") == "folder-symbolic"

    def test_get_icon_for_category_unknown(self):
        icon = get_icon_for_category("unknown-category")
        assert icon == "folder-symbolic"
