"""Template browser UI component using .ui definition files."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Dict, List, Optional

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, GObject, Gtk

from gaphor.abc import ActionProvider, Service
from gaphor.action import action
from gaphor.i18n import gettext, translated_ui_string
from gaphor.transaction import Transaction
from gaphor.ui.abc import UIComponent
from gaphor.ui.actiongroup import apply_action_group
from gaphor.ui.templatebrowser.preview import (
    TemplatePreviewGenerator,
    get_icon_for_category,
)
from gaphor.ui.templatebrowser.storage import TemplateStorage
from gaphor.ui.templatebrowser.template import (
    DiagramTemplate,
    ParameterType,
    TemplateCategory,
    TemplateParameter,
)
from gaphor.ui.templatebrowser.validation import (
    TemplateValidator,
    ValidationResult,
    validate_parameter_values,
)

if TYPE_CHECKING:
    from gaphor.core.modeling import Diagram, ElementFactory

log = logging.getLogger(__name__)

UI_PACKAGE = "gaphor.ui.templatebrowser"


def load_ui_string(ui_filename: str) -> str:
    """Load and translate a UI definition file."""
    return translated_ui_string(UI_PACKAGE, ui_filename)


def safe_get_builder_object(builder: Gtk.Builder, name: str) -> Optional[GObject.Object]:
    """Safely get an object from a builder, returning None if not found."""
    try:
        obj = builder.get_object(name)
        if obj is None:
            log.warning(f"UI object not found: {name}")
        return obj
    except Exception as e:
        log.error(f"Error getting UI object {name}: {e}")
        return None


class TemplateListItem(GObject.Object):
    """GObject wrapper for template list items."""

    __gtype_name__ = "TemplateListItem"

    def __init__(self, template: DiagramTemplate):
        super().__init__()
        self._template = template

    @GObject.Property(type=str)
    def id(self) -> str:
        return self._template.id if self._template else ""

    @GObject.Property(type=str)
    def name(self) -> str:
        return self._template.name if self._template else ""

    @GObject.Property(type=str)
    def description(self) -> str:
        return self._template.description if self._template else ""

    @GObject.Property(type=str)
    def category_id(self) -> str:
        return self._template.category_id if self._template else ""

    @GObject.Property(type=str)
    def modeling_language(self) -> str:
        return self._template.modeling_language if self._template else "UML"

    @property
    def template(self) -> Optional[DiagramTemplate]:
        return self._template


class CategoryListItem(GObject.Object):
    """GObject wrapper for category list items."""

    __gtype_name__ = "CategoryListItem"

    def __init__(self, category: TemplateCategory, count: int = 0):
        super().__init__()
        self._category = category
        self._count = count

    @GObject.Property(type=str)
    def id(self) -> str:
        return self._category.id if self._category else ""

    @GObject.Property(type=str)
    def name(self) -> str:
        return self._category.name if self._category else ""

    @GObject.Property(type=str)
    def icon(self) -> str:
        if self._category:
            return get_icon_for_category(self._category.id)
        return "folder-symbolic"

    @GObject.Property(type=int)
    def count(self) -> int:
        return self._count

    @property
    def category(self) -> Optional[TemplateCategory]:
        return self._category


class TemplateBrowser(UIComponent, ActionProvider):
    """Main template browser window."""

    def __init__(
        self,
        event_manager,
        element_factory: ElementFactory,
        modeling_language,
    ):
        self.event_manager = event_manager
        self.element_factory = element_factory
        self.modeling_language = modeling_language

        self._storage: Optional[TemplateStorage] = None
        self._validator: Optional[TemplateValidator] = None
        self._preview_generator: Optional[TemplatePreviewGenerator] = None

        self._window: Optional[Gtk.Window] = None
        self._builder: Optional[Gtk.Builder] = None
        self._category_store: Optional[Gio.ListStore] = None
        self._template_store: Optional[Gio.ListStore] = None
        self._selected_category: Optional[str] = None
        self._on_template_selected: Optional[Callable[[DiagramTemplate], None]] = None

    def _ensure_initialized(self):
        """Lazy initialization of storage and related components."""
        if self._storage is None:
            self._storage = TemplateStorage()
        if self._validator is None:
            self._validator = TemplateValidator()
        if self._preview_generator is None:
            self._preview_generator = TemplatePreviewGenerator(self.element_factory)

    def open(self) -> Gtk.Widget:
        """Open the template browser window."""
        if self._window:
            self._window.present()
            return self._window

        self._ensure_initialized()
        self._window = self._create_window()
        self._connect_signals()
        self._load_categories()
        self._load_templates()

        return self._window

    def close(self):
        """Close the template browser window."""
        if self._window:
            self._window.destroy()
            self._window = None
            self._builder = None

        if self._storage:
            self._storage.flush_index()

    def shutdown(self):
        """Shutdown the template browser service."""
        self.close()

    def _create_window(self) -> Gtk.Window:
        """Create the main browser window from UI definition."""
        self._builder = Gtk.Builder()
        try:
            ui_string = load_ui_string("templatebrowser.ui")
            self._builder.add_from_string(ui_string)
        except GLib.Error as e:
            log.error(f"Failed to load template browser UI: {e}")
            return self._create_fallback_window()

        window = safe_get_builder_object(self._builder, "template_browser_window")
        if not window:
            return self._create_fallback_window()

        self._setup_category_list()
        self._setup_template_grid()

        apply_action_group(self, "template", window)
        return window

    def _create_fallback_window(self) -> Gtk.Window:
        """Create a minimal fallback window if UI loading fails."""
        window = Gtk.Window()
        window.set_title(gettext("Template Browser"))
        window.set_default_size(900, 600)

        label = Gtk.Label(label=gettext("Failed to load template browser UI"))
        window.set_child(label)

        return window

    def _setup_category_list(self):
        """Setup the category list view."""
        category_list = safe_get_builder_object(self._builder, "category_list")
        if not category_list:
            return

        self._category_store = Gio.ListStore(item_type=CategoryListItem)
        selection = Gtk.SingleSelection(model=self._category_store)
        selection.connect("selection-changed", self._on_category_selected)

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._category_item_setup)
        factory.connect("bind", self._category_item_bind)

        category_list.set_model(selection)
        category_list.set_factory(factory)

    def _category_item_setup(self, factory, list_item):
        """Setup category list item widget."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(6)
        box.set_margin_bottom(6)

        icon = Gtk.Image()
        box.append(icon)

        label = Gtk.Label()
        label.set_hexpand(True)
        label.set_halign(Gtk.Align.START)
        box.append(label)

        count_label = Gtk.Label()
        count_label.add_css_class("dim-label")
        box.append(count_label)

        list_item.set_child(box)

    def _category_item_bind(self, factory, list_item):
        """Bind category data to list item widget."""
        item = list_item.get_item()
        if not item:
            return

        box = list_item.get_child()
        if not box:
            return

        children = self._get_box_children(box)
        if len(children) < 3:
            return

        icon, label, count_label = children[:3]
        icon.set_from_icon_name(item.icon)
        label.set_label(item.name)
        count_label.set_label(str(item.count))

    def _setup_template_grid(self):
        """Setup the template grid view."""
        template_grid = safe_get_builder_object(self._builder, "template_grid")
        if not template_grid:
            return

        self._template_store = Gio.ListStore(item_type=TemplateListItem)
        selection = Gtk.SingleSelection(model=self._template_store)
        selection.connect("selection-changed", self._on_template_selection_changed)

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._template_item_setup)
        factory.connect("bind", self._template_item_bind)

        template_grid.set_model(selection)
        template_grid.set_factory(factory)
        template_grid.connect("activate", self._on_template_activated)

    def _template_item_setup(self, factory, list_item):
        """Setup template grid item widget."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_size_request(160, 180)

        frame = Gtk.Frame()
        thumbnail = Gtk.Picture()
        thumbnail.set_size_request(150, 100)
        thumbnail.set_content_fit(Gtk.ContentFit.CONTAIN)
        frame.set_child(thumbnail)
        box.append(frame)

        name_label = Gtk.Label()
        name_label.set_ellipsize(3)
        name_label.set_max_width_chars(20)
        name_label.add_css_class("heading")
        box.append(name_label)

        desc_label = Gtk.Label()
        desc_label.set_ellipsize(3)
        desc_label.set_max_width_chars(25)
        desc_label.set_lines(2)
        desc_label.set_wrap(True)
        desc_label.add_css_class("dim-label")
        box.append(desc_label)

        lang_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        lang_box.set_halign(Gtk.Align.CENTER)
        lang_icon = Gtk.Image()
        lang_icon.set_pixel_size(16)
        lang_box.append(lang_icon)
        lang_label = Gtk.Label()
        lang_label.add_css_class("caption")
        lang_box.append(lang_label)
        box.append(lang_box)

        list_item.set_child(box)

    def _template_item_bind(self, factory, list_item):
        """Bind template data to grid item widget."""
        item = list_item.get_item()
        if not item or not item.template:
            return

        box = list_item.get_child()
        if not box:
            return

        children = self._get_box_children(box)
        if len(children) < 4:
            return

        frame, name_label, desc_label, lang_box = children[:4]

        thumbnail = frame.get_child()
        if thumbnail and self._preview_generator:
            try:
                thumb_data = self._preview_generator.generate_thumbnail(item.template)
                if thumb_data:
                    loader = GdkPixbuf.PixbufLoader()
                    loader.write(thumb_data)
                    loader.close()
                    pixbuf = loader.get_pixbuf()
                    if pixbuf:
                        texture = Gdk.Texture.new_for_pixbuf(pixbuf)
                        thumbnail.set_paintable(texture)
            except Exception as e:
                log.debug(f"Failed to load thumbnail: {e}")

        name_label.set_label(item.name or gettext("Unnamed"))
        desc_label.set_label(item.description or gettext("No description"))

        lang_children = self._get_box_children(lang_box)
        if len(lang_children) >= 2:
            lang_icon, lang_label = lang_children[:2]
            lang_icon.set_from_icon_name(item.modeling_language)
            lang_label.set_label(item.modeling_language)

    def _get_box_children(self, box: Gtk.Box) -> List[Gtk.Widget]:
        """Get all children of a box widget."""
        children = []
        child = box.get_first_child()
        while child:
            children.append(child)
            child = child.get_next_sibling()
        return children

    def _connect_signals(self):
        """Connect UI signals to handlers."""
        if not self._builder:
            return

        signal_handlers = {
            "search_entry": ("search-changed", self._on_search_changed),
            "new_template_button": ("clicked", self._on_new_template_clicked),
            "import_button": ("clicked", self._on_import_clicked),
            "add_category_button": ("clicked", self._on_add_category_clicked),
            "use_button": ("clicked", self._on_use_template_clicked),
            "edit_button": ("clicked", self._on_edit_template_clicked),
            "delete_button": ("clicked", self._on_delete_template_clicked),
            "export_button": ("clicked", self._on_export_clicked),
        }

        for widget_name, (signal_name, handler) in signal_handlers.items():
            widget = safe_get_builder_object(self._builder, widget_name)
            if widget:
                widget.connect(signal_name, handler)

        if self._window:
            self._window.connect("close-request", self._on_window_close_request)

    def _on_window_close_request(self, window):
        """Handle window close request."""
        self.close()
        return False

    def _load_categories(self):
        """Load categories into the list store."""
        if not self._category_store or not self._storage:
            return

        self._category_store.remove_all()

        all_item = CategoryListItem(
            TemplateCategory(
                id="__all__",
                name=gettext("All Templates"),
                icon="view-list-symbolic"
            ),
            count=self._storage.get_template_count()
        )
        self._category_store.append(all_item)

        for category in self._storage.list_categories():
            count = self._storage.get_template_count(category.id)
            self._category_store.append(CategoryListItem(category, count))

    def _load_templates(
        self,
        category_id: Optional[str] = None,
        search_query: str = ""
    ):
        """Load templates into the grid store."""
        if not self._template_store or not self._storage:
            return

        self._template_store.remove_all()

        actual_category = None if category_id == "__all__" else category_id

        try:
            if search_query:
                templates = self._storage.search_templates(search_query, actual_category)
            else:
                templates = list(self._storage.list_templates(actual_category))

            for template in templates:
                self._template_store.append(TemplateListItem(template))
        except Exception as e:
            log.error(f"Failed to load templates: {e}")

    def _on_category_selected(self, selection, position, n_items):
        """Handle category selection change."""
        item = selection.get_selected_item()
        if item:
            self._selected_category = item.id
            search_entry = safe_get_builder_object(self._builder, "search_entry")
            search_text = search_entry.get_text() if search_entry else ""
            self._load_templates(self._selected_category, search_text)

    def _on_search_changed(self, entry):
        """Handle search text change."""
        search_text = entry.get_text() if entry else ""
        self._load_templates(self._selected_category, search_text)

    def _on_template_selection_changed(self, selection, position, n_items):
        """Handle template selection change."""
        pass

    def _on_template_activated(self, grid_view, position):
        """Handle template double-click/activation."""
        self._on_use_template_clicked(None)

    def _get_selected_template(self) -> Optional[DiagramTemplate]:
        """Get the currently selected template."""
        template_grid = safe_get_builder_object(self._builder, "template_grid")
        if not template_grid:
            return None

        selection = template_grid.get_model()
        if not selection:
            return None

        item = selection.get_selected_item()
        return item.template if item else None

    def _on_new_template_clicked(self, button):
        """Handle new template button click."""
        dialog = TemplateEditorDialog(
            parent=self._window,
            storage=self._storage,
            validator=self._validator,
            on_save=self._on_template_saved,
        )
        dialog.present()

    def _on_edit_template_clicked(self, button):
        """Handle edit template button click."""
        template = self._get_selected_template()
        if not template:
            return

        dialog = TemplateEditorDialog(
            parent=self._window,
            storage=self._storage,
            validator=self._validator,
            template=template,
            on_save=self._on_template_saved,
        )
        dialog.present()

    def _on_template_saved(self, template: DiagramTemplate):
        """Handle template save completion."""
        self._load_categories()
        self._load_templates(self._selected_category)

    def _on_use_template_clicked(self, button):
        """Handle use template button click."""
        template = self._get_selected_template()
        if not template:
            return

        if template.parameters:
            dialog = ParameterDialog(
                parent=self._window,
                template=template,
                on_apply=lambda values: self._apply_template(template, values),
            )
            dialog.present()
        else:
            self._apply_template(template, {})

    def _apply_template(self, template: DiagramTemplate, values: Dict):
        """Apply a template with parameter values."""
        content = template.apply_parameters(values)

        if self._on_template_selected:
            self._on_template_selected(template)

        self.close()

    def _on_delete_template_clicked(self, button):
        """Handle delete template button click."""
        template = self._get_selected_template()
        if not template:
            return

        dialog = Gtk.AlertDialog()
        dialog.set_message(gettext("Delete Template?"))
        dialog.set_detail(
            gettext("Are you sure you want to delete '{name}'?").format(name=template.name)
        )
        dialog.set_buttons([gettext("Cancel"), gettext("Delete")])
        dialog.set_default_button(0)
        dialog.set_cancel_button(0)

        def on_response(dialog, result):
            try:
                response = dialog.choose_finish(result)
                if response == 1 and self._storage:
                    self._storage.delete_template(template.id)
                    self._load_categories()
                    self._load_templates(self._selected_category)
            except GLib.Error:
                pass

        dialog.choose(self._window, None, on_response)

    def _on_import_clicked(self, button):
        """Handle import button click."""
        dialog = Gtk.FileDialog()
        dialog.set_title(gettext("Import Template"))

        filter_all = Gtk.FileFilter()
        filter_all.set_name(gettext("Gaphor files"))
        filter_all.add_pattern("*.gaphor")
        filter_all.add_pattern("*.gaphor-template")

        filters = Gio.ListStore(item_type=Gtk.FileFilter)
        filters.append(filter_all)
        dialog.set_filters(filters)

        def on_response(dialog, result):
            try:
                file = dialog.open_finish(result)
                if file and self._storage:
                    path = Path(file.get_path())
                    self._storage.import_template(path)
                    self._load_categories()
                    self._load_templates(self._selected_category)
            except GLib.Error:
                pass
            except Exception as e:
                log.error(f"Failed to import template: {e}")

        dialog.open(self._window, None, on_response)

    def _on_export_clicked(self, button):
        """Handle export button click."""
        template = self._get_selected_template()
        if not template:
            return

        dialog = Gtk.FileDialog()
        dialog.set_title(gettext("Export Template"))
        dialog.set_initial_name(f"{template.name}.gaphor-template")

        def on_response(dialog, result):
            try:
                file = dialog.save_finish(result)
                if file and self._storage:
                    path = Path(file.get_path())
                    self._storage.export_template(template.id, path)
            except GLib.Error:
                pass
            except Exception as e:
                log.error(f"Failed to export template: {e}")

        dialog.save(self._window, None, on_response)

    def _on_add_category_clicked(self, button):
        """Handle add category button click."""
        dialog = CategoryDialog(
            parent=self._window,
            storage=self._storage,
            on_save=self._on_category_saved,
        )
        dialog.present()

    def _on_category_saved(self, category: TemplateCategory):
        """Handle category save completion."""
        self._load_categories()

    @action(name="template.browse", shortcut="<Primary>t")
    def browse_templates(self):
        """Open the template browser."""
        self.open()
        if self._window:
            self._window.present()

    def set_on_template_selected(self, callback: Callable[[DiagramTemplate], None]):
        """Set callback for template selection."""
        self._on_template_selected = callback


class TemplateEditorDialog(Gtk.Window):
    """Dialog for creating and editing templates."""

    def __init__(
        self,
        parent: Optional[Gtk.Window],
        storage: Optional[TemplateStorage],
        validator: Optional[TemplateValidator],
        template: Optional[DiagramTemplate] = None,
        on_save: Optional[Callable[[DiagramTemplate], None]] = None,
    ):
        super().__init__()
        self._storage = storage
        self._validator = validator
        self._template = template
        self._on_save = on_save
        self._parameters: List[TemplateParameter] = (
            list(template.parameters) if template else []
        )
        self._builder: Optional[Gtk.Builder] = None

        self._setup_window(parent)
        self._build_ui()
        if template:
            self._populate_from_template()

    def _setup_window(self, parent: Optional[Gtk.Window]):
        """Setup window properties."""
        title = gettext("Edit Template") if self._template else gettext("New Template")
        self.set_title(title)
        self.set_default_size(700, 600)
        self.set_modal(True)
        if parent:
            self.set_transient_for(parent)

    def _build_ui(self):
        """Build the editor UI from definition file."""
        self._builder = Gtk.Builder()
        try:
            ui_string = load_ui_string("templateeditor.ui")
            self._builder.add_from_string(ui_string)
        except GLib.Error as e:
            log.error(f"Failed to load template editor UI: {e}")
            self._build_fallback_ui()
            return

        editor_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        header = safe_get_builder_object(self._builder, "editor_header")
        if header:
            self.set_titlebar(header)
            cancel_btn = safe_get_builder_object(self._builder, "cancel_button")
            if cancel_btn:
                cancel_btn.connect("clicked", lambda b: self.close())
            save_btn = safe_get_builder_object(self._builder, "save_button")
            if save_btn:
                save_btn.connect("clicked", self._on_save_clicked)

        notebook = safe_get_builder_object(self._builder, "editor_notebook")
        if notebook:
            editor_box.append(notebook)

        validation_bar = safe_get_builder_object(self._builder, "validation_bar")
        if validation_bar:
            editor_box.append(validation_bar)

        self._setup_category_dropdown()
        self._setup_language_dropdown()
        self._connect_editor_signals()
        self._refresh_parameters_list()

        self.set_child(editor_box)

    def _build_fallback_ui(self):
        """Build a minimal fallback UI."""
        label = Gtk.Label(label=gettext("Failed to load editor UI"))
        self.set_child(label)

    def _setup_category_dropdown(self):
        """Setup the category dropdown."""
        dropdown = safe_get_builder_object(self._builder, "category_dropdown")
        if not dropdown or not self._storage:
            return

        categories = self._storage.list_categories()
        self._category_ids = [c.id for c in categories]
        category_names = [c.name for c in categories]
        dropdown.set_model(Gtk.StringList.new(category_names))

    def _setup_language_dropdown(self):
        """Setup the modeling language dropdown."""
        dropdown = safe_get_builder_object(self._builder, "language_dropdown")
        if not dropdown:
            return

        languages = ["UML", "SysML", "C4Model", "RAAML"]
        dropdown.set_model(Gtk.StringList.new(languages))

    def _connect_editor_signals(self):
        """Connect editor signals."""
        extract_btn = safe_get_builder_object(self._builder, "extract_params_button")
        if extract_btn:
            extract_btn.connect("clicked", self._on_extract_parameters)

        add_param_btn = safe_get_builder_object(self._builder, "add_param_button")
        if add_param_btn:
            add_param_btn.connect("clicked", self._on_add_parameter)

    def _refresh_parameters_list(self):
        """Refresh the parameters list display."""
        params_list = safe_get_builder_object(self._builder, "params_list")
        if not params_list:
            return

        while True:
            row = params_list.get_row_at_index(0)
            if not row:
                break
            params_list.remove(row)

        for i, param in enumerate(self._parameters):
            row = self._create_parameter_row(param, i)
            params_list.append(row)

    def _create_parameter_row(self, param: TemplateParameter, index: int) -> Gtk.Widget:
        """Create a parameter editor row."""
        row = Gtk.ListBoxRow()
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(6)
        box.set_margin_bottom(6)

        name_entry = Gtk.Entry()
        name_entry.set_text(param.name)
        name_entry.set_placeholder_text(gettext("Name"))
        name_entry.set_width_chars(15)
        name_entry.connect(
            "changed",
            lambda e: self._update_parameter(index, "name", e.get_text())
        )
        box.append(name_entry)

        type_combo = Gtk.DropDown()
        types = [t.value for t in ParameterType]
        type_combo.set_model(Gtk.StringList.new(types))
        try:
            type_combo.set_selected(types.index(param.param_type.value))
        except ValueError:
            type_combo.set_selected(0)
        type_combo.connect(
            "notify::selected",
            lambda c, p: self._update_parameter(
                index, "param_type", ParameterType(types[c.get_selected()])
            )
        )
        box.append(type_combo)

        default_entry = Gtk.Entry()
        default_entry.set_text(str(param.default_value or ""))
        default_entry.set_placeholder_text(gettext("Default"))
        default_entry.set_width_chars(12)
        default_entry.connect(
            "changed",
            lambda e: self._update_parameter(index, "default_value", e.get_text())
        )
        box.append(default_entry)

        required_check = Gtk.CheckButton(label=gettext("Required"))
        required_check.set_active(param.required)
        required_check.connect(
            "toggled",
            lambda c: self._update_parameter(index, "required", c.get_active())
        )
        box.append(required_check)

        remove_btn = Gtk.Button(icon_name="list-remove-symbolic")
        remove_btn.connect("clicked", lambda b: self._remove_parameter(index))
        box.append(remove_btn)

        row.set_child(box)
        return row

    def _update_parameter(self, index: int, field: str, value):
        """Update a parameter field."""
        if 0 <= index < len(self._parameters):
            setattr(self._parameters[index], field, value)

    def _remove_parameter(self, index: int):
        """Remove a parameter."""
        if 0 <= index < len(self._parameters):
            del self._parameters[index]
            self._refresh_parameters_list()

    def _on_add_parameter(self, button):
        """Handle add parameter button click."""
        param = TemplateParameter(
            name=f"param_{len(self._parameters) + 1}",
            param_type=ParameterType.STRING,
        )
        self._parameters.append(param)
        self._refresh_parameters_list()

    def _on_extract_parameters(self, button):
        """Extract parameters from content."""
        content_view = safe_get_builder_object(self._builder, "content_view")
        if not content_view:
            return

        buffer = content_view.get_buffer()
        content = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)

        temp_template = DiagramTemplate.create_new(
            name="temp",
            description="",
            category_id="custom",
            content=content,
        )
        temp_template.parameters = self._parameters
        self._parameters = temp_template.extract_parameters()
        self._refresh_parameters_list()

    def _populate_from_template(self):
        """Populate form from existing template."""
        if not self._template or not self._builder:
            return

        name_entry = safe_get_builder_object(self._builder, "name_entry")
        if name_entry:
            name_entry.set_text(self._template.name)

        desc_view = safe_get_builder_object(self._builder, "description_view")
        if desc_view:
            desc_view.get_buffer().set_text(self._template.description)

        category_dropdown = safe_get_builder_object(self._builder, "category_dropdown")
        if category_dropdown and hasattr(self, "_category_ids"):
            if self._template.category_id in self._category_ids:
                category_dropdown.set_selected(
                    self._category_ids.index(self._template.category_id)
                )

        language_dropdown = safe_get_builder_object(self._builder, "language_dropdown")
        if language_dropdown:
            languages = ["UML", "SysML", "C4Model", "RAAML"]
            if self._template.modeling_language in languages:
                language_dropdown.set_selected(
                    languages.index(self._template.modeling_language)
                )

        tags_entry = safe_get_builder_object(self._builder, "tags_entry")
        if tags_entry:
            tags_entry.set_text(", ".join(self._template.tags))

        content_view = safe_get_builder_object(self._builder, "content_view")
        if content_view:
            content_view.get_buffer().set_text(self._template.content)

    def _on_save_clicked(self, button):
        """Handle save button click."""
        name_entry = safe_get_builder_object(self._builder, "name_entry")
        name = name_entry.get_text().strip() if name_entry else ""

        desc_view = safe_get_builder_object(self._builder, "description_view")
        description = ""
        if desc_view:
            buffer = desc_view.get_buffer()
            description = buffer.get_text(
                buffer.get_start_iter(), buffer.get_end_iter(), False
            )

        category_dropdown = safe_get_builder_object(self._builder, "category_dropdown")
        category_idx = category_dropdown.get_selected() if category_dropdown else 0
        category_id = (
            self._category_ids[category_idx]
            if hasattr(self, "_category_ids") and category_idx < len(self._category_ids)
            else "custom"
        )

        language_dropdown = safe_get_builder_object(self._builder, "language_dropdown")
        lang_idx = language_dropdown.get_selected() if language_dropdown else 0
        languages = ["UML", "SysML", "C4Model", "RAAML"]
        modeling_language = languages[lang_idx] if lang_idx < len(languages) else "UML"

        tags_entry = safe_get_builder_object(self._builder, "tags_entry")
        tags_text = tags_entry.get_text() if tags_entry else ""
        tags = [t.strip() for t in tags_text.split(",") if t.strip()]

        content_view = safe_get_builder_object(self._builder, "content_view")
        content = ""
        if content_view:
            buffer = content_view.get_buffer()
            content = buffer.get_text(
                buffer.get_start_iter(), buffer.get_end_iter(), False
            )

        if self._template:
            template = self._template
            template.name = name
            template.description = description
            template.category_id = category_id
            template.modeling_language = modeling_language
            template.tags = tags
            template.content = content
            template.parameters = self._parameters
        else:
            template = DiagramTemplate.create_new(
                name=name,
                description=description,
                category_id=category_id,
                content=content,
                modeling_language=modeling_language,
            )
            template.tags = tags
            template.parameters = self._parameters

        if self._validator:
            result = self._validator.validate(template)
            if not result.is_valid:
                self._show_validation_errors(result)
                return

        if self._storage:
            self._storage.save_template(template)

        if self._on_save:
            self._on_save(template)

        self.close()

    def _show_validation_errors(self, result: ValidationResult):
        """Show validation errors in the UI."""
        validation_bar = safe_get_builder_object(self._builder, "validation_bar")
        validation_label = safe_get_builder_object(self._builder, "validation_label")

        if validation_bar and validation_label:
            errors = [e.message for e in result.errors]
            validation_label.set_text("\n".join(errors))
            validation_bar.set_revealed(True)


class ParameterDialog(Gtk.Window):
    """Dialog for entering template parameter values."""

    def __init__(
        self,
        parent: Optional[Gtk.Window],
        template: DiagramTemplate,
        on_apply: Optional[Callable[[Dict], None]] = None,
    ):
        super().__init__()
        self._template = template
        self._on_apply = on_apply
        self._entries: Dict[str, Gtk.Widget] = {}
        self._builder: Optional[Gtk.Builder] = None

        self._setup_window(parent)
        self._build_ui()

    def _setup_window(self, parent: Optional[Gtk.Window]):
        """Setup window properties."""
        self.set_title(gettext("Template Parameters"))
        self.set_default_size(400, 350)
        self.set_modal(True)
        if parent:
            self.set_transient_for(parent)

    def _build_ui(self):
        """Build the parameter dialog UI."""
        self._builder = Gtk.Builder()
        try:
            ui_string = load_ui_string("parameterdialog.ui")
            self._builder.add_from_string(ui_string)
        except GLib.Error as e:
            log.error(f"Failed to load parameter dialog UI: {e}")
            self._build_fallback_ui()
            return

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        header = safe_get_builder_object(self._builder, "param_dialog_header")
        if header:
            self.set_titlebar(header)
            cancel_btn = safe_get_builder_object(self._builder, "param_cancel_button")
            if cancel_btn:
                cancel_btn.connect("clicked", lambda b: self.close())
            apply_btn = safe_get_builder_object(self._builder, "param_apply_button")
            if apply_btn:
                apply_btn.connect("clicked", self._on_apply_clicked)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)

        list_box = safe_get_builder_object(self._builder, "param_input_list")
        if list_box:
            for param in self._template.parameters:
                row = self._create_parameter_input(param)
                list_box.append(row)
            scrolled.set_child(list_box)

        main_box.append(scrolled)

        validation_bar = safe_get_builder_object(self._builder, "param_validation_bar")
        if validation_bar:
            main_box.append(validation_bar)

        self.set_child(main_box)

    def _build_fallback_ui(self):
        """Build a minimal fallback UI."""
        label = Gtk.Label(label=gettext("Failed to load parameter dialog UI"))
        self.set_child(label)

    def _create_parameter_input(self, param: TemplateParameter) -> Gtk.Widget:
        """Create an input widget for a parameter."""
        row = Gtk.ListBoxRow()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(8)
        box.set_margin_bottom(8)

        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        name_label = Gtk.Label(label=param.name)
        name_label.add_css_class("heading")
        header_box.append(name_label)

        if param.required:
            required_label = Gtk.Label(label="*")
            required_label.add_css_class("error")
            header_box.append(required_label)

        box.append(header_box)

        if param.description:
            desc_label = Gtk.Label(label=param.description)
            desc_label.set_halign(Gtk.Align.START)
            desc_label.add_css_class("dim-label")
            box.append(desc_label)

        widget: Gtk.Widget
        if param.param_type == ParameterType.BOOLEAN:
            widget = Gtk.Switch()
            widget.set_halign(Gtk.Align.START)
            if param.default_value:
                widget.set_active(
                    str(param.default_value).lower() in ("true", "1", "yes")
                )
        elif param.param_type == ParameterType.CHOICE:
            widget = Gtk.DropDown()
            widget.set_model(Gtk.StringList.new(param.choices))
            if param.default_value and param.default_value in param.choices:
                widget.set_selected(param.choices.index(param.default_value))
        elif param.param_type == ParameterType.INTEGER:
            widget = Gtk.SpinButton()
            widget.set_range(-999999, 999999)
            widget.set_increments(1, 10)
            if param.default_value:
                try:
                    widget.set_value(int(param.default_value))
                except ValueError:
                    pass
        else:
            widget = Gtk.Entry()
            if param.default_value:
                widget.set_text(str(param.default_value))

        box.append(widget)
        self._entries[param.name] = widget

        row.set_child(box)
        return row

    def _on_apply_clicked(self, button):
        """Handle apply button click."""
        values = {}
        for param in self._template.parameters:
            widget = self._entries.get(param.name)
            if not widget:
                continue

            if param.param_type == ParameterType.BOOLEAN:
                values[param.name] = widget.get_active()
            elif param.param_type == ParameterType.CHOICE:
                idx = widget.get_selected()
                values[param.name] = (
                    param.choices[idx] if idx < len(param.choices) else ""
                )
            elif param.param_type == ParameterType.INTEGER:
                values[param.name] = int(widget.get_value())
            else:
                values[param.name] = widget.get_text()

        result = validate_parameter_values(self._template, values)
        if not result.is_valid:
            self._show_validation_errors(result)
            return

        if self._on_apply:
            self._on_apply(values)

        self.close()

    def _show_validation_errors(self, result: ValidationResult):
        """Show validation errors."""
        validation_bar = safe_get_builder_object(self._builder, "param_validation_bar")
        validation_label = safe_get_builder_object(
            self._builder, "param_validation_label"
        )

        if validation_bar and validation_label:
            errors = [e.message for e in result.errors]
            validation_label.set_text("\n".join(errors))
            validation_bar.set_revealed(True)


class CategoryDialog(Gtk.Window):
    """Dialog for creating and editing categories."""

    def __init__(
        self,
        parent: Optional[Gtk.Window],
        storage: Optional[TemplateStorage],
        category: Optional[TemplateCategory] = None,
        on_save: Optional[Callable[[TemplateCategory], None]] = None,
    ):
        super().__init__()
        self._storage = storage
        self._category = category
        self._on_save = on_save
        self._builder: Optional[Gtk.Builder] = None

        self._setup_window(parent)
        self._build_ui()
        if category:
            self._populate_from_category()

    def _setup_window(self, parent: Optional[Gtk.Window]):
        """Setup window properties."""
        title = (
            gettext("Edit Category") if self._category else gettext("New Category")
        )
        self.set_title(title)
        self.set_default_size(350, 220)
        self.set_modal(True)
        if parent:
            self.set_transient_for(parent)

    def _build_ui(self):
        """Build the category dialog UI."""
        self._builder = Gtk.Builder()
        try:
            ui_string = load_ui_string("categorydialog.ui")
            self._builder.add_from_string(ui_string)
        except GLib.Error as e:
            log.error(f"Failed to load category dialog UI: {e}")
            self._build_fallback_ui()
            return

        header = safe_get_builder_object(self._builder, "category_dialog_header")
        if header:
            self.set_titlebar(header)
            cancel_btn = safe_get_builder_object(self._builder, "category_cancel_button")
            if cancel_btn:
                cancel_btn.connect("clicked", lambda b: self.close())
            save_btn = safe_get_builder_object(self._builder, "category_save_button")
            if save_btn:
                save_btn.connect("clicked", self._on_save_clicked)

        grid = safe_get_builder_object(self._builder, "category_grid")
        if grid:
            self.set_child(grid)

    def _build_fallback_ui(self):
        """Build a minimal fallback UI."""
        label = Gtk.Label(label=gettext("Failed to load category dialog UI"))
        self.set_child(label)

    def _populate_from_category(self):
        """Populate form from existing category."""
        if not self._category or not self._builder:
            return

        name_entry = safe_get_builder_object(self._builder, "category_name_entry")
        if name_entry:
            name_entry.set_text(self._category.name)

        desc_entry = safe_get_builder_object(self._builder, "category_desc_entry")
        if desc_entry:
            desc_entry.set_text(self._category.description)

        icon_entry = safe_get_builder_object(self._builder, "category_icon_entry")
        if icon_entry:
            icon_entry.set_text(self._category.icon)

    def _on_save_clicked(self, button):
        """Handle save button click."""
        import uuid

        name_entry = safe_get_builder_object(self._builder, "category_name_entry")
        name = name_entry.get_text().strip() if name_entry else ""
        if not name:
            return

        desc_entry = safe_get_builder_object(self._builder, "category_desc_entry")
        description = desc_entry.get_text() if desc_entry else ""

        icon_entry = safe_get_builder_object(self._builder, "category_icon_entry")
        icon = icon_entry.get_text() if icon_entry else "folder-symbolic"
        if not icon:
            icon = "folder-symbolic"

        if self._category:
            category = TemplateCategory(
                id=self._category.id,
                name=name,
                description=description,
                icon=icon,
                parent_id=self._category.parent_id,
            )
        else:
            category = TemplateCategory(
                id=str(uuid.uuid4()),
                name=name,
                description=description,
                icon=icon,
            )

        if self._storage:
            self._storage.save_category(category)

        if self._on_save:
            self._on_save(category)

        self.close()
