"""Model comparison window for Gaphor.

This module provides the split-screen comparison view that highlights
differences between two model versions with color coding.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from gi.repository import Gdk, GLib, GObject, Gtk, Pango

from gaphor.core import gettext
from gaphor.ui.modelcompare.differ import (
    ChangeType,
    ElementDiff,
    ModelDiff,
    PropertyChange,
    format_property_change,
    get_element_display_name,
)

if TYPE_CHECKING:
    from gaphor.core.modeling import Base, ElementFactory

log = logging.getLogger(__name__)

# Colors for diff highlighting
COLORS = {
    ChangeType.ADDED: Gdk.RGBA(red=0.2, green=0.7, blue=0.2, alpha=0.3),
    ChangeType.REMOVED: Gdk.RGBA(red=0.8, green=0.2, blue=0.2, alpha=0.3),
    ChangeType.MODIFIED: Gdk.RGBA(red=0.7, green=0.6, blue=0.1, alpha=0.3),
    ChangeType.UNCHANGED: Gdk.RGBA(red=0.0, green=0.0, blue=0.0, alpha=0.0),
}

COLOR_NAMES = {
    ChangeType.ADDED: "#34a853",
    ChangeType.REMOVED: "#ea4335",
    ChangeType.MODIFIED: "#fbbc04",
    ChangeType.UNCHANGED: "#808080",
}


class DiffListItem(GObject.Object):
    """A single item in the diff list."""

    def __init__(
        self,
        diff: ElementDiff | None = None,
        change: PropertyChange | None = None,
        is_header: bool = False,
        header_text: str = "",
        level: int = 0,
    ):
        super().__init__()
        self.diff = diff
        self.change = change
        self.is_header = is_header
        self.header_text = header_text
        self.level = level

    @property
    def element_id(self) -> str | None:
        """Get the element ID if this item represents an element diff."""
        if self.diff:
            return self.diff.element_id
        return None

    @property
    def change_type(self) -> ChangeType:
        """Get the change type for this item."""
        if self.diff:
            return self.diff.change_type
        if self.change:
            return self.change.change_type
        return ChangeType.UNCHANGED

    @property
    def display_text(self) -> str:
        """Get the display text for this item."""
        if self.is_header:
            return self.header_text
        if self.diff:
            name = self.diff.element_name or self.diff.element_id[:8]
            type_name = self.diff.element_type
            change_symbol = self._get_change_symbol(self.diff.change_type)
            return f"{change_symbol} {type_name}: {name}"
        if self.change:
            return format_property_change(self.change)
        return ""

    def _get_change_symbol(self, change_type: ChangeType) -> str:
        """Get a symbol representing the change type."""
        symbols = {
            ChangeType.ADDED: "+",
            ChangeType.REMOVED: "-",
            ChangeType.MODIFIED: "~",
            ChangeType.UNCHANGED: " ",
        }
        return symbols.get(change_type, " ")


class ModelCompareWindow:
    """Window showing split-screen model comparison."""

    def __init__(
        self,
        diff: ModelDiff,
        base_factory: "ElementFactory",
        compare_factory: "ElementFactory | None",
        parent: Gtk.Window | None = None,
        on_close: Callable[[], None] | None = None,
        on_navigate: Callable[[str], None] | None = None,
    ):
        if diff is None:
            raise ValueError("diff cannot be None")

        self._diff = diff
        self._base_factory = base_factory
        self._compare_factory = compare_factory
        self._parent = parent
        self._on_close = on_close
        self._on_navigate = on_navigate
        self._window: Gtk.Window | None = None
        self._list_store: Gtk.ListStore | None = None
        self._tree_view: Gtk.TreeView | None = None

        self._build_window()

    def _build_window(self):
        """Build the comparison window UI."""
        self._window = Gtk.Window()
        self._window.set_title(gettext("Model Comparison"))
        self._window.set_default_size(900, 700)

        if self._parent:
            self._window.set_transient_for(self._parent)
            self._window.set_modal(False)

        self._window.connect("close-request", self._on_window_close)

        # Main container
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._window.set_child(main_box)

        # Header bar with summary
        header = self._create_header()
        main_box.append(header)

        # Paned container for split view
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_vexpand(True)
        paned.set_hexpand(True)
        main_box.append(paned)

        # Left panel: diff tree
        left_panel = self._create_diff_tree_panel()
        paned.set_start_child(left_panel)
        paned.set_resize_start_child(True)

        # Right panel: details view
        right_panel = self._create_details_panel()
        paned.set_end_child(right_panel)
        paned.set_resize_end_child(True)

        # Set initial position
        paned.set_position(450)

        # Footer with action buttons
        footer = self._create_footer()
        main_box.append(footer)

        # Populate the diff tree
        self._populate_diff_tree()

    def _create_header(self) -> Gtk.Widget:
        """Create the header with comparison summary."""
        header_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        header_box.add_css_class("card")
        header_box.set_margin_top(8)
        header_box.set_margin_bottom(8)
        header_box.set_margin_start(8)
        header_box.set_margin_end(8)

        # Title
        title = Gtk.Label()
        title.set_markup(f"<b>{gettext('Model Comparison Results')}</b>")
        title.set_halign(Gtk.Align.START)
        header_box.append(title)

        # Summary statistics
        summary = self._create_summary_label()
        header_box.append(summary)

        # File paths if available
        if self._diff.compare_model_path:
            path_label = Gtk.Label()
            path_label.set_markup(
                f"<small>{gettext('Comparing with')}: {self._diff.compare_model_path}</small>"
            )
            path_label.set_halign(Gtk.Align.START)
            path_label.add_css_class("dim-label")
            header_box.append(path_label)

        return header_box

    def _create_summary_label(self) -> Gtk.Label:
        """Create the summary statistics label."""
        added = len(self._diff.added_elements)
        removed = len(self._diff.removed_elements)
        modified = len(self._diff.modified_elements)

        parts = []
        if added:
            parts.append(
                f"<span foreground='{COLOR_NAMES[ChangeType.ADDED]}'>"
                f"+{added} {gettext('added')}</span>"
            )
        if removed:
            parts.append(
                f"<span foreground='{COLOR_NAMES[ChangeType.REMOVED]}'>"
                f"-{removed} {gettext('removed')}</span>"
            )
        if modified:
            parts.append(
                f"<span foreground='{COLOR_NAMES[ChangeType.MODIFIED]}'>"
                f"~{modified} {gettext('modified')}</span>"
            )

        label = Gtk.Label()
        label.set_markup(", ".join(parts) if parts else gettext("No changes"))
        label.set_halign(Gtk.Align.START)
        return label

    def _create_diff_tree_panel(self) -> Gtk.Widget:
        """Create the left panel with diff tree."""
        frame = Gtk.Frame()
        frame.set_label(gettext("Changes"))

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_min_content_height(400)
        frame.set_child(scrolled)

        # Create list store: text, change_type_str, element_id, level, is_header
        self._list_store = Gtk.ListStore(str, str, str, int, bool)

        # Create tree view
        self._tree_view = Gtk.TreeView(model=self._list_store)
        self._tree_view.set_headers_visible(False)
        self._tree_view.set_enable_tree_lines(True)

        # Text column with custom rendering
        renderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn("Change", renderer, text=0)
        column.set_cell_data_func(renderer, self._cell_data_func)
        self._tree_view.append_column(column)

        # Selection handling
        selection = self._tree_view.get_selection()
        selection.set_mode(Gtk.SelectionMode.SINGLE)
        selection.connect("changed", self._on_selection_changed)

        # Double-click handling
        self._tree_view.connect("row-activated", self._on_row_activated)

        scrolled.set_child(self._tree_view)
        return frame

    def _cell_data_func(
        self,
        column: Gtk.TreeViewColumn,
        cell: Gtk.CellRendererText,
        model: Gtk.ListStore,
        iter: Gtk.TreeIter,
        data=None,
    ):
        """Custom cell rendering for diff items."""
        change_type_str = model.get_value(iter, 1)
        level = model.get_value(iter, 3)
        is_header = model.get_value(iter, 4)

        # Set indentation based on level
        cell.set_property("xpad", level * 20)

        # Set style based on change type
        if is_header:
            cell.set_property("weight", Pango.Weight.BOLD)
            cell.set_property("foreground", "#555555")
            cell.set_property("background-set", False)
        else:
            cell.set_property("weight", Pango.Weight.NORMAL)

            if change_type_str == "ADDED":
                cell.set_property("foreground", COLOR_NAMES[ChangeType.ADDED])
                cell.set_property("background", "#e6f4ea")
            elif change_type_str == "REMOVED":
                cell.set_property("foreground", COLOR_NAMES[ChangeType.REMOVED])
                cell.set_property("background", "#fce8e6")
            elif change_type_str == "MODIFIED":
                cell.set_property("foreground", COLOR_NAMES[ChangeType.MODIFIED])
                cell.set_property("background", "#fef7e0")
            else:
                cell.set_property("foreground-set", False)
                cell.set_property("background-set", False)

    def _create_details_panel(self) -> Gtk.Widget:
        """Create the right panel with element details."""
        frame = Gtk.Frame()
        frame.set_label(gettext("Details"))

        self._details_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._details_box.set_margin_top(8)
        self._details_box.set_margin_bottom(8)
        self._details_box.set_margin_start(8)
        self._details_box.set_margin_end(8)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_child(self._details_box)
        frame.set_child(scrolled)

        # Initial placeholder
        placeholder = Gtk.Label()
        placeholder.set_markup(
            f"<i>{gettext('Select an item to view details')}</i>"
        )
        placeholder.add_css_class("dim-label")
        self._details_box.append(placeholder)

        return frame

    def _create_footer(self) -> Gtk.Widget:
        """Create the footer with action buttons."""
        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        footer.set_margin_top(8)
        footer.set_margin_bottom(8)
        footer.set_margin_start(8)
        footer.set_margin_end(8)

        # Legend
        legend_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        footer.append(legend_box)

        for change_type, color in COLOR_NAMES.items():
            if change_type == ChangeType.UNCHANGED:
                continue
            label = Gtk.Label()
            symbol = {
                ChangeType.ADDED: "+",
                ChangeType.REMOVED: "-",
                ChangeType.MODIFIED: "~",
            }.get(change_type, " ")
            name = {
                ChangeType.ADDED: gettext("Added"),
                ChangeType.REMOVED: gettext("Removed"),
                ChangeType.MODIFIED: gettext("Modified"),
            }.get(change_type, "")
            label.set_markup(f"<span foreground='{color}'>{symbol}</span> {name}")
            legend_box.append(label)

        # Spacer
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        footer.append(spacer)

        # Close button
        close_btn = Gtk.Button(label=gettext("Close"))
        close_btn.connect("clicked", lambda _: self.close())
        footer.append(close_btn)

        return footer

    def _populate_diff_tree(self):
        """Populate the diff tree with comparison results."""
        if not self._list_store or not self._diff:
            return

        self._list_store.clear()

        # Group diffs by category
        diagrams = [d for d in self._diff.element_diffs if d.is_diagram]
        presentations = [d for d in self._diff.element_diffs if d.is_presentation]
        others = [
            d
            for d in self._diff.element_diffs
            if not d.is_diagram and not d.is_presentation
        ]

        # Add diagrams section
        if diagrams:
            self._add_section(gettext("Diagrams"), diagrams)

        # Add model elements section
        if others:
            self._add_section(gettext("Model Elements"), others)

        # Add presentation elements section
        if presentations:
            self._add_section(gettext("Presentation Items"), presentations)

    def _add_section(self, header: str, diffs: list[ElementDiff]):
        """Add a section with header to the tree."""
        if not self._list_store:
            return

        # Add header
        self._list_store.append([f"▼ {header} ({len(diffs)})", "", "", 0, True])

        # Sort diffs by change type then name
        sorted_diffs = sorted(
            diffs,
            key=lambda d: (
                {ChangeType.REMOVED: 0, ChangeType.ADDED: 1, ChangeType.MODIFIED: 2}.get(
                    d.change_type, 3
                ),
                d.element_name or d.element_id,
            ),
        )

        for diff in sorted_diffs:
            name = diff.element_name or diff.element_id[:12]
            type_name = diff.element_type
            symbol = {
                ChangeType.ADDED: "+",
                ChangeType.REMOVED: "-",
                ChangeType.MODIFIED: "~",
            }.get(diff.change_type, " ")

            display_text = f"{symbol} [{type_name}] {name}"
            self._list_store.append(
                [display_text, diff.change_type.name, diff.element_id, 1, False]
            )

            # Add property changes for modified elements
            if diff.change_type == ChangeType.MODIFIED and diff.property_changes:
                for change in diff.property_changes[:10]:  # Limit to 10 changes
                    change_text = format_property_change(change)
                    self._list_store.append(
                        [change_text, change.change_type.name, "", 2, False]
                    )
                if len(diff.property_changes) > 10:
                    self._list_store.append(
                        [
                            f"  ... and {len(diff.property_changes) - 10} more",
                            "",
                            "",
                            2,
                            False,
                        ]
                    )

    def _on_selection_changed(self, selection: Gtk.TreeSelection):
        """Handle tree selection change."""
        model, tree_iter = selection.get_selected()
        if not tree_iter:
            return

        element_id = model.get_value(tree_iter, 2)
        if element_id:
            self._show_element_details(element_id)

    def _on_row_activated(
        self, tree_view: Gtk.TreeView, path: Gtk.TreePath, column: Gtk.TreeViewColumn
    ):
        """Handle double-click on a row."""
        if not self._list_store:
            return

        tree_iter = self._list_store.get_iter(path)
        if not tree_iter:
            return

        element_id = self._list_store.get_value(tree_iter, 2)
        if element_id and self._on_navigate:
            self._on_navigate(element_id)

    def _show_element_details(self, element_id: str):
        """Show details for an element."""
        diff = self._diff.get_diff_for_element(element_id)
        if not diff:
            return

        # Clear current details
        while child := self._details_box.get_first_child():
            self._details_box.remove(child)

        # Element header
        header = Gtk.Label()
        color = COLOR_NAMES.get(diff.change_type, "#000000")
        header.set_markup(
            f"<b><span foreground='{color}'>{diff.element_type}</span></b>: "
            f"{diff.element_name or diff.element_id}"
        )
        header.set_halign(Gtk.Align.START)
        header.set_wrap(True)
        self._details_box.append(header)

        # Change type
        change_label = Gtk.Label()
        change_label.set_markup(
            f"<span foreground='{color}'>{diff.change_type.name}</span>"
        )
        change_label.set_halign(Gtk.Align.START)
        self._details_box.append(change_label)

        # Element ID
        id_label = Gtk.Label()
        id_label.set_markup(f"<small>ID: {element_id}</small>")
        id_label.set_halign(Gtk.Align.START)
        id_label.add_css_class("dim-label")
        self._details_box.append(id_label)

        # Separator
        sep = Gtk.Separator()
        sep.set_margin_top(8)
        sep.set_margin_bottom(8)
        self._details_box.append(sep)

        # Property changes
        if diff.property_changes:
            changes_label = Gtk.Label()
            changes_label.set_markup(
                f"<b>{gettext('Property Changes')} ({len(diff.property_changes)})</b>"
            )
            changes_label.set_halign(Gtk.Align.START)
            self._details_box.append(changes_label)

            for change in diff.property_changes:
                change_box = self._create_property_change_widget(change)
                self._details_box.append(change_box)
        else:
            no_changes = Gtk.Label()
            no_changes.set_markup(
                f"<i>{gettext('No property changes')}</i>"
            )
            no_changes.add_css_class("dim-label")
            no_changes.set_halign(Gtk.Align.START)
            self._details_box.append(no_changes)

        # Navigate button
        if diff.change_type != ChangeType.REMOVED:
            nav_btn = Gtk.Button(label=gettext("Show in Model"))
            nav_btn.set_margin_top(16)
            nav_btn.connect(
                "clicked", lambda _: self._on_navigate(element_id) if self._on_navigate else None
            )
            self._details_box.append(nav_btn)

    def _create_property_change_widget(self, change: PropertyChange) -> Gtk.Widget:
        """Create a widget displaying a property change."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_top(4)
        box.set_margin_bottom(4)

        # Property name
        name_label = Gtk.Label()
        color = COLOR_NAMES.get(change.change_type, "#000000")
        name_label.set_markup(f"<span foreground='{color}'><b>{change.property_name}</b></span>")
        name_label.set_halign(Gtk.Align.START)
        box.append(name_label)

        # Values
        if change.old_value is not None:
            old_label = Gtk.Label()
            old_text = self._format_value_for_display(change.old_value)
            old_label.set_markup(
                f"<span foreground='{COLOR_NAMES[ChangeType.REMOVED]}'>- {old_text}</span>"
            )
            old_label.set_halign(Gtk.Align.START)
            old_label.set_wrap(True)
            old_label.set_max_width_chars(40)
            box.append(old_label)

        if change.new_value is not None:
            new_label = Gtk.Label()
            new_text = self._format_value_for_display(change.new_value)
            new_label.set_markup(
                f"<span foreground='{COLOR_NAMES[ChangeType.ADDED]}'>+ {new_text}</span>"
            )
            new_label.set_halign(Gtk.Align.START)
            new_label.set_wrap(True)
            new_label.set_max_width_chars(40)
            box.append(new_label)

        return box

    def _format_value_for_display(self, value) -> str:
        """Format a value for display in the details panel."""
        if value is None:
            return "<none>"

        str_value = str(value)

        # Truncate long values
        if len(str_value) > 100:
            return str_value[:97] + "..."

        # Escape markup characters
        return GLib.markup_escape_text(str_value)

    def _on_window_close(self, window: Gtk.Window) -> bool:
        """Handle window close request."""
        self.close()
        return True

    def show(self):
        """Show the comparison window."""
        if self._window:
            self._window.present()

    def close(self):
        """Close the comparison window."""
        if self._window:
            self._window.destroy()
            self._window = None

        if self._on_close:
            try:
                self._on_close()
            except Exception:
                pass
