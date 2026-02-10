"""Presentation editor for creating and managing slides.

This module provides a dialog for creating and editing presentations,
including adding slides, setting regions, and configuring hotspots.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from gi.repository import Gdk, GLib, Gtk

from gaphor.core.modeling import Diagram
from gaphor.i18n import gettext
from gaphor.plugins.presentation.model import (
    Hotspot,
    HotspotAction,
    Presentation,
    Slide,
    ViewRegion,
)

if TYPE_CHECKING:
    from gaphor.core.modeling import ElementFactory

log = logging.getLogger(__name__)


class PresentationEditor:
    """Editor dialog for creating and managing presentations."""

    def __init__(
        self,
        presentation: Presentation,
        element_factory: ElementFactory,
        parent_window: Gtk.Window | None = None,
        on_save: Callable[[Presentation], None] | None = None,
        on_present: Callable[[Presentation], None] | None = None,
    ):
        self.presentation = presentation
        self.element_factory = element_factory
        self.parent_window = parent_window
        self._on_save = on_save
        self._on_present = on_present

        self._window: Gtk.Window | None = None
        self._slides_list: Gtk.ListBox | None = None
        self._slide_editor: Gtk.Box | None = None
        self._selected_slide: Slide | None = None

        self._title_entry: Gtk.Entry | None = None
        self._slide_title_entry: Gtk.Entry | None = None
        self._slide_notes_view: Gtk.TextView | None = None
        self._diagram_dropdown: Gtk.DropDown | None = None
        self._region_entries: dict[str, Gtk.SpinButton] = {}
        self._duration_spin: Gtk.SpinButton | None = None
        self._hotspots_list: Gtk.ListBox | None = None

    def open(self) -> None:
        """Open the presentation editor."""
        self._window = Gtk.Window()
        self._window.set_title(gettext("Presentation Editor"))
        self._window.set_default_size(900, 600)

        if self.parent_window:
            self._window.set_transient_for(self.parent_window)
            self._window.set_modal(True)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._window.set_child(main_box)

        header_bar = self._create_header_bar()
        main_box.append(header_bar)

        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        title_box.set_margin_start(12)
        title_box.set_margin_end(12)
        title_box.set_margin_top(12)
        title_label = Gtk.Label(label=gettext("Presentation Title:"))
        title_box.append(title_label)
        self._title_entry = Gtk.Entry()
        self._title_entry.set_text(self.presentation.title)
        self._title_entry.set_hexpand(True)
        self._title_entry.connect("changed", self._on_title_changed)
        title_box.append(self._title_entry)
        main_box.append(title_box)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_vexpand(True)
        main_box.append(paned)

        left_box = self._create_slides_panel()
        paned.set_start_child(left_box)
        paned.set_resize_start_child(False)
        paned.set_shrink_start_child(False)

        right_box = self._create_slide_editor_panel()
        paned.set_end_child(right_box)
        paned.set_resize_end_child(True)
        paned.set_shrink_end_child(False)

        paned.set_position(250)

        self._refresh_slides_list()
        if self.presentation.slides:
            self._select_slide(self.presentation.slides[0])

        self._window.present()

    def _create_header_bar(self) -> Gtk.Box:
        """Create the header bar with actions."""
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header.set_margin_start(12)
        header.set_margin_end(12)
        header.set_margin_top(6)
        header.set_margin_bottom(6)

        present_btn = Gtk.Button.new_with_label(gettext("Present"))
        present_btn.add_css_class("suggested-action")
        present_btn.connect("clicked", self._on_present_clicked)
        header.append(present_btn)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        header.append(spacer)

        save_btn = Gtk.Button.new_with_label(gettext("Save"))
        save_btn.connect("clicked", self._on_save_clicked)
        header.append(save_btn)

        close_btn = Gtk.Button.new_with_label(gettext("Close"))
        close_btn.connect("clicked", lambda b: self.close())
        header.append(close_btn)

        return header

    def _create_slides_panel(self) -> Gtk.Box:
        """Create the slides list panel."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_start(12)
        box.set_margin_end(6)
        box.set_margin_top(12)
        box.set_margin_bottom(12)

        label = Gtk.Label(label=gettext("Slides"))
        label.set_xalign(0)
        label.add_css_class("heading")
        box.append(label)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        box.append(scroll)

        self._slides_list = Gtk.ListBox()
        self._slides_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._slides_list.connect("row-selected", self._on_slide_selected)
        self._slides_list.add_css_class("boxed-list")
        scroll.set_child(self._slides_list)

        buttons_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.append(buttons_box)

        add_btn = Gtk.Button.new_from_icon_name("list-add-symbolic")
        add_btn.set_tooltip_text(gettext("Add slide"))
        add_btn.connect("clicked", self._on_add_slide)
        buttons_box.append(add_btn)

        remove_btn = Gtk.Button.new_from_icon_name("list-remove-symbolic")
        remove_btn.set_tooltip_text(gettext("Remove slide"))
        remove_btn.connect("clicked", self._on_remove_slide)
        buttons_box.append(remove_btn)

        up_btn = Gtk.Button.new_from_icon_name("go-up-symbolic")
        up_btn.set_tooltip_text(gettext("Move up"))
        up_btn.connect("clicked", self._on_move_slide_up)
        buttons_box.append(up_btn)

        down_btn = Gtk.Button.new_from_icon_name("go-down-symbolic")
        down_btn.set_tooltip_text(gettext("Move down"))
        down_btn.connect("clicked", self._on_move_slide_down)
        buttons_box.append(down_btn)

        return box

    def _create_slide_editor_panel(self) -> Gtk.Box:
        """Create the slide editor panel."""
        self._slide_editor = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._slide_editor.set_margin_start(6)
        self._slide_editor.set_margin_end(12)
        self._slide_editor.set_margin_top(12)
        self._slide_editor.set_margin_bottom(12)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_child(self._slide_editor)

        self._create_slide_basic_section()
        self._create_slide_region_section()
        self._create_slide_notes_section()
        self._create_slide_hotspots_section()

        return scroll

    def _create_slide_basic_section(self) -> None:
        """Create basic slide settings section."""
        frame = Gtk.Frame()
        frame.set_label(gettext("Slide Settings"))
        self._slide_editor.append(frame)

        grid = Gtk.Grid()
        grid.set_column_spacing(12)
        grid.set_row_spacing(6)
        grid.set_margin_start(12)
        grid.set_margin_end(12)
        grid.set_margin_top(12)
        grid.set_margin_bottom(12)
        frame.set_child(grid)

        row = 0

        title_label = Gtk.Label(label=gettext("Title:"))
        title_label.set_xalign(1)
        grid.attach(title_label, 0, row, 1, 1)

        self._slide_title_entry = Gtk.Entry()
        self._slide_title_entry.set_hexpand(True)
        self._slide_title_entry.connect("changed", self._on_slide_title_changed)
        grid.attach(self._slide_title_entry, 1, row, 1, 1)
        row += 1

        diagram_label = Gtk.Label(label=gettext("Diagram:"))
        diagram_label.set_xalign(1)
        grid.attach(diagram_label, 0, row, 1, 1)

        diagrams = list(self.element_factory.select(Diagram))
        diagram_names = [d.name or f"Diagram {d.id[:8]}" for d in diagrams]

        string_list = Gtk.StringList.new(diagram_names)
        self._diagram_dropdown = Gtk.DropDown.new(string_list, None)
        self._diagram_dropdown.set_hexpand(True)
        self._diagram_dropdown.connect("notify::selected", self._on_diagram_changed)
        self._diagram_dropdown._diagrams = diagrams
        grid.attach(self._diagram_dropdown, 1, row, 1, 1)
        row += 1

        duration_label = Gtk.Label(label=gettext("Transition (s):"))
        duration_label.set_xalign(1)
        grid.attach(duration_label, 0, row, 1, 1)

        self._duration_spin = Gtk.SpinButton.new_with_range(0, 5, 0.1)
        self._duration_spin.set_digits(1)
        self._duration_spin.connect("value-changed", self._on_duration_changed)
        grid.attach(self._duration_spin, 1, row, 1, 1)

    def _create_slide_region_section(self) -> None:
        """Create view region settings section."""
        frame = Gtk.Frame()
        frame.set_label(gettext("View Region"))
        self._slide_editor.append(frame)

        grid = Gtk.Grid()
        grid.set_column_spacing(12)
        grid.set_row_spacing(6)
        grid.set_margin_start(12)
        grid.set_margin_end(12)
        grid.set_margin_top(12)
        grid.set_margin_bottom(12)
        frame.set_child(grid)

        fields = [
            ("x", gettext("X:")),
            ("y", gettext("Y:")),
            ("width", gettext("Width:")),
            ("height", gettext("Height:")),
            ("zoom", gettext("Zoom:")),
        ]

        for row, (field, label_text) in enumerate(fields):
            label = Gtk.Label(label=label_text)
            label.set_xalign(1)
            grid.attach(label, 0, row, 1, 1)

            if field == "zoom":
                spin = Gtk.SpinButton.new_with_range(0.1, 10, 0.1)
                spin.set_digits(2)
            else:
                spin = Gtk.SpinButton.new_with_range(-10000, 10000, 10)
                spin.set_digits(0)

            spin.set_hexpand(True)
            spin.connect("value-changed", self._on_region_changed, field)
            grid.attach(spin, 1, row, 1, 1)
            self._region_entries[field] = spin

        capture_btn = Gtk.Button.new_with_label(gettext("Capture Current View"))
        capture_btn.set_tooltip_text(
            gettext("Capture the current diagram view as the slide region")
        )
        capture_btn.connect("clicked", self._on_capture_view)
        grid.attach(capture_btn, 0, len(fields), 2, 1)

    def _create_slide_notes_section(self) -> None:
        """Create presenter notes section."""
        frame = Gtk.Frame()
        frame.set_label(gettext("Presenter Notes"))
        self._slide_editor.append(frame)

        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_height(100)
        scroll.set_max_content_height(150)
        scroll.set_margin_start(12)
        scroll.set_margin_end(12)
        scroll.set_margin_top(12)
        scroll.set_margin_bottom(12)
        frame.set_child(scroll)

        self._slide_notes_view = Gtk.TextView()
        self._slide_notes_view.set_wrap_mode(Gtk.WrapMode.WORD)
        self._slide_notes_view.get_buffer().connect("changed", self._on_notes_changed)
        scroll.set_child(self._slide_notes_view)

    def _create_slide_hotspots_section(self) -> None:
        """Create hotspots configuration section."""
        frame = Gtk.Frame()
        frame.set_label(gettext("Hotspots"))
        self._slide_editor.append(frame)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        frame.set_child(box)

        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_height(100)
        scroll.set_max_content_height(150)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        box.append(scroll)

        self._hotspots_list = Gtk.ListBox()
        self._hotspots_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._hotspots_list.add_css_class("boxed-list")
        scroll.set_child(self._hotspots_list)

        buttons_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.append(buttons_box)

        add_hotspot_btn = Gtk.Button.new_from_icon_name("list-add-symbolic")
        add_hotspot_btn.set_tooltip_text(gettext("Add hotspot"))
        add_hotspot_btn.connect("clicked", self._on_add_hotspot)
        buttons_box.append(add_hotspot_btn)

        remove_hotspot_btn = Gtk.Button.new_from_icon_name("list-remove-symbolic")
        remove_hotspot_btn.set_tooltip_text(gettext("Remove hotspot"))
        remove_hotspot_btn.connect("clicked", self._on_remove_hotspot)
        buttons_box.append(remove_hotspot_btn)

        edit_hotspot_btn = Gtk.Button.new_from_icon_name("document-edit-symbolic")
        edit_hotspot_btn.set_tooltip_text(gettext("Edit hotspot"))
        edit_hotspot_btn.connect("clicked", self._on_edit_hotspot)
        buttons_box.append(edit_hotspot_btn)

    def _refresh_slides_list(self) -> None:
        """Refresh the slides list."""
        if not self._slides_list:
            return

        while child := self._slides_list.get_first_child():
            self._slides_list.remove(child)

        for i, slide in enumerate(self.presentation.slides):
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            box.set_margin_start(6)
            box.set_margin_end(6)
            box.set_margin_top(6)
            box.set_margin_bottom(6)

            number_label = Gtk.Label(label=f"{i + 1}.")
            number_label.set_width_chars(3)
            box.append(number_label)

            title = slide.title or f"Slide {i + 1}"
            title_label = Gtk.Label(label=title)
            title_label.set_ellipsize(3)  # PANGO_ELLIPSIZE_END
            title_label.set_hexpand(True)
            title_label.set_xalign(0)
            box.append(title_label)

            row.set_child(box)
            row._slide = slide
            self._slides_list.append(row)

    def _select_slide(self, slide: Slide | None) -> None:
        """Select a slide for editing."""
        self._selected_slide = slide
        self._update_slide_editor()

    def _update_slide_editor(self) -> None:
        """Update the slide editor with current slide data."""
        slide = self._selected_slide

        if not slide:
            self._slide_editor.set_sensitive(False)
            return

        self._slide_editor.set_sensitive(True)

        if self._slide_title_entry:
            self._slide_title_entry.set_text(slide.title or "")

        if self._diagram_dropdown:
            diagrams = getattr(self._diagram_dropdown, "_diagrams", [])
            for i, d in enumerate(diagrams):
                if d.id == slide.diagram_id:
                    self._diagram_dropdown.set_selected(i)
                    break

        if self._duration_spin:
            self._duration_spin.set_value(slide.transition_duration)

        for field, spin in self._region_entries.items():
            value = getattr(slide.region, field, 0)
            spin.set_value(value)

        if self._slide_notes_view:
            self._slide_notes_view.get_buffer().set_text(slide.notes or "")

        self._refresh_hotspots_list()

    def _refresh_hotspots_list(self) -> None:
        """Refresh the hotspots list."""
        if not self._hotspots_list or not self._selected_slide:
            return

        while child := self._hotspots_list.get_first_child():
            self._hotspots_list.remove(child)

        for hotspot in self._selected_slide.hotspots:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            box.set_margin_start(6)
            box.set_margin_end(6)
            box.set_margin_top(6)
            box.set_margin_bottom(6)

            action_label = Gtk.Label(label=hotspot.action.value)
            action_label.set_width_chars(15)
            action_label.set_xalign(0)
            box.append(action_label)

            target_label = Gtk.Label(label=hotspot.target or hotspot.tooltip or "-")
            target_label.set_ellipsize(3)
            target_label.set_hexpand(True)
            target_label.set_xalign(0)
            box.append(target_label)

            row.set_child(box)
            row._hotspot = hotspot
            self._hotspots_list.append(row)

    def _on_title_changed(self, entry: Gtk.Entry) -> None:
        """Handle presentation title change."""
        self.presentation.title = entry.get_text()

    def _on_slide_selected(self, listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        """Handle slide selection."""
        if row:
            self._select_slide(row._slide)
        else:
            self._select_slide(None)

    def _on_slide_title_changed(self, entry: Gtk.Entry) -> None:
        """Handle slide title change."""
        if self._selected_slide:
            self._selected_slide.title = entry.get_text()
            self._refresh_slides_list()

    def _on_diagram_changed(self, dropdown: Gtk.DropDown, _param) -> None:
        """Handle diagram selection change."""
        if not self._selected_slide:
            return

        diagrams = getattr(dropdown, "_diagrams", [])
        selected = dropdown.get_selected()
        if 0 <= selected < len(diagrams):
            self._selected_slide.diagram_id = diagrams[selected].id

    def _on_duration_changed(self, spin: Gtk.SpinButton) -> None:
        """Handle transition duration change."""
        if self._selected_slide:
            self._selected_slide.transition_duration = spin.get_value()

    def _on_region_changed(self, spin: Gtk.SpinButton, field: str) -> None:
        """Handle region value change."""
        if self._selected_slide:
            setattr(self._selected_slide.region, field, spin.get_value())

    def _on_notes_changed(self, buffer: Gtk.TextBuffer) -> None:
        """Handle notes change."""
        if self._selected_slide:
            start, end = buffer.get_bounds()
            self._selected_slide.notes = buffer.get_text(start, end, False)

    def _on_add_slide(self, button: Gtk.Button) -> None:
        """Add a new slide."""
        diagrams = list(self.element_factory.select(Diagram))
        diagram_id = diagrams[0].id if diagrams else ""

        slide = Slide(
            title=f"Slide {len(self.presentation.slides) + 1}",
            diagram_id=diagram_id,
            region=ViewRegion(0, 0, 800, 600, 1.0),
        )
        self.presentation.add_slide(slide)
        self._refresh_slides_list()
        self._select_slide(slide)

    def _on_remove_slide(self, button: Gtk.Button) -> None:
        """Remove the selected slide."""
        if not self._selected_slide:
            return

        self.presentation.remove_slide(self._selected_slide.id)
        self._refresh_slides_list()

        if self.presentation.slides:
            self._select_slide(self.presentation.slides[0])
        else:
            self._select_slide(None)

    def _on_move_slide_up(self, button: Gtk.Button) -> None:
        """Move the selected slide up."""
        if not self._selected_slide:
            return

        index = self.presentation.get_slide_index(self._selected_slide.id)
        if index > 0:
            self.presentation.move_slide(self._selected_slide.id, index - 1)
            self._refresh_slides_list()

    def _on_move_slide_down(self, button: Gtk.Button) -> None:
        """Move the selected slide down."""
        if not self._selected_slide:
            return

        index = self.presentation.get_slide_index(self._selected_slide.id)
        if index < len(self.presentation.slides) - 1:
            self.presentation.move_slide(self._selected_slide.id, index + 1)
            self._refresh_slides_list()

    def _on_capture_view(self, button: Gtk.Button) -> None:
        """Capture current diagram view as slide region."""
        log.info("Capture view requested - implement by connecting to diagram view")

    def _on_add_hotspot(self, button: Gtk.Button) -> None:
        """Add a new hotspot to the current slide."""
        if not self._selected_slide:
            return

        hotspot = Hotspot(
            x=100,
            y=100,
            width=50,
            height=50,
            action=HotspotAction.SHOW_TOOLTIP,
            tooltip="Click here",
        )
        self._selected_slide.hotspots.append(hotspot)
        self._refresh_hotspots_list()

    def _on_remove_hotspot(self, button: Gtk.Button) -> None:
        """Remove the selected hotspot."""
        if not self._selected_slide or not self._hotspots_list:
            return

        row = self._hotspots_list.get_selected_row()
        if row and hasattr(row, "_hotspot"):
            self._selected_slide.hotspots.remove(row._hotspot)
            self._refresh_hotspots_list()

    def _on_edit_hotspot(self, button: Gtk.Button) -> None:
        """Edit the selected hotspot."""
        if not self._hotspots_list:
            return

        row = self._hotspots_list.get_selected_row()
        if row and hasattr(row, "_hotspot"):
            self._open_hotspot_editor(row._hotspot)

    def _open_hotspot_editor(self, hotspot: Hotspot) -> None:
        """Open a dialog to edit a hotspot."""
        dialog = Gtk.Dialog()
        dialog.set_title(gettext("Edit Hotspot"))
        dialog.set_transient_for(self._window)
        dialog.set_modal(True)
        dialog.set_default_size(400, 300)

        content = dialog.get_content_area()
        content.set_spacing(12)
        content.set_margin_start(12)
        content.set_margin_end(12)
        content.set_margin_top(12)
        content.set_margin_bottom(12)

        grid = Gtk.Grid()
        grid.set_column_spacing(12)
        grid.set_row_spacing(6)
        content.append(grid)

        row = 0

        action_label = Gtk.Label(label=gettext("Action:"))
        action_label.set_xalign(1)
        grid.attach(action_label, 0, row, 1, 1)

        actions = list(HotspotAction)
        action_names = [a.value for a in actions]
        action_dropdown = Gtk.DropDown.new_from_strings(action_names)
        action_dropdown.set_selected(actions.index(hotspot.action))
        grid.attach(action_dropdown, 1, row, 1, 1)
        row += 1

        target_label = Gtk.Label(label=gettext("Target:"))
        target_label.set_xalign(1)
        grid.attach(target_label, 0, row, 1, 1)

        target_entry = Gtk.Entry()
        target_entry.set_text(hotspot.target)
        target_entry.set_hexpand(True)
        grid.attach(target_entry, 1, row, 1, 1)
        row += 1

        tooltip_label = Gtk.Label(label=gettext("Tooltip:"))
        tooltip_label.set_xalign(1)
        grid.attach(tooltip_label, 0, row, 1, 1)

        tooltip_entry = Gtk.Entry()
        tooltip_entry.set_text(hotspot.tooltip)
        tooltip_entry.set_hexpand(True)
        grid.attach(tooltip_entry, 1, row, 1, 1)
        row += 1

        visible_check = Gtk.CheckButton(label=gettext("Show indicator"))
        visible_check.set_active(hotspot.visible)
        grid.attach(visible_check, 1, row, 1, 1)
        row += 1

        position_fields = [
            ("X:", hotspot.x),
            ("Y:", hotspot.y),
            ("Width:", hotspot.width),
            ("Height:", hotspot.height),
        ]
        position_spins = []

        for label_text, value in position_fields:
            label = Gtk.Label(label=label_text)
            label.set_xalign(1)
            grid.attach(label, 0, row, 1, 1)

            spin = Gtk.SpinButton.new_with_range(-10000, 10000, 1)
            spin.set_value(value)
            grid.attach(spin, 1, row, 1, 1)
            position_spins.append(spin)
            row += 1

        buttons_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        buttons_box.set_halign(Gtk.Align.END)
        content.append(buttons_box)

        cancel_btn = Gtk.Button.new_with_label(gettext("Cancel"))
        cancel_btn.connect("clicked", lambda b: dialog.close())
        buttons_box.append(cancel_btn)

        save_btn = Gtk.Button.new_with_label(gettext("Save"))
        save_btn.add_css_class("suggested-action")

        def save_hotspot(btn):
            hotspot.action = actions[action_dropdown.get_selected()]
            hotspot.target = target_entry.get_text()
            hotspot.tooltip = tooltip_entry.get_text()
            hotspot.visible = visible_check.get_active()
            hotspot.x = position_spins[0].get_value()
            hotspot.y = position_spins[1].get_value()
            hotspot.width = position_spins[2].get_value()
            hotspot.height = position_spins[3].get_value()
            self._refresh_hotspots_list()
            dialog.close()

        save_btn.connect("clicked", save_hotspot)
        buttons_box.append(save_btn)

        dialog.present()

    def _on_save_clicked(self, button: Gtk.Button) -> None:
        """Handle save button click."""
        if self._on_save:
            self._on_save(self.presentation)

    def _on_present_clicked(self, button: Gtk.Button) -> None:
        """Handle present button click."""
        if self._on_present:
            self._on_present(self.presentation)

    def close(self) -> None:
        """Close the editor."""
        if self._window:
            self._window.destroy()
            self._window = None
