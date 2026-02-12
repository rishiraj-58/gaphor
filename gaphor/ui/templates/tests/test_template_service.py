"""Tests for the template service."""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
import tempfile
from pathlib import Path

from gaphor.ui.templates.template_model import (
    DiagramTemplate,
    TemplateCategory,
    TemplateParameter,
    TemplateParameterType,
)
from gaphor.ui.templates.template_service import (
    TemplateService,
    TemplateCreatedEvent,
    TemplateUpdatedEvent,
    TemplateDeletedEvent,
    TemplateAppliedEvent,
)
from gaphor.ui.templates.template_storage import (
    TemplateStorage,
    TemplateStorageError,
    TemplateNotFoundError,
)


@pytest.fixture
def mock_event_manager():
    """Create a mock event manager."""
    manager = MagicMock()
    manager.subscribe = MagicMock()
    manager.unsubscribe = MagicMock()
    manager.handle = MagicMock()
    return manager


@pytest.fixture
def mock_element_factory():
    """Create a mock element factory."""
    return MagicMock()


@pytest.fixture
def mock_modeling_language():
    """Create a mock modeling language service."""
    service = MagicMock()
    service.active_modeling_language = "UML"
    service.modeling_language = MagicMock()
    return service


@pytest.fixture
def temp_storage_dir():
    """Create a temporary directory for storage."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def template_service(mock_event_manager, mock_element_factory, mock_modeling_language, temp_storage_dir):
    """Create a template service with mock dependencies."""
    service = TemplateService(
        event_manager=mock_event_manager,
        element_factory=mock_element_factory,
        modeling_language=mock_modeling_language,
    )
    # Use temp storage
    service._storage = TemplateStorage(base_dir=temp_storage_dir)
    return service


class TestTemplateServiceBasics:
    """Basic tests for TemplateService."""

    def test_service_creation(self, template_service, mock_event_manager):
        assert template_service is not None
        mock_event_manager.subscribe.assert_called()

    def test_shutdown(self, template_service, mock_event_manager):
        template_service.shutdown()
        mock_event_manager.unsubscribe.assert_called()

    def test_storage_initialization(self, template_service):
        storage = template_service.storage
        assert storage is not None


class TestTemplateServiceCRUD:
    """Tests for CRUD operations."""

    def test_create_template(self, template_service, mock_event_manager):
        template = template_service.create_template(
            name="Test Template",
            description="A test template",
            template_data="<gaphor>test</gaphor>",
        )

        assert template is not None
        assert template.name == "Test Template"
        assert template.description == "A test template"
        assert template.modeling_language == "UML"

        # Event should be fired
        mock_event_manager.handle.assert_called()
        event_call = mock_event_manager.handle.call_args
        assert isinstance(event_call[0][0], TemplateCreatedEvent)

    def test_create_template_with_parameters(self, template_service):
        params = [
            TemplateParameter(name="class_name", default_value="MyClass"),
            TemplateParameter(name="attribute", required=True),
        ]

        template = template_service.create_template(
            name="Parameterized Template",
            template_data="<gaphor>${class_name}</gaphor>",
            parameters=params,
        )

        assert len(template.parameters) == 2
        assert template.parameters[0].name == "class_name"

    def test_create_template_invalid_raises(self, template_service):
        with pytest.raises(TemplateStorageError):
            template_service.create_template(
                name="",  # Empty name
                template_data="",  # Empty data
            )

    def test_get_template(self, template_service):
        created = template_service.create_template(
            name="Get Test",
            template_data="<gaphor/>",
        )

        retrieved = template_service.get_template(created.id)
        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.name == created.name

    def test_get_template_nonexistent(self, template_service):
        result = template_service.get_template("nonexistent-id")
        assert result is None

    def test_update_template(self, template_service, mock_event_manager):
        created = template_service.create_template(
            name="Original Name",
            template_data="<gaphor>original</gaphor>",
        )

        mock_event_manager.reset_mock()

        updated = template_service.update_template(
            created.id,
            name="Updated Name",
            description="Updated description",
        )

        assert updated.name == "Updated Name"
        assert updated.description == "Updated description"

        # Event should be fired
        event_call = mock_event_manager.handle.call_args
        assert isinstance(event_call[0][0], TemplateUpdatedEvent)

    def test_update_template_nonexistent_raises(self, template_service):
        with pytest.raises(TemplateNotFoundError):
            template_service.update_template(
                "nonexistent-id",
                name="New Name",
            )

    def test_update_builtin_template_raises(self, template_service):
        # Add a builtin template
        builtin = DiagramTemplate(
            id="builtin-test",
            name="Builtin",
            template_data="<gaphor/>",
            is_builtin=True,
        )
        template_service._builtin_templates[builtin.id] = builtin

        with pytest.raises(TemplateStorageError):
            template_service.update_template(
                builtin.id,
                name="Modified",
            )

    def test_delete_template(self, template_service, mock_event_manager):
        created = template_service.create_template(
            name="To Delete",
            template_data="<gaphor/>",
        )

        mock_event_manager.reset_mock()

        template_service.delete_template(created.id)

        # Verify deleted
        assert template_service.get_template(created.id) is None

        # Event should be fired
        event_call = mock_event_manager.handle.call_args
        assert isinstance(event_call[0][0], TemplateDeletedEvent)

    def test_delete_builtin_template_raises(self, template_service):
        builtin = DiagramTemplate(
            id="builtin-delete",
            name="Builtin",
            template_data="<gaphor/>",
            is_builtin=True,
        )
        template_service._builtin_templates[builtin.id] = builtin

        with pytest.raises(TemplateStorageError):
            template_service.delete_template(builtin.id)


class TestTemplateServiceListing:
    """Tests for listing and filtering templates."""

    def test_list_templates_empty(self, template_service):
        templates = template_service.list_templates(include_builtin=False)
        assert templates == []

    def test_list_templates(self, template_service):
        template_service.create_template(name="T1", template_data="<gaphor/>")
        template_service.create_template(name="T2", template_data="<gaphor/>")

        templates = template_service.list_templates(include_builtin=False)
        assert len(templates) == 2

    def test_list_templates_includes_builtin(self, template_service):
        # Add builtin template
        builtin = DiagramTemplate(
            id="builtin-list",
            name="Builtin",
            template_data="<gaphor/>",
            is_builtin=True,
        )
        template_service._builtin_templates[builtin.id] = builtin

        template_service.create_template(name="User", template_data="<gaphor/>")

        templates = template_service.list_templates(include_builtin=True)
        assert len(templates) == 2

        builtin_items = [t for t in templates if t.get("is_builtin")]
        assert len(builtin_items) == 1

    def test_list_templates_filter_category(self, template_service):
        template_service.create_template(
            name="Class T",
            template_data="<gaphor/>",
            category=TemplateCategory.CLASS_DIAGRAM,
        )
        template_service.create_template(
            name="Sequence T",
            template_data="<gaphor/>",
            category=TemplateCategory.SEQUENCE_DIAGRAM,
        )

        templates = template_service.list_templates(
            category=TemplateCategory.CLASS_DIAGRAM,
            include_builtin=False,
        )
        assert len(templates) == 1
        assert templates[0]["category"] == "class_diagram"

    def test_list_templates_filter_language(self, template_service):
        template_service.create_template(
            name="UML T",
            template_data="<gaphor/>",
            modeling_language="UML",
        )
        template_service.create_template(
            name="SysML T",
            template_data="<gaphor/>",
            modeling_language="SysML",
        )

        templates = template_service.list_templates(
            modeling_language="SysML",
            include_builtin=False,
        )
        assert len(templates) == 1
        assert templates[0]["modeling_language"] == "SysML"

    def test_list_templates_search(self, template_service):
        template_service.create_template(
            name="Customer Class",
            template_data="<gaphor/>",
        )
        template_service.create_template(
            name="Order Sequence",
            template_data="<gaphor/>",
        )

        templates = template_service.list_templates(
            search_query="customer",
            include_builtin=False,
        )
        assert len(templates) == 1
        assert "customer" in templates[0]["name"].lower()

    def test_get_categories(self, template_service):
        template_service.create_template(
            name="T1",
            template_data="<gaphor/>",
            category=TemplateCategory.CLASS_DIAGRAM,
        )
        template_service.create_template(
            name="T2",
            template_data="<gaphor/>",
            category=TemplateCategory.CLASS_DIAGRAM,
        )
        template_service.create_template(
            name="T3",
            template_data="<gaphor/>",
            category=TemplateCategory.SEQUENCE_DIAGRAM,
        )

        categories = template_service.get_categories()
        category_dict = dict(categories)

        assert category_dict[TemplateCategory.CLASS_DIAGRAM] == 2
        assert category_dict[TemplateCategory.SEQUENCE_DIAGRAM] == 1


class TestTemplateServiceApplication:
    """Tests for applying templates to diagrams."""

    def test_apply_template_basic(self, template_service, mock_event_manager):
        template = template_service.create_template(
            name="Apply Test",
            template_data="<gaphor><test/></gaphor>",
        )

        mock_diagram = MagicMock()
        mock_diagram.model = MagicMock()

        mock_event_manager.reset_mock()

        errors = template_service.apply_template(
            template.id,
            mock_diagram,
        )

        # The actual application may fail due to mock diagram,
        # but the service should attempt it

    def test_apply_template_with_parameters(self, template_service):
        template = template_service.create_template(
            name="Param Apply",
            template_data="<gaphor><class name='${class_name}'/></gaphor>",
            parameters=[
                TemplateParameter(name="class_name", default_value="Default"),
            ],
        )

        mock_diagram = MagicMock()
        mock_diagram.model = MagicMock()

        errors = template_service.apply_template(
            template.id,
            mock_diagram,
            parameter_values={"class_name": "Customer"},
        )

    def test_apply_template_validation_error(self, template_service):
        template = template_service.create_template(
            name="Validation Test",
            template_data="<gaphor>${count}</gaphor>",
            parameters=[
                TemplateParameter(
                    name="count",
                    param_type=TemplateParameterType.INTEGER,
                    min_value=0,
                    required=True,
                ),
            ],
        )

        mock_diagram = MagicMock()

        errors = template_service.apply_template(
            template.id,
            mock_diagram,
            parameter_values={"count": "-5"},  # Invalid: negative
        )

        assert len(errors) > 0

    def test_apply_nonexistent_template(self, template_service):
        mock_diagram = MagicMock()

        errors = template_service.apply_template(
            "nonexistent-id",
            mock_diagram,
        )

        assert len(errors) > 0
        assert "not found" in errors[0].lower()


class TestTemplateServiceValidation:
    """Tests for template validation."""

    def test_validate_template(self, template_service):
        template = template_service.create_template(
            name="Valid Template",
            template_data="<gaphor/>",
        )

        result = template_service.validate_template(template.id)
        assert result.is_valid

    def test_validate_template_strict(self, template_service):
        template = template_service.create_template(
            name="Strict Test",
            template_data="${undefined}",  # Undefined placeholder
            parameters=[],
        )

        result = template_service.validate_template(template.id, strict=True)
        assert not result.is_valid

    def test_validate_nonexistent_template(self, template_service):
        result = template_service.validate_template("nonexistent")
        assert not result.is_valid


class TestTemplateServiceImportExport:
    """Tests for import/export functionality."""

    def test_export_template(self, template_service, temp_storage_dir):
        template = template_service.create_template(
            name="Export Test",
            template_data="<gaphor/>",
        )

        export_path = temp_storage_dir / "exported.json"
        template_service.export_template(template.id, export_path)

        assert export_path.exists()

    def test_import_template(self, template_service, temp_storage_dir):
        # Create and export a template
        original = template_service.create_template(
            name="Import Test",
            template_data="<gaphor>import</gaphor>",
        )

        export_path = temp_storage_dir / "for_import.json"
        template_service.export_template(original.id, export_path)

        # Delete the original
        template_service.delete_template(original.id)

        # Import it back
        imported = template_service.import_template(export_path)
        assert imported.name == original.name

    def test_duplicate_template(self, template_service, mock_event_manager):
        original = template_service.create_template(
            name="Original",
            description="Original description",
            template_data="<gaphor/>",
            category=TemplateCategory.CLASS_DIAGRAM,
        )

        mock_event_manager.reset_mock()

        duplicated = template_service.duplicate_template(original.id)

        assert duplicated.id != original.id
        assert duplicated.name == "Original (Copy)"
        assert duplicated.description == original.description
        assert duplicated.category == original.category
        assert not duplicated.is_builtin

        # Event should be fired
        event_call = mock_event_manager.handle.call_args
        assert isinstance(event_call[0][0], TemplateCreatedEvent)

    def test_duplicate_template_custom_name(self, template_service):
        original = template_service.create_template(
            name="Original",
            template_data="<gaphor/>",
        )

        duplicated = template_service.duplicate_template(
            original.id,
            new_name="Custom Copy Name",
        )

        assert duplicated.name == "Custom Copy Name"

    def test_duplicate_builtin_template(self, template_service):
        builtin = DiagramTemplate(
            id="builtin-dup",
            name="Builtin",
            template_data="<gaphor/>",
            is_builtin=True,
        )
        template_service._builtin_templates[builtin.id] = builtin

        # Duplicating builtin should work (creates user copy)
        duplicated = template_service.duplicate_template(builtin.id)

        assert duplicated.id != builtin.id
        assert not duplicated.is_builtin


class TestTemplateServiceEvents:
    """Tests for event handling."""

    def test_events_subscribed_on_init(self, mock_event_manager, mock_element_factory, mock_modeling_language):
        service = TemplateService(
            event_manager=mock_event_manager,
            element_factory=mock_element_factory,
            modeling_language=mock_modeling_language,
        )

        assert mock_event_manager.subscribe.called

    def test_events_unsubscribed_on_shutdown(self, template_service, mock_event_manager):
        template_service.shutdown()
        assert mock_event_manager.unsubscribe.called


class TestTemplateServiceCategoryInference:
    """Tests for category inference from diagrams."""

    def test_infer_category_class(self, template_service):
        mock_diagram = MagicMock()
        mock_diagram.diagramType = "cls"

        category = template_service._infer_category_from_diagram(mock_diagram)
        assert category == TemplateCategory.CLASS_DIAGRAM

    def test_infer_category_sequence(self, template_service):
        mock_diagram = MagicMock()
        mock_diagram.diagramType = "sd"

        category = template_service._infer_category_from_diagram(mock_diagram)
        assert category == TemplateCategory.SEQUENCE_DIAGRAM

    def test_infer_category_sysml(self, template_service):
        mock_diagram = MagicMock()
        mock_diagram.diagramType = "bdd"

        category = template_service._infer_category_from_diagram(mock_diagram)
        assert category == TemplateCategory.SYSML

    def test_infer_category_unknown(self, template_service):
        mock_diagram = MagicMock()
        mock_diagram.diagramType = "unknown"

        category = template_service._infer_category_from_diagram(mock_diagram)
        assert category == TemplateCategory.GENERAL
