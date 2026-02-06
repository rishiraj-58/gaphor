"""Global search functionality for finding elements across the model."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING
from unicodedata import normalize

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Pango

from gaphor.abc import ActionProvider, Service
from gaphor.core import action, event_handler
from gaphor.core.modeling import Base, Diagram, Presentation
from gaphor.diagram.event import DiagramOpened
from gaphor.diagram.group import owner
from gaphor.diagram.iconname import icon_name
from gaphor.i18n import gettext, translated_ui_string
from gaphor.ui.event import CurrentDiagramChanged

if TYPE_CHECKING:
    from gaphor.core.eventmanager import EventManager
    from gaphor.core.modeling import ElementFactory


class SearchScope(Enum):
    GLOBAL = "global"
    CURRENT_DIAGRAM = "current_diagram"


@dataclass
class SearchResult:
    element: Base
    match_type: str
    match_field: str
    match_value: str
    diagrams: list[Diagram]

    @property
    def element_name(self) -> str:
        return getattr(self.element, "name", None) or f"<{type(self.element).__name__}>"

    @property
    def element_type(self) -> str:
        return type(self.element).__name__

    @property
    def owner_path(self) -> str:
        parts = []
        current = owner(self.element)
        while current and not isinstance(current, str):
            name = getattr(current, "name", None) or f"<{type(current).__name__}>"
            parts.append(name)
            current = owner(current)
        return " → ".join(reversed(parts)) if parts else ""


class SearchResultItem(GObject.Object):
    def __init__(self, result: SearchResult):
        super().__init__()
        self.result = result

    name = GObject.Property(type=str)
    element_type = GObject.Property(type=str)
    match_info = GObject.Property(type=str)
    location = GObject.Property(type=str)
    icon = GObject.Property(type=str)
    diagram_count = GObject.Property(type=int)

    def sync(self):
        result = self.result
        self.name = result.element_name
        self.element_type = result.element_type
        self.match_info = f"{result.match_type}: {result.match_field} = {result.match_value}"
        self.location = result.owner_path
        self.icon = icon_name(result.element) or "help-about-symbolic"
        self.diagram_count = len(result.diagrams)


def new_builder():
    builder = Gtk.Builder()
    builder.add_from_string(translated_ui_string("gaphor.ui", "globalsearch.ui"))
    return builder


class GlobalSearch(Service, ActionProvider):
    def __init__(
        self,
        event_manager: EventManager,
        element_factory: ElementFactory,
        diagrams,
        main_window,
    ):
        self.event_manager = event_manager
        self.element_factory = element_factory
        self.diagrams = diagrams
        self.main_window = main_window
        self._dialog: Adw.Dialog | None = None
        self._search_entry: Gtk.SearchEntry | None = None
        self._results_list: Gtk.ListView | None = None
        self._results_model: Gtk.SingleSelection | None = None
        self._scope_toggle: Gtk.ToggleButton | None = None
        self._status_label: Gtk.Label | None = None
        self._search_scope = SearchScope.GLOBAL
        self._current_diagram: Diagram | None = None
        self._highlight_timeout_id: int | None = None

        self.event_manager.subscribe(self._on_current_diagram_changed)

    def shutdown(self):
        self.event_manager.unsubscribe(self._on_current_diagram_changed)
        if self._dialog:
            self._dialog.close()
            self._dialog = None

    @event_handler(CurrentDiagramChanged)
    def _on_current_diagram_changed(self, event: CurrentDiagramChanged):
        self._current_diagram = event.diagram

    @action(name="win.global-search", shortcut="<Primary><Shift>f")
    def open_search_dialog(self):
        if self._dialog:
            self._dialog.present(self._get_parent_window())
            return

        builder = new_builder()
        self._dialog = builder.get_object("search-dialog")
        self._search_entry = builder.get_object("search-entry")
        self._results_list = builder.get_object("results-list")
        self._scope_toggle = builder.get_object("scope-toggle")
        self._status_label = builder.get_object("status-label")

        # Setup results model
        results_store = Gio.ListStore.new(SearchResultItem.__gtype__)
        self._results_model = Gtk.SingleSelection.new(results_store)
        self._results_list.set_model(self._results_model)

        # Setup list factory
        factory = Gtk.SignalListItemFactory.new()
        factory.connect("setup", self._on_factory_setup)
        factory.connect("bind", self._on_factory_bind)
        self._results_list.set_factory(factory)

        # Connect signals
        self._search_entry.connect("search-changed", self._on_search_changed)
        self._search_entry.connect("activate", self._on_activate_result)
        self._scope_toggle.connect("toggled", self._on_scope_toggled)
        self._results_list.connect("activate", self._on_result_activated)

        # Key controller for navigation
        key_ctrl = Gtk.EventControllerKey.new()
        key_ctrl.connect("key-pressed", self._on_key_pressed)
        self._search_entry.add_controller(key_ctrl)

        self._dialog.connect("closed", self._on_dialog_closed)
        self._dialog.present(self._get_parent_window())
        self._search_entry.grab_focus()

    def _get_parent_window(self) -> Gtk.Window | None:
        return self.main_window.window

    def _on_factory_setup(self, factory, list_item):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(12)
        box.set_margin_end(12)

        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        icon = Gtk.Image()
        icon.set_icon_size(Gtk.IconSize.NORMAL)
        header_box.append(icon)

        name_label = Gtk.Label()
        name_label.set_halign(Gtk.Align.START)
        name_label.set_hexpand(True)
        name_label.add_css_class("heading")
        header_box.append(name_label)

        type_label = Gtk.Label()
        type_label.set_halign(Gtk.Align.END)
        type_label.add_css_class("dim-label")
        header_box.append(type_label)

        box.append(header_box)

        match_label = Gtk.Label()
        match_label.set_halign(Gtk.Align.START)
        match_label.add_css_class("caption")
        box.append(match_label)

        location_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        location_label = Gtk.Label()
        location_label.set_halign(Gtk.Align.START)
        location_label.add_css_class("dim-label")
        location_label.add_css_class("caption")
        location_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        location_box.append(location_label)

        diagram_label = Gtk.Label()
        diagram_label.set_halign(Gtk.Align.END)
        diagram_label.set_hexpand(True)
        diagram_label.add_css_class("caption")
        location_box.append(diagram_label)

        box.append(location_box)

        list_item.set_child(box)
        list_item.icon = icon
        list_item.name_label = name_label
        list_item.type_label = type_label
        list_item.match_label = match_label
        list_item.location_label = location_label
        list_item.diagram_label = diagram_label

    def _on_factory_bind(self, factory, list_item):
        item: SearchResultItem = list_item.get_item()
        item.sync()

        list_item.icon.set_from_icon_name(item.icon)
        list_item.name_label.set_text(item.name)
        list_item.type_label.set_text(item.element_type)
        list_item.match_label.set_text(item.match_info)
        list_item.location_label.set_text(item.location or gettext("(root)"))

        if item.diagram_count > 0:
            list_item.diagram_label.set_text(
                gettext("In {count} diagram(s)").format(count=item.diagram_count)
            )
        else:
            list_item.diagram_label.set_text(gettext("Not in any diagram"))

    def _on_search_changed(self, entry):
        search_text = entry.get_text().strip()
        if len(search_text) < 2:
            self._clear_results()
            self._update_status(gettext("Type at least 2 characters to search"))
            return

        results = list(self._search(search_text))
        self._display_results(results)
        self._update_status(
            gettext("{count} result(s) found").format(count=len(results))
        )

    def _on_scope_toggled(self, toggle):
        if toggle.get_active():
            self._search_scope = SearchScope.CURRENT_DIAGRAM
            toggle.set_label(gettext("Current Diagram"))
        else:
            self._search_scope = SearchScope.GLOBAL
            toggle.set_label(gettext("All Diagrams"))

        # Re-run search with new scope
        if self._search_entry:
            self._on_search_changed(self._search_entry)

    def _on_key_pressed(self, controller, keyval, keycode, state):
        if keyval == Gdk.KEY_Down:
            self._select_next_result()
            return True
        elif keyval == Gdk.KEY_Up:
            self._select_previous_result()
            return True
        elif keyval == Gdk.KEY_Escape:
            if self._dialog:
                self._dialog.close()
            return True
        return False

    def _on_activate_result(self, entry):
        self._navigate_to_selected()

    def _on_result_activated(self, list_view, position):
        self._navigate_to_selected()

    def _on_dialog_closed(self, dialog):
        self._dialog = None
        self._search_entry = None
        self._results_list = None
        self._results_model = None
        self._scope_toggle = None
        self._status_label = None

    def _select_next_result(self):
        if not self._results_model:
            return
        current = self._results_model.get_selected()
        n_items = self._results_model.get_n_items()
        if n_items > 0 and current < n_items - 1:
            self._results_model.set_selected(current + 1)

    def _select_previous_result(self):
        if not self._results_model:
            return
        current = self._results_model.get_selected()
        if current > 0:
            self._results_model.set_selected(current - 1)

    def _navigate_to_selected(self):
        if not self._results_model:
            return

        selected = self._results_model.get_selected_item()
        if not selected:
            return

        result: SearchResult = selected.result
        element = result.element

        # Find diagram to open
        diagram = None
        if result.diagrams:
            # Prefer current diagram if element is there
            if (
                self._current_diagram
                and self._current_diagram in result.diagrams
            ):
                diagram = self._current_diagram
            else:
                diagram = result.diagrams[0]
        elif isinstance(element, Diagram):
            diagram = element

        if diagram:
            self.event_manager.handle(DiagramOpened(diagram))
            # Highlight element after diagram opens
            GLib.timeout_add(100, self._highlight_element, element, diagram)

        if self._dialog:
            self._dialog.close()

    def _highlight_element(self, element: Base, diagram: Diagram) -> bool:
        view = self.diagrams.get_current_view()
        if not view:
            return False

        # Find presentation in diagram
        presentation = None
        if isinstance(element, Presentation):
            if element.diagram is diagram:
                presentation = element
        else:
            presentation = next(
                (p for p in diagram.ownedPresentation if p.subject is element),
                None,
            )

        if presentation:
            view.selection.unselect_all()
            view.selection.focused_item = presentation

            # Scroll to item and flash highlight
            self._flash_highlight(view, presentation)

        return False

    def _flash_highlight(self, view, item):
        # Add highlight class
        view.add_css_class("search-highlight")

        def remove_highlight():
            view.remove_css_class("search-highlight")
            return False

        # Remove after delay
        if self._highlight_timeout_id:
            GLib.source_remove(self._highlight_timeout_id)
        self._highlight_timeout_id = GLib.timeout_add(1500, remove_highlight)

    def _clear_results(self):
        if self._results_model:
            store = self._results_model.get_model()
            store.remove_all()

    def _display_results(self, results: list[SearchResult]):
        if not self._results_model:
            return

        store = self._results_model.get_model()
        store.remove_all()

        for result in results:
            item = SearchResultItem(result)
            store.append(item)

        if store.get_n_items() > 0:
            self._results_model.set_selected(0)

    def _update_status(self, text: str):
        if self._status_label:
            self._status_label.set_text(text)

    def _search(self, search_text: str) -> Iterator[SearchResult]:
        search_text_lower = normalize("NFC", search_text).casefold()
        seen_elements: set[str] = set()

        elements: Iterator[Base]
        if (
            self._search_scope == SearchScope.CURRENT_DIAGRAM
            and self._current_diagram
        ):
            elements = self._elements_in_diagram(self._current_diagram)
        else:
            elements = self.element_factory.select(None)

        for element in elements:
            if element.id in seen_elements:
                continue
            seen_elements.add(element.id)

            for result in self._match_element(element, search_text_lower):
                yield result

    def _elements_in_diagram(self, diagram: Diagram) -> Iterator[Base]:
        yield diagram
        for presentation in diagram.ownedPresentation:
            yield presentation
            if presentation.subject:
                yield presentation.subject

    def _match_element(
        self, element: Base, search_text: str
    ) -> Iterator[SearchResult]:
        diagrams = self._get_diagrams_for_element(element)

        # Match by name
        name = getattr(element, "name", None)
        if name and search_text in normalize("NFC", name).casefold():
            yield SearchResult(
                element=element,
                match_type=gettext("Name"),
                match_field="name",
                match_value=name,
                diagrams=diagrams,
            )
            return  # Don't duplicate

        # Match by type name
        type_name = type(element).__name__
        if search_text in type_name.lower():
            yield SearchResult(
                element=element,
                match_type=gettext("Type"),
                match_field="type",
                match_value=type_name,
                diagrams=diagrams,
            )
            return

        # Match by attributes (for classes with ownedAttribute)
        owned_attrs = getattr(element, "ownedAttribute", None)
        if owned_attrs:
            for attr in owned_attrs:
                attr_name = getattr(attr, "name", None)
                if attr_name and search_text in normalize("NFC", attr_name).casefold():
                    yield SearchResult(
                        element=element,
                        match_type=gettext("Attribute"),
                        match_field=attr_name,
                        match_value=attr_name,
                        diagrams=diagrams,
                    )
                    return

        # Match by operations (for classes with ownedOperation)
        owned_ops = getattr(element, "ownedOperation", None)
        if owned_ops:
            for op in owned_ops:
                op_name = getattr(op, "name", None)
                if op_name and search_text in normalize("NFC", op_name).casefold():
                    yield SearchResult(
                        element=element,
                        match_type=gettext("Operation"),
                        match_field=op_name,
                        match_value=op_name,
                        diagrams=diagrams,
                    )
                    return

        # Match relationships by connected elements
        if self._is_relationship(element):
            rel_info = self._get_relationship_info(element)
            if rel_info and search_text in normalize("NFC", rel_info).casefold():
                yield SearchResult(
                    element=element,
                    match_type=gettext("Relationship"),
                    match_field="connection",
                    match_value=rel_info,
                    diagrams=diagrams,
                )

    def _is_relationship(self, element: Base) -> bool:
        # Check common relationship types
        return any(
            hasattr(element, attr)
            for attr in ("source", "target", "client", "supplier", "memberEnd")
        )

    def _get_relationship_info(self, element: Base) -> str:
        parts = []

        # Association memberEnd
        member_end = getattr(element, "memberEnd", None)
        if member_end:
            for end in member_end:
                end_type = getattr(end, "type", None)
                if end_type:
                    parts.append(getattr(end_type, "name", "") or type(end_type).__name__)

        # Dependency client/supplier
        client = getattr(element, "client", None)
        supplier = getattr(element, "supplier", None)
        if client or supplier:
            if client:
                for c in client:
                    parts.append(getattr(c, "name", "") or type(c).__name__)
            if supplier:
                for s in supplier:
                    parts.append(getattr(s, "name", "") or type(s).__name__)

        # Generalization
        general = getattr(element, "general", None)
        specific = getattr(element, "specific", None)
        if general or specific:
            if specific:
                parts.append(getattr(specific, "name", "") or type(specific).__name__)
            if general:
                parts.append(getattr(general, "name", "") or type(general).__name__)

        return " ↔ ".join(parts)

    def _get_diagrams_for_element(self, element: Base) -> list[Diagram]:
        if isinstance(element, Diagram):
            return [element]
        if isinstance(element, Presentation):
            return [element.diagram] if element.diagram else []

        # Find diagrams containing presentations of this element
        presentations = getattr(element, "presentation", [])
        return [p.diagram for p in presentations if p.diagram]
