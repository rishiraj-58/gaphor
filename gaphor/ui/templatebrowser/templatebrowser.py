"""Template browser UI component."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable, Dict, List, Optional

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, GObject, Gtk

from gaphor.abc import ActionProvider, Service
from gaphor.action import action
from gaphor.i18n import gettext
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
from gaphor.ui.templatebrowser.validation import TemplateValidator, ValidationResult

if TYPE_CHECKING:
    from gaphor.core.modeling import Diagram, ElementFactory

log = logging.getLogger(__name__)


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
        self._category_list: Optional[Gtk.ListView] = None
        self._template_grid: Optional[Gtk.GridView] = None
        self._search_entry: Optional[Gtk.SearchEntry] = None
        self._category_store: Optional[Gio.ListStore] = None
        self._template_store: Optional[Gio.ListStore] = None
        self._selected_category: Optional[str] = None

        self._on_template_selected: Optional[Callable[[DiagramTemplate], None]] = None

    def open(self) -> Gtk.Widget:
        if self._window:
            self._window.present()
            return self._window

        self._window = self._create_window()
        self._load_categories()
        self._load_templates()
        return self._window

    def close(self):
        if self._window:
            self._window.destroy()
            self._window = None

    def shutdown(self):
        self.close()

    def _create_window(self) -> Gtk.Window:
        window = Gtk.Window()
        window.set_title(gettext("Template Browser"))
        window.set_default_size(900, 600)
        window.set_modal(True)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        header = self._create_header()
        main_box.append(header)

        content = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        content.set_vexpand(True)

        sidebar = self._create_sidebar()
        content.set_start_child(sidebar)
        content.set_resize_start_child(False)
        content.set_shrink_start_child(False)

        main_content = self._create_main_content()
        content.set_end_child(main_content)
        content.set_resize_end_child(True)

        content.set_position(200)
        main_box.append(content)

        window.set_child(main_box)
        apply_action_group(self, "template", window)

        return window

    def _create_header(self) -> Gtk.Widget:
        header = Gtk.HeaderBar()

        self._search_entry = Gtk.SearchEntry()
        self._search_entry.set_placeholder_text(gettext("Search templates..."))
        self._search_entry.set_hexpand(True)
        self._search_entry.connect("search-changed", self._on_search_changed)
        header.set_title_widget(self._search_entry)

        new_btn = Gtk.Button(label=gettext("New Template"))
        new_btn.connect("clicked", self._on_new_template_clicked)
        header.pack_start(new_btn)

        import_btn = Gtk.Button(icon_name="document-open-symbolic")
        import_btn.set_tooltip_text(gettext("Import Template"))
        import_btn.connect("clicked", self._on_import_clicked)
        header.pack_end(import_btn)

        return header

    def _create_sidebar(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.set_size_request(180, -1)

        label = Gtk.Label(label=gettext("Categories"))
        label.add_css_class("heading")
        label.set_halign(Gtk.Align.START)
        label.set_margin_start(12)
        label.set_margin_top(12)
        label.set_margin_bottom(6)
        box.append(label)

        self._category_store = Gio.ListStore(item_type=CategoryListItem)
        selection = Gtk.SingleSelection(model=self._category_store)
        selection.connect("selection-changed", self._on_category_selected)

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._category_item_setup)
        factory.connect("bind", self._category_item_bind)

        self._category_list = Gtk.ListView(model=selection, factory=factory)
        self._category_list.add_css_class("navigation-sidebar")

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_child(self._category_list)
        box.append(scrolled)

        separator = Gtk.Separator()
        box.append(separator)

        add_category_btn = Gtk.Button(label=gettext("Add Category"))
        add_category_btn.set_margin_start(12)
        add_category_btn.set_margin_end(12)
        add_category_btn.set_margin_top(6)
        add_category_btn.set_margin_bottom(12)
        add_category_btn.connect("clicked", self._on_add_category_clicked)
        box.append(add_category_btn)

        return box

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
        children = []
        child = box.get_first_child()
        while child:
            children.append(child)
            child = child.get_next_sibling()

        icon, label, count_label = children
        icon.set_from_icon_name(get_icon_for_category(item.id))
        label.set_label(item.name)
        count_label.set_label(str(item.count))

    def _create_main_content(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        self._template_store = Gio.ListStore(item_type=TemplateListItem)
        selection = Gtk.SingleSelection(model=self._template_store)
        selection.connect("selection-changed", self._on_template_selection_changed)

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._template_item_setup)
        factory.connect("bind", self._template_item_bind)

        self._template_grid = Gtk.GridView(model=selection, factory=factory)
        self._template_grid.set_min_columns(2)
        self._template_grid.set_max_columns(5)
        self._template_grid.connect("activate", self._on_template_activated)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_child(self._template_grid)
        box.append(scrolled)

        action_bar = self._create_action_bar()
        box.append(action_bar)

        return box

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
        name_label.set_ellipsize(3)  # PANGO_ELLIPSIZE_END
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

        children = []
        child = box.get_first_child()
        while child:
            children.append(child)
            child = child.get_next_sibling()

        frame, name_label, desc_label, lang_box = children
        thumbnail = frame.get_child()

        thumb_data = self._preview_generator.generate_thumbnail(item.template)
        if thumb_data:
            loader = GdkPixbuf.PixbufLoader()
            loader.write(thumb_data)
            loader.close()
            pixbuf = loader.get_pixbuf()
            texture = Gdk.Texture.new_for_pixbuf(pixbuf)
            thumbnail.set_paintable(texture)

        name_label.set_label(item.name)
        desc_label.set_label(item.description or gettext("No description"))

        lang_children = []
        lang_child = lang_box.get_first_child()
        while lang_child:
            lang_children.append(lang_child)
            lang_child = lang_child.get_next_sibling()

        lang_icon, lang_label = lang_children
        lang_icon.set_from_icon_name(item.modeling_language)
        lang_label.set_label(item.modeling_language)

    def _create_action_bar(self) -> Gtk.Widget:
        action_bar = Gtk.ActionBar()

        use_btn = Gtk.Button(label=gettext("Use Template"))
        use_btn.add_css_class("suggested-action")
        use_btn.connect("clicked", self._on_use_template_clicked)
        action_bar.pack_end(use_btn)

        edit_btn = Gtk.Button(label=gettext("Edit"))
        edit_btn.connect("clicked", self._on_edit_template_clicked)
        action_bar.pack_end(edit_btn)

        delete_btn = Gtk.Button(icon_name="user-trash-symbolic")
        delete_btn.set_tooltip_text(gettext("Delete Template"))
        delete_btn.connect("clicked", self._on_delete_template_clicked)
        action_bar.pack_start(delete_btn)

        export_btn = Gtk.Button(icon_name="document-save-symbolic")
        export_btn.set_tooltip_text(gettext("Export Template"))
        export_btn.connect("clicked", self._on_export_clicked)
        action_bar.pack_start(export_btn)

        return action_bar

    def _load_categories(self):
        if not self._category_store:
            return

        self._category_store.remove_all()

        all_item = CategoryListItem(
            TemplateCategory(id="__all__", name=gettext("All Templates"), icon="view-list-symbolic"),
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
            search_text = self._search_entry.get_text() if self._search_entry else ""
            self._load_templates(self._selected_category, search_text)

    def _on_search_changed(self, entry):
        search_text = entry.get_text()
        self._load_templates(self._selected_category, search_text)

    def _on_template_selection_changed(self, selection, position, n_items):
        pass

    def _on_template_activated(self, grid_view, position):
        self._on_use_template_clicked(None)

    def _get_selected_template(self) -> Optional[DiagramTemplate]:
        if not self._template_grid:
            return None
        selection = self._template_grid.get_model()
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
        dialog.set_detail(gettext("Are you sure you want to delete '{name}'?").format(name=template.name))
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


class TemplateEditorDialog(Gtk.Window):
    def __init__(
        self,
        parent: Optional[Gtk.Window],
        storage: TemplateStorage,
        validator: TemplateValidator,
        template: Optional[DiagramTemplate] = None,
        on_save: Optional[Callable[[DiagramTemplate], None]] = None,
    ):
        super().__init__()
        self._storage = storage
        self._validator = validator
        self._template = template
        self._on_save = on_save
        self._parameters: List[TemplateParameter] = list(template.parameters) if template else []

        self.set_title(gettext("Edit Template") if template else gettext("New Template"))
        self.set_default_size(700, 600)
        self.set_modal(True)
        if parent:
            self.set_transient_for(parent)

        self._build_ui()
        if template:
            self._populate_from_template()

    def _build_ui(self):
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        header = Gtk.HeaderBar()
        cancel_btn = Gtk.Button(label=gettext("Cancel"))
        cancel_btn.connect("clicked", lambda b: self.close())
        header.pack_start(cancel_btn)

        save_btn = Gtk.Button(label=gettext("Save"))
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", self._on_save_clicked)
        header.pack_end(save_btn)
        self.set_titlebar(header)

        notebook = Gtk.Notebook()

        general_page = self._build_general_page()
        notebook.append_page(general_page, Gtk.Label(label=gettext("General")))

        content_page = self._build_content_page()
        notebook.append_page(content_page, Gtk.Label(label=gettext("Content")))

        params_page = self._build_parameters_page()
        notebook.append_page(params_page, Gtk.Label(label=gettext("Parameters")))

        main_box.append(notebook)

        validation_bar = Gtk.InfoBar()
        validation_bar.set_revealed(False)
        self._validation_label = Gtk.Label()
        validation_bar.add_child(self._validation_label)
        self._validation_bar = validation_bar
        main_box.append(validation_bar)

        self.set_child(main_box)

    def _build_general_page(self) -> Gtk.Widget:
        grid = Gtk.Grid()
        grid.set_row_spacing(12)
        grid.set_column_spacing(12)
        grid.set_margin_start(18)
        grid.set_margin_end(18)
        grid.set_margin_top(18)
        grid.set_margin_bottom(18)

        row = 0

        name_label = Gtk.Label(label=gettext("Name:"))
        name_label.set_halign(Gtk.Align.END)
        grid.attach(name_label, 0, row, 1, 1)
        self._name_entry = Gtk.Entry()
        self._name_entry.set_hexpand(True)
        grid.attach(self._name_entry, 1, row, 1, 1)
        row += 1

        desc_label = Gtk.Label(label=gettext("Description:"))
        desc_label.set_halign(Gtk.Align.END)
        desc_label.set_valign(Gtk.Align.START)
        grid.attach(desc_label, 0, row, 1, 1)
        self._desc_view = Gtk.TextView()
        self._desc_view.set_wrap_mode(Gtk.WrapMode.WORD)
        desc_scroll = Gtk.ScrolledWindow()
        desc_scroll.set_min_content_height(80)
        desc_scroll.set_child(self._desc_view)
        grid.attach(desc_scroll, 1, row, 1, 1)
        row += 1

        category_label = Gtk.Label(label=gettext("Category:"))
        category_label.set_halign(Gtk.Align.END)
        grid.attach(category_label, 0, row, 1, 1)
        self._category_combo = Gtk.DropDown()
        categories = self._storage.list_categories()
        category_names = [c.name for c in categories]
        self._category_ids = [c.id for c in categories]
        self._category_combo.set_model(Gtk.StringList.new(category_names))
        grid.attach(self._category_combo, 1, row, 1, 1)
        row += 1

        lang_label = Gtk.Label(label=gettext("Modeling Language:"))
        lang_label.set_halign(Gtk.Align.END)
        grid.attach(lang_label, 0, row, 1, 1)
        self._lang_combo = Gtk.DropDown()
        languages = ["UML", "SysML", "C4Model", "RAAML"]
        self._lang_combo.set_model(Gtk.StringList.new(languages))
        grid.attach(self._lang_combo, 1, row, 1, 1)
        row += 1

        tags_label = Gtk.Label(label=gettext("Tags:"))
        tags_label.set_halign(Gtk.Align.END)
        grid.attach(tags_label, 0, row, 1, 1)
        self._tags_entry = Gtk.Entry()
        self._tags_entry.set_placeholder_text(gettext("Comma-separated tags"))
        grid.attach(self._tags_entry, 1, row, 1, 1)

        return grid

    def _build_content_page(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)

        hint = Gtk.Label(label=gettext("Paste Gaphor XML content here. Use ${parameter_name} for placeholders."))
        hint.set_halign(Gtk.Align.START)
        hint.add_css_class("dim-label")
        box.append(hint)

        self._content_view = Gtk.TextView()
        self._content_view.set_monospace(True)
        self._content_view.set_wrap_mode(Gtk.WrapMode.NONE)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_child(self._content_view)
        box.append(scrolled)

        extract_btn = Gtk.Button(label=gettext("Extract Parameters"))
        extract_btn.connect("clicked", self._on_extract_parameters)
        extract_btn.set_halign(Gtk.Align.START)
        box.append(extract_btn)

        return box

    def _build_parameters_page(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        add_btn = Gtk.Button(label=gettext("Add Parameter"))
        add_btn.connect("clicked", self._on_add_parameter)
        toolbar.append(add_btn)
        box.append(toolbar)

        self._params_list = Gtk.ListBox()
        self._params_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._params_list.add_css_class("boxed-list")

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_child(self._params_list)
        box.append(scrolled)

        self._refresh_parameters_list()

        return box

    def _refresh_parameters_list(self):
        while row := self._params_list.get_row_at_index(0):
            self._params_list.remove(row)

        for i, param in enumerate(self._parameters):
            row = self._create_parameter_row(param, i)
            self._params_list.append(row)

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
        type_combo.connect("notify::selected", lambda c, p: self._update_parameter(
            index, "param_type", ParameterType(types[c.get_selected()])
        ))
        box.append(type_combo)

        default_entry = Gtk.Entry()
        default_entry.set_text(str(param.default_value or ""))
        default_entry.set_placeholder_text(gettext("Default"))
        default_entry.set_width_chars(12)
        default_entry.connect("changed", lambda e: self._update_parameter(index, "default_value", e.get_text()))
        box.append(default_entry)

        required_check = Gtk.CheckButton(label=gettext("Required"))
        required_check.set_active(param.required)
        required_check.connect("toggled", lambda c: self._update_parameter(index, "required", c.get_active()))
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
        buffer = self._content_view.get_buffer()
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
        if not self._template:
            return

        self._name_entry.set_text(self._template.name)
        self._desc_view.get_buffer().set_text(self._template.description)

        if self._template.category_id in self._category_ids:
            self._category_combo.set_selected(self._category_ids.index(self._template.category_id))

        languages = ["UML", "SysML", "C4Model", "RAAML"]
        if self._template.modeling_language in languages:
            self._lang_combo.set_selected(languages.index(self._template.modeling_language))

        self._tags_entry.set_text(", ".join(self._template.tags))
        self._content_view.get_buffer().set_text(self._template.content)

    def _on_save_clicked(self, button):
        name = self._name_entry.get_text().strip()
        desc_buffer = self._desc_view.get_buffer()
        description = desc_buffer.get_text(desc_buffer.get_start_iter(), desc_buffer.get_end_iter(), False)

        category_idx = self._category_combo.get_selected()
        category_id = self._category_ids[category_idx] if category_idx < len(self._category_ids) else "custom"

        lang_idx = self._lang_combo.get_selected()
        languages = ["UML", "SysML", "C4Model", "RAAML"]
        modeling_language = languages[lang_idx] if lang_idx < len(languages) else "UML"

        tags = [t.strip() for t in self._tags_entry.get_text().split(",") if t.strip()]

        content_buffer = self._content_view.get_buffer()
        content = content_buffer.get_text(content_buffer.get_start_iter(), content_buffer.get_end_iter(), False)

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

        self.close()

    def _show_validation_errors(self, result: ValidationResult):
        errors = [e.message for e in result.errors]
        self._validation_label.set_text("\n".join(errors))
        self._validation_bar.set_message_type(Gtk.MessageType.ERROR)
        self._validation_bar.set_revealed(True)


class ParameterDialog(Gtk.Window):
    def __init__(
        self,
        parent: Optional[Gtk.Window],
        template: DiagramTemplate,
        on_apply: Optional[Callable[[dict], None]] = None,
    ):
        super().__init__()
        self._template = template
        self._on_apply = on_apply
        self._entries: Dict[str, Gtk.Widget] = {}

        self.set_title(gettext("Template Parameters"))
        self.set_default_size(400, 300)
        self.set_modal(True)
        if parent:
            self.set_transient_for(parent)

        self._build_ui()

    def _build_ui(self):
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        header = Gtk.HeaderBar()
        cancel_btn = Gtk.Button(label=gettext("Cancel"))
        cancel_btn.connect("clicked", lambda b: self.close())
        header.pack_start(cancel_btn)

        apply_btn = Gtk.Button(label=gettext("Apply"))
        apply_btn.add_css_class("suggested-action")
        apply_btn.connect("clicked", self._on_apply_clicked)
        header.pack_end(apply_btn)
        self.set_titlebar(header)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)

        list_box = Gtk.ListBox()
        list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        list_box.add_css_class("boxed-list")
        list_box.set_margin_start(18)
        list_box.set_margin_end(18)
        list_box.set_margin_top(18)
        list_box.set_margin_bottom(18)

        for param in self._template.parameters:
            row = self._create_parameter_input(param)
            list_box.append(row)

        scrolled.set_child(list_box)
        main_box.append(scrolled)
        self.set_child(main_box)

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
        from gaphor.ui.templatebrowser.validation import validate_parameter_values

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

        self.close()


class CategoryDialog(Gtk.Window):
    def __init__(
        self,
        parent: Optional[Gtk.Window],
        storage: TemplateStorage,
        category: Optional[TemplateCategory] = None,
        on_save: Optional[Callable[[TemplateCategory], None]] = None,
    ):
        super().__init__()
        self._storage = storage
        self._category = category
        self._on_save = on_save

        self.set_title(gettext("Edit Category") if category else gettext("New Category"))
        self.set_default_size(350, 200)
        self.set_modal(True)
        if parent:
            self.set_transient_for(parent)

        self._build_ui()
        if category:
            self._populate_from_category()

    def _build_ui(self):
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        header = Gtk.HeaderBar()
        cancel_btn = Gtk.Button(label=gettext("Cancel"))
        cancel_btn.connect("clicked", lambda b: self.close())
        header.pack_start(cancel_btn)

        save_btn = Gtk.Button(label=gettext("Save"))
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", self._on_save_clicked)
        header.pack_end(save_btn)
        self.set_titlebar(header)

        grid = Gtk.Grid()
        grid.set_row_spacing(12)
        grid.set_column_spacing(12)
        grid.set_margin_start(18)
        grid.set_margin_end(18)
        grid.set_margin_top(18)
        grid.set_margin_bottom(18)

        name_label = Gtk.Label(label=gettext("Name:"))
        name_label.set_halign(Gtk.Align.END)
        grid.attach(name_label, 0, 0, 1, 1)
        self._name_entry = Gtk.Entry()
        self._name_entry.set_hexpand(True)
        grid.attach(self._name_entry, 1, 0, 1, 1)

        desc_label = Gtk.Label(label=gettext("Description:"))
        desc_label.set_halign(Gtk.Align.END)
        grid.attach(desc_label, 0, 1, 1, 1)
        self._desc_entry = Gtk.Entry()
        grid.attach(self._desc_entry, 1, 1, 1, 1)

        icon_label = Gtk.Label(label=gettext("Icon:"))
        icon_label.set_halign(Gtk.Align.END)
        grid.attach(icon_label, 0, 2, 1, 1)
        self._icon_entry = Gtk.Entry()
        self._icon_entry.set_text("folder-symbolic")
        grid.attach(self._icon_entry, 1, 2, 1, 1)

        main_box.append(grid)
        self.set_child(main_box)

    def _populate_from_category(self):
        if not self._category:
            return
        self._name_entry.set_text(self._category.name)
        self._desc_entry.set_text(self._category.description)
        self._icon_entry.set_text(self._category.icon)

    def _on_save_clicked(self, button):
        import uuid

        name = self._name_entry.get_text().strip()
        if not name:
            return

        description = self._desc_entry.get_text()
        icon = self._icon_entry.get_text() or "folder-symbolic"

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

        self.close()
