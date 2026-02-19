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
    PropertyDiff,
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

# Brighter colors for selected/focused items
SELECTED_COLORS = {
    ChangeType.ADDED: (0.0, 1.0, 0.0, 0.5),  # Bright Green
    ChangeType.REMOVED: (1.0, 0.0, 0.0, 0.5),  # Bright Red
    ChangeType.MODIFIED: (0.0, 0.0, 1.0, 0.5),  # Bright Blue
}


class CompareItemPainter(ItemPainter):
    """Custom painter that highlights items based on their change status."""

    def __init__(
        self,
        selection,
        style_func,
        diff: DiagramDiff,
        is_base: bool,
        selected_id: str | None = None,
    ):
        super().__init__(selection, style_func)
        self._diff = diff
        self._is_base = is_base
        self._selected_id = selected_id
        self._highlight_ids: dict[str, ChangeType] = {}
        self._build_highlight_map()

    def _build_highlight_map(self):
        """Build a map of presentation IDs to their change types."""
        for pres_diff in self._diff.presentation_diffs:
            self._highlight_ids[pres_diff.presentation_id] = pres_diff.change_type

    def set_selected_id(self, selected_id: str | None):
        """Update the currently selected/focused item."""
        self._selected_id = selected_id

    def paint_item(self, item, cairo):
        """Paint an item with optional highlight overlay."""
        super().paint_item(item, cairo)

        change_type = self._highlight_ids.get(item.id)
        if change_type:
            is_selected = item.id == self._selected_id
            self._draw_highlight(item, cairo, change_type, is_selected)

    def _draw_highlight(
        self, item, cairo, change_type: ChangeType, is_selected: bool = False
    ):
        """Draw a highlight overlay on the item."""
        colors = SELECTED_COLORS if is_selected else COLORS
        color = colors.get(change_type)
        if not color:
            return

        bounds = item.bounds()
        if bounds:
            x, y, x2, y2 = bounds
            width = x2 - x
            height = y2 - y

            cairo.save()
            cairo.set_source_rgba(*color)
            padding = 4 if is_selected else 2
            cairo.rectangle(x - padding, y - padding, width + 2 * padding, height + 2 * padding)
            cairo.fill()

            # Draw border for selected item
            if is_selected:
                border_color = (
                    color[0] * 0.7,
                    color[1] * 0.7,
                    color[2] * 0.7,
                    1.0,
                )
                cairo.set_source_rgba(*border_color)
                cairo.set_line_width(2)
                cairo.rectangle(x - padding, y - padding, width + 2 * padding, height + 2 * padding)
                cairo.stroke()

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
        self._base_painter: CompareItemPainter | None = None
        self._compare_painter: CompareItemPainter | None = None

        # Navigation state
        self._current_diff_index = -1
        self._diff_list: list[PresentationDiff] = list(self._diff.presentation_diffs)

        # UI elements
        self._prev_button: Gtk.Button | None = None
        self._next_button: Gtk.Button | None = None
        self._nav_label: Gtk.Label | None = None
        self._details_box: Gtk.Box | None = None

        self._build_ui()
        self._update_navigation_state()

    @property
    def diff(self) -> DiagramDiff:
        """Get the computed diagram diff."""
        return self._diff

    def _build_ui(self):
        """Build the comparison UI."""
        # Toolbar with navigation
        toolbar = self._create_toolbar()
        self.append(toolbar)

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

        # Details panel at bottom
        details_panel = self._create_details_panel()
        self.append(details_panel)

    def _create_toolbar(self) -> Gtk.Box:
        """Create the toolbar with navigation and summary."""
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        toolbar.add_css_class("toolbar")
        toolbar.set_margin_start(6)
        toolbar.set_margin_end(6)
        toolbar.set_margin_top(6)
        toolbar.set_margin_bottom(6)

        # Navigation buttons (left side)
        nav_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

        self._prev_button = Gtk.Button()
        self._prev_button.set_icon_name("go-previous-symbolic")
        self._prev_button.set_tooltip_text(gettext("Previous Change (Ctrl+Up)"))
        self._prev_button.connect("clicked", self._on_prev_clicked)
        nav_box.append(self._prev_button)

        self._next_button = Gtk.Button()
        self._next_button.set_icon_name("go-next-symbolic")
        self._next_button.set_tooltip_text(gettext("Next Change (Ctrl+Down)"))
        self._next_button.connect("clicked", self._on_next_clicked)
        nav_box.append(self._next_button)

        # Navigation counter
        self._nav_label = Gtk.Label()
        self._nav_label.add_css_class("dim-label")
        self._nav_label.set_margin_start(8)
        nav_box.append(self._nav_label)

        toolbar.append(nav_box)

        # Summary label (center)
        summary = self._create_summary_label()
        summary.set_hexpand(True)
        summary.set_halign(Gtk.Align.CENTER)
        toolbar.append(summary)

        # Legend (right side)
        legend = self._create_legend()
        toolbar.append(legend)

        # Add keyboard shortcuts
        key_controller = Gtk.EventControllerKey.new()
        key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_controller)

        return toolbar

    def _create_summary_label(self) -> Gtk.Label:
        """Create the summary label."""
        added = len(self._diff.added_presentations)
        removed = len(self._diff.removed_presentations)
        modified = len(self._diff.modified_presentations)

        summary_parts = []
        if added:
            summary_parts.append(gettext("{count} added").format(count=added))
        if removed:
            summary_parts.append(gettext("{count} removed").format(count=removed))
        if modified:
            summary_parts.append(gettext("{count} modified").format(count=modified))

        summary_text = ", ".join(summary_parts) if summary_parts else gettext("No changes detected")
        return Gtk.Label(label=summary_text)

    def _create_legend(self) -> Gtk.Box:
        """Create the color legend."""
        legend = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

        for change_type, color in COLORS.items():
            item = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

            swatch = Gtk.DrawingArea()
            swatch.set_size_request(16, 16)
            swatch.set_draw_func(self._draw_swatch, color)
            item.append(swatch)

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
            placeholder = Gtk.Label(label=gettext("No diagram"))
            placeholder.add_css_class("dim-label")
            frame.set_child(placeholder)
            return frame

        view = GtkView()
        view.model = diagram
        view.set_hexpand(True)
        view.set_vexpand(True)

        if is_base:
            self._base_view = view
        else:
            self._compare_view = view

        self._setup_view_painter(view, diagram, is_base)

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

        if is_base:
            self._base_painter = item_painter
        else:
            self._compare_painter = item_painter

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
        """Create the details panel showing selected element properties."""
        frame = Gtk.Frame()
        frame.set_label(gettext("Change Details"))
        frame.set_margin_start(6)
        frame.set_margin_end(6)
        frame.set_margin_top(6)
        frame.set_margin_bottom(6)

        self._details_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._details_box.set_margin_start(12)
        self._details_box.set_margin_end(12)
        self._details_box.set_margin_top(12)
        self._details_box.set_margin_bottom(12)

        # Initial placeholder
        placeholder = Gtk.Label(
            label=gettext("Select a change using the navigation buttons to see details")
        )
        placeholder.add_css_class("dim-label")
        self._details_box.append(placeholder)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(120)
        scrolled.set_max_content_height(200)
        scrolled.set_child(self._details_box)

        frame.set_child(scrolled)
        return frame

    def _update_details_panel(self, pres_diff: PresentationDiff | None):
        """Update the details panel with the selected change."""
        # Clear existing content
        while child := self._details_box.get_first_child():
            self._details_box.remove(child)

        if pres_diff is None:
            placeholder = Gtk.Label(
                label=gettext("Select a change using the navigation buttons to see details")
            )
            placeholder.add_css_class("dim-label")
            self._details_box.append(placeholder)
            return

        # Header with element type and change type
        header = self._create_detail_header(pres_diff)
        self._details_box.append(header)

        # Separator
        self._details_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Property changes grid
        if pres_diff.change_type in (ChangeType.ADDED, ChangeType.REMOVED):
            self._add_element_info(pres_diff)
        else:
            self._add_property_changes(pres_diff)

        # Subject changes if any
        if pres_diff.subject_diff and pres_diff.subject_diff.property_diffs:
            self._details_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
            subject_header = Gtk.Label(
                label=gettext("Subject Changes: {name}").format(
                    name=pres_diff.subject_diff.display_name
                )
            )
            subject_header.set_halign(Gtk.Align.START)
            subject_header.add_css_class("heading")
            self._details_box.append(subject_header)
            self._add_subject_property_changes(pres_diff.subject_diff.property_diffs)

    def _create_detail_header(self, pres_diff: PresentationDiff) -> Gtk.Box:
        """Create the header for the details panel."""
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

        # Element type
        type_label = Gtk.Label(label=pres_diff.presentation_type)
        type_label.add_css_class("title-3")
        type_label.set_halign(Gtk.Align.START)
        type_label.set_hexpand(True)
        header.append(type_label)

        # Change type badge
        change_text = {
            ChangeType.ADDED: gettext("Added"),
            ChangeType.REMOVED: gettext("Removed"),
            ChangeType.MODIFIED: gettext("Modified"),
        }.get(pres_diff.change_type, "")

        badge = Gtk.Label(label=change_text)
        badge.add_css_class("caption")
        if pres_diff.change_type == ChangeType.ADDED:
            badge.add_css_class("success")
        elif pres_diff.change_type == ChangeType.REMOVED:
            badge.add_css_class("error")
        else:
            badge.add_css_class("accent")
        header.append(badge)

        return header

    def _add_element_info(self, pres_diff: PresentationDiff):
        """Add element info for added/removed items."""
        pres = pres_diff.base_presentation or pres_diff.compare_presentation
        if not pres:
            return

        grid = Gtk.Grid()
        grid.set_column_spacing(24)
        grid.set_row_spacing(6)

        row = 0

        # ID
        self._add_grid_row(grid, row, gettext("ID"), pres.id[:12] + "...")
        row += 1

        # Subject info if available
        if pres.subject:
            subject = pres.subject
            if hasattr(subject, "name") and subject.name:
                self._add_grid_row(grid, row, gettext("Name"), subject.name)
                row += 1

            self._add_grid_row(grid, row, gettext("Type"), type(subject).__name__)
            row += 1

            if hasattr(subject, "visibility"):
                self._add_grid_row(grid, row, gettext("Visibility"), str(subject.visibility or "public"))
                row += 1

            if hasattr(subject, "isAbstract") and subject.isAbstract:
                self._add_grid_row(grid, row, gettext("Abstract"), gettext("Yes"))
                row += 1

        self._details_box.append(grid)

    def _add_property_changes(self, pres_diff: PresentationDiff):
        """Add property change rows for modified items."""
        if not pres_diff.property_diffs:
            label = Gtk.Label(label=gettext("No presentation property changes"))
            label.add_css_class("dim-label")
            label.set_halign(Gtk.Align.START)
            self._details_box.append(label)
            return

        grid = Gtk.Grid()
        grid.set_column_spacing(24)
        grid.set_row_spacing(6)

        for row, prop_diff in enumerate(pres_diff.property_diffs):
            self._add_property_change_row(grid, row, prop_diff)

        self._details_box.append(grid)

    def _add_subject_property_changes(self, property_diffs: list[PropertyDiff]):
        """Add subject property changes."""
        grid = Gtk.Grid()
        grid.set_column_spacing(24)
        grid.set_row_spacing(6)

        for row, prop_diff in enumerate(property_diffs):
            self._add_property_change_row(grid, row, prop_diff)

        self._details_box.append(grid)

    def _add_grid_row(self, grid: Gtk.Grid, row: int, label_text: str, value_text: str):
        """Add a simple label-value row to the grid."""
        label = Gtk.Label(label=label_text)
        label.add_css_class("dim-label")
        label.set_halign(Gtk.Align.START)
        grid.attach(label, 0, row, 1, 1)

        value = Gtk.Label(label=value_text)
        value.set_halign(Gtk.Align.START)
        value.set_selectable(True)
        grid.attach(value, 1, row, 1, 1)

    def _add_property_change_row(self, grid: Gtk.Grid, row: int, prop_diff: PropertyDiff):
        """Add a property change row to the grid."""
        # Property name
        name_label = Gtk.Label(label=prop_diff.property_name)
        name_label.add_css_class("dim-label")
        name_label.set_halign(Gtk.Align.START)
        grid.attach(name_label, 0, row, 1, 1)

        # Old value
        old_label = Gtk.Label(label=prop_diff.display_old)
        old_label.set_halign(Gtk.Align.START)
        old_label.add_css_class("dim-label")
        old_label.set_max_width_chars(30)
        old_label.set_ellipsize(Pango.EllipsizeMode.END)
        old_label.set_selectable(True)
        grid.attach(old_label, 1, row, 1, 1)

        # Arrow
        arrow_label = Gtk.Label(label="→")
        arrow_label.set_halign(Gtk.Align.CENTER)
        grid.attach(arrow_label, 2, row, 1, 1)

        # New value
        new_label = Gtk.Label(label=prop_diff.display_new)
        new_label.set_halign(Gtk.Align.START)
        new_label.set_max_width_chars(30)
        new_label.set_ellipsize(Pango.EllipsizeMode.END)
        new_label.set_selectable(True)
        grid.attach(new_label, 3, row, 1, 1)

    def _update_navigation_state(self):
        """Update the navigation buttons and label state."""
        total = len(self._diff_list)
        has_diffs = total > 0

        if self._prev_button:
            self._prev_button.set_sensitive(has_diffs)
        if self._next_button:
            self._next_button.set_sensitive(has_diffs)

        if self._nav_label:
            if has_diffs:
                current = self._current_diff_index + 1 if self._current_diff_index >= 0 else 0
                self._nav_label.set_text(f"{current}/{total}")
            else:
                self._nav_label.set_text(gettext("No changes"))

    def _on_prev_clicked(self, button):
        """Handle previous button click."""
        self._navigate(-1)

    def _on_next_clicked(self, button):
        """Handle next button click."""
        self._navigate(1)

    def _on_key_pressed(self, controller, keyval, keycode, state):
        """Handle keyboard shortcuts."""
        ctrl_pressed = state & Gdk.ModifierType.CONTROL_MASK

        if ctrl_pressed:
            if keyval == Gdk.KEY_Up:
                self._navigate(-1)
                return True
            elif keyval == Gdk.KEY_Down:
                self._navigate(1)
                return True

        return False

    def _navigate(self, direction: int):
        """Navigate to the next/previous diff item."""
        if not self._diff_list:
            return

        total = len(self._diff_list)

        # Cycle through diffs
        if self._current_diff_index < 0:
            # First navigation - start at beginning or end
            self._current_diff_index = 0 if direction > 0 else total - 1
        else:
            self._current_diff_index = (self._current_diff_index + direction) % total

        pres_diff = self._diff_list[self._current_diff_index]

        # Update painters with selected item
        selected_id = pres_diff.presentation_id
        if self._base_painter:
            self._base_painter.set_selected_id(selected_id)
        if self._compare_painter:
            self._compare_painter.set_selected_id(selected_id)

        # Scroll to the item in both views
        self._scroll_to_item(pres_diff)

        # Update details panel
        self._update_details_panel(pres_diff)

        # Update navigation label
        self._update_navigation_state()

        # Refresh views
        if self._base_view:
            self._base_view.update_back_buffer()
            self._base_view.queue_draw()
        if self._compare_view:
            self._compare_view.update_back_buffer()
            self._compare_view.queue_draw()

    def _scroll_to_item(self, pres_diff: PresentationDiff):
        """Scroll both views to show the specified item."""
        # Get the presentation from whichever diagram has it
        base_pres = pres_diff.base_presentation
        compare_pres = pres_diff.compare_presentation

        if base_pres and self._base_view:
            self._scroll_view_to_item(self._base_view, base_pres)

        if compare_pres and self._compare_view:
            self._scroll_view_to_item(self._compare_view, compare_pres)

    def _scroll_view_to_item(self, view: GtkView, item):
        """Scroll a view to center on an item."""
        bounds = item.bounds()
        if not bounds:
            return

        x, y, x2, y2 = bounds
        center_x = (x + x2) / 2
        center_y = (y + y2) / 2

        # Get the view's visible area
        allocation = view.get_allocation()
        view_width = allocation.width
        view_height = allocation.height

        # Calculate the matrix transformation to center the item
        matrix = view.matrix
        cx, cy = matrix.transform_point(center_x, center_y)

        # Calculate the scroll offset to center the item
        target_x = cx - view_width / 2
        target_y = cy - view_height / 2

        # Get the parent scrolled window
        parent = view.get_parent()
        if isinstance(parent, Gtk.ScrolledWindow):
            h_adj = parent.get_hadjustment()
            v_adj = parent.get_vadjustment()

            if h_adj:
                h_adj.set_value(target_x)
            if v_adj:
                v_adj.set_value(target_y)

    def sync_views(self):
        """Synchronize the two diagram views (zoom and pan)."""
        if not (self._base_view and self._compare_view):
            return

        base_matrix = self._base_view.matrix
        self._compare_view.matrix = base_matrix
