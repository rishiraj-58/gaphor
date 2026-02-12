"""Template browser UI for Gaphor.

This module provides a GTK-based UI for browsing, searching, and
applying diagram templates.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, GObject, Gtk

from gaphor.abc import ActionProvider
from gaphor.action import action
from gaphor.core import event_handler
from gaphor.i18n import gettext
from gaphor.transaction import Transaction
from gaphor.ui.abc import UIComponent

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
)

if TYPE_CHECKING:
    from gaphor.core.eventmanager import EventManager
    from gaphor.core.modeling import Diagram, ElementFactory
    from gaphor.services.modelinglanguage import ModelingLanguageService
    from gaphor.ui.diagrams import Diagrams

log = logging.getLogger(__name__)

# Debounce delay for search input
SEARCH_DEBOUNCE_MS = 300

# Default thumbnail placeholder
DEFAULT_THUMBNAIL_ICON = "document-new-symbolic"


class TemplateBrowserModel(GObject.Object):
    """GObject wrapper for template data in list models."""

    __gtype_name__ = "TemplateBrowserModel"

    def __init__(
        self,
        template_id: str,
        name: str,
        category: str,
        modeling_language: str,
        tags: list[str],
        is_builtin: bool,
        updated_at: str,
    ):
        super().__init__()
        self.template_id = template_id
        self.name = name
        self.category = category
        self.modeling_language = modeling_language
        self.tags = tags
        self.is_builtin = is_builtin
        self.updated_at = updated_at


class TemplateBrowser(UIComponent, ActionProvider):
    """Template browser UI component."""

    def __init__(
        self,
        event_manager: EventManager,
        element_factory: ElementFactory,
        modeling_language: ModelingLanguageService,
        template_service: TemplateService,
        diagrams: Diagrams,
    ):
        self._event_manager = event_manager
        self._element_factory = element_factory
        self._modeling_language = modeling_language
        self._template_service = template_service
        self._diagrams = diagrams

        self._window: Adw.Window | None = None
        self._search_entry: Gtk.SearchEntry | None = None
        self._category_dropdown: Gtk.DropDown | None = None
        self._template_list: Gtk.ListView | None = None
        self._selection_model: Gtk.SingleSelection | None = None
        self._preview_image: Gtk.Picture | None = None
        self._preview_name: Gtk.Label | None = None
        self._preview_description: Gtk.Label | None = None
        self._preview_details: Gtk.Label | None = None
        self._parameters_box: Gtk.Box | None = None
        self._apply_button: Gtk.Button | None = None

        self._search_timeout_id: int = 0
        self._current_filter_category: TemplateCategory | None = None
        self._current_search_query: str = ""
        self._parameter_widgets: dict[str, Gtk.Widget] = {}

    def open(self) -> Gtk.Widget:
        """Open the template browser."""
        if self._window:
            self._window.present()
            return self._window

        self._window = self._create_window()

        self._event_manager.subscribe(self._on_template_created)
        self._event_manager.subscribe(self._on_template_updated)
        self._event_manager.subscribe(self._on_template_deleted)

        self._refresh_templates()
        self._window.present()

        return self._window

    def close(self) -> None:
        """Close the template browser."""
        if self._search_timeout_id:
            GLib.source_remove(self._search_timeout_id)
            self._search_timeout_id = 0

        self._event_manager.unsubscribe(self._on_template_created)
        self._event_manager.unsubscribe(self._on_template_updated)
        self._event_manager.unsubscribe(self._on_template_deleted)

        if self._window:
            self._window.destroy()
            self._window = None

        self._parameter_widgets.clear()

    def _create_window(self) -> Adw.Window:
        """Create the main browser window."""
        window = Adw.Window()
        window.set_title(gettext("Template Browser"))
        window.set_default_size(900, 600)
        window.set_modal(False)

        # Main content box
        main_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)

        # Left panel - template list
        left_panel = self._create_left_panel()
        main_box.append(left_panel)

        # Separator
        separator = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        main_box.append(separator)

        # Right panel - preview and parameters
        right_panel = self._create_right_panel()
        main_box.append(right_panel)

        # Header bar
        header = Adw.HeaderBar()

        # Search toggle
        search_button = Gtk.ToggleButton()
        search_button.set_icon_name("edit-find-symbolic")
        search_button.set_tooltip_text(gettext("Search templates"))
        header.pack_start(search_button)

        # Create template button
        create_button = Gtk.Button()
        create_button.set_icon_name("list-add-symbolic")
        create_button.set_tooltip_text(gettext("Create template from diagram"))
        create_button.connect("clicked", self._on_create_clicked)
        header.pack_end(create_button)

        # Refresh button
        refresh_button = Gtk.Button()
        refresh_button.set_icon_name("view-refresh-symbolic")
        refresh_button.set_tooltip_text(gettext("Refresh templates"))
        refresh_button.connect("clicked", self._on_refresh_clicked)
        header.pack_end(refresh_button)

        # Content with header
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        content_box.append(header)

        # Search bar
        self._search_entry = Gtk.SearchEntry()
        self._search_entry.set_placeholder_text(gettext("Search templates..."))
        self._search_entry.connect("search-changed", self._on_search_changed)

        search_bar = Gtk.SearchBar()
        search_bar.set_child(self._search_entry)
        search_bar.connect_entry(self._search_entry)
        search_button.bind_property(
            "active", search_bar, "search-mode-enabled",
            GObject.BindingFlags.BIDIRECTIONAL
        )
        content_box.append(search_bar)

        content_box.append(main_box)

        window.set_content(content_box)
        window.connect("close-request", self._on_window_close)

        return window

    def _create_left_panel(self) -> Gtk.Widget:
        """Create the left panel with category filter and template list."""
        left_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        left_box.set_size_request(350, -1)
        left_box.set_margin_top(8)
        left_box.set_margin_bottom(8)
        left_box.set_margin_start(8)
        left_box.set_margin_end(8)

        # Category filter
        category_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        category_label = Gtk.Label(label=gettext("Category:"))
        category_box.append(category_label)

        # Build category model
        category_model = Gtk.StringList()
        category_model.append(gettext("All Categories"))
        self._category_values = [None]

        for category in TemplateCategory:
            display_name = category.value.replace("_", " ").title()
            category_model.append(display_name)
            self._category_values.append(category)

        self._category_dropdown = Gtk.DropDown(model=category_model)
        self._category_dropdown.set_hexpand(True)
        self._category_dropdown.connect("notify::selected", self._on_category_changed)
        category_box.append(self._category_dropdown)

        left_box.append(category_box)

        # Template list
        list_model = Gio.ListStore.new(TemplateBrowserModel)
        self._selection_model = Gtk.SingleSelection(model=list_model)
        self._selection_model.connect("selection-changed", self._on_selection_changed)

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_list_item_setup)
        factory.connect("bind", self._on_list_item_bind)

        self._template_list = Gtk.ListView(
            model=self._selection_model,
            factory=factory,
        )
        self._template_list.add_css_class("navigation-sidebar")

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_child(self._template_list)

        left_box.append(scrolled)

        return left_box

    def _create_right_panel(self) -> Gtk.Widget:
        """Create the right panel with preview and parameters."""
        right_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        right_box.set_hexpand(True)
        right_box.set_margin_top(16)
        right_box.set_margin_bottom(16)
        right_box.set_margin_start(16)
        right_box.set_margin_end(16)

        # Preview section
        preview_frame = Gtk.Frame()
        preview_frame.add_css_class("view")

        preview_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        preview_box.set_margin_top(12)
        preview_box.set_margin_bottom(12)
        preview_box.set_margin_start(12)
        preview_box.set_margin_end(12)

        # Thumbnail
        self._preview_image = Gtk.Picture()
        self._preview_image.set_size_request(256, 192)
        self._preview_image.set_content_fit(Gtk.ContentFit.CONTAIN)
        self._preview_image.add_css_class("card")
        preview_box.append(self._preview_image)

        # Template name
        self._preview_name = Gtk.Label()
        self._preview_name.add_css_class("title-2")
        self._preview_name.set_wrap(True)
        self._preview_name.set_xalign(0)
        preview_box.append(self._preview_name)

        # Description
        self._preview_description = Gtk.Label()
        self._preview_description.set_wrap(True)
        self._preview_description.set_xalign(0)
        self._preview_description.add_css_class("dim-label")
        preview_box.append(self._preview_description)

        # Details (category, language, etc.)
        self._preview_details = Gtk.Label()
        self._preview_details.set_wrap(True)
        self._preview_details.set_xalign(0)
        self._preview_details.add_css_class("caption")
        preview_box.append(self._preview_details)

        preview_frame.set_child(preview_box)
        right_box.append(preview_frame)

        # Parameters section
        params_label = Gtk.Label(label=gettext("Parameters"))
        params_label.add_css_class("title-3")
        params_label.set_xalign(0)
        right_box.append(params_label)

        self._parameters_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        right_box.append(self._parameters_box)

        # Spacer
        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        right_box.append(spacer)

        # Action buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        button_box.set_halign(Gtk.Align.END)

        # Delete button
        delete_button = Gtk.Button(label=gettext("Delete"))
        delete_button.add_css_class("destructive-action")
        delete_button.connect("clicked", self._on_delete_clicked)
        button_box.append(delete_button)

        # Duplicate button
        duplicate_button = Gtk.Button(label=gettext("Duplicate"))
        duplicate_button.connect("clicked", self._on_duplicate_clicked)
        button_box.append(duplicate_button)

        # Apply button
        self._apply_button = Gtk.Button(label=gettext("Apply to Diagram"))
        self._apply_button.add_css_class("suggested-action")
        self._apply_button.connect("clicked", self._on_apply_clicked)
        self._apply_button.set_sensitive(False)
        button_box.append(self._apply_button)

        right_box.append(button_box)

        return right_box

    def _on_list_item_setup(self, factory: Gtk.ListItemFactory, list_item: Gtk.ListItem) -> None:
        """Set up a list item widget."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(8)
        box.set_margin_end(8)

        # Icon
        icon = Gtk.Image.new_from_icon_name(DEFAULT_THUMBNAIL_ICON)
        icon.set_pixel_size(32)
        box.append(icon)

        # Text box
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)

        name_label = Gtk.Label()
        name_label.set_xalign(0)
        name_label.set_ellipsize(3)  # PANGO_ELLIPSIZE_END
        text_box.append(name_label)

        details_label = Gtk.Label()
        details_label.set_xalign(0)
        details_label.add_css_class("dim-label")
        details_label.add_css_class("caption")
        text_box.append(details_label)

        box.append(text_box)

        # Builtin indicator
        builtin_icon = Gtk.Image.new_from_icon_name("emblem-system-symbolic")
        builtin_icon.set_pixel_size(16)
        builtin_icon.set_tooltip_text(gettext("Built-in template"))
        box.append(builtin_icon)

        list_item.set_child(box)

    def _on_list_item_bind(self, factory: Gtk.ListItemFactory, list_item: Gtk.ListItem) -> None:
        """Bind data to a list item."""
        item: TemplateBrowserModel = list_item.get_item()
        box = list_item.get_child()

        if not item or not box:
            return

        children = list(self._iter_children(box))
        if len(children) < 3:
            return

        icon = children[0]
        text_box = children[1]
        builtin_icon = children[2]

        # Set icon based on category
        icon_name = self._get_category_icon(item.category)
        if isinstance(icon, Gtk.Image):
            icon.set_from_icon_name(icon_name)

        # Set text
        text_children = list(self._iter_children(text_box))
        if len(text_children) >= 2:
            name_label = text_children[0]
            details_label = text_children[1]

            if isinstance(name_label, Gtk.Label):
                name_label.set_text(item.name or gettext("Unnamed"))

            if isinstance(details_label, Gtk.Label):
                category_display = item.category.replace("_", " ").title()
                details_label.set_text(f"{category_display} • {item.modeling_language}")

        # Show/hide builtin indicator
        if isinstance(builtin_icon, Gtk.Image):
            builtin_icon.set_visible(item.is_builtin)

    def _iter_children(self, widget: Gtk.Widget):
        """Iterate over children of a widget."""
        child = widget.get_first_child()
        while child:
            yield child
            child = child.get_next_sibling()

    def _get_category_icon(self, category: str) -> str:
        """Get icon name for a category."""
        icon_map = {
            "class_diagram": "class-diagram-symbolic",
            "sequence_diagram": "sequence-diagram-symbolic",
            "use_case": "use-case-symbolic",
            "activity": "activity-diagram-symbolic",
            "state_machine": "state-machine-symbolic",
            "component": "component-diagram-symbolic",
            "deployment": "deployment-diagram-symbolic",
            "package": "package-symbolic",
            "sysml": "sysml-symbolic",
            "c4_model": "c4-model-symbolic",
            "raaml": "raaml-symbolic",
        }
        return icon_map.get(category, "document-new-symbolic")

    def _refresh_templates(self) -> None:
        """Refresh the template list."""
        if not self._selection_model:
            return

        list_model = self._selection_model.get_model()
        if not isinstance(list_model, Gio.ListStore):
            return

        list_model.remove_all()

        try:
            templates = self._template_service.list_templates(
                category=self._current_filter_category,
                search_query=self._current_search_query or None,
            )

            for t in templates:
                item = TemplateBrowserModel(
                    template_id=t.get("id", ""),
                    name=t.get("name", ""),
                    category=t.get("category", "general"),
                    modeling_language=t.get("modeling_language", "UML"),
                    tags=t.get("tags", []),
                    is_builtin=t.get("is_builtin", False),
                    updated_at=t.get("updated_at", ""),
                )
                list_model.append(item)

        except Exception as e:
            log.error(f"Failed to refresh templates: {e}")
            self._show_error(gettext("Could not load templates"))

    def _update_preview(self, template: DiagramTemplate | None) -> None:
        """Update the preview panel with template details."""
        if template is None:
            self._preview_name.set_text(gettext("No template selected"))
            self._preview_description.set_text("")
            self._preview_details.set_text("")
            self._preview_image.set_paintable(None)
            self._clear_parameters()
            self._apply_button.set_sensitive(False)
            return

        self._preview_name.set_text(template.name or gettext("Unnamed"))
        self._preview_description.set_text(template.description or "")

        # Build details text
        category_display = template.category.value.replace("_", " ").title()
        details_parts = [
            f"{gettext('Category')}: {category_display}",
            f"{gettext('Language')}: {template.modeling_language}",
            f"{gettext('Version')}: {template.version}",
        ]
        if template.author:
            details_parts.append(f"{gettext('Author')}: {template.author}")
        if template.tags:
            details_parts.append(f"{gettext('Tags')}: {', '.join(template.tags[:5])}")

        self._preview_details.set_text("\n".join(details_parts))

        # Set thumbnail
        if template.thumbnail_data:
            try:
                loader = GdkPixbuf.PixbufLoader()
                loader.write(template.thumbnail_data)
                loader.close()
                pixbuf = loader.get_pixbuf()
                if pixbuf:
                    texture = Gdk.Texture.new_for_pixbuf(pixbuf)
                    self._preview_image.set_paintable(texture)
                else:
                    self._preview_image.set_paintable(None)
            except Exception as e:
                log.warning(f"Could not load thumbnail: {e}")
                self._preview_image.set_paintable(None)
        else:
            self._preview_image.set_paintable(None)

        # Build parameter widgets
        self._build_parameter_widgets(template.parameters)

        # Enable apply button if there's a current diagram
        current_view = self._diagrams.get_current_view() if self._diagrams else None
        self._apply_button.set_sensitive(current_view is not None)

    def _clear_parameters(self) -> None:
        """Clear all parameter widgets."""
        while child := self._parameters_box.get_first_child():
            self._parameters_box.remove(child)
        self._parameter_widgets.clear()

    def _build_parameter_widgets(self, parameters: list[TemplateParameter]) -> None:
        """Build widgets for template parameters."""
        self._clear_parameters()

        if not parameters:
            no_params_label = Gtk.Label(label=gettext("No parameters"))
            no_params_label.add_css_class("dim-label")
            self._parameters_box.append(no_params_label)
            return

        for param in parameters:
            row = self._create_parameter_row(param)
            self._parameters_box.append(row)

    def _create_parameter_row(self, param: TemplateParameter) -> Gtk.Widget:
        """Create a widget row for a single parameter."""
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        # Label
        label_text = param.label or param.name
        if param.required:
            label_text += " *"
        label = Gtk.Label(label=label_text)
        label.set_xalign(0)
        label.set_size_request(120, -1)
        row.append(label)

        # Input widget based on type
        widget: Gtk.Widget

        if param.param_type == TemplateParameterType.BOOLEAN:
            widget = Gtk.Switch()
            if param.default_value:
                widget.set_active(param.default_value.lower() in ("true", "1", "yes"))

        elif param.param_type == TemplateParameterType.CHOICE:
            model = Gtk.StringList()
            selected_index = 0
            for i, choice in enumerate(param.choices):
                label_text = choice.get("label", choice.get("value", ""))
                model.append(label_text)
                if choice.get("value") == param.default_value:
                    selected_index = i
            widget = Gtk.DropDown(model=model)
            widget.set_selected(selected_index)
            # Store choices for value lookup
            widget._choices = param.choices

        elif param.param_type == TemplateParameterType.INTEGER:
            adjustment = Gtk.Adjustment(
                value=int(param.default_value) if param.default_value else 0,
                lower=param.min_value or -999999,
                upper=param.max_value or 999999,
                step_increment=1,
            )
            widget = Gtk.SpinButton(adjustment=adjustment)
            widget.set_digits(0)

        elif param.param_type == TemplateParameterType.FLOAT:
            adjustment = Gtk.Adjustment(
                value=float(param.default_value) if param.default_value else 0.0,
                lower=param.min_value or -999999.0,
                upper=param.max_value or 999999.0,
                step_increment=0.1,
            )
            widget = Gtk.SpinButton(adjustment=adjustment)
            widget.set_digits(2)

        else:  # STRING or ELEMENT_NAME
            widget = Gtk.Entry()
            widget.set_text(param.default_value or "")
            widget.set_placeholder_text(param.description or param.name)

        widget.set_hexpand(True)

        if param.description:
            widget.set_tooltip_text(param.description)

        self._parameter_widgets[param.name] = widget
        row.append(widget)

        return row

    def _get_parameter_values(self) -> dict[str, str]:
        """Get current values from parameter widgets."""
        values: dict[str, str] = {}

        for name, widget in self._parameter_widgets.items():
            if isinstance(widget, Gtk.Switch):
                values[name] = "true" if widget.get_active() else "false"
            elif isinstance(widget, Gtk.DropDown):
                index = widget.get_selected()
                choices = getattr(widget, "_choices", [])
                if 0 <= index < len(choices):
                    values[name] = choices[index].get("value", "")
            elif isinstance(widget, Gtk.SpinButton):
                values[name] = str(widget.get_value())
            elif isinstance(widget, Gtk.Entry):
                values[name] = widget.get_text()

        return values

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        """Handle search text changes with debouncing."""
        if self._search_timeout_id:
            GLib.source_remove(self._search_timeout_id)

        def do_search():
            self._search_timeout_id = 0
            self._current_search_query = entry.get_text()
            self._refresh_templates()
            return False

        self._search_timeout_id = GLib.timeout_add(SEARCH_DEBOUNCE_MS, do_search)

    def _on_category_changed(self, dropdown: Gtk.DropDown, _pspec) -> None:
        """Handle category filter changes."""
        index = dropdown.get_selected()
        if 0 <= index < len(self._category_values):
            self._current_filter_category = self._category_values[index]
            self._refresh_templates()

    def _on_selection_changed(self, selection: Gtk.SelectionModel, position: int, n_items: int) -> None:
        """Handle template selection changes."""
        selected = selection.get_selected_item()
        if not isinstance(selected, TemplateBrowserModel):
            self._update_preview(None)
            return

        template = self._template_service.get_template(selected.template_id)
        self._update_preview(template)

    def _on_apply_clicked(self, button: Gtk.Button) -> None:
        """Apply the selected template to the current diagram."""
        if not self._selection_model:
            return

        selected = self._selection_model.get_selected_item()
        if not isinstance(selected, TemplateBrowserModel):
            return

        current_view = self._diagrams.get_current_view() if self._diagrams else None
        if not current_view:
            self._show_error(gettext("No diagram selected"))
            return

        diagram = current_view.diagram
        if not diagram:
            self._show_error(gettext("No diagram available"))
            return

        parameter_values = self._get_parameter_values()

        try:
            with Transaction(self._event_manager):
                errors = self._template_service.apply_template(
                    selected.template_id,
                    diagram,
                    parameter_values,
                )

            if errors:
                self._show_error("\n".join(errors))
            else:
                self._show_info(gettext("Template applied successfully"))
                self.close()

        except Exception as e:
            log.error(f"Failed to apply template: {e}")
            self._show_error(str(e))

    def _on_delete_clicked(self, button: Gtk.Button) -> None:
        """Delete the selected template."""
        if not self._selection_model:
            return

        selected = self._selection_model.get_selected_item()
        if not isinstance(selected, TemplateBrowserModel):
            return

        if selected.is_builtin:
            self._show_error(gettext("Cannot delete built-in templates"))
            return

        # Show confirmation dialog
        dialog = Adw.MessageDialog(
            transient_for=self._window,
            heading=gettext("Delete Template?"),
            body=gettext("This action cannot be undone."),
        )
        dialog.add_response("cancel", gettext("Cancel"))
        dialog.add_response("delete", gettext("Delete"))
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def on_response(dialog, response):
            if response == "delete":
                try:
                    self._template_service.delete_template(selected.template_id)
                    self._refresh_templates()
                except Exception as e:
                    log.error(f"Failed to delete template: {e}")
                    self._show_error(str(e))
            dialog.destroy()

        dialog.connect("response", on_response)
        dialog.present()

    def _on_duplicate_clicked(self, button: Gtk.Button) -> None:
        """Duplicate the selected template."""
        if not self._selection_model:
            return

        selected = self._selection_model.get_selected_item()
        if not isinstance(selected, TemplateBrowserModel):
            return

        try:
            self._template_service.duplicate_template(selected.template_id)
            self._refresh_templates()
            self._show_info(gettext("Template duplicated"))
        except Exception as e:
            log.error(f"Failed to duplicate template: {e}")
            self._show_error(str(e))

    def _on_create_clicked(self, button: Gtk.Button) -> None:
        """Create a new template from the current diagram."""
        current_view = self._diagrams.get_current_view() if self._diagrams else None
        if not current_view or not current_view.diagram:
            self._show_error(gettext("No diagram selected"))
            return

        # Show name dialog
        dialog = Adw.MessageDialog(
            transient_for=self._window,
            heading=gettext("Create Template"),
            body=gettext("Enter a name for the new template:"),
        )

        # Add name entry
        entry = Gtk.Entry()
        entry.set_placeholder_text(gettext("Template name"))
        entry.set_text(current_view.diagram.name or gettext("New Template"))
        dialog.set_extra_child(entry)

        dialog.add_response("cancel", gettext("Cancel"))
        dialog.add_response("create", gettext("Create"))
        dialog.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("create")
        dialog.set_close_response("cancel")

        def on_response(dialog, response):
            if response == "create":
                name = entry.get_text().strip()
                if not name:
                    self._show_error(gettext("Name cannot be empty"))
                else:
                    try:
                        self._template_service.create_template_from_diagram(
                            current_view.diagram,
                            name=name,
                        )
                        self._refresh_templates()
                        self._show_info(gettext("Template created"))
                    except Exception as e:
                        log.error(f"Failed to create template: {e}")
                        self._show_error(str(e))
            dialog.destroy()

        dialog.connect("response", on_response)
        dialog.present()

    def _on_refresh_clicked(self, button: Gtk.Button) -> None:
        """Refresh the template list."""
        self._refresh_templates()

    def _on_window_close(self, window: Gtk.Window) -> bool:
        """Handle window close."""
        self.close()
        return False

    @event_handler(TemplateCreatedEvent)
    def _on_template_created(self, event: TemplateCreatedEvent) -> None:
        """Handle template created event."""
        self._refresh_templates()

    @event_handler(TemplateUpdatedEvent)
    def _on_template_updated(self, event: TemplateUpdatedEvent) -> None:
        """Handle template updated event."""
        self._refresh_templates()

    @event_handler(TemplateDeletedEvent)
    def _on_template_deleted(self, event: TemplateDeletedEvent) -> None:
        """Handle template deleted event."""
        self._refresh_templates()

    def _show_error(self, message: str) -> None:
        """Show an error notification."""
        if self._window:
            toast = Adw.Toast.new(message)
            toast.set_timeout(5)

            # Find or create toast overlay
            content = self._window.get_content()
            if isinstance(content, Adw.ToastOverlay):
                content.add_toast(toast)
            else:
                overlay = Adw.ToastOverlay()
                overlay.set_child(content)
                self._window.set_content(overlay)
                overlay.add_toast(toast)

    def _show_info(self, message: str) -> None:
        """Show an info notification."""
        self._show_error(message)  # Reuse same mechanism

    @action(name="win.open-template-browser")
    def open_template_browser(self) -> None:
        """Action to open the template browser."""
        self.open()
