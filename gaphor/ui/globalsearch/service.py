"""Global search service for Gaphor."""

from __future__ import annotations

import importlib.resources
import logging
from typing import TYPE_CHECKING

from gi.repository import Adw, Gio, GLib, GObject, Gtk

from gaphor.abc import ActionProvider, Service
from gaphor.action import action
from gaphor.core import event_handler
from gaphor.diagram.event import DiagramOpened
from gaphor.diagram.iconname import icon_name
from gaphor.i18n import gettext
from gaphor.ui.globalsearch.engine import (
    SearchCategory,
    SearchEngine,
    SearchResult,
    SearchScope,
)

if TYPE_CHECKING:
    from gaphor.core.modeling import Diagram


log = logging.getLogger(__name__)

SEARCH_DELAY_MS = 150
HIGHLIGHT_DURATION_MS = 1000


class SearchResultItem(GObject.Object):
    def __init__(self, result: SearchResult):
        super().__init__()
        self._result = result

    @GObject.Property(type=str)
    def element_name(self) -> str:
        return self._result.element_name

    @GObject.Property(type=str)
    def element_type(self) -> str:
        return self._result.element_type

    @GObject.Property(type=str)
    def element_id(self) -> str:
        return self._result.element_id

    @GObject.Property(type=str)
    def icon(self) -> str:
        return icon_name(self._result.element) or "gaphor-element-symbolic"

    @GObject.Property(type=str)
    def match_category_label(self) -> str:
        category_labels = {
            SearchCategory.NAME: gettext("Name:"),
            SearchCategory.TYPE: gettext("Type:"),
            SearchCategory.ATTRIBUTE: gettext("Attribute:"),
            SearchCategory.ATTRIBUTE_VALUE: gettext("Value in:"),
            SearchCategory.RELATIONSHIP: gettext("Relationship:"),
        }
        field = self._result.match_field
        category = category_labels.get(self._result.match_category, "")
        if self._result.match_category in (
            SearchCategory.ATTRIBUTE,
            SearchCategory.ATTRIBUTE_VALUE,
        ):
            return f"{category} {field}"
        return category

    @GObject.Property(type=str)
    def match_value(self) -> str:
        return self._result.match_value

    @GObject.Property(type=str)
    def diagram_locations_label(self) -> str:
        locations = self._result.diagram_locations
        if not locations:
            return ""

        diagram_names = list(set(loc.diagram_name for loc in locations))
        if len(diagram_names) <= 2:
            return gettext("In diagrams: ") + ", ".join(diagram_names)
        return gettext("In diagrams: ") + ", ".join(diagram_names[:2]) + f" (+{len(diagram_names) - 2})"

    @GObject.Property(type=bool, default=False)
    def has_diagram_locations(self) -> bool:
        return bool(self._result.diagram_locations)

    @property
    def result(self) -> SearchResult:
        return self._result


class GlobalSearchService(Service, ActionProvider):
    def __init__(
        self,
        event_manager,
        element_factory,
        modeling_language,
        diagrams,
    ):
        self.event_manager = event_manager
        self.element_factory = element_factory
        self.modeling_language = modeling_language
        self.diagrams = diagrams

        self._search_engine = SearchEngine(element_factory, modeling_language)
        self._dialog: Adw.Dialog | None = None
        self._search_timeout_id: int | None = None
        self._results_model: Gio.ListStore | None = None
        self._current_diagram: Diagram | None = None

        self._search_entry: Gtk.SearchEntry | None = None
        self._scope_dropdown: Gtk.DropDown | None = None
        self._results_info: Gtk.Label | None = None
        self._search_names: Gtk.CheckButton | None = None
        self._search_types: Gtk.CheckButton | None = None
        self._search_attributes: Gtk.CheckButton | None = None
        self._search_relationships: Gtk.CheckButton | None = None

        event_manager.subscribe(self._on_diagram_opened)

    def shutdown(self):
        self.event_manager.unsubscribe(self._on_diagram_opened)
        if self._search_timeout_id:
            GLib.source_remove(self._search_timeout_id)
            self._search_timeout_id = None

    @action(name="win.global-search", shortcut="<Primary><Shift>f")
    def open_search_dialog(self):
        if self._dialog is None:
            self._create_dialog()

        self._current_diagram = self.diagrams.get_current_diagram()

        parent = self._get_parent_window()
        if parent and self._dialog:
            self._dialog.present(parent)
            if self._search_entry:
                self._search_entry.grab_focus()

    def _get_parent_window(self) -> Gtk.Window | None:
        from gi.repository import Gtk

        app = Gtk.Application.get_default()
        return app.get_active_window() if app else None

    def _create_dialog(self):
        builder = Gtk.Builder()
        ui_file = (
            importlib.resources.files("gaphor.ui.globalsearch") / "dialog.ui"
        ).read_text(encoding="utf-8")
        builder.add_from_string(ui_file)

        self._dialog = builder.get_object("search-dialog")
        self._search_entry = builder.get_object("search-entry")
        self._scope_dropdown = builder.get_object("scope-dropdown")
        self._results_info = builder.get_object("results-info")
        self._search_names = builder.get_object("search-names")
        self._search_types = builder.get_object("search-types")
        self._search_attributes = builder.get_object("search-attributes")
        self._search_relationships = builder.get_object("search-relationships")

        results_list = builder.get_object("results-list")

        self._results_model = Gio.ListStore.new(SearchResultItem.__gtype__)
        selection = Gtk.SingleSelection.new(self._results_model)
        results_list.set_model(selection)

        factory = Gtk.SignalListItemFactory.new()
        factory.connect("setup", self._on_result_item_setup)
        factory.connect("bind", self._on_result_item_bind)
        results_list.set_factory(factory)

        results_list.connect("activate", self._on_result_activated)

        self._search_entry.connect("search-changed", self._on_search_changed)
        self._search_entry.connect("activate", self._on_search_activate)

        self._scope_dropdown.connect("notify::selected", self._on_scope_changed)
        self._search_names.connect("toggled", self._on_filter_changed)
        self._search_types.connect("toggled", self._on_filter_changed)
        self._search_attributes.connect("toggled", self._on_filter_changed)
        self._search_relationships.connect("toggled", self._on_filter_changed)

    def _on_result_item_setup(self, factory, list_item):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)

        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        icon = Gtk.Image()
        icon.set_icon_size(Gtk.IconSize.NORMAL)
        header_box.append(icon)

        name_label = Gtk.Label()
        name_label.set_halign(Gtk.Align.START)
        name_label.set_hexpand(True)
        name_label.set_ellipsize(3)  # PANGO_ELLIPSIZE_END
        name_label.add_css_class("heading")
        header_box.append(name_label)

        type_label = Gtk.Label()
        type_label.set_halign(Gtk.Align.END)
        type_label.add_css_class("dim-label")
        header_box.append(type_label)

        box.append(header_box)

        match_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        category_label = Gtk.Label()
        category_label.set_halign(Gtk.Align.START)
        category_label.add_css_class("caption")
        match_box.append(category_label)

        value_label = Gtk.Label()
        value_label.set_halign(Gtk.Align.START)
        value_label.set_hexpand(True)
        value_label.set_ellipsize(3)
        value_label.set_max_width_chars(60)
        value_label.add_css_class("dim-label")
        value_label.add_css_class("caption")
        match_box.append(value_label)

        box.append(match_box)

        diagrams_label = Gtk.Label()
        diagrams_label.set_halign(Gtk.Align.START)
        diagrams_label.set_ellipsize(3)
        diagrams_label.set_max_width_chars(80)
        diagrams_label.add_css_class("caption")
        diagrams_label.add_css_class("accent")
        box.append(diagrams_label)

        list_item.set_child(box)

        list_item._icon = icon
        list_item._name_label = name_label
        list_item._type_label = type_label
        list_item._category_label = category_label
        list_item._value_label = value_label
        list_item._diagrams_label = diagrams_label

    def _on_result_item_bind(self, factory, list_item):
        item: SearchResultItem = list_item.get_item()

        list_item._icon.set_from_icon_name(item.icon)
        list_item._name_label.set_label(item.element_name)
        list_item._type_label.set_label(item.element_type)
        list_item._category_label.set_label(item.match_category_label)
        list_item._value_label.set_label(item.match_value)
        list_item._diagrams_label.set_label(item.diagram_locations_label)
        list_item._diagrams_label.set_visible(item.has_diagram_locations)

    def _on_search_changed(self, entry):
        if self._search_timeout_id:
            GLib.source_remove(self._search_timeout_id)

        self._search_timeout_id = GLib.timeout_add(
            SEARCH_DELAY_MS, self._perform_search
        )

    def _on_search_activate(self, entry):
        if self._search_timeout_id:
            GLib.source_remove(self._search_timeout_id)
            self._search_timeout_id = None

        self._perform_search()

    def _on_scope_changed(self, dropdown, param):
        self._perform_search()

    def _on_filter_changed(self, button):
        self._perform_search()

    def _perform_search(self) -> bool:
        self._search_timeout_id = None

        if not self._search_entry or not self._results_model:
            return False

        query = self._search_entry.get_text()

        scope = (
            SearchScope.CURRENT_DIAGRAM
            if self._scope_dropdown and self._scope_dropdown.get_selected() == 1
            else SearchScope.GLOBAL
        )

        results = self._search_engine.search(
            query=query,
            scope=scope,
            current_diagram=self._current_diagram,
            search_names=self._search_names.get_active() if self._search_names else True,
            search_types=self._search_types.get_active() if self._search_types else True,
            search_attributes=self._search_attributes.get_active() if self._search_attributes else True,
            search_relationships=self._search_relationships.get_active() if self._search_relationships else True,
        )

        self._results_model.remove_all()
        for result in results:
            self._results_model.append(SearchResultItem(result))

        self._update_results_info(query, len(results))

        return False

    def _update_results_info(self, query: str, count: int):
        if not self._results_info:
            return

        if not query:
            self._results_info.set_label(
                gettext("Enter a search term to find elements")
            )
        elif count == 0:
            self._results_info.set_label(gettext("No results found"))
        elif count == 1:
            self._results_info.set_label(gettext("1 result found"))
        else:
            self._results_info.set_label(
                gettext("{count} results found").format(count=count)
            )

    def _on_result_activated(self, list_view, position):
        item: SearchResultItem = self._results_model.get_item(position)
        if not item:
            return

        result = item.result

        if self._dialog:
            self._dialog.close()

        self._navigate_to_result(result)

    def _navigate_to_result(self, result: SearchResult):
        element = result.element

        if result.diagram_locations:
            location = result.diagram_locations[0]
            self.event_manager.handle(DiagramOpened(location.diagram))

            GLib.timeout_add(100, self._highlight_element, location)
        else:
            from gaphor.ui.event import ElementFocused

            self.event_manager.handle(ElementFocused(element))

    def _highlight_element(self, location) -> bool:
        view = self.diagrams.get_current_view()
        if not view:
            return False

        presentation = location.presentation

        view.selection.unselect_all()
        view.selection.focused_item = presentation

        self._scroll_to_item(view, presentation)
        self._flash_highlight(view, presentation)

        return False

    def _scroll_to_item(self, view, item):
        """Scroll the view to center the given item."""
        try:
            # Get item position from its matrix
            matrix = item.matrix_i2c
            cx, cy = matrix[4], matrix[5]

            # Transform to view coordinates
            view_matrix = view.matrix
            sx, sy = view_matrix.transform_point(cx, cy)

            # Get view dimensions
            width = view.get_width()
            height = view.get_height()

            # Calculate how much we need to pan
            dx = sx - width / 2
            dy = sy - height / 2

            # Only pan if the item is significantly off-center
            if abs(dx) > 50 or abs(dy) > 50:
                # Update the view matrix translation
                m = list(view.matrix)
                m[4] -= dx
                m[5] -= dy
                view.matrix.set(*m)
                view.update_back_buffer()
        except Exception as e:
            log.debug(f"Could not scroll to item: {e}")

    def _flash_highlight(self, view, item):
        """Create a visual flash effect to highlight the found element."""

        def update_view():
            if view:
                view.update_back_buffer()
            return False

        def select_item():
            if view and item:
                view.selection.focused_item = item
                update_view()
            return False

        def unselect_item():
            if view:
                view.selection.focused_item = None
                update_view()
            return False

        # Flash sequence: select -> unselect -> select -> unselect -> select (final)
        GLib.timeout_add(0, select_item)
        GLib.timeout_add(150, unselect_item)
        GLib.timeout_add(300, select_item)
        GLib.timeout_add(450, unselect_item)
        GLib.timeout_add(600, select_item)

    @event_handler(DiagramOpened)
    def _on_diagram_opened(self, event: DiagramOpened):
        self._current_diagram = event.diagram
