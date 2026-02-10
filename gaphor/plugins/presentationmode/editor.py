"""Presentation editor for creating and editing presentations."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from gaphor.i18n import gettext
from gaphor.plugins.presentationmode.errors import handle_errors, show_warning_dialog
from gaphor.plugins.presentationmode.model import Presentation, Slide, SlideRegion

if TYPE_CHECKING:
    from gaphor.core.modeling import Diagram

log = logging.getLogger(__name__)


class SlideEditor(Gtk.Box):
    """Editor widget for a single slide."""

    def __init__(self, slide: Slide, on_change: Callable[[], None]):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.slide = slide
        self.on_change = on_change
        self._capture_callback: Callable[[], tuple[float, float, float, float] | None] | None = None

        self.set_margin_start(6)
        self.set_margin_end(6)
        self.set_margin_top(6)
        self.set_margin_bottom(6)

        self._build_ui()

    def _build_ui(self) -> None:
        """Build the slide editor UI."""
        title_label = Gtk.Label(label=gettext("Title"))
        title_label.set_halign(Gtk.Align.START)
        self.append(title_label)

        self.title_entry = Gtk.Entry()
        self.title_entry.set_text(self.slide.title)
        self.title_entry.connect("changed", self._on_title_changed)
        self.append(self.title_entry)

        notes_label = Gtk.Label(label=gettext("Presenter Notes"))
        notes_label.set_halign(Gtk.Align.START)
        self.append(notes_label)

        notes_scroll = Gtk.ScrolledWindow()
        notes_scroll.set_min_content_height(100)
        notes_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        self.notes_view = Gtk.TextView()
        self.notes_view.set_wrap_mode(Gtk.WrapMode.WORD)
        self.notes_view.get_buffer().set_text(self.slide.notes)
        self.notes_view.get_buffer().connect("changed", self._on_notes_changed)
        notes_scroll.set_child(self.notes_view)
        self.append(notes_scroll)

        self._build_region_section()

    def _build_region_section(self) -> None:
        """Build the focus region section."""
        region_frame = Gtk.Frame(label=gettext("Focus Region"))
        region_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        region_box.set_margin_start(6)
        region_box.set_margin_end(6)
        region_box.set_margin_top(6)
        region_box.set_margin_bottom(6)

        self.use_region = Gtk.CheckButton(label=gettext("Use custom focus region"))
        self.use_region.set_active(self.slide.region is not None)
        self.use_region.connect("toggled", self._on_use_region_toggled)
        region_box.append(self.use_region)

        coords_grid = Gtk.Grid()
        coords_grid.set_row_spacing(6)
        coords_grid.set_column_spacing(6)

        coords_grid.attach(Gtk.Label(label="X:"), 0, 0, 1, 1)
        self.region_x = Gtk.SpinButton.new_with_range(-10000, 10000, 10)
        self.region_x.connect("value-changed", self._on_region_changed)
        coords_grid.attach(self.region_x, 1, 0, 1, 1)

        coords_grid.attach(Gtk.Label(label="Y:"), 2, 0, 1, 1)
        self.region_y = Gtk.SpinButton.new_with_range(-10000, 10000, 10)
        self.region_y.connect("value-changed", self._on_region_changed)
        coords_grid.attach(self.region_y, 3, 0, 1, 1)

        coords_grid.attach(Gtk.Label(label=gettext("Width:")), 0, 1, 1, 1)
        self.region_w = Gtk.SpinButton.new_with_range(10, 10000, 10)
        self.region_w.set_value(500)
        self.region_w.connect("value-changed", self._on_region_changed)
        coords_grid.attach(self.region_w, 1, 1, 1, 1)

        coords_grid.attach(Gtk.Label(label=gettext("Height:")), 2, 1, 1, 1)
        self.region_h = Gtk.SpinButton.new_with_range(10, 10000, 10)
        self.region_h.set_value(400)
        self.region_h.connect("value-changed", self._on_region_changed)
        coords_grid.attach(self.region_h, 3, 1, 1, 1)

        region_box.append(coords_grid)

        self.capture_btn = Gtk.Button(label=gettext("Capture Current View"))
        self.capture_btn.connect("clicked", self._on_capture_view)
        region_box.append(self.capture_btn)

        region_frame.set_child(region_box)
        self.append(region_frame)

        if self.slide.region:
            self.region_x.set_value(self.slide.region.x)
            self.region_y.set_value(self.slide.region.y)
            self.region_w.set_value(self.slide.region.width)
            self.region_h.set_value(self.slide.region.height)

        self._update_region_sensitivity()

    def set_capture_callback(
        self, callback: Callable[[], tuple[float, float, float, float] | None]
    ) -> None:
        """Set callback to capture current view region."""
        self._capture_callback = callback

    def _on_title_changed(self, entry) -> None:
        """Handle title change."""
        self.slide.title = entry.get_text()
        self.on_change()

    def _on_notes_changed(self, buffer) -> None:
        """Handle notes change."""
        start, end = buffer.get_bounds()
        self.slide.notes = buffer.get_text(start, end, True)
        self.on_change()

    def _on_use_region_toggled(self, btn) -> None:
        """Handle region toggle."""
        if btn.get_active():
            self.slide.region = SlideRegion(
                x=self.region_x.get_value(),
                y=self.region_y.get_value(),
                width=self.region_w.get_value(),
                height=self.region_h.get_value(),
            )
        else:
            self.slide.region = None
        self._update_region_sensitivity()
        self.on_change()

    def _on_region_changed(self, spin) -> None:
        """Handle region coordinate change."""
        if self.use_region.get_active():
            self.slide.region = SlideRegion(
                x=self.region_x.get_value(),
                y=self.region_y.get_value(),
                width=self.region_w.get_value(),
                height=self.region_h.get_value(),
            )
            self.on_change()

    def _on_capture_view(self, btn) -> None:
        """Capture the current view region."""
        if self._capture_callback:
            region = self._capture_callback()
            if region:
                x, y, w, h = region
                self.region_x.set_value(x)
                self.region_y.set_value(y)
                self.region_w.set_value(w)
                self.region_h.set_value(h)
                self.use_region.set_active(True)

    def _update_region_sensitivity(self) -> None:
        """Update region controls sensitivity."""
        sensitive = self.use_region.get_active()
        self.region_x.set_sensitive(sensitive)
        self.region_y.set_sensitive(sensitive)
        self.region_w.set_sensitive(sensitive)
        self.region_h.set_sensitive(sensitive)
        self.capture_btn.set_sensitive(sensitive)


class PresentationEditor(Adw.Window):
    """Window for editing a presentation."""

    def __init__(
        self,
        parent_window: Gtk.Window | None,
        presentation: Presentation,
        element_factory,
        on_start: Callable[[Presentation], None],
    ):
        super().__init__()
        if parent_window:
            self.set_transient_for(parent_window)
        self.set_title(gettext("Edit Presentation"))
        self.set_default_size(800, 600)

        self.presentation = presentation
        self.element_factory = element_factory
        self.on_start = on_start
        self._current_view = None
        self._current_slide_editor: SlideEditor | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        """Build the editor UI."""
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        header = Adw.HeaderBar()

        start_btn = Gtk.Button(label=gettext("Start Presentation"))
        start_btn.add_css_class("suggested-action")
        start_btn.connect("clicked", self._on_start_clicked)
        header.pack_end(start_btn)

        main_box.append(header)

        content_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        content_box.set_vexpand(True)

        slides_frame = self._build_slides_panel()
        content_box.append(slides_frame)

        editor_frame = self._build_editor_panel()
        content_box.append(editor_frame)

        main_box.append(content_box)
        self.set_content(main_box)

        self._refresh_slides_list()

    def _build_slides_panel(self) -> Gtk.Frame:
        """Build the slides list panel."""
        slides_frame = Gtk.Frame()
        slides_frame.set_size_request(250, -1)

        slides_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        slides_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        slides_header.set_margin_start(6)
        slides_header.set_margin_end(6)
        slides_header.set_margin_top(6)
        slides_header.set_margin_bottom(6)

        slides_label = Gtk.Label(label=gettext("Slides"))
        slides_label.set_hexpand(True)
        slides_label.set_halign(Gtk.Align.START)
        slides_header.append(slides_label)

        add_btn = Gtk.Button(icon_name="list-add-symbolic")
        add_btn.set_tooltip_text(gettext("Add slide from diagram"))
        add_btn.connect("clicked", self._on_add_slide)
        slides_header.append(add_btn)

        remove_btn = Gtk.Button(icon_name="list-remove-symbolic")
        remove_btn.set_tooltip_text(gettext("Remove selected slide"))
        remove_btn.connect("clicked", self._on_remove_slide)
        slides_header.append(remove_btn)

        slides_box.append(slides_header)

        self.slides_list = Gtk.ListBox()
        self.slides_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.slides_list.connect("row-selected", self._on_slide_selected)

        slides_scroll = Gtk.ScrolledWindow()
        slides_scroll.set_vexpand(True)
        slides_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        slides_scroll.set_child(self.slides_list)
        slides_box.append(slides_scroll)

        move_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        move_box.set_halign(Gtk.Align.CENTER)
        move_box.set_margin_start(6)
        move_box.set_margin_end(6)
        move_box.set_margin_top(6)
        move_box.set_margin_bottom(6)

        move_up_btn = Gtk.Button(icon_name="go-up-symbolic")
        move_up_btn.set_tooltip_text(gettext("Move slide up"))
        move_up_btn.connect("clicked", self._on_move_up)
        move_box.append(move_up_btn)

        move_down_btn = Gtk.Button(icon_name="go-down-symbolic")
        move_down_btn.set_tooltip_text(gettext("Move slide down"))
        move_down_btn.connect("clicked", self._on_move_down)
        move_box.append(move_down_btn)

        slides_box.append(move_box)

        slides_frame.set_child(slides_box)
        return slides_frame

    def _build_editor_panel(self) -> Gtk.Frame:
        """Build the slide editor panel."""
        editor_frame = Gtk.Frame()
        editor_frame.set_hexpand(True)

        self.editor_scroll = Gtk.ScrolledWindow()
        self.editor_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        self.editor_placeholder = Gtk.Label(label=gettext("Select a slide to edit"))
        self.editor_placeholder.set_vexpand(True)
        self.editor_scroll.set_child(self.editor_placeholder)

        editor_frame.set_child(self.editor_scroll)
        return editor_frame

    def set_current_view(self, view) -> None:
        """Set the current diagram view for capturing regions."""
        self._current_view = view

    def _refresh_slides_list(self) -> None:
        """Refresh the slides list."""
        while row := self.slides_list.get_row_at_index(0):
            self.slides_list.remove(row)

        for i, slide in enumerate(self.presentation.slides):
            row = self._create_slide_row(i, slide)
            self.slides_list.append(row)

    def _create_slide_row(self, index: int, slide: Slide) -> Gtk.ListBoxRow:
        """Create a list row for a slide."""
        row = Gtk.ListBoxRow()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        box.set_margin_start(6)
        box.set_margin_end(6)
        box.set_margin_top(6)
        box.set_margin_bottom(6)

        title = slide.title or slide.diagram.name or gettext("Untitled")
        title_label = Gtk.Label(label=f"{index + 1}. {title}")
        title_label.set_halign(Gtk.Align.START)
        title_label.set_ellipsize(3)
        box.append(title_label)

        diagram_label = Gtk.Label(label=slide.diagram.name or "")
        diagram_label.set_halign(Gtk.Align.START)
        diagram_label.add_css_class("dim-label")
        diagram_label.add_css_class("caption")
        box.append(diagram_label)

        row.set_child(box)
        return row

    def _on_slide_selected(self, listbox, row) -> None:
        """Handle slide selection."""
        if row is None:
            self.editor_scroll.set_child(self.editor_placeholder)
            self._current_slide_editor = None
            return

        index = row.get_index()
        if 0 <= index < len(self.presentation.slides):
            slide = self.presentation.slides[index]
            editor = SlideEditor(slide, self._on_slide_changed)
            editor.set_capture_callback(self._capture_current_view)
            self.editor_scroll.set_child(editor)
            self._current_slide_editor = editor

    def _on_slide_changed(self) -> None:
        """Handle slide content change."""
        self._refresh_slides_list()

    @handle_errors(error_title=gettext("Add Slide Error"))
    def _on_add_slide(self, btn) -> None:
        """Show dialog to add a slide."""
        from gaphor.core.modeling import Diagram

        diagrams = list(self.element_factory.select(Diagram))
        if not diagrams:
            show_warning_dialog(
                self,
                gettext("No Diagrams"),
                gettext("There are no diagrams in the model."),
            )
            return

        dialog = Adw.AlertDialog.new(
            gettext("Add Slide"),
            gettext("Select a diagram to add as a slide"),
        )

        for diagram in diagrams:
            name = diagram.name or gettext("Untitled Diagram")
            dialog.add_response(diagram.id, name)

        dialog.set_close_response("cancel")
        dialog.add_response("cancel", gettext("Cancel"))

        def on_response(dialog, response):
            if response != "cancel":
                diagram = self.element_factory.lookup(response)
                if diagram:
                    slide = Slide(diagram=diagram)
                    self.presentation.add_slide(slide)
                    self._refresh_slides_list()

        dialog.connect("response", on_response)
        dialog.present(self)

    def _on_remove_slide(self, btn) -> None:
        """Remove the selected slide."""
        row = self.slides_list.get_selected_row()
        if row:
            index = row.get_index()
            self.presentation.remove_slide(index)
            self._refresh_slides_list()
            self.editor_scroll.set_child(self.editor_placeholder)
            self._current_slide_editor = None

    def _on_move_up(self, btn) -> None:
        """Move the selected slide up."""
        row = self.slides_list.get_selected_row()
        if row:
            index = row.get_index()
            if index > 0:
                self.presentation.move_slide(index, index - 1)
                self._refresh_slides_list()
                self.slides_list.select_row(
                    self.slides_list.get_row_at_index(index - 1)
                )

    def _on_move_down(self, btn) -> None:
        """Move the selected slide down."""
        row = self.slides_list.get_selected_row()
        if row:
            index = row.get_index()
            if index < len(self.presentation.slides) - 1:
                self.presentation.move_slide(index, index + 1)
                self._refresh_slides_list()
                self.slides_list.select_row(
                    self.slides_list.get_row_at_index(index + 1)
                )

    def _on_start_clicked(self, btn) -> None:
        """Start the presentation."""
        if not self.presentation.slides:
            show_warning_dialog(
                self,
                gettext("No Slides"),
                gettext("Add at least one slide before starting the presentation."),
            )
            return

        self.close()
        self.on_start(self.presentation)

    def _capture_current_view(self) -> tuple[float, float, float, float] | None:
        """Capture the current view region."""
        if not self._current_view:
            return None

        try:
            view = self._current_view
            matrix = view.matrix
            width = view.get_width()
            height = view.get_height()

            if width == 0 or height == 0:
                return None

            scale = matrix[0]
            if scale == 0:
                return None

            offset_x = matrix[4]
            offset_y = matrix[5]

            x = -offset_x / scale
            y = -offset_y / scale
            w = width / scale
            h = height / scale

            return (x, y, w, h)

        except Exception as e:
            log.warning(f"Failed to capture view: {e}")
            return None
