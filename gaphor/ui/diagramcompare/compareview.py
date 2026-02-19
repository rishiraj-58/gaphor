"""Split-screen comparison view for diagrams.

Displays two versions of a diagram side by side with highlighted differences.
"""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING

from gaphas.painter import PainterChain
from gaphas.view import GtkView
from gi.repository import Adw, Gdk, Gtk, Pango

from gaphor.core.modeling import Diagram, StyleSheet
from gaphor.core.modeling.diagram import StyledDiagram
from gaphor.core.styling import PrefersColorScheme
from gaphor.diagram.painter import DiagramTypePainter, ItemPainter
from gaphor.i18n import gettext
from gaphor.ui.diagramcompare.comparator import (
    ChangeType,
    DiagramDiff,
    PresentationDiff,
    compare_diagrams,
)

if TYPE_CHECKING:
    from gaphor.core.modeling import ElementFactory


# Colors for highlighting differences
COLORS = {
    ChangeType.ADDED: (0.0, 0.8, 0.0, 0.3),  # Green
    ChangeType.REMOVED: (0.8, 0.0, 0.0, 0.3),  # Red
    ChangeType.MODIFIED: (0.0, 0.0, 0.8, 0.3),  # Blue
}


class CompareItemPainter(ItemPainter):
    """Custom painter that highlights items based on their change status."""

    def __init__(self, selection, style_func, diff: DiagramDiff, is_base: bool):
        super().__init__(selection, style_func)
        self._diff = diff
        self._is_base = is_base
        self._highlight_ids: dict[str, ChangeType] = {}
        self._build_highlight_map()

    def _build_highlight_map(self):
        """Build a map of presentation IDs to their change types."""
        for pres_diff in self._diff.presentation_diffs:
            self._highlight_ids[pres_diff.presentation_id] = pres_diff.change_type

    def paint_item(self, item, cairo):
        """Paint an item with optional highlight overlay."""
        super().paint_item(item, cairo)

        change_type = self._highlight_ids.get(item.id)
        if change_type:
            self._draw_highlight(item, cairo, change_type)

    def _draw_highlight(self, item, cairo, change_type: ChangeType):
        """Draw a highlight overlay on the item."""
        color = COLORS.get(change_type)
        if not color:
            return

        # Get item bounds
        bounds = item.bounds()
        if bounds:
            x, y, x2, y2 = bounds
            width = x2 - x
            height = y2 - y

            # Draw semi-transparent overlay
            cairo.save()
            cairo.set_source_rgba(*color)
            cairo.rectangle(x - 2, y - 2, width + 4, height + 4)
            cairo.fill()
            cairo.restore()


class DiagramCompareView(Gtk.Box):
    """A split-screen view for comparing two diagram versions."""

    def __init__(
        self,
        base_diagram: Diagram | None,
        compare_diagram: Diagram | None,
        element_factory: ElementFactory,
    ):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)

        self._base_diagram = base_diagram
        self._compare_diagram = compare_diagram
        self._element_factory = element_factory
        self._diff = compare_diagrams(base_diagram, compare_diagram)

        self._style_manager = Adw.StyleManager.get_default()
        self._base_view: GtkView | None = None
        self._compare_view: GtkView | None = None

        self._build_ui()

    @property
    def diff(self) -> DiagramDiff:
        """Get the computed diagram diff."""
        return self._diff

    def _build_ui(self):
        """Build the comparison UI."""
        # Header bar with diff summary
        header = self._create_header()
        self.append(header)

        # Main content area with split views
        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, homogeneous=True)
        content.set_vexpand(True)

        # Base diagram view (left side)
        base_frame = self._create_diagram_frame(
            gettext("Base Version"),
            self._base_diagram,
            is_base=True,
        )
        content.append(base_frame)

        # Separator
        separator = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        content.append(separator)

        # Compare diagram view (right side)
        compare_frame = self._create_diagram_frame(
            gettext("Compare Version"),
            self._compare_diagram,
            is_base=False,
        )
        content.append(compare_frame)

        self.append(content)

        # Diff details panel at bottom
        details = self._create_details_panel()
        self.append(details)

    def _create_header(self) -> Gtk.Box:
        """Create the header with diff summary."""
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        header.add_css_class("toolbar")
        header.set_margin_start(6)
        header.set_margin_end(6)
        header.set_margin_top(6)
        header.set_margin_bottom(6)

        # Summary label
        added = len(self._diff.added_presentations)
        removed = len(self._diff.removed_presentations)
        modified = len(self._diff.modified_presentations)

        summary_parts = []
        if added:
            summary_parts.append(
                gettext("{count} added").format(count=added)
            )
        if removed:
            summary_parts.append(
                gettext("{count} removed").format(count=removed)
            )
        if modified:
            summary_parts.append(
                gettext("{count} modified").format(count=modified)
            )

        summary_text = ", ".join(summary_parts) if summary_parts else gettext("No changes detected")
        summary = Gtk.Label(label=summary_text)
        summary.set_hexpand(True)
        summary.set_halign(Gtk.Align.START)
        header.append(summary)

        # Legend
        legend = self._create_legend()
        header.append(legend)

        return header

    def _create_legend(self) -> Gtk.Box:
        """Create the color legend."""
        legend = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

        for change_type, color in COLORS.items():
            item = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

            # Color swatch
            swatch = Gtk.DrawingArea()
            swatch.set_size_request(16, 16)
            swatch.set_draw_func(self._draw_swatch, color)
            item.append(swatch)

            # Label
            label_text = {
                ChangeType.ADDED: gettext("Added"),
                ChangeType.REMOVED: gettext("Removed"),
                ChangeType.MODIFIED: gettext("Modified"),
            }.get(change_type, "")
            label = Gtk.Label(label=label_text)
            label.add_css_class("dim-label")
            item.append(label)

            legend.append(item)

        return legend

    def _draw_swatch(self, area, cairo, width, height, color):
        """Draw a color swatch."""
        cairo.set_source_rgba(*color)
        cairo.rectangle(0, 0, width, height)
        cairo.fill()
        cairo.set_source_rgba(0.5, 0.5, 0.5, 1.0)
        cairo.rectangle(0, 0, width, height)
        cairo.stroke()

    def _create_diagram_frame(
        self, title: str, diagram: Diagram | None, is_base: bool
    ) -> Gtk.Frame:
        """Create a framed diagram view."""
        frame = Gtk.Frame()
        frame.set_label(title)
        frame.set_hexpand(True)
        frame.set_vexpand(True)

        if diagram is None:
            # Show placeholder for missing diagram
            placeholder = Gtk.Label(label=gettext("No diagram"))
            placeholder.add_css_class("dim-label")
            frame.set_child(placeholder)
            return frame

        # Create the diagram view
        view = GtkView()
        view.model = diagram
        view.set_hexpand(True)
        view.set_vexpand(True)

        if is_base:
            self._base_view = view
        else:
            self._compare_view = view

        # Set up the painter with highlighting
        self._setup_view_painter(view, diagram, is_base)

        # Wrap in scrolled window
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_child(view)
        frame.set_child(scrolled)

        return frame

    def _setup_view_painter(self, view: GtkView, diagram: Diagram, is_base: bool):
        """Set up the view painter with diff highlighting."""
        prefers_color_scheme = (
            PrefersColorScheme.DARK
            if self._style_manager.get_dark()
            else PrefersColorScheme.LIGHT
        )

        style_sheet = self._element_factory.style_sheet or StyleSheet()

        item_painter = CompareItemPainter(
            view.selection,
            functools.partial(
                style_sheet.compute_style, prefers_color_scheme=prefers_color_scheme
            ),
            self._diff,
            is_base,
        )

        view.bounding_box_painter = item_painter
        view.painter = (
            PainterChain()
            .append(item_painter)
            .append(
                DiagramTypePainter(
                    diagram,
                    functools.partial(
                        style_sheet.compute_style,
                        prefers_color_scheme=prefers_color_scheme,
                    ),
                )
            )
        )

    def _create_details_panel(self) -> Gtk.Widget:
        """Create the diff details panel."""
        expander = Gtk.Expander(label=gettext("Diff Details"))
        expander.set_margin_start(6)
        expander.set_margin_end(6)
        expander.set_margin_top(6)
        expander.set_margin_bottom(6)

        # Create a scrolled list of changes
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(150)
        scrolled.set_max_content_height(200)

        listbox = Gtk.ListBox()
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        listbox.add_css_class("boxed-list")

        # Add diagram property changes
        for prop_diff in self._diff.diagram_property_diffs:
            row = self._create_property_row(
                gettext("Diagram"),
                prop_diff.property_name,
                prop_diff.display_old,
                prop_diff.display_new,
            )
            listbox.append(row)

        # Add presentation changes
        for pres_diff in self._diff.presentation_diffs:
            if pres_diff.change_type == ChangeType.ADDED:
                row = self._create_change_row(
                    pres_diff.presentation_type,
                    gettext("Added"),
                    ChangeType.ADDED,
                )
            elif pres_diff.change_type == ChangeType.REMOVED:
                row = self._create_change_row(
                    pres_diff.presentation_type,
                    gettext("Removed"),
                    ChangeType.REMOVED,
                )
            else:
                # Modified - show property details
                for prop_diff in pres_diff.property_diffs:
                    row = self._create_property_row(
                        pres_diff.presentation_type,
                        prop_diff.property_name,
                        prop_diff.display_old,
                        prop_diff.display_new,
                    )
                    listbox.append(row)
                continue

            listbox.append(row)

            # Show subject changes if any
            if pres_diff.subject_diff:
                subj = pres_diff.subject_diff
                for prop_diff in subj.property_diffs:
                    row = self._create_property_row(
                        subj.display_name,
                        prop_diff.property_name,
                        prop_diff.display_old,
                        prop_diff.display_new,
                    )
                    listbox.append(row)

        if listbox.get_first_child() is None:
            # No changes to show
            label = Gtk.Label(label=gettext("No detailed changes"))
            label.add_css_class("dim-label")
            label.set_margin_top(12)
            label.set_margin_bottom(12)
            scrolled.set_child(label)
        else:
            scrolled.set_child(listbox)

        expander.set_child(scrolled)
        return expander

    def _create_change_row(
        self, element_type: str, change_text: str, change_type: ChangeType
    ) -> Gtk.ListBoxRow:
        """Create a row showing a simple change."""
        row = Gtk.ListBoxRow()
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(6)
        box.set_margin_bottom(6)

        # Element type
        type_label = Gtk.Label(label=element_type)
        type_label.set_hexpand(True)
        type_label.set_halign(Gtk.Align.START)
        type_label.set_ellipsize(Pango.EllipsizeMode.END)
        box.append(type_label)

        # Change badge
        badge = Gtk.Label(label=change_text)
        badge.add_css_class("caption")
        if change_type == ChangeType.ADDED:
            badge.add_css_class("success")
        elif change_type == ChangeType.REMOVED:
            badge.add_css_class("error")
        else:
            badge.add_css_class("warning")
        box.append(badge)

        row.set_child(box)
        return row

    def _create_property_row(
        self, element_name: str, prop_name: str, old_value: str, new_value: str
    ) -> Gtk.ListBoxRow:
        """Create a row showing a property change."""
        row = Gtk.ListBoxRow()
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(6)
        box.set_margin_bottom(6)

        # Element and property name
        name_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        name_box.set_hexpand(True)

        elem_label = Gtk.Label(label=element_name)
        elem_label.set_halign(Gtk.Align.START)
        elem_label.set_ellipsize(Pango.EllipsizeMode.END)
        name_box.append(elem_label)

        prop_label = Gtk.Label(label=prop_name)
        prop_label.add_css_class("dim-label")
        prop_label.add_css_class("caption")
        prop_label.set_halign(Gtk.Align.START)
        name_box.append(prop_label)

        box.append(name_box)

        # Old value
        old_label = Gtk.Label(label=old_value)
        old_label.add_css_class("dim-label")
        old_label.set_ellipsize(Pango.EllipsizeMode.END)
        old_label.set_max_width_chars(20)
        box.append(old_label)

        # Arrow
        arrow = Gtk.Label(label="→")
        box.append(arrow)

        # New value
        new_label = Gtk.Label(label=new_value)
        new_label.set_ellipsize(Pango.EllipsizeMode.END)
        new_label.set_max_width_chars(20)
        box.append(new_label)

        row.set_child(box)
        return row

    def sync_views(self):
        """Synchronize the two diagram views (zoom and pan)."""
        if not (self._base_view and self._compare_view):
            return

        # Sync zoom level
        base_matrix = self._base_view.matrix
        self._compare_view.matrix = base_matrix

        # This is a simple sync - for more advanced sync,
        # we could add event handlers to keep them in sync during interaction
