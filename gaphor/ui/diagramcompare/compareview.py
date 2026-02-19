"""Split-screen comparison view for diagrams.

Displays two versions of a diagram side by side with highlighted differences.
Includes navigation controls and a details panel for property changes.
"""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING

from gaphas.painter import PainterChain
from gaphas.view import GtkView
from gi.repository import Adw, Gdk, GLib, Gtk, Pango

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

# Border colors for selected diff item
SELECTED_BORDER_COLORS = {
    ChangeType.ADDED: (0.0, 0.6, 0.0, 1.0),
    ChangeType.REMOVED: (0.6, 0.0, 0.0, 1.0),
    ChangeType.MODIFIED: (0.0, 0.0, 0.6, 1.0),
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

    def set_selected_id(self, selected_id: str | None):
        """Update the currently selected diff item."""
        self._selected_id = selected_id

    def _build_highlight_map(self):
        """Build a map of presentation IDs to their change types."""
        for pres_diff in self._diff.presentation_diffs:
            self._highlight_ids[pres_diff.presentation_id] = pres_diff.change_type

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
        color = COLORS.get(change_type)
        if not color:
            return

        bounds = item.bounds()
        if not bounds:
            return

        x, y, x2, y2 = bounds
        width = x2 - x
        height = y2 - y

        cairo.save()

        # Draw semi-transparent fill
        cairo.set_source_rgba(*color)
        cairo.rectangle(x - 2, y - 2, width + 4, height + 4)
        cairo.fill()

        # Draw border for selected item
        if is_selected:
            border_color = SELECTED_BORDER_COLORS.get(change_type, (0.5, 0.5, 0.5, 1.0))
            cairo.set_source_rgba(*border_color)
            cairo.set_line_width(3)
            cairo.rectangle(x - 4, y - 4, width + 8, height + 8)
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
        self._current_diff_index: int = -1
        self._diff_items: list[PresentationDiff] = []
        self._nav_label: Gtk.Label | None = None
        self._prev_button: Gtk.Button | None = None
        self._next_button: Gtk.Button | None = None

        # Details panel widgets
        self._details_title: Gtk.Label | None = None
        self._details_listbox: Gtk.ListBox | None = None
        self._details_placeholder: Gtk.Label | None = None
        self._details_stack: Gtk.Stack | None = None

        self._build_diff_items_list()
        self._build_ui()

    @property
    def diff(self) -> DiagramDiff:
        """Get the computed diagram diff."""
        return self._diff

    def _build_diff_items_list(self):
        """Build the list of navigable diff items."""
        self._diff_items = [
            p for p in self._diff.presentation_diffs if p.change_type != ChangeType.UNCHANGED
        ]

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
        details = self._create_details_panel()
        self.append(details)

        # Update navigation state
        self._update_navigation_ui()

    def _create_toolbar(self) -> Gtk.Box:
        """Create the toolbar with navigation and summary."""
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        toolbar.add_css_class("toolbar")
        toolbar.set_margin_start(6)
        toolbar.set_margin_end(6)
        toolbar.set_margin_top(6)
        toolbar.set_margin_bottom(6)

        # Summary label (left side)
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

        summary_text = (
            ", ".join(summary_parts) if summary_parts else gettext("No changes detected")
        )
        summary = Gtk.Label(label=summary_text)
        summary.set_hexpand(True)
        summary.set_halign(Gtk.Align.START)
        toolbar.append(summary)

        # Navigation controls (center)
        nav_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        nav_box.add_css_class("linked")

        # Previous button
        self._prev_button = Gtk.Button()
        self._prev_button.set_icon_name("go-previous-symbolic")
        self._prev_button.set_tooltip_text(gettext("Previous Change (↑)"))
        self._prev_button.connect("clicked", self._on_prev_clicked)
        nav_box.append(self._prev_button)

        # Navigation label showing current position
        self._nav_label = Gtk.Label()
        self._nav_label.set_width_chars(10)
        self._nav_label.add_css_class("caption")
        nav_box.append(self._nav_label)

        # Next button
        self._next_button = Gtk.Button()
        self._next_button.set_icon_name("go-next-symbolic")
        self._next_button.set_tooltip_text(gettext("Next Change (↓)"))
        self._next_button.connect("clicked", self._on_next_clicked)
        nav_box.append(self._next_button)

        toolbar.append(nav_box)

        # Legend (right side)
        legend = self._create_legend()
        toolbar.append(legend)

        # Add keyboard shortcuts
        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_controller)

        return toolbar

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
        """Create the details panel showing property changes for selected element."""
        frame = Gtk.Frame()
        frame.set_label(gettext("Change Details"))
        frame.set_margin_start(6)
        frame.set_margin_end(6)
        frame.set_margin_top(6)
        frame.set_margin_bottom(6)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(6)
        box.set_margin_bottom(6)

        # Title showing selected element info
        self._details_title = Gtk.Label()
        self._details_title.set_halign(Gtk.Align.START)
        self._details_title.add_css_class("heading")
        box.append(self._details_title)

        # Stack to switch between placeholder and content
        self._details_stack = Gtk.Stack()
        self._details_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)

        # Placeholder when no item is selected
        self._details_placeholder = Gtk.Label(
            label=gettext("Select a change using the navigation buttons to see details")
        )
        self._details_placeholder.add_css_class("dim-label")
        self._details_placeholder.set_margin_top(12)
        self._details_placeholder.set_margin_bottom(12)
        self._details_stack.add_named(self._details_placeholder, "placeholder")

        # Scrolled list of property changes
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(120)
        scrolled.set_max_content_height(180)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self._details_listbox = Gtk.ListBox()
        self._details_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self._details_listbox.add_css_class("boxed-list")
        scrolled.set_child(self._details_listbox)

        self._details_stack.add_named(scrolled, "content")
        self._details_stack.set_visible_child_name("placeholder")

        box.append(self._details_stack)
        frame.set_child(box)

        return frame

    def _update_navigation_ui(self):
        """Update the navigation UI based on current state."""
        total = len(self._diff_items)
        has_items = total > 0

        if self._prev_button:
            self._prev_button.set_sensitive(has_items)
        if self._next_button:
            self._next_button.set_sensitive(has_items)

        if self._nav_label:
            if has_items:
                current = self._current_diff_index + 1 if self._current_diff_index >= 0 else 0
                self._nav_label.set_text(f"{current} / {total}")
            else:
                self._nav_label.set_text(gettext("No changes"))

    def _on_prev_clicked(self, button):
        """Navigate to previous diff item."""
        self._navigate_diff(-1)

    def _on_next_clicked(self, button):
        """Navigate to next diff item."""
        self._navigate_diff(1)

    def _on_key_pressed(self, controller, keyval, keycode, state):
        """Handle keyboard navigation."""
        if keyval in (Gdk.KEY_Up, Gdk.KEY_k):
            self._navigate_diff(-1)
            return True
        elif keyval in (Gdk.KEY_Down, Gdk.KEY_j):
            self._navigate_diff(1)
            return True
        return False

    def _navigate_diff(self, direction: int):
        """Navigate to previous (-1) or next (1) diff item with cycling."""
        if not self._diff_items:
            return

        total = len(self._diff_items)

        if self._current_diff_index < 0:
            # First navigation - start at beginning or end
            self._current_diff_index = 0 if direction > 0 else total - 1
        else:
            # Cycle through items
            self._current_diff_index = (self._current_diff_index + direction) % total

        self._select_current_diff()

    def _select_current_diff(self):
        """Select and scroll to the current diff item."""
        if self._current_diff_index < 0 or self._current_diff_index >= len(self._diff_items):
            return

        pres_diff = self._diff_items[self._current_diff_index]
        presentation_id = pres_diff.presentation_id

        # Update painters with selected ID
        if self._base_painter:
            self._base_painter.set_selected_id(presentation_id)
        if self._compare_painter:
            self._compare_painter.set_selected_id(presentation_id)

        # Scroll to the item in both views
        self._scroll_to_item(self._base_view, self._base_diagram, presentation_id)
        self._scroll_to_item(self._compare_view, self._compare_diagram, presentation_id)

        # Update the details panel
        self._update_details_panel(pres_diff)

        # Update navigation label
        self._update_navigation_ui()

        # Request redraw
        if self._base_view:
            self._base_view.queue_draw()
        if self._compare_view:
            self._compare_view.queue_draw()

    def _scroll_to_item(
        self, view: GtkView | None, diagram: Diagram | None, presentation_id: str
    ):
        """Scroll the view to center on the specified presentation."""
        if not view or not diagram:
            return

        # Find the presentation in the diagram
        presentation = None
        for pres in diagram.ownedPresentation:
            if pres.id == presentation_id:
                presentation = pres
                break

        if not presentation:
            return

        # Get the bounds of the presentation
        bounds = presentation.bounds()
        if not bounds:
            return

        x1, y1, x2, y2 = bounds
        center_x = (x1 + x2) / 2
        center_y = (y1 + y2) / 2

        # Get view allocation for centering calculation
        width = view.get_allocated_width()
        height = view.get_allocated_height()

        if width <= 0 or height <= 0:
            return

        # Calculate the matrix transformation to center the item
        matrix = view.matrix
        zoom = matrix[0]  # Assuming uniform scaling

        # Transform center point to view coordinates
        view_x = center_x * zoom
        view_y = center_y * zoom

        # Calculate scroll offsets to center the item
        target_x = view_x - width / 2
        target_y = view_y - height / 2

        # Get the scrolled window parent
        scrolled = view.get_parent()
        if isinstance(scrolled, Gtk.ScrolledWindow):
            h_adj = scrolled.get_hadjustment()
            v_adj = scrolled.get_vadjustment()

            if h_adj:
                # Clamp to valid range
                target_x = max(0, min(target_x, h_adj.get_upper() - h_adj.get_page_size()))
                h_adj.set_value(target_x)
            if v_adj:
                target_y = max(0, min(target_y, v_adj.get_upper() - v_adj.get_page_size()))
                v_adj.set_value(target_y)

    def _update_details_panel(self, pres_diff: PresentationDiff):
        """Update the details panel with information about the selected change."""
        if not self._details_title or not self._details_listbox or not self._details_stack:
            return

        # Clear previous content
        while child := self._details_listbox.get_first_child():
            self._details_listbox.remove(child)

        # Update title
        change_type_text = {
            ChangeType.ADDED: gettext("Added"),
            ChangeType.REMOVED: gettext("Removed"),
            ChangeType.MODIFIED: gettext("Modified"),
        }.get(pres_diff.change_type, "")

        element_name = ""
        if pres_diff.subject_diff and pres_diff.subject_diff.element_name:
            element_name = f" - {pres_diff.subject_diff.element_name}"

        self._details_title.set_markup(
            f"<b>{pres_diff.presentation_type}</b>{element_name} "
            f"<span color='gray'>({change_type_text})</span>"
        )

        has_details = False

        # Add presentation property changes
        if pres_diff.property_diffs:
            header = self._create_section_header(gettext("Presentation Properties"))
            self._details_listbox.append(header)

            for prop_diff in pres_diff.property_diffs:
                row = self._create_detail_row(prop_diff)
                self._details_listbox.append(row)
                has_details = True

        # Add subject (element) property changes
        if pres_diff.subject_diff:
            subj = pres_diff.subject_diff

            if subj.property_diffs:
                header = self._create_section_header(
                    gettext("Element Properties ({type})").format(type=subj.element_type)
                )
                self._details_listbox.append(header)

                for prop_diff in subj.property_diffs:
                    row = self._create_detail_row(prop_diff)
                    self._details_listbox.append(row)
                    has_details = True
            elif subj.change_type in (ChangeType.ADDED, ChangeType.REMOVED):
                # Show basic info for added/removed elements
                header = self._create_section_header(
                    gettext("Element: {type}").format(type=subj.element_type)
                )
                self._details_listbox.append(header)

                status_row = self._create_info_row(
                    gettext("Status"),
                    change_type_text,
                    pres_diff.change_type,
                )
                self._details_listbox.append(status_row)

                if subj.element_name:
                    name_row = self._create_info_row(
                        gettext("Name"),
                        subj.element_name,
                    )
                    self._details_listbox.append(name_row)

                has_details = True

        # If no property changes, show basic change info
        if not has_details:
            info_row = self._create_info_row(
                gettext("Change Type"),
                change_type_text,
                pres_diff.change_type,
            )
            self._details_listbox.append(info_row)

            id_row = self._create_info_row(
                gettext("Element ID"),
                pres_diff.presentation_id[:12] + "...",
            )
            self._details_listbox.append(id_row)

        # Show content instead of placeholder
        self._details_stack.set_visible_child_name("content")

    def _create_section_header(self, title: str) -> Gtk.ListBoxRow:
        """Create a section header row."""
        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        row.set_activatable(False)

        label = Gtk.Label(label=title)
        label.set_halign(Gtk.Align.START)
        label.add_css_class("heading")
        label.add_css_class("dim-label")
        label.set_margin_start(6)
        label.set_margin_top(12)
        label.set_margin_bottom(4)

        row.set_child(label)
        return row

    def _create_detail_row(self, prop_diff: PropertyDiff) -> Gtk.ListBoxRow:
        """Create a row showing a property change with old and new values."""
        row = Gtk.ListBoxRow()
        row.set_selectable(False)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(8)
        box.set_margin_bottom(8)

        # Property name
        name_label = Gtk.Label(label=prop_diff.property_name)
        name_label.set_halign(Gtk.Align.START)
        name_label.set_width_chars(15)
        name_label.set_xalign(0)
        name_label.add_css_class("caption")
        name_label.add_css_class("dim-label")
        box.append(name_label)

        # Old value with strikethrough
        old_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        old_box.set_hexpand(True)

        old_header = Gtk.Label(label=gettext("Before"))
        old_header.set_halign(Gtk.Align.START)
        old_header.add_css_class("caption")
        old_header.add_css_class("dim-label")
        old_box.append(old_header)

        old_value = Gtk.Label(label=prop_diff.display_old)
        old_value.set_halign(Gtk.Align.START)
        old_value.set_ellipsize(Pango.EllipsizeMode.END)
        old_value.set_max_width_chars(25)
        old_value.set_selectable(True)
        old_value.add_css_class("error")  # Red for old value
        old_box.append(old_value)

        box.append(old_box)

        # Arrow separator
        arrow = Gtk.Label(label="→")
        arrow.add_css_class("dim-label")
        box.append(arrow)

        # New value
        new_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        new_box.set_hexpand(True)

        new_header = Gtk.Label(label=gettext("After"))
        new_header.set_halign(Gtk.Align.START)
        new_header.add_css_class("caption")
        new_header.add_css_class("dim-label")
        new_box.append(new_header)

        new_value = Gtk.Label(label=prop_diff.display_new)
        new_value.set_halign(Gtk.Align.START)
        new_value.set_ellipsize(Pango.EllipsizeMode.END)
        new_value.set_max_width_chars(25)
        new_value.set_selectable(True)
        new_value.add_css_class("success")  # Green for new value
        new_box.append(new_value)

        box.append(new_box)

        row.set_child(box)
        return row

    def _create_info_row(
        self,
        label_text: str,
        value_text: str,
        change_type: ChangeType | None = None,
    ) -> Gtk.ListBoxRow:
        """Create a simple info row with label and value."""
        row = Gtk.ListBoxRow()
        row.set_selectable(False)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(6)
        box.set_margin_bottom(6)

        # Label
        label = Gtk.Label(label=label_text)
        label.set_halign(Gtk.Align.START)
        label.set_width_chars(15)
        label.set_xalign(0)
        label.add_css_class("caption")
        label.add_css_class("dim-label")
        box.append(label)

        # Value with optional color based on change type
        value = Gtk.Label(label=value_text)
        value.set_halign(Gtk.Align.START)
        value.set_hexpand(True)
        value.set_selectable(True)

        if change_type == ChangeType.ADDED:
            value.add_css_class("success")
        elif change_type == ChangeType.REMOVED:
            value.add_css_class("error")
        elif change_type == ChangeType.MODIFIED:
            value.add_css_class("warning")

        box.append(value)

        row.set_child(box)
        return row

    def sync_views(self):
        """Synchronize the two diagram views (zoom and pan)."""
        if not (self._base_view and self._compare_view):
            return

        base_matrix = self._base_view.matrix
        self._compare_view.matrix = base_matrix
