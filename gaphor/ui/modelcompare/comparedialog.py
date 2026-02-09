"""Model comparison dialog and UI components."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from gi.repository import Adw, Gio, GLib, GObject, Gtk

import gaphor.storage as storage
from gaphor.abc import ActionProvider, Service
from gaphor.core import action, event_handler, gettext
from gaphor.core.modeling import Diagram, ElementFactory, ModelReady
from gaphor.i18n import translated_ui_string
from gaphor.transaction import Transaction
from gaphor.ui.filedialog import GAPHOR_FILTER, open_file_dialog
from gaphor.ui.modelcompare.differ import (
    Change,
    ChangeCategory,
    ChangeType,
    DiffResult,
    compare_models,
)
from gaphor.ui.modelcompare.diagramcompare import DiagramCompareWindow
from gaphor.ui.modelcompare.merge import apply_change, can_apply_change, merge_changes
from gaphor.ui.modelcompare.organize import CompareNode, organize_diff_result

if TYPE_CHECKING:
    from gaphor.core.modeling.modelinglanguage import ModelingLanguage

log = logging.getLogger(__name__)


class ModelCompare(Service, ActionProvider):
    """Service for comparing and merging model versions."""

    def __init__(
        self,
        event_manager,
        element_factory,
        modeling_language,
        main_window,
    ):
        self.event_manager = event_manager
        self.element_factory = element_factory
        self.modeling_language = modeling_language
        self.main_window = main_window

        self._compare_factory: ElementFactory | None = None
        self._diff_result: DiffResult | None = None
        self._compare_window: Gtk.Window | None = None

    def shutdown(self):
        if self._compare_window:
            self._compare_window.close()
            self._compare_window = None

    @property
    def parent_window(self):
        return self.main_window.window if self.main_window else None

    @action(name="model-compare", shortcut="<Primary><Shift>c")
    async def compare_with_file(self):
        """Open a file dialog to select a model file to compare with."""
        filename = await open_file_dialog(
            gettext("Compare With Model"),
            parent=self.parent_window,
            filters=GAPHOR_FILTER,
            multiple=False,
        )
        if filename:
            await self._load_and_compare(filename)

    async def _load_and_compare(self, filename: Path):
        """Load a model file and compare with the current model."""
        self._compare_factory = ElementFactory()

        try:
            with filename.open(encoding="utf-8", errors="replace") as file_obj:
                for _ in storage.load_generator(
                    file_obj,
                    self._compare_factory,
                    self.modeling_language,
                ):
                    pass
        except Exception as e:
            log.error(f"Failed to load comparison model: {e}")
            await self._show_error_dialog(
                gettext("Failed to load model"),
                str(e),
            )
            return

        self._diff_result = compare_models(
            self.element_factory,
            self._compare_factory,
        )

        if not self._diff_result.changes:
            await self._show_info_dialog(
                gettext("No Differences"),
                gettext("The models are identical."),
            )
            return

        self._show_compare_window(filename.name)

    async def _show_error_dialog(self, title: str, message: str):
        dialog = Adw.AlertDialog.new(title, message)
        dialog.add_response("ok", gettext("OK"))
        await dialog.choose(self.parent_window)

    async def _show_info_dialog(self, title: str, message: str):
        dialog = Adw.AlertDialog.new(title, message)
        dialog.add_response("ok", gettext("OK"))
        await dialog.choose(self.parent_window)

    def _show_compare_window(self, compare_filename: str):
        """Show the comparison window."""
        if self._compare_window:
            self._compare_window.close()

        self._compare_window = CompareWindow(
            diff_result=self._diff_result,
            base_factory=self.element_factory,
            compare_factory=self._compare_factory,
            compare_filename=compare_filename,
            modeling_language=self.modeling_language,
            event_manager=self.event_manager,
            on_close=self._on_compare_window_closed,
        )
        self._compare_window.set_transient_for(self.parent_window)
        self._compare_window.present()

    def _on_compare_window_closed(self):
        """Clean up when compare window is closed."""
        self._compare_window = None
        self._compare_factory = None
        self._diff_result = None


class CompareWindow(Adw.Window):
    """Window for displaying model comparison results."""

    def __init__(
        self,
        diff_result: DiffResult,
        base_factory: ElementFactory,
        compare_factory: ElementFactory,
        compare_filename: str,
        modeling_language: ModelingLanguage,
        event_manager,
        on_close=None,
    ):
        super().__init__()
        self.diff_result = diff_result
        self.base_factory = base_factory
        self.compare_factory = compare_factory
        self.modeling_language = modeling_language
        self.event_manager = event_manager
        self._on_close = on_close

        self.set_title(
            gettext("Compare: Current ↔ {filename}").format(filename=compare_filename)
        )
        self.set_default_size(900, 700)

        self._build_ui()
        self.connect("close-request", self._on_close_request)

    def _build_ui(self):
        """Build the comparison window UI."""
        toolbar_view = Adw.ToolbarView()

        # Header bar
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)

        # Merge button
        merge_button = Gtk.Button(label=gettext("Merge Selected"))
        merge_button.add_css_class("suggested-action")
        merge_button.connect("clicked", self._on_merge_clicked)
        header.pack_end(merge_button)

        # Select all button
        select_all_button = Gtk.Button(label=gettext("Select All"))
        select_all_button.connect("clicked", self._on_select_all_clicked)
        header.pack_start(select_all_button)

        toolbar_view.add_top_bar(header)

        # Main content - split view
        split_view = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        split_view.set_position(400)

        # Left side - tree view of changes
        left_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        left_box.set_margin_start(6)
        left_box.set_margin_end(6)
        left_box.set_margin_top(6)
        left_box.set_margin_bottom(6)

        # Summary label
        summary_label = Gtk.Label()
        summary_label.set_markup(self._get_summary_markup())
        summary_label.set_halign(Gtk.Align.START)
        summary_label.set_margin_bottom(6)
        left_box.append(summary_label)

        # Tree view
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)

        self._tree_model = organize_diff_result(
            self.diff_result,
            self.base_factory,
            self.compare_factory,
        )

        tree_model = Gtk.TreeListModel.new(
            self._tree_model,
            passthrough=False,
            autoexpand=False,
            create_func=lambda node, _: node.children,
            user_data=None,
        )

        self._selection = Gtk.MultiSelection.new(tree_model)

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_list_item_setup)
        factory.connect("bind", self._on_list_item_bind)

        self._tree_view = Gtk.ListView()
        self._tree_view.set_model(self._selection)
        self._tree_view.set_factory(factory)
        self._tree_view.add_css_class("navigation-sidebar")

        scrolled.set_child(self._tree_view)
        left_box.append(scrolled)

        split_view.set_start_child(left_box)

        # Right side - details view
        right_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        right_box.set_margin_start(6)
        right_box.set_margin_end(6)
        right_box.set_margin_top(6)
        right_box.set_margin_bottom(6)

        details_label = Gtk.Label(label=gettext("Change Details"))
        details_label.add_css_class("heading")
        details_label.set_halign(Gtk.Align.START)
        right_box.append(details_label)

        self._details_view = Gtk.TextView()
        self._details_view.set_editable(False)
        self._details_view.set_wrap_mode(Gtk.WrapMode.WORD)
        self._details_view.set_vexpand(True)

        details_scrolled = Gtk.ScrolledWindow()
        details_scrolled.set_child(self._details_view)
        right_box.append(details_scrolled)

        split_view.set_end_child(right_box)

        toolbar_view.set_content(split_view)
        self.set_content(toolbar_view)

        # Add CSS
        self._add_css()

    def _add_css(self):
        """Add CSS for change type styling."""
        css_provider = Gtk.CssProvider()
        css_provider.load_from_string(
            """
            .change-added {
                color: @success_color;
            }
            .change-removed {
                color: @error_color;
            }
            .change-modified {
                color: @warning_color;
            }
            .change-indicator {
                font-weight: bold;
                margin-end: 6px;
            }
            """
        )
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def _get_summary_markup(self) -> str:
        """Get summary statistics as markup."""
        added = len(self.diff_result.added)
        removed = len(self.diff_result.removed)
        modified = len(self.diff_result.modified)
        total = len(self.diff_result.changes)

        return gettext(
            "<b>Summary:</b> {total} changes "
            "(<span color='green'>+{added}</span>, "
            "<span color='red'>−{removed}</span>, "
            "<span color='orange'>~{modified}</span>)"
        ).format(total=total, added=added, removed=removed, modified=modified)

    def _on_list_item_setup(self, factory, list_item):
        """Set up a list item widget."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        expander = Gtk.TreeExpander()
        expander.set_indent_for_icon(True)
        box.append(expander)

        checkbox = Gtk.CheckButton()
        expander.set_child(checkbox)

        indicator = Gtk.Label()
        indicator.add_css_class("change-indicator")
        box.append(indicator)

        label = Gtk.Label()
        label.set_xalign(0)
        label.set_hexpand(True)
        box.append(label)

        count_label = Gtk.Label()
        count_label.add_css_class("dim-label")
        box.append(count_label)

        list_item.set_child(box)

    def _on_list_item_bind(self, factory, list_item):
        """Bind data to a list item widget."""
        box = list_item.get_child()
        expander = box.get_first_child()
        checkbox = expander.get_child()
        indicator = checkbox.get_next_sibling()
        label = indicator.get_next_sibling()
        count_label = label.get_next_sibling()

        tree_row = list_item.get_item()
        node = tree_row.get_item()

        expander.set_list_row(tree_row)

        # Set checkbox state
        checkbox.set_active(node.selected)
        checkbox.connect(
            "toggled",
            lambda btn: setattr(node, "selected", btn.get_active()),
        )

        # Set indicator based on change type
        if node.changes:
            change_type = node.changes[0].change_type
            if change_type == ChangeType.ADDED:
                indicator.set_text("+")
                indicator.add_css_class("change-added")
            elif change_type == ChangeType.REMOVED:
                indicator.set_text("−")
                indicator.add_css_class("change-removed")
            else:
                indicator.set_text("~")
                indicator.add_css_class("change-modified")
        else:
            indicator.set_text("")

        label.set_text(node.label)

        # Show count for group nodes
        if node.children:
            count_label.set_text(f"({node.change_count})")
        else:
            count_label.set_text("")

        # Connect click to show details
        gesture = Gtk.GestureClick.new()
        gesture.connect("released", lambda g, n, x, y: self._show_change_details(node))
        box.add_controller(gesture)

    def _show_change_details(self, node: CompareNode):
        """Show details for the selected change in the details view."""
        buffer = self._details_view.get_buffer()
        changes = node.all_changes()

        if not changes:
            buffer.set_text(gettext("Select a change to see details."))
            return

        lines = []
        for change in changes:
            lines.append(f"• {change.description}")
            if change.property_name:
                lines.append(f"  Property: {change.property_name}")
            if change.old_value is not None:
                lines.append(f"  Old value: {change.old_value}")
            if change.new_value is not None:
                lines.append(f"  New value: {change.new_value}")
            lines.append(f"  Element ID: {change.element_id}")
            if change.diagram_id:
                lines.append(f"  Diagram ID: {change.diagram_id}")
            lines.append("")

        buffer.set_text("\n".join(lines))

    def _on_select_all_clicked(self, button):
        """Select all changes."""
        for i in range(self._tree_model.get_n_items()):
            node = self._tree_model.get_item(i)
            node.selected = True

    def _on_merge_clicked(self, button):
        """Merge selected changes."""
        selected_changes: list[Change] = []

        def collect_selected(store):
            for i in range(store.get_n_items()):
                node = store.get_item(i)
                if node.selected:
                    selected_changes.extend(node.changes)
                if node.children:
                    collect_selected(node.children)

        collect_selected(self._tree_model)

        if not selected_changes:
            return

        with Transaction(self.event_manager):
            result = merge_changes(
                selected_changes,
                self.base_factory,
                self.compare_factory,
                self.modeling_language,
            )

        # Show result
        if result.conflicts:
            conflict_msgs = [f"• {c.reason}: {c.change.description}" for c in result.conflicts]
            self._show_merge_result(
                gettext("Merge completed with conflicts"),
                gettext(
                    "Applied {applied} changes.\n"
                    "Skipped {skipped} changes.\n"
                    "Conflicts:\n{conflicts}"
                ).format(
                    applied=len(result.applied),
                    skipped=len(result.skipped),
                    conflicts="\n".join(conflict_msgs),
                ),
            )
        else:
            self._show_merge_result(
                gettext("Merge completed"),
                gettext("Applied {applied} changes.").format(
                    applied=len(result.applied)
                ),
            )

        # Refresh diff
        self.diff_result = compare_models(self.base_factory, self.compare_factory)
        self._tree_model = organize_diff_result(
            self.diff_result,
            self.base_factory,
            self.compare_factory,
        )
        tree_model = Gtk.TreeListModel.new(
            self._tree_model,
            passthrough=False,
            autoexpand=False,
            create_func=lambda node, _: node.children,
            user_data=None,
        )
        self._selection = Gtk.MultiSelection.new(tree_model)
        self._tree_view.set_model(self._selection)

    def _show_merge_result(self, title: str, message: str):
        """Show merge result in a dialog."""
        dialog = Adw.AlertDialog.new(title, message)
        dialog.add_response("ok", gettext("OK"))
        dialog.choose(self)

    def _on_close_request(self, window):
        """Handle window close."""
        if self._on_close:
            self._on_close()
        return False

    def compare_diagram(self, diagram_id: str):
        """Open a visual comparison for a specific diagram."""
        base_diagram = self.base_factory.lookup(diagram_id)
        compare_diagram = (
            self.compare_factory.lookup(diagram_id)
            if self.compare_factory
            else None
        )

        if not isinstance(base_diagram, Diagram):
            return

        diagram_changes = self.diff_result.changes_for_diagram(diagram_id)

        window = DiagramCompareWindow(
            base_diagram=base_diagram,
            compare_diagram=compare_diagram if isinstance(compare_diagram, Diagram) else None,
            changes=diagram_changes,
            base_factory=self.base_factory,
            compare_factory=self.compare_factory,
            compare_filename="",
        )
        window.set_transient_for(self)
        window.present()
