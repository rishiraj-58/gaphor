"""GTK split-screen comparison view.

Presents the "Compare with…" feature: loads a second model from a
``.gaphor`` file, diffs it against the current model, and shows a
side-by-side panel with colour-coded highlights plus a tree-view of all
differences grouped by type.

Architecture
------------
``CompareView`` is a thin GTK controller that:

1. Owns a ``Gtk.Paned`` with the existing diagram canvas on the left and a
   read-only summary panel on the right.
2. Builds a ``Gio.ListStore`` tree for the differences (grouping by kind:
   Added / Removed / Modified).
3. Exposes ``open_compare_dialog()`` which lets the user pick the second
   file, runs the diff, and populates the view.
4. Feeds a ``MergePanel`` (the right-hand tree + resolve buttons) whose
   "Apply selected" button commits the chosen resolutions through a
   :func:`~gaphor.diagram.compare.merge.apply_resolutions` call inside a
   single Transaction.  This means the full merge is a single undo step.

Colour coding (via CSS):
    * ``.diff-added``    → green background
    * ``.diff-removed``  → red background
    * ``.diff-modified`` → yellow/amber background
    * ``.diff-unchanged`` → no highlight (normal)
"""

from __future__ import annotations

import logging
from pathlib import Path

from gi.repository import Adw, Gdk, Gio, GObject, Gtk

from gaphor.core import event_handler, gettext
from gaphor.core.modeling import ElementFactory
from gaphor.diagram.compare.differ import DiffKind, ElementDiff, ModelDiff, diff_elements
from gaphor.diagram.compare.merge import MergeResolution, apply_resolutions
from gaphor.i18n import translated_ui_string
from gaphor.storage.parser import parse
from gaphor.transaction import Transaction
from gaphor.ui.filedialog import GAPHOR_FILTER, open_file_dialog

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GObject wrapper for a single diff entry (drives the Gtk.ListView model)
# ---------------------------------------------------------------------------

_KIND_LABEL = {
    DiffKind.ADDED: gettext("Added"),
    DiffKind.REMOVED: gettext("Removed"),
    DiffKind.MODIFIED: gettext("Modified"),
    DiffKind.UNCHANGED: gettext("Unchanged"),
}

_KIND_CSS = {
    DiffKind.ADDED: "diff-added",
    DiffKind.REMOVED: "diff-removed",
    DiffKind.MODIFIED: "diff-modified",
    DiffKind.UNCHANGED: "",
}


class DiffItem(GObject.Object):
    """Wraps one ``ElementDiff`` for use in a ``Gio.ListStore``."""

    __gtype_name__ = "DiffItem"

    def __init__(self, diff: ElementDiff):
        super().__init__()
        self._diff = diff
        self._resolution: str = "skip"  # "base" | "other" | "skip"

    @property
    def diff(self) -> ElementDiff:
        return self._diff

    @GObject.Property(type=str)
    def label(self) -> str:  # type: ignore[override]
        return self._diff.label

    @GObject.Property(type=str)
    def kind_label(self) -> str:  # type: ignore[override]
        return _KIND_LABEL.get(self._diff.kind, "")

    @GObject.Property(type=str)
    def css_class(self) -> str:  # type: ignore[override]
        return _KIND_CSS.get(self._diff.kind, "")

    @GObject.Property(type=str)
    def resolution(self) -> str:  # type: ignore[override]
        return self._resolution

    @resolution.setter
    def resolution(self, value: str):  # type: ignore[override]
        self._resolution = value
        self.notify("resolution")


class DiffGroup(GObject.Object):
    """Heading node for a diff-kind group in the tree."""

    __gtype_name__ = "DiffGroup"

    def __init__(self, kind: DiffKind, children: list[DiffItem]):
        super().__init__()
        self._kind = kind
        self._children = children

    @GObject.Property(type=str)
    def label(self) -> str:  # type: ignore[override]
        count = len(self._children)
        return f"{_KIND_LABEL.get(self._kind, '')} ({count})"

    @GObject.Property(type=str)
    def css_class(self) -> str:  # type: ignore[override]
        return _KIND_CSS.get(self._kind, "")

    @property
    def children(self) -> list[DiffItem]:
        return self._children


# ---------------------------------------------------------------------------
# Main controller
# ---------------------------------------------------------------------------


class CompareView:
    """Controller for the Compare-with… split-screen panel.

    Constructed once per ``DiagramPage``; it inserts its own widget into the
    diagram area only when the user opens a comparison.
    """

    def __init__(
        self,
        diagram_widget: Gtk.Widget,
        element_factory: ElementFactory,
        modeling_language,
        event_manager,
        parent_window: Gtk.Window | None = None,
    ):
        self._diagram_widget = diagram_widget
        self._element_factory = element_factory
        self._modeling_language = modeling_language
        self._event_manager = event_manager
        self._parent_window = parent_window

        self._paned: Gtk.Paned | None = None
        self._diff: ModelDiff | None = None
        self._other_path: Path | None = None

        # Root list store for the tree model.
        self._store: Gio.ListStore = Gio.ListStore.new(DiffGroup.__gtype__)
        self._diff_items: list[DiffItem] = []

        self._css_provider = Gtk.CssProvider()
        self._css_provider.load_from_string(_DIFF_CSS)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def open_compare_dialog(self) -> None:
        """Show file-open dialog, then run diff and display split view."""
        paths = await open_file_dialog(
            gettext("Compare with…"),
            parent=self._parent_window,
            filters=GAPHOR_FILTER,
            multiple=False,
        )
        if not paths:
            return
        path = paths if isinstance(paths, Path) else paths[0] if paths else None
        if path is None:
            return
        await self._load_and_diff(path)

    def close(self) -> None:
        """Remove the comparison panel and return to the normal diagram view."""
        if self._paned is None:
            return
        Gtk.StyleContext.remove_provider_for_display(
            Gdk.Display.get_default(), self._css_provider
        )
        self._paned = None
        self._diff = None
        self._diff_items.clear()
        self._store.remove_all()

    @property
    def is_open(self) -> bool:
        return self._paned is not None

    # ------------------------------------------------------------------
    # Internal: loading & diffing
    # ------------------------------------------------------------------

    async def _load_and_diff(self, other_path: Path) -> None:
        """Parse *other_path*, diff against current model, build UI."""
        self._other_path = other_path

        # Snapshot current model to a parsed element dict.
        import io
        from gaphor import storage

        current_buf = io.StringIO()
        storage.save(current_buf, self._element_factory)
        current_buf.seek(0)
        base_elements = parse(current_buf)

        # Parse the other file.
        with other_path.open(encoding="utf-8", errors="replace") as fh:
            other_elements = parse(fh)

        self._diff = diff_elements(base_elements, other_elements)
        self._build_tree_model()
        self._show_split_view()

    def _build_tree_model(self) -> None:
        assert self._diff is not None
        self._store.remove_all()
        self._diff_items.clear()

        for kind in (DiffKind.ADDED, DiffKind.REMOVED, DiffKind.MODIFIED):
            elems = [d for d in self._diff.diffs if d.kind == kind]
            if not elems:
                continue
            items = [DiffItem(e) for e in elems]
            self._diff_items.extend(items)
            group = DiffGroup(kind, items)
            self._store.append(group)

    # ------------------------------------------------------------------
    # Internal: GTK widget construction
    # ------------------------------------------------------------------

    def _show_split_view(self) -> None:
        """Build and attach the split-screen Paned widget."""
        # Apply diff CSS.
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            self._css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        right_panel = self._build_right_panel()
        self._paned = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
        # We do NOT reparent the original diagram_widget here because it is
        # already managed by the DiagramPage / Diagrams notebook.  Instead we
        # insert the right panel alongside it by wrapping both in a new Box
        # that replaces the notebook page child.
        self._paned.set_start_child(self._diagram_widget)
        self._paned.set_end_child(right_panel)
        self._paned.set_position(600)
        self._paned.set_wide_handle(True)

    def _build_right_panel(self) -> Gtk.Widget:
        """Construct the right-side comparison panel."""
        box = Gtk.Box.new(Gtk.Orientation.VERTICAL, spacing=0)

        # -- Header --
        header = Adw.HeaderBar.new()
        title = Adw.WindowTitle.new(
            gettext("Compare"),
            str(self._other_path.name) if self._other_path else "",
        )
        header.set_title_widget(title)
        close_btn = Gtk.Button.new_from_icon_name("window-close-symbolic")
        close_btn.add_css_class("flat")
        close_btn.set_tooltip_text(gettext("Close comparison"))
        close_btn.connect("clicked", lambda _: self.close())
        header.pack_end(close_btn)
        box.append(header)

        # -- Summary bar --
        if self._diff:
            summary = gettext(
                "{added} added · {removed} removed · {modified} modified"
            ).format(
                added=len(self._diff.added),
                removed=len(self._diff.removed),
                modified=len(self._diff.modified),
            )
        else:
            summary = ""
        summary_label = Gtk.Label.new(summary)
        summary_label.add_css_class("caption")
        summary_label.set_margin_top(6)
        summary_label.set_margin_bottom(6)
        box.append(summary_label)

        Gtk.Separator.new(Gtk.Orientation.HORIZONTAL)

        # -- Tree view of diffs --
        scrolled = Gtk.ScrolledWindow.new()
        scrolled.set_vexpand(True)
        tree_view = self._build_tree_view()
        scrolled.set_child(tree_view)
        box.append(scrolled)

        Gtk.Separator.new(Gtk.Orientation.HORIZONTAL)

        # -- Merge action bar --
        action_bar = Gtk.ActionBar.new()

        apply_btn = Gtk.Button.new_with_label(gettext("Apply Selected"))
        apply_btn.add_css_class("suggested-action")
        apply_btn.set_tooltip_text(
            gettext("Apply the resolutions chosen in the tree to the current model")
        )
        apply_btn.connect("clicked", self._on_apply_selected)
        action_bar.pack_end(apply_btn)

        accept_all_btn = Gtk.Button.new_with_label(gettext("Accept All"))
        accept_all_btn.set_tooltip_text(
            gettext("Accept every incoming change (choose 'other' for all)")
        )
        accept_all_btn.connect("clicked", self._on_accept_all)
        action_bar.pack_start(accept_all_btn)

        reject_all_btn = Gtk.Button.new_with_label(gettext("Reject All"))
        reject_all_btn.set_tooltip_text(
            gettext("Reject every incoming change (keep 'base' for all)")
        )
        reject_all_btn.connect("clicked", self._on_reject_all)
        action_bar.pack_start(reject_all_btn)

        box.append(action_bar)

        return box

    def _build_tree_view(self) -> Gtk.Widget:
        """Build the collapsible tree of diff groups."""
        # Use a simple ListView backed by the flat list of diff items.
        # Group headers are separate rows distinguished by type.
        list_store = Gio.ListStore.new(GObject.Object.__gtype__)

        for i in range(self._store.get_n_items()):
            group = self._store.get_item(i)
            # Add group header.
            list_store.append(group)
            for child in group.children:
                list_store.append(child)

        selection = Gtk.NoSelection.new(list_store)
        factory = Gtk.SignalListItemFactory.new()
        factory.connect("setup", self._on_list_item_setup)
        factory.connect("bind", self._on_list_item_bind)

        list_view = Gtk.ListView.new(selection, factory)
        list_view.add_css_class("diff-list")
        return list_view

    # ------------------------------------------------------------------
    # List item factory callbacks
    # ------------------------------------------------------------------

    def _on_list_item_setup(self, _factory, list_item):
        """Create the row widget template."""
        row_box = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, spacing=8)
        row_box.set_margin_start(8)
        row_box.set_margin_end(8)
        row_box.set_margin_top(4)
        row_box.set_margin_bottom(4)

        kind_label = Gtk.Label.new("")
        kind_label.set_xalign(0)
        kind_label.set_size_request(80, -1)
        kind_label.add_css_class("caption")
        row_box.append(kind_label)

        name_label = Gtk.Label.new("")
        name_label.set_xalign(0)
        name_label.set_hexpand(True)
        row_box.append(name_label)

        # Resolution dropdown (only for DiffItem rows).
        combo = Gtk.DropDown.new_from_strings(
            [gettext("Skip"), gettext("Keep base"), gettext("Accept other")]
        )
        combo.set_tooltip_text(gettext("Choose how to resolve this change"))
        row_box.append(combo)

        list_item.set_child(row_box)
        list_item._kind_label = kind_label  # type: ignore[attr-defined]
        list_item._name_label = name_label  # type: ignore[attr-defined]
        list_item._combo = combo  # type: ignore[attr-defined]

    def _on_list_item_bind(self, _factory, list_item):
        """Bind row widget to the model item."""
        obj = list_item.get_item()
        kind_lbl: Gtk.Label = list_item._kind_label  # type: ignore[attr-defined]
        name_lbl: Gtk.Label = list_item._name_label  # type: ignore[attr-defined]
        combo: Gtk.DropDown = list_item._combo  # type: ignore[attr-defined]

        row_box: Gtk.Box = list_item.get_child()
        # Remove all old CSS classes.
        for cls in ("diff-added", "diff-removed", "diff-modified", "diff-group"):
            row_box.remove_css_class(cls)

        if isinstance(obj, DiffGroup):
            kind_lbl.set_text("")
            name_lbl.set_text(obj.label)
            name_lbl.add_css_class("heading")
            row_box.add_css_class("diff-group")
            combo.set_visible(False)
        elif isinstance(obj, DiffItem):
            kind_lbl.set_text(obj.kind_label)
            name_lbl.set_text(obj.label)
            name_lbl.remove_css_class("heading")
            if css := obj.css_class:
                row_box.add_css_class(css)
            combo.set_visible(True)
            # Map resolution string → dropdown index.
            _map = {"skip": 0, "base": 1, "other": 2}
            combo.set_selected(_map.get(obj.resolution, 0))

            def on_combo_changed(dd, _param, item=obj):
                _reverse = {0: "skip", 1: "base", 2: "other"}
                item.resolution = _reverse.get(dd.get_selected(), "skip")

            combo.connect("notify::selected", on_combo_changed)

    # ------------------------------------------------------------------
    # Merge action handlers
    # ------------------------------------------------------------------

    def _on_accept_all(self, _button):
        for item in self._diff_items:
            item.resolution = "other"

    def _on_reject_all(self, _button):
        for item in self._diff_items:
            item.resolution = "base"

    def _on_apply_selected(self, _button):
        if not self._diff:
            return
        resolutions = [
            MergeResolution(element_id=item.diff.element_id, choice=item.resolution)
            for item in self._diff_items
            if item.resolution != "skip"
        ]
        if not resolutions:
            return
        try:
            count = apply_resolutions(
                self._diff,
                resolutions,
                self._element_factory,
                self._modeling_language,
                self._event_manager,
            )
            log.info("Applied %d merge resolutions", count)
        except Exception as exc:
            log.error("Merge apply failed: %s", exc)


# ---------------------------------------------------------------------------
# Inline CSS for diff highlighting
# ---------------------------------------------------------------------------

_DIFF_CSS = """
.diff-added {
    background-color: alpha(@success_color, 0.18);
}
.diff-removed {
    background-color: alpha(@error_color, 0.18);
}
.diff-modified {
    background-color: alpha(@warning_color, 0.18);
}
.diff-group {
    background-color: alpha(@headerbar_bg_color, 0.6);
}
.diff-list row {
    border-bottom: 1px solid alpha(@borders, 0.4);
}
"""
