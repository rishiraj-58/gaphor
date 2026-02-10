"""Main presentation window and controls."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from gi.repository import Adw, Gdk, GLib, Gtk

from gaphor.i18n import gettext, translated_ui_string
from gaphor.plugins.presentationmode.animator import EasingFunction, ViewAnimator
from gaphor.plugins.presentationmode.drawing import DrawingOverlay, LaserPointerOverlay
from gaphor.plugins.presentationmode.errors import (
    DiagramNotFoundError,
    SlideLoadError,
    handle_errors,
    show_error_dialog,
)
from gaphor.plugins.presentationmode.hotspots import HotspotManager, HotspotOverlay
from gaphor.plugins.presentationmode.model import Presentation, Slide, SlideRegion

if TYPE_CHECKING:
    from gaphas.view import GtkView

    from gaphor.core.modeling import Diagram

log = logging.getLogger(__name__)


def load_presenter_notes_ui() -> Gtk.Builder:
    """Load the presenter notes UI template."""
    builder = Gtk.Builder()
    builder.add_from_string(
        translated_ui_string("gaphor.plugins.presentationmode", "presenternotes.ui")
    )
    return builder


class PresenterNotesWindow(Adw.Window):
    """Window showing presenter notes and slide controls."""

    def __init__(self, parent_window: Gtk.Window):
        super().__init__()
        self.set_transient_for(parent_window)
        self.set_title(gettext("Presenter Notes"))
        self.set_default_size(400, 350)

        self._on_prev: Callable[[], None] | None = None
        self._on_next: Callable[[], None] | None = None
        self._on_goto: Callable[[int], None] | None = None

        self._timer_running = False
        self._timer_seconds = 0
        self._timer_id: int | None = None

        self._build_ui()
        self._start_timer()

    def _build_ui(self) -> None:
        """Build the UI from template."""
        try:
            builder = load_presenter_notes_ui()

            self.slide_label = builder.get_object("slide-label")
            self.title_label = builder.get_object("title-label")
            self.notes_view = builder.get_object("notes-view")
            self.timer_label = builder.get_object("timer-label")

            prev_btn = builder.get_object("prev-btn")
            next_btn = builder.get_object("next-btn")
            timer_reset_btn = builder.get_object("timer-reset-btn")

            if prev_btn:
                prev_btn.connect("clicked", lambda b: self._on_prev and self._on_prev())
            if next_btn:
                next_btn.connect("clicked", lambda b: self._on_next and self._on_next())
            if timer_reset_btn:
                timer_reset_btn.connect("clicked", lambda b: self._reset_timer())

            content = builder.get_object("content-box")
            if content:
                main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
                header = Adw.HeaderBar()
                main_box.append(header)
                main_box.append(content)
                self.set_content(main_box)
            else:
                self._build_fallback_ui()

        except Exception as e:
            log.warning(f"Failed to load UI template, using fallback: {e}")
            self._build_fallback_ui()

    def _build_fallback_ui(self) -> None:
        """Build fallback UI if template loading fails."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        header = Adw.HeaderBar()
        box.append(header)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_start(12)
        content.set_margin_end(12)
        content.set_margin_top(12)
        content.set_margin_bottom(12)

        self.slide_label = Gtk.Label(label="Slide 0 / 0")
        self.slide_label.add_css_class("title-3")
        content.append(self.slide_label)

        self.title_label = Gtk.Label(label="")
        self.title_label.add_css_class("title-2")
        content.append(self.title_label)

        self.timer_label = Gtk.Label(label="00:00")
        self.timer_label.add_css_class("title-1")
        content.append(self.timer_label)

        notes_scroll = Gtk.ScrolledWindow()
        notes_scroll.set_vexpand(True)
        notes_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        self.notes_view = Gtk.TextView()
        self.notes_view.set_editable(False)
        self.notes_view.set_wrap_mode(Gtk.WrapMode.WORD)
        notes_scroll.set_child(self.notes_view)
        content.append(notes_scroll)

        nav_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        nav_box.set_halign(Gtk.Align.CENTER)

        prev_btn = Gtk.Button(label=gettext("Previous"))
        prev_btn.connect("clicked", lambda b: self._on_prev and self._on_prev())
        nav_box.append(prev_btn)

        next_btn = Gtk.Button(label=gettext("Next"))
        next_btn.add_css_class("suggested-action")
        next_btn.connect("clicked", lambda b: self._on_next and self._on_next())
        nav_box.append(next_btn)

        content.append(nav_box)
        box.append(content)
        self.set_content(box)

    def _start_timer(self) -> None:
        """Start the presentation timer."""
        self._timer_running = True
        self._timer_id = GLib.timeout_add(1000, self._update_timer)

    def _reset_timer(self) -> None:
        """Reset the timer to zero."""
        self._timer_seconds = 0
        self._update_timer_display()

    def _update_timer(self) -> bool:
        """Update the timer display."""
        if not self._timer_running:
            return False

        self._timer_seconds += 1
        self._update_timer_display()
        return True

    def _update_timer_display(self) -> None:
        """Update the timer label."""
        minutes = self._timer_seconds // 60
        seconds = self._timer_seconds % 60
        if self.timer_label:
            self.timer_label.set_label(f"{minutes:02d}:{seconds:02d}")

    def set_callbacks(
        self,
        on_prev: Callable[[], None],
        on_next: Callable[[], None],
        on_goto: Callable[[int], None],
    ) -> None:
        """Set navigation callbacks."""
        self._on_prev = on_prev
        self._on_next = on_next
        self._on_goto = on_goto

    def update_slide(self, slide: Slide | None, index: int, total: int) -> None:
        """Update the display for a new slide."""
        if self.slide_label:
            self.slide_label.set_label(f"{gettext('Slide')} {index + 1} / {total}")

        if slide:
            if self.title_label:
                self.title_label.set_label(slide.title or slide.diagram.name or "")
            if self.notes_view:
                self.notes_view.get_buffer().set_text(slide.notes)
        else:
            if self.title_label:
                self.title_label.set_label("")
            if self.notes_view:
                self.notes_view.get_buffer().set_text("")

    def close(self) -> None:
        """Close the window and clean up."""
        self._timer_running = False
        if self._timer_id:
            GLib.source_remove(self._timer_id)
            self._timer_id = None
        super().close()


class PresentationWindow(Adw.Window):
    """Fullscreen presentation window."""

    def __init__(
        self,
        parent_window: Gtk.Window,
        presentation: Presentation,
        element_factory,
        event_manager,
    ):
        super().__init__()
        self.set_transient_for(parent_window)
        self.set_title(gettext("Presentation"))
        self.set_default_size(1024, 768)

        self.parent_window = parent_window
        self.presentation = presentation
        self.element_factory = element_factory
        self.event_manager = event_manager

        self.animator: ViewAnimator | None = None
        self.hotspot_manager = HotspotManager()
        self.notes_window: PresenterNotesWindow | None = None
        self._is_fullscreen = False
        self._hide_controls_timeout: int | None = None
        self._current_view: GtkView | None = None

        self._build_ui()
        self._setup_keyboard()
        self._setup_hotspot_callbacks()

    def _build_ui(self) -> None:
        """Build the presentation UI."""
        overlay = Gtk.Overlay()

        self.view_container = Gtk.Box()
        self.view_container.set_hexpand(True)
        self.view_container.set_vexpand(True)
        overlay.set_child(self.view_container)

        self.drawing_overlay = DrawingOverlay()
        self.drawing_overlay.set_hexpand(True)
        self.drawing_overlay.set_vexpand(True)
        overlay.add_overlay(self.drawing_overlay)

        self.laser_overlay = LaserPointerOverlay()
        self.laser_overlay.set_hexpand(True)
        self.laser_overlay.set_vexpand(True)
        overlay.add_overlay(self.laser_overlay)

        self.hotspot_overlay = HotspotOverlay(self.hotspot_manager)
        self.hotspot_overlay.set_hexpand(True)
        self.hotspot_overlay.set_vexpand(True)
        overlay.add_overlay(self.hotspot_overlay)

        self.controls_revealer = Gtk.Revealer()
        self.controls_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)
        self.controls_revealer.set_valign(Gtk.Align.END)
        self.controls_revealer.set_reveal_child(True)

        controls_box = self._build_controls()
        self.controls_revealer.set_child(controls_box)
        overlay.add_overlay(self.controls_revealer)

        self.drawing_tools_revealer = Gtk.Revealer()
        self.drawing_tools_revealer.set_transition_type(
            Gtk.RevealerTransitionType.SLIDE_DOWN
        )
        self.drawing_tools_revealer.set_valign(Gtk.Align.START)
        self.drawing_tools_revealer.set_halign(Gtk.Align.CENTER)
        self.drawing_tools_revealer.set_margin_top(10)

        drawing_tools = self._build_drawing_tools()
        self.drawing_tools_revealer.set_child(drawing_tools)
        overlay.add_overlay(self.drawing_tools_revealer)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        main_box.append(overlay)
        self.set_content(main_box)

        motion = Gtk.EventControllerMotion.new()
        motion.connect("motion", self._on_mouse_motion)
        self.add_controller(motion)

    def _build_controls(self) -> Gtk.Box:
        """Build the bottom control bar."""
        controls_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        controls_box.add_css_class("toolbar")
        controls_box.add_css_class("osd")
        controls_box.set_halign(Gtk.Align.CENTER)
        controls_box.set_margin_bottom(20)

        prev_btn = Gtk.Button(icon_name="go-previous-symbolic")
        prev_btn.set_tooltip_text(gettext("Previous slide (Left/Page Up)"))
        prev_btn.connect("clicked", lambda b: self.previous_slide())
        controls_box.append(prev_btn)

        self.slide_indicator = Gtk.Label(label="0 / 0")
        controls_box.append(self.slide_indicator)

        next_btn = Gtk.Button(icon_name="go-next-symbolic")
        next_btn.set_tooltip_text(gettext("Next slide (Right/Page Down/Space)"))
        next_btn.connect("clicked", lambda b: self.next_slide())
        controls_box.append(next_btn)

        controls_box.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        self.drawing_btn = Gtk.ToggleButton(icon_name="document-edit-symbolic")
        self.drawing_btn.set_tooltip_text(gettext("Drawing tools (D)"))
        self.drawing_btn.connect("toggled", self._on_drawing_toggled)
        controls_box.append(self.drawing_btn)

        self.laser_btn = Gtk.ToggleButton(icon_name="starred-symbolic")
        self.laser_btn.set_tooltip_text(gettext("Laser pointer (L)"))
        self.laser_btn.connect("toggled", self._on_laser_toggled)
        controls_box.append(self.laser_btn)

        clear_btn = Gtk.Button(icon_name="edit-clear-symbolic")
        clear_btn.set_tooltip_text(gettext("Clear drawings (C)"))
        clear_btn.connect("clicked", lambda b: self.drawing_overlay.clear_annotations())
        controls_box.append(clear_btn)

        controls_box.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        self.hotspot_btn = Gtk.ToggleButton(icon_name="find-location-symbolic")
        self.hotspot_btn.set_tooltip_text(gettext("Show hotspots (H)"))
        self.hotspot_btn.connect("toggled", self._on_hotspot_toggled)
        controls_box.append(self.hotspot_btn)

        notes_btn = Gtk.Button(icon_name="accessories-text-editor-symbolic")
        notes_btn.set_tooltip_text(gettext("Presenter notes (N)"))
        notes_btn.connect("clicked", lambda b: self.toggle_notes_window())
        controls_box.append(notes_btn)

        controls_box.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        fullscreen_btn = Gtk.Button(icon_name="view-fullscreen-symbolic")
        fullscreen_btn.set_tooltip_text(gettext("Toggle fullscreen (F/F11)"))
        fullscreen_btn.connect("clicked", lambda b: self.toggle_fullscreen())
        controls_box.append(fullscreen_btn)

        exit_btn = Gtk.Button(icon_name="window-close-symbolic")
        exit_btn.set_tooltip_text(gettext("Exit presentation (Escape)"))
        exit_btn.connect("clicked", lambda b: self.close())
        controls_box.append(exit_btn)

        return controls_box

    def _build_drawing_tools(self) -> Gtk.Box:
        """Build the drawing tools toolbar."""
        drawing_tools_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=3)
        drawing_tools_box.add_css_class("toolbar")
        drawing_tools_box.add_css_class("osd")

        tool_group = None
        tools = [
            ("pen", "edit-symbolic", gettext("Pen")),
            ("highlighter", "format-text-highlight-symbolic", gettext("Highlighter")),
            ("arrow", "go-next-symbolic", gettext("Arrow")),
            ("line", "object-flip-horizontal-symbolic", gettext("Line")),
            ("rectangle", "view-fullscreen-symbolic", gettext("Rectangle")),
            ("ellipse", "media-record-symbolic", gettext("Ellipse")),
        ]

        for tool_id, icon, tooltip in tools:
            btn = Gtk.ToggleButton(icon_name=icon)
            btn.set_tooltip_text(tooltip)
            if tool_group:
                btn.set_group(tool_group)
            else:
                tool_group = btn
                btn.set_active(True)
            btn.connect("toggled", self._on_tool_selected, tool_id)
            drawing_tools_box.append(btn)

        drawing_tools_box.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        colors = [
            ("red", "#FF0000"),
            ("blue", "#0000FF"),
            ("green", "#009900"),
            ("yellow", "#FFFF00"),
            ("black", "#000000"),
        ]

        color_group = None
        for color_name, color_hex in colors:
            btn = Gtk.ToggleButton()
            btn.set_size_request(24, 24)
            provider = Gtk.CssProvider()
            provider.load_from_string(
                f"button {{ background-color: {color_hex}; min-width: 20px; min-height: 20px; }}"
            )
            btn.get_style_context().add_provider(
                provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
            if color_group:
                btn.set_group(color_group)
            else:
                color_group = btn
                btn.set_active(True)
            btn.connect("toggled", self._on_color_selected, color_name)
            drawing_tools_box.append(btn)

        drawing_tools_box.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        undo_btn = Gtk.Button(icon_name="edit-undo-symbolic")
        undo_btn.set_tooltip_text(gettext("Undo (Ctrl+Z)"))
        undo_btn.connect("clicked", lambda b: self.drawing_overlay.undo_last())
        drawing_tools_box.append(undo_btn)

        return drawing_tools_box

    def _setup_keyboard(self) -> None:
        """Set up keyboard event handling."""
        key_ctrl = Gtk.EventControllerKey.new()
        key_ctrl.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_ctrl)

    def _setup_hotspot_callbacks(self) -> None:
        """Set up callbacks for hotspot navigation."""
        self.hotspot_manager.set_navigate_callback(self._navigate_to_diagram)
        self.hotspot_manager.set_reveal_callback(self._reveal_elements)

    def _on_key_pressed(self, controller, keyval, keycode, state) -> bool:
        """Handle keyboard input."""
        ctrl_pressed = state & Gdk.ModifierType.CONTROL_MASK

        if keyval in (Gdk.KEY_Right, Gdk.KEY_space, Gdk.KEY_Page_Down):
            self.next_slide()
            return True
        elif keyval in (Gdk.KEY_Left, Gdk.KEY_Page_Up):
            self.previous_slide()
            return True
        elif keyval == Gdk.KEY_Home:
            self.go_to_slide(0)
            return True
        elif keyval == Gdk.KEY_End:
            self.go_to_slide(len(self.presentation.slides) - 1)
            return True
        elif keyval == Gdk.KEY_Escape:
            if self._is_fullscreen:
                self.unfullscreen()
                self._is_fullscreen = False
            else:
                self.close()
            return True
        elif keyval in (Gdk.KEY_f, Gdk.KEY_F11):
            self.toggle_fullscreen()
            return True
        elif keyval == Gdk.KEY_d:
            self.drawing_btn.set_active(not self.drawing_btn.get_active())
            return True
        elif keyval == Gdk.KEY_l:
            self.laser_btn.set_active(not self.laser_btn.get_active())
            return True
        elif keyval == Gdk.KEY_c:
            self.drawing_overlay.clear_annotations()
            return True
        elif keyval == Gdk.KEY_h:
            self.hotspot_btn.set_active(not self.hotspot_btn.get_active())
            return True
        elif keyval == Gdk.KEY_n:
            self.toggle_notes_window()
            return True
        elif keyval == Gdk.KEY_z and ctrl_pressed:
            self.drawing_overlay.undo_last()
            return True
        elif keyval == Gdk.KEY_b:
            self._blank_screen()
            return True
        elif keyval >= Gdk.KEY_1 and keyval <= Gdk.KEY_9:
            slide_num = keyval - Gdk.KEY_1
            self.go_to_slide(slide_num)
            return True

        return False

    def _on_mouse_motion(self, controller, x, y) -> None:
        """Show controls on mouse movement."""
        self.controls_revealer.set_reveal_child(True)

        if self._hide_controls_timeout:
            GLib.source_remove(self._hide_controls_timeout)

        def hide_controls():
            self.controls_revealer.set_reveal_child(False)
            self._hide_controls_timeout = None
            return False

        self._hide_controls_timeout = GLib.timeout_add(3000, hide_controls)

    def _on_drawing_toggled(self, btn) -> None:
        """Handle drawing mode toggle."""
        active = btn.get_active()
        self.drawing_overlay.state.enabled = active
        self.drawing_tools_revealer.set_reveal_child(active)

        if active:
            self.laser_btn.set_active(False)

    def _on_laser_toggled(self, btn) -> None:
        """Handle laser pointer toggle."""
        active = btn.get_active()
        self.laser_overlay.set_enabled(active)

        if active:
            self.drawing_btn.set_active(False)

    def _on_hotspot_toggled(self, btn) -> None:
        """Handle hotspot visibility toggle."""
        self.hotspot_overlay.toggle_hotspot_visibility()

    def _on_tool_selected(self, btn, tool_id) -> None:
        """Handle drawing tool selection."""
        if btn.get_active():
            self.drawing_overlay.set_tool(tool_id)

    def _on_color_selected(self, btn, color_name) -> None:
        """Handle color selection."""
        if btn.get_active():
            self.drawing_overlay.set_color(color_name)
            self.laser_overlay.set_color(color_name)

    @handle_errors(error_title=gettext("Slide Error"))
    def show_slide(self, slide: Slide) -> None:
        """Display a slide."""
        from gaphor.diagram.painter import ItemPainter
        from gaphor.diagram.selection import Selection
        from gaphor.ui.diagramview import DiagramView

        if not slide.diagram:
            raise SlideLoadError(
                gettext("Slide has no diagram"),
                gettext("The slide references a diagram that no longer exists."),
            )

        for child in list(self.view_container):
            self.view_container.remove(child)

        try:
            view = DiagramView(slide.diagram)
            view.set_hexpand(True)
            view.set_vexpand(True)
            self.view_container.append(view)
            self._current_view = view

            self.animator = ViewAnimator(view)

            if slide.region:
                GLib.idle_add(
                    lambda: self.animator.animate_to_region(
                        slide.region, 600, EasingFunction.EASE_IN_OUT_CUBIC
                    )
                )
            else:
                GLib.idle_add(
                    lambda: self.animator.fit_to_diagram(
                        600, EasingFunction.EASE_IN_OUT_CUBIC
                    )
                )

            self.hotspot_overlay.set_view_matrix(view.matrix)
            self._update_indicator()

            self.drawing_overlay.clear_annotations()
            self.hotspot_manager.reset_reveals()

            if self.notes_window:
                self.notes_window.update_slide(
                    slide,
                    self.presentation.current_index,
                    len(self.presentation.slides),
                )

        except Exception as e:
            raise SlideLoadError(
                gettext("Failed to load slide"),
                str(e),
            )

    def next_slide(self) -> None:
        """Go to the next slide."""
        slide = self.presentation.next_slide()
        if slide:
            self.show_slide(slide)

    def previous_slide(self) -> None:
        """Go to the previous slide."""
        slide = self.presentation.previous_slide()
        if slide:
            self.show_slide(slide)

    def go_to_slide(self, index: int) -> None:
        """Go to a specific slide."""
        slide = self.presentation.go_to_slide(index)
        if slide:
            self.show_slide(slide)

    def toggle_fullscreen(self) -> None:
        """Toggle fullscreen mode."""
        if self._is_fullscreen:
            self.unfullscreen()
        else:
            self.fullscreen()
        self._is_fullscreen = not self._is_fullscreen

    def toggle_notes_window(self) -> None:
        """Toggle the presenter notes window."""
        if self.notes_window:
            self.notes_window.close()
            self.notes_window = None
        else:
            self.notes_window = PresenterNotesWindow(self)
            self.notes_window.set_callbacks(
                self.previous_slide, self.next_slide, self.go_to_slide
            )
            self.notes_window.update_slide(
                self.presentation.get_current_slide(),
                self.presentation.current_index,
                len(self.presentation.slides),
            )
            self.notes_window.present()

    def _update_indicator(self) -> None:
        """Update the slide indicator."""
        current = self.presentation.current_index + 1
        total = len(self.presentation.slides)
        self.slide_indicator.set_label(f"{current} / {total}")

    def _blank_screen(self) -> None:
        """Toggle blank screen (for Q&A, etc.)."""
        pass

    @handle_errors(error_title=gettext("Navigation Error"))
    def _navigate_to_diagram(self, diagram_id: str) -> None:
        """Navigate to a linked diagram."""
        diagram = self.element_factory.lookup(diagram_id)
        if not diagram:
            raise DiagramNotFoundError(
                gettext("Diagram not found"),
                gettext("The linked diagram could not be found in the model."),
            )

        for i, slide in enumerate(self.presentation.slides):
            if slide.diagram.id == diagram_id:
                self.go_to_slide(i)
                return

        new_slide = Slide(diagram=diagram)
        self.presentation.add_slide(new_slide)
        self.go_to_slide(len(self.presentation.slides) - 1)

    def _reveal_elements(self, element_ids: list[str]) -> None:
        """Reveal hidden elements on the current slide."""
        pass

    def start(self) -> None:
        """Start the presentation."""
        if self.presentation.slides:
            slide = self.presentation.get_current_slide()
            if slide:
                self.show_slide(slide)
        self.present()

    def close(self) -> None:
        """Close the presentation window."""
        if self._hide_controls_timeout:
            GLib.source_remove(self._hide_controls_timeout)
            self._hide_controls_timeout = None

        if self.notes_window:
            self.notes_window.close()
            self.notes_window = None

        if self.animator:
            self.animator.stop_animation()

        super().close()
