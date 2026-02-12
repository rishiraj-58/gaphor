"""Template browser UI component using .ui files for layout."""

from __future__ import annotations

import logging
import uuid
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


def new_builder(ui_file: str) -> Gtk.Builder:
    builder = Gtk.Builder()
    builder.add_from_string(translated_ui_string("gaphor.ui.templatebrowser", f"{ui_file}.ui"))
    return builder


class TemplateListItem(GObject.Object):
    __gtype_name__ = "TemplateListItem"

    def __init__(self, template: DiagramTemplate):
        super().__init__()
        self._template = template

    @GObject.Property(type=str)
    def id(self) -> str:
        return self._template.id

    @GObject.Property(type=str)
    def name(self) -> str:
        return self._template.name

    @GObject.Property(type=str)
    def description(self) -> str:
        return self._template.description

    @GObject.Property(type=str)
    def category_id(self) -> str:
        return self._template.category_id

    @GObject.Property(type=str)
    def modeling_language(self) -> str:
        return self._template.modeling_language

    @property
    def template(self) -> DiagramTemplate:
        return self._template


class CategoryListItem(GObject.Object):
    __gtype_name__ = "CategoryListItem"

    def __init__(self, category: TemplateCategory, count: int = 0):
        super().__init__()
        self._category = category
        self._count = count

    @GObject.Property(type=str)
    def id(self) -> str:
        return self._category.id

    @GObject.Property(type=str)
    def name(self) -> str:
        return self._category.name

    @GObject.Property(type=str)
    def icon(self) -> str:
        return self._category.icon

    @GObject.Property(type=int)
    def count(self) -> int:
        return self._count

    @property
    def category(self) -> TemplateCategory:
        return self._category


class TemplateBrowser(UIComponent, ActionProvider):
    def __init__(
        self,
        event_manager,
        element_factory: ElementFactory,
        modeling_language,
    ):
        self.event_manager = event_manager
        self.element_factory = element_factory
        self.modeling_language = modeling_language

        self._storage = TemplateStorage()
        self._validator = TemplateValidator()
        self._preview_generator = TemplatePreviewGenerator(element_factory)

        self._window: Optional[Gtk.Window] = None
        self._builder: Optional[Gtk.Builder] = None
        self._category_store: Optional[Gio.ListStore] = None
        self._template_store: Optional[Gio.ListStore] = None
        self._selected_category: Optional[str] = None

        self._on_template_selected: Optional[Callable[[DiagramTemplate], None]] = None

    def open(self) -> Gtk.Widget:
        if self._window:
            self._window.present()
            return self._window

        self._builder = new_builder("templatebrowser")
        self._window = self._builder.get_object("template-browser-window")

        self._setup_category_list()
        self._setup_template_grid()
        self._connect_signals()

        self._load_categories()
        self._load_templates()

        apply_action_group(self, "template", self._window)

        return self._window

    def close(self):
        if self._window:
            self._window.destroy()
            self._window = None
            self._builder = None

    def shutdown(self):
        self.close()

    def _setup_category_list(self):
        self._category_store = Gio.ListStore(item_type=CategoryListItem)
        selection = Gtk.SingleSelection(model=self._category_store)
        selection.connect("selection-changed", self._on_category_selected)

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._category_item_setup)
        factory.connect("bind", self._category_item_bind)

        category_list = self._builder.get_object("category-list")
        category_list.set_model(selection)
        category_list.set_factory(factory)

    def _category_item_setup(self, factory, list_item):
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
        item = list_item.get_item()
        box = list_item.get_child()
        children = list(self._get_children(box))

        icon, label, count_label = children
        icon.set_from_icon_name(get_icon_for_category(item.id))
        label.set_label(item.name)
        count_label.set_label(str(item.count))

    def _setup_template_grid(self):
        self._template_store = Gio.ListStore(item_type=TemplateListItem)
        selection = Gtk.SingleSelection(model=self._template_store)
        selection.connect("selection-changed", self._on_template_selection_changed)

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._template_item_setup)
        factory.connect("bind", self._template_item_bind)

        template_grid = self._builder.get_object("template-grid")
        template_grid.set_model(selection)
        template_grid.set_factory(factory)
        template_grid.connect("activate", self._on_template_activated)

    def _template_item_setup(self, factory, list_item):
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
        item = list_item.get_item()
        box = list_item.get_child()

        children = list(self._get_children(box))
        frame, name_label, desc_label, lang_box = children
        thumbnail = frame.get_child()

        thumb_data = self._preview_generator.generate_thumbnail(item.template)
        if thumb_data:
            try:
                loader = GdkPixbuf.PixbufLoader()
                loader.write(thumb_data)
                loader.close()
                pixbuf = loader.get_pixbuf()
                texture = Gdk.Texture.new_for_pixbuf(pixbuf)
                thumbnail.set_paintable(texture)
            except GLib.Error as e:
                log.debug(f"Failed to load thumbnail: {e}")

        name_label.set_label(item.name)
        desc_label.set_label(item.description or gettext("No description"))

        lang_children = list(self._get_children(lang_box))
        lang_icon, lang_label = lang_children
        lang_icon.set_from_icon_name(item.modeling_language)
        lang_label.set_label(item.modeling_language)

    def _get_children(self, widget):
        child = widget.get_first_child()
        while child:
            yield child
            child = child.get_next_sibling()

    def _connect_signals(self):
        self._builder.get_object("search-entry").connect(
            "search-changed", self._on_search_changed
        )
        self._builder.get_object("new-template-button").connect(
            "clicked", self._on_new_template_clicked
        )
        self._builder.get_object("import-button").connect(
            "clicked", self._on_import_clicked
        )
        self._builder.get_object("add-category-button").connect(
            "clicked", self._on_add_category_clicked
        )
        self._builder.get_object("use-template-button").connect(
            "clicked", self._on_use_template_clicked
        )
        self._builder.get_object("edit-button").connect(
            "clicked", self._on_edit_template_clicked
        )
        self._builder.get_object("delete-button").connect(
            "clicked", self._on_delete_template_clicked
        )
        self._builder.get_object("export-button").connect(
            "clicked", self._on_export_clicked
        )

    def _load_categories(self):
        if not self._category_store:
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

    def _load_templates(self, category_id: Optional[str] = None, search_query: str = ""):
        if not self._template_store:
            return

        self._template_store.remove_all()

        actual_category = None if category_id == "__all__" else category_id

        if search_query:
            templates = self._storage.search_templates(search_query, actual_category)
        else:
            templates = list(self._storage.list_templates(actual_category))

        for template in templates:
            self._template_store.append(TemplateListItem(template))

    def _on_category_selected(self, selection, position, n_items):
        item = selection.get_selected_item()
        if item:
            self._selected_category = item.id
            search_entry = self._builder.get_object("search-entry")
            search_text = search_entry.get_text() if search_entry else ""
            self._load_templates(self._selected_category, search_text)

    def _on_search_changed(self, entry):
        search_text = entry.get_text()
        self._load_templates(self._selected_category, search_text)

    def _on_template_selection_changed(self, selection, position, n_items):
        pass

    def _on_template_activated(self, grid_view, position):
        self._on_use_template_clicked(None)

    def _get_selected_template(self) -> Optional[DiagramTemplate]:
        template_grid = self._builder.get_object("template-grid")
        selection = template_grid.get_model()
        item = selection.get_selected_item()
        return item.template if item else None

    def _on_new_template_clicked(self, button):
        dialog = TemplateEditorDialog(
            self._window,
            self._storage,
            self._validator,
            on_save=self._on_template_saved,
        )
        dialog.present()

    def _on_edit_template_clicked(self, button):
        template = self._get_selected_template()
        if not template:
            return

        dialog = TemplateEditorDialog(
            self._window,
            self._storage,
            self._validator,
            template=template,
            on_save=self._on_template_saved,
        )
        dialog.present()

    def _on_template_saved(self, template: DiagramTemplate):
        self._load_categories()
        self._load_templates(self._selected_category)

    def _on_use_template_clicked(self, button):
        template = self._get_selected_template()
        if not template:
            return

        if template.parameters:
            dialog = ParameterDialog(
                self._window,
                template,
                on_apply=lambda values: self._apply_template(template, values),
            )
            dialog.present()
        else:
            self._apply_template(template, {})

    def _apply_template(self, template: DiagramTemplate, values: dict):
        content = template.apply_parameters(values)

        if self._on_template_selected:
            self._on_template_selected(template)

        self.close()

    def _on_delete_template_clicked(self, button):
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
                if response == 1:
                    self._storage.delete_template(template.id)
                    self._load_categories()
                    self._load_templates(self._selected_category)
            except GLib.Error:
                pass

        dialog.choose(self._window, None, on_response)

    def _on_import_clicked(self, button):
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
                if file:
                    from pathlib import Path
                    path = Path(file.get_path())
                    self._storage.import_template(path)
                    self._load_categories()
                    self._load_templates(self._selected_category)
            except GLib.Error:
                pass

        dialog.open(self._window, None, on_response)

    def _on_export_clicked(self, button):
        template = self._get_selected_template()
        if not template:
            return

        dialog = Gtk.FileDialog()
        dialog.set_title(gettext("Export Template"))
        dialog.set_initial_name(f"{template.name}.gaphor-template")

        def on_response(dialog, result):
            try:
                file = dialog.save_finish(result)
                if file:
                    from pathlib import Path
                    path = Path(file.get_path())
                    self._storage.export_template(template.id, path)
            except GLib.Error:
                pass

        dialog.save(self._window, None, on_response)

    def _on_add_category_clicked(self, button):
        dialog = CategoryDialog(
            self._window,
            self._storage,
            on_save=self._on_category_saved,
        )
        dialog.present()

    def _on_category_saved(self, category: TemplateCategory):
        self._load_categories()

    @action(name="template.browse", shortcut="<Primary>t")
    def browse_templates(self):
        self.open()
        if self._window:
            self._window.present()

    def set_on_template_selected(self, callback: Callable[[DiagramTemplate], None]):
        self._on_template_selected = callback


class TemplateEditorDialog:
    def __init__(
        self,
        parent: Optional[Gtk.Window],
        storage: TemplateStorage,
        validator: TemplateValidator,
        template: Optional[DiagramTemplate] = None,
        on_save: Optional[Callable[[DiagramTemplate], None]] = None,
    ):
        self._storage = storage
        self._validator = validator
        self._template = template
        self._on_save = on_save
        self._parameters: List[TemplateParameter] = list(template.parameters) if template else []

        self._builder = new_builder("templateeditor")
        self._window = self._builder.get_object("template-editor-window")

        if parent:
            self._window.set_transient_for(parent)

        title = gettext("Edit Template") if template else gettext("New Template")
        self._window.set_title(title)

        self._setup_dropdowns()
        self._connect_signals()

        if template:
            self._populate_from_template()

        self._refresh_parameters_list()

    def _setup_dropdowns(self):
        categories = self._storage.list_categories()
        category_names = [c.name for c in categories]
        self._category_ids = [c.id for c in categories]

        category_dropdown = self._builder.get_object("category-dropdown")
        category_dropdown.set_model(Gtk.StringList.new(category_names))

        languages = ["UML", "SysML", "C4Model", "RAAML"]
        language_dropdown = self._builder.get_object("language-dropdown")
        language_dropdown.set_model(Gtk.StringList.new(languages))

    def _connect_signals(self):
        self._builder.get_object("cancel-button").connect(
            "clicked", lambda b: self._window.close()
        )
        self._builder.get_object("save-button").connect(
            "clicked", self._on_save_clicked
        )
        self._builder.get_object("extract-params-button").connect(
            "clicked", self._on_extract_parameters
        )
        self._builder.get_object("add-param-button").connect(
            "clicked", self._on_add_parameter
        )

    def _populate_from_template(self):
        if not self._template:
            return

        self._builder.get_object("name-entry").set_text(self._template.name)

        desc_view = self._builder.get_object("description-view")
        desc_view.get_buffer().set_text(self._template.description)

        if self._template.category_id in self._category_ids:
            idx = self._category_ids.index(self._template.category_id)
            self._builder.get_object("category-dropdown").set_selected(idx)

        languages = ["UML", "SysML", "C4Model", "RAAML"]
        if self._template.modeling_language in languages:
            idx = languages.index(self._template.modeling_language)
            self._builder.get_object("language-dropdown").set_selected(idx)

        self._builder.get_object("tags-entry").set_text(", ".join(self._template.tags))

        content_view = self._builder.get_object("content-view")
        content_view.get_buffer().set_text(self._template.content)

    def _refresh_parameters_list(self):
        params_list = self._builder.get_object("parameters-list")

        # Remove all existing rows
        while row := params_list.get_row_at_index(0):
            params_list.remove(row)

        for i, param in enumerate(self._parameters):
            row = self._create_parameter_row(param, i)
            params_list.append(row)

    def _create_parameter_row(self, param: TemplateParameter, index: int) -> Gtk.Widget:
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
        name_entry.connect("changed", lambda e: self._update_parameter(index, "name", e.get_text()))
        box.append(name_entry)

        type_combo = Gtk.DropDown()
        types = [t.value for t in ParameterType]
        type_combo.set_model(Gtk.StringList.new(types))
        type_combo.set_selected(types.index(param.param_type.value))
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
            "changed", lambda e: self._update_parameter(index, "default_value", e.get_text())
        )
        box.append(default_entry)

        required_check = Gtk.CheckButton(label=gettext("Required"))
        required_check.set_active(param.required)
        required_check.connect(
            "toggled", lambda c: self._update_parameter(index, "required", c.get_active())
        )
        box.append(required_check)

        remove_btn = Gtk.Button(icon_name="list-remove-symbolic")
        remove_btn.connect("clicked", lambda b: self._remove_parameter(index))
        box.append(remove_btn)

        row.set_child(box)
        return row

    def _update_parameter(self, index: int, field: str, value):
        if 0 <= index < len(self._parameters):
            setattr(self._parameters[index], field, value)

    def _remove_parameter(self, index: int):
        if 0 <= index < len(self._parameters):
            del self._parameters[index]
            self._refresh_parameters_list()

    def _on_add_parameter(self, button):
        param = TemplateParameter(
            name=f"param_{len(self._parameters) + 1}",
            param_type=ParameterType.STRING,
        )
        self._parameters.append(param)
        self._refresh_parameters_list()

    def _on_extract_parameters(self, button):
        content_view = self._builder.get_object("content-view")
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

    def _on_save_clicked(self, button):
        name = self._builder.get_object("name-entry").get_text().strip()

        desc_view = self._builder.get_object("description-view")
        desc_buffer = desc_view.get_buffer()
        description = desc_buffer.get_text(
            desc_buffer.get_start_iter(), desc_buffer.get_end_iter(), False
        )

        category_idx = self._builder.get_object("category-dropdown").get_selected()
        category_id = (
            self._category_ids[category_idx]
            if category_idx < len(self._category_ids)
            else "custom"
        )

        lang_idx = self._builder.get_object("language-dropdown").get_selected()
        languages = ["UML", "SysML", "C4Model", "RAAML"]
        modeling_language = languages[lang_idx] if lang_idx < len(languages) else "UML"

        tags = [
            t.strip()
            for t in self._builder.get_object("tags-entry").get_text().split(",")
            if t.strip()
        ]

        content_view = self._builder.get_object("content-view")
        content_buffer = content_view.get_buffer()
        content = content_buffer.get_text(
            content_buffer.get_start_iter(), content_buffer.get_end_iter(), False
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

        result = self._validator.validate(template)
        if not result.is_valid:
            self._show_validation_errors(result)
            return

        self._storage.save_template(template)

        if self._on_save:
            self._on_save(template)

        self._window.close()

    def _show_validation_errors(self, result: ValidationResult):
        errors = [e.message for e in result.errors]
        validation_label = self._builder.get_object("validation-label")
        validation_label.set_text("\n".join(errors))

        validation_bar = self._builder.get_object("validation-bar")
        validation_bar.set_revealed(True)

    def present(self):
        self._window.present()


class ParameterDialog:
    def __init__(
        self,
        parent: Optional[Gtk.Window],
        template: DiagramTemplate,
        on_apply: Optional[Callable[[dict], None]] = None,
    ):
        self._template = template
        self._on_apply = on_apply
        self._entries: Dict[str, Gtk.Widget] = {}

        self._builder = new_builder("parameterdialog")
        self._window = self._builder.get_object("parameter-dialog-window")

        if parent:
            self._window.set_transient_for(parent)

        self._connect_signals()
        self._build_parameter_inputs()

    def _connect_signals(self):
        self._builder.get_object("cancel-button").connect(
            "clicked", lambda b: self._window.close()
        )
        self._builder.get_object("apply-button").connect(
            "clicked", self._on_apply_clicked
        )

    def _build_parameter_inputs(self):
        params_list = self._builder.get_object("parameters-list")

        for param in self._template.parameters:
            row = self._create_parameter_input(param)
            params_list.append(row)

    def _create_parameter_input(self, param: TemplateParameter) -> Gtk.Widget:
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
                widget.set_active(str(param.default_value).lower() in ("true", "1", "yes"))
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
        values = {}
        for param in self._template.parameters:
            widget = self._entries[param.name]
            if param.param_type == ParameterType.BOOLEAN:
                values[param.name] = widget.get_active()
            elif param.param_type == ParameterType.CHOICE:
                idx = widget.get_selected()
                values[param.name] = param.choices[idx] if idx < len(param.choices) else ""
            elif param.param_type == ParameterType.INTEGER:
                values[param.name] = int(widget.get_value())
            else:
                values[param.name] = widget.get_text()

        result = validate_parameter_values(self._template, values)
        if not result.is_valid:
            return

        if self._on_apply:
            self._on_apply(values)

        self._window.close()

    def present(self):
        self._window.present()


class CategoryDialog:
    def __init__(
        self,
        parent: Optional[Gtk.Window],
        storage: TemplateStorage,
        category: Optional[TemplateCategory] = None,
        on_save: Optional[Callable[[TemplateCategory], None]] = None,
    ):
        self._storage = storage
        self._category = category
        self._on_save = on_save

        self._builder = new_builder("categorydialog")
        self._window = self._builder.get_object("category-dialog-window")

        if parent:
            self._window.set_transient_for(parent)

        title = gettext("Edit Category") if category else gettext("New Category")
        self._window.set_title(title)

        self._connect_signals()

        if category:
            self._populate_from_category()

    def _connect_signals(self):
        self._builder.get_object("cancel-button").connect(
            "clicked", lambda b: self._window.close()
        )
        self._builder.get_object("save-button").connect(
            "clicked", self._on_save_clicked
        )

    def _populate_from_category(self):
        if not self._category:
            return
        self._builder.get_object("name-entry").set_text(self._category.name)
        self._builder.get_object("description-entry").set_text(self._category.description)
        self._builder.get_object("icon-entry").set_text(self._category.icon)

    def _on_save_clicked(self, button):
        name = self._builder.get_object("name-entry").get_text().strip()
        if not name:
            return

        description = self._builder.get_object("description-entry").get_text()
        icon = self._builder.get_object("icon-entry").get_text() or "folder-symbolic"

        if self._category:
            category = self._category
            category.name = name
            category.description = description
            category.icon = icon
        else:
            category = TemplateCategory(
                id=str(uuid.uuid4()),
                name=name,
                description=description,
                icon=icon,
            )

        self._storage.save_category(category)

        if self._on_save:
            self._on_save(category)

        self._window.close()

    def present(self):
        self._window.present()
