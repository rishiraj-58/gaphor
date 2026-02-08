"""Advanced search dialog for Gaphor."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from gi.repository import Gdk, Gio, GLib, GObject, Gtk, Pango

from gaphor.abc import ActionProvider
from gaphor.core import action, event_handler, gettext
from gaphor.core.modeling import Diagram
from gaphor.core.modeling.event import (
    ElementCreated,
    ElementDeleted,
    ModelFlushed,
    ModelReady,
)
from gaphor.diagram.event import DiagramOpened
from gaphor.ui.abc import UIComponent
from gaphor.ui.advancedsearch.searchengine import AdvancedSearchEngine, SearchScope
from gaphor.ui.advancedsearch.searchresult import SearchResult, SearchResultType

if TYPE_CHECKING:
    from gaphor.core.eventmanager import EventManager
    from gaphor.core.modeling import ElementFactory

log = logging.getLogger(__name__)

# Debounce delay for search input (ms)
SEARCH_DEBOUNCE_MS = 150
# Highlight duration for selected element (ms)
HIGHLIGHT_DURATION_MS = 1500


class SearchResultItem(GObject.Object):
    """GObject wrapper for SearchResult to use with Gtk.ListView."""

    def __init__(self, result: SearchResult):
        super().__init__()
        self._result = result

    @GObject.Property(type=str)
    def element_name(self) -> str:
        return self._result.element_name

    @GObject.Property(type=str)
    def element_type(self) -> str:
        return self._result.element_type_name

    @GObject.Property(type=str)
    def description(self) -> str:
        return self._result.description

    @GObject.Property(type=str)
    def location(self) -> str:
        return self._result.location_summary

    @GObject.Property(type=str)
    def result_type_icon(self) -> str:
        icons = {
            SearchResultType.ELEMENT_NAME: "edit-find-symbolic",
            SearchResultType.ELEMENT_TYPE: "dialog-information-symbolic",
            SearchResultType.ATTRIBUTE_NAME: "format-text-direction-ltr-symbolic",
            SearchResultType.ATTRIBUTE_VALUE: "accessories-text-editor-symbolic",
            SearchResultType.RELATIONSHIP_TYPE: "insert-link-symbolic",
            SearchResultType.DIAGRAM_NAME: "x-office-drawing-symbolic",
        }
        return icons.get(self._result.result_type, "edit-find-symbolic")

    @property
    def result(self) -> SearchResult:
        return self._result


class AdvancedSearchDialog(UIComponent, ActionProvider):
    """Advanced search dialog component for Gaphor.

    Provides comprehensive search functionality with:
    - Search across element names, types, attributes, and relationships
    - Toggle between global and current diagram scope
    - Navigate to search results with highlighting
    """

    def __init__(
        self,
        event_manager: EventManager,
        element_factory: ElementFactory,
        diagrams,
    ):
        if event_manager is None:
            raise ValueError("event_manager cannot be None")
        if element_factory is None:
            raise ValueError("element_factory cannot be None")
        if diagrams is None:
            raise ValueError("diagrams cannot be None")

        self.event_manager = event_manager
        self.element_factory = element_factory
        self.diagrams = diagrams

        self._search_engine: AdvancedSearchEngine | None = None
        self._dialog: Gtk.Window | None = None
        self._search_entry: Gtk.SearchEntry | None = None
        self._results_list: Gtk.ListView | None = None
        self._results_store: Gtk.ListStore | None = None
        self._scope_toggle: Gtk.ToggleButton | None = None
        self._status_label: Gtk.Label | None = None
        self._search_timeout_id: int | None = None
        self._parent_window: Gtk.Window | None = None

        # Filter toggles
        self._filter_names: Gtk.ToggleButton | None = None
        self._filter_types: Gtk.ToggleButton | None = None
        self._filter_attributes: Gtk.ToggleButton | None = None
        self._filter_relationships: Gtk.ToggleButton | None = None

    def open(self) -> Gtk.Widget:
        """Open the search dialog component."""
        # Subscribe to model events
        self.event_manager.subscribe(self._on_element_created)
        self.event_manager.subscribe(self._on_element_deleted)
        self.event_manager.subscribe(self._on_model_flushed)
        self.event_manager.subscribe(self._on_model_ready)

        # Initialize search engine
        self._search_engine = AdvancedSearchEngine(self.element_factory)

        # Create a placeholder - the actual dialog is shown via action
        placeholder = Gtk.Box()
        placeholder.set_visible(False)
        return placeholder

    def close(self) -> None:
        """Close the search dialog component."""
        self.event_manager.unsubscribe(self._on_element_created)
        self.event_manager.unsubscribe(self._on_element_deleted)
        self.event_manager.unsubscribe(self._on_model_flushed)
        self.event_manager.unsubscribe(self._on_model_ready)

        if self._search_timeout_id is not None:
            GLib.source_remove(self._search_timeout_id)
            self._search_timeout_id = None

        if self._dialog is not None:
            self._dialog.destroy()
            self._dialog = None

        self._search_engine = None

    @action(name="win.advanced-search", shortcut="<Primary><Shift>f")
    def show_search_dialog(self) -> None:
        """Show the advanced search dialog."""
        if self._dialog is None:
            self._create_dialog()

        if self._dialog is not None:
            self._dialog.present()
            if self._search_entry is not None:
                self._search_entry.grab_focus()

    def _create_dialog(self) -> None:
        """Create the search dialog window."""
        self._dialog = Gtk.Window()
        self._dialog.set_title(gettext("Advanced Search"))
        self._dialog.set_default_size(600, 500)
        self._dialog.set_modal(False)
        self._dialog.set_hide_on_close(True)

        # Try to set transient for main window
        try:
            app = Gtk.Application.get_default()
            if app is not None:
                windows = app.get_windows()
                if windows:
                    self._dialog.set_transient_for(windows[0])
                    self._parent_window = windows[0]
        except Exception as e:
            log.debug(f"Could not set transient parent: {e}")

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        main_box.set_margin_top(12)
        main_box.set_margin_bottom(12)
        main_box.set_margin_start(12)
        main_box.set_margin_end(12)

        # Search entry
        self._search_entry = Gtk.SearchEntry()
        self._search_entry.set_placeholder_text(
            gettext("Search elements, types, attributes...")
        )
        self._search_entry.connect("search-changed", self._on_search_changed)
        self._search_entry.connect("activate", self._on_search_activate)
        main_box.append(self._search_entry)

        # Filter and scope controls
        controls_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        controls_box.set_margin_top(6)

        # Scope toggle
        self._scope_toggle = Gtk.ToggleButton()
        self._scope_toggle.set_label(gettext("Current Diagram Only"))
        self._scope_toggle.set_tooltip_text(
            gettext("Toggle between searching all packages or current diagram only")
        )
        self._scope_toggle.connect("toggled", self._on_scope_toggled)
        controls_box.append(self._scope_toggle)

        # Spacer
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        controls_box.append(spacer)

        # Filter buttons
        filter_label = Gtk.Label(label=gettext("Search in:"))
        filter_label.set_margin_end(6)
        controls_box.append(filter_label)

        self._filter_names = Gtk.ToggleButton(label=gettext("Names"))
        self._filter_names.set_active(True)
        self._filter_names.set_tooltip_text(gettext("Search in element names"))
        self._filter_names.connect("toggled", self._on_filter_changed)
        controls_box.append(self._filter_names)

        self._filter_types = Gtk.ToggleButton(label=gettext("Types"))
        self._filter_types.set_active(True)
        self._filter_types.set_tooltip_text(gettext("Search in element types"))
        self._filter_types.connect("toggled", self._on_filter_changed)
        controls_box.append(self._filter_types)

        self._filter_attributes = Gtk.ToggleButton(label=gettext("Attrs"))
        self._filter_attributes.set_active(True)
        self._filter_attributes.set_tooltip_text(
            gettext("Search in attribute names and values")
        )
        self._filter_attributes.connect("toggled", self._on_filter_changed)
        controls_box.append(self._filter_attributes)

        self._filter_relationships = Gtk.ToggleButton(label=gettext("Rels"))
        self._filter_relationships.set_active(True)
        self._filter_relationships.set_tooltip_text(
            gettext("Search in relationship types")
        )
        self._filter_relationships.connect("toggled", self._on_filter_changed)
        controls_box.append(self._filter_relationships)

        main_box.append(controls_box)

        # Results list
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        self._results_store = Gio.ListStore.new(SearchResultItem)

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_list_item_setup)
        factory.connect("bind", self._on_list_item_bind)

        selection = Gtk.SingleSelection.new(self._results_store)
        self._results_list = Gtk.ListView.new(selection, factory)
        self._results_list.connect("activate", self._on_result_activated)
        self._results_list.add_css_class("navigation-sidebar")

        scrolled.set_child(self._results_list)
        main_box.append(scrolled)

        # Status bar
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        status_box.set_margin_top(6)

        self._status_label = Gtk.Label(label=gettext("Enter search text..."))
        self._status_label.set_xalign(0)
        self._status_label.set_hexpand(True)
        status_box.append(self._status_label)

        # Keyboard shortcut hint
        hint_label = Gtk.Label(
            label=gettext("Enter to navigate • Ctrl+Shift+F to open")
        )
        hint_label.add_css_class("dim-label")
        status_box.append(hint_label)

        main_box.append(status_box)

        # Add keyboard controller for Escape
        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_key_pressed)
        self._dialog.add_controller(key_controller)

        self._dialog.set_child(main_box)

    def _on_list_item_setup(
        self, factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem
    ) -> None:
        """Set up a list item widget."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(6)
        box.set_margin_end(6)

        # Icon
        icon = Gtk.Image()
        icon.set_pixel_size(16)
        box.append(icon)

        # Text content
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text_box.set_hexpand(True)

        # Element name and type
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        name_label = Gtk.Label()
        name_label.set_xalign(0)
        name_label.set_ellipsize(Pango.EllipsizeMode.END)
        name_label.add_css_class("heading")
        header_box.append(name_label)

        type_label = Gtk.Label()
        type_label.set_xalign(0)
        type_label.add_css_class("dim-label")
        header_box.append(type_label)

        text_box.append(header_box)

        # Description
        desc_label = Gtk.Label()
        desc_label.set_xalign(0)
        desc_label.set_ellipsize(Pango.EllipsizeMode.END)
        text_box.append(desc_label)

        # Location
        loc_label = Gtk.Label()
        loc_label.set_xalign(0)
        loc_label.add_css_class("dim-label")
        loc_label.set_ellipsize(Pango.EllipsizeMode.END)
        text_box.append(loc_label)

        box.append(text_box)

        list_item.set_child(box)

    def _on_list_item_bind(
        self, factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem
    ) -> None:
        """Bind data to a list item."""
        item: SearchResultItem = list_item.get_item()
        box = list_item.get_child()

        if item is None or box is None:
            return

        try:
            # Get child widgets
            icon = box.get_first_child()
            text_box = icon.get_next_sibling() if icon else None

            if icon is not None:
                icon.set_from_icon_name(item.result_type_icon)

            if text_box is not None:
                header_box = text_box.get_first_child()
                if header_box is not None:
                    name_label = header_box.get_first_child()
                    type_label = name_label.get_next_sibling() if name_label else None

                    if name_label is not None:
                        name_label.set_label(item.element_name)
                    if type_label is not None:
                        type_label.set_label(f"({item.element_type})")

                desc_label = header_box.get_next_sibling() if header_box else None
                if desc_label is not None:
                    desc_label.set_label(item.description)

                loc_label = desc_label.get_next_sibling() if desc_label else None
                if loc_label is not None:
                    loc_label.set_label(item.location)

        except Exception as e:
            log.debug(f"Error binding list item: {e}")

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        """Handle search text changes with debouncing."""
        # Cancel previous timeout
        if self._search_timeout_id is not None:
            GLib.source_remove(self._search_timeout_id)
            self._search_timeout_id = None

        # Schedule new search
        self._search_timeout_id = GLib.timeout_add(
            SEARCH_DEBOUNCE_MS, self._perform_search
        )

    def _on_search_activate(self, entry: Gtk.SearchEntry) -> None:
        """Handle Enter key in search entry."""
        # Navigate to first result if available
        if self._results_store is not None and self._results_store.get_n_items() > 0:
            selection = self._results_list.get_model()
            if selection is not None:
                item = selection.get_selected_item()
                if item is not None:
                    self._navigate_to_result(item.result)

    def _on_result_activated(
        self, list_view: Gtk.ListView, position: int
    ) -> None:
        """Handle result item activation (double-click or Enter)."""
        if self._results_store is None:
            return

        item = self._results_store.get_item(position)
        if item is not None:
            self._navigate_to_result(item.result)

    def _on_scope_toggled(self, button: Gtk.ToggleButton) -> None:
        """Handle scope toggle."""
        self._perform_search()

    def _on_filter_changed(self, button: Gtk.ToggleButton) -> None:
        """Handle filter toggle."""
        self._perform_search()

    def _on_key_pressed(
        self,
        controller: Gtk.EventControllerKey,
        keyval: int,
        keycode: int,
        state: Gdk.ModifierType,
    ) -> bool:
        """Handle key press events."""
        if keyval == Gdk.KEY_Escape:
            if self._dialog is not None:
                self._dialog.hide()
            return True
        return False

    def _perform_search(self) -> bool:
        """Perform the actual search."""
        self._search_timeout_id = None

        if self._search_engine is None:
            return False

        if self._search_entry is None:
            return False

        search_text = self._search_entry.get_text().strip()

        if self._results_store is None:
            return False

        self._results_store.remove_all()

        if not search_text:
            self._update_status(gettext("Enter search text..."))
            return False

        # Determine scope
        scope = SearchScope.GLOBAL
        current_diagram = None
        if self._scope_toggle is not None and self._scope_toggle.get_active():
            scope = SearchScope.CURRENT_DIAGRAM
            current_diagram = self.diagrams.get_current_diagram()
            if current_diagram is None:
                self._update_status(gettext("No diagram is currently open"))
                return False

        # Get filter settings
        include_names = (
            self._filter_names.get_active() if self._filter_names else True
        )
        include_types = (
            self._filter_types.get_active() if self._filter_types else True
        )
        include_attributes = (
            self._filter_attributes.get_active() if self._filter_attributes else True
        )
        include_relationships = (
            self._filter_relationships.get_active()
            if self._filter_relationships
            else True
        )

        # Perform search
        try:
            results = self._search_engine.search(
                search_text=search_text,
                scope=scope,
                current_diagram=current_diagram,
                include_names=include_names,
                include_types=include_types,
                include_attributes=include_attributes,
                include_relationships=include_relationships,
            )

            # Populate results
            for result in results:
                self._results_store.append(SearchResultItem(result))

            # Update status
            count = len(results)
            if count == 0:
                self._update_status(gettext("No results found"))
            elif count == 1:
                self._update_status(gettext("1 result found"))
            else:
                self._update_status(gettext("{count} results found").format(count=count))

        except Exception as e:
            log.error(f"Search error: {e}")
            self._update_status(gettext("Search error occurred"))

        return False

    def _update_status(self, message: str) -> None:
        """Update the status label."""
        if self._status_label is not None:
            self._status_label.set_label(message)

    def _navigate_to_result(self, result: SearchResult) -> None:
        """Navigate to a search result, opening the diagram and highlighting the element."""
        if result is None:
            return

        element = result.element
        if element is None:
            return

        try:
            # If it's a diagram, just open it
            if isinstance(element, Diagram):
                self.event_manager.handle(DiagramOpened(element))
                return

            # Find a diagram containing this element
            diagram_locations = result.diagram_locations
            if not diagram_locations:
                log.info(f"Element {result.element_name} is not in any diagram")
                return

            # Open the first diagram
            location = diagram_locations[0]
            diagram = location.diagram
            presentation = location.presentation

            if diagram is None:
                return

            # Open the diagram
            self.event_manager.handle(DiagramOpened(diagram))

            # Wait a bit for the diagram to render, then highlight
            GLib.timeout_add(100, self._highlight_element, presentation)

        except Exception as e:
            log.error(f"Error navigating to result: {e}")

    def _highlight_element(self, presentation) -> bool:
        """Highlight an element in the current diagram view."""
        if presentation is None:
            return False

        try:
            view = self.diagrams.get_current_view()
            if view is None:
                return False

            # Select the element
            view.selection.unselect_all()
            view.selection.focused_item = presentation

            # Scroll to make it visible
            try:
                # Get bounding box of the item
                bounds = presentation.matrix_i2c.transform_point(0, 0)
                if bounds:
                    # Try to scroll the view
                    view.hadjustment.set_value(bounds[0] - 100)
                    view.vadjustment.set_value(bounds[1] - 100)
            except Exception as e:
                log.debug(f"Could not scroll to element: {e}")

            # Flash highlight effect using CSS
            self._apply_highlight_effect(view, presentation)

        except Exception as e:
            log.debug(f"Error highlighting element: {e}")

        return False

    def _apply_highlight_effect(self, view, presentation) -> None:
        """Apply a temporary highlight effect to an element."""
        try:
            # Request a view update to ensure the selection is visible
            view.queue_draw()

            # Schedule removal of any special highlighting after duration
            GLib.timeout_add(
                HIGHLIGHT_DURATION_MS,
                lambda: view.queue_draw() if view else False,
            )
        except Exception as e:
            log.debug(f"Error applying highlight effect: {e}")

    @event_handler(ElementCreated)
    def _on_element_created(self, event: ElementCreated) -> None:
        """Handle element creation - invalidate cache."""
        if self._search_engine is not None:
            self._search_engine.invalidate_cache()

    @event_handler(ElementDeleted)
    def _on_element_deleted(self, event: ElementDeleted) -> None:
        """Handle element deletion - invalidate cache."""
        if self._search_engine is not None:
            self._search_engine.invalidate_cache()

    @event_handler(ModelFlushed)
    def _on_model_flushed(self, event: ModelFlushed) -> None:
        """Handle model flush - clear results and invalidate cache."""
        if self._search_engine is not None:
            self._search_engine.invalidate_cache()
        if self._results_store is not None:
            self._results_store.remove_all()
        self._update_status(gettext("Model cleared"))

    @event_handler(ModelReady)
    def _on_model_ready(self, event: ModelReady) -> None:
        """Handle model ready - invalidate cache."""
        if self._search_engine is not None:
            self._search_engine.invalidate_cache()
