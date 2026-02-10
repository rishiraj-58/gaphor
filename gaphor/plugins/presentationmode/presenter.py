"""Main presentation window and controls."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from gi.repository import Adw, Gdk, GLib, Gtk

from gaphor.i18n import gettext
from gaphor.plugins.presentationmode.animator import ViewAnimator
from gaphor.plugins.presentationmode.drawing import DrawingOverlay
from gaphor.plugins.presentationmode.hotspots import HotspotManager, HotspotOverlay
from gaphor.plugins.presentationmode.model import Presentation, Slide, SlideRegion

if TYPE_CHECKING:
    from gaphas.view import GtkView

    from gaphor.core.modeling import Diagram


class PresenterNotesWindow(Adw.Window):
    """Window showing presenter notes and slide controls."""

    def __init__(self, parent_window):
        super().__init__()
        self.set_transient_for(parent_window)
        self.set_title(gettext("Presenter Notes"))
        self.set_default_size(400, 300)

        self._on_prev: Callable[[], None] | None = None
        self._on_next: Callable[[], None] | None = None
        self._on_goto: Callable[[int], None] | None = None

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

    def set_callbacks(
        self,
        on_prev: Callable[[], None],
        on_next: Callable[[], None],
        on_goto: Callable[[int], None],
    ) -> None:
        self._on_prev = on_prev
        self._on_next = on_next
        self._on_goto = on_goto

    def update_slide(self, slide: Slide | None, index: int, total: int) -> None:
        self.slide_label.set_label(f"Slide {index + 1} / {total}")

        if slide:
            self.title_label.set_label(slide.title or slide.diagram.name or "")
            self.notes_view.get_buffer().set_text(slide.notes)
        else:
            self.title_label.set_label("")
            self.notes_view.get_buffer().set_text("")


class PresentationWindow(Adw.Window):
    """Fullscreen presentation window."""

    def __init__(
        self,
        parent_window,
        presentation: Presentation,
        element_factory,
        event_manager,
    ):
        super().__init__()
        self.set_transient_for(parent_window)
        self.set_title(gettext("Presentation"))
        self.set_default_size(1024, 768)

        self.presentation = presentation
        self.element_factory = element_factory
        self.event_manager = event_manager

        self.animator: ViewAnimator | None = None
        self.hotspot_manager = HotspotManager()
        self.notes_window: PresenterNotesWindow | None = None
        self._is_fullscreen = False

        self._build_ui()
        self._setup_keyboard()
        self._setup_hotspot_callbacks()

    def _build_ui(self) -> None:
        overlay = Gtk.Overlay()

        self.view_container = Gtk.Box()
        self.view_container.set_hexpand(True)
        self.view_container.set_vexpand(True)
        overlay.set_child(self.view_container)

        self.drawing_overlay = DrawingOverlay()
        self.drawing_overlay.set_hexpand(True)
        self.drawing_overlay.set_vexpand(True)
        overlay.add_overlay(self.drawing_overlay)

        self.hotspot_overlay = HotspotOverlay(self.hotspot_manager)
        self.hotspot_overlay.set_hexpand(True)
        self.hotspot_overlay.set_vexpand(True)
        overlay.add_overlay(self.hotspot_overlay)

        self.controls_revealer = Gtk.Revealer()
        self.controls_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)
        self.controls_revealer.set_valign(Gtk.Align.END)
        self.controls_revealer.set_reveal_child(True)

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

        sep1 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        controls_box.append(sep1)

        drawing_btn = Gtk.ToggleButton(icon_name="document-edit-symbolic")
        drawing_btn.set_tooltip_text(gettext("Drawing tools (D)"))
        drawing_btn.connect("toggled", self._on_drawing_toggled)
        controls_box.append(drawing_btn)
        self.drawing_btn = drawing_btn

        clear_btn = Gtk.Button(icon_name="edit-clear-symbolic")
        clear_btn.set_tooltip_text(gettext("Clear drawings (C)"))
        clear_btn.connect("clicked", lambda b: self.drawing_overlay.clear_annotations())
        controls_box.append(clear_btn)

        sep2 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        controls_box.append(sep2)

        hotspot_btn = Gtk.ToggleButton(icon_name="find-location-symbolic")
        hotspot_btn.set_tooltip_text(gettext("Show hotspots (H)"))
        hotspot_btn.connect("toggled", self._on_hotspot_toggled)
        controls_box.append(hotspot_btn)
        self.hotspot_btn = hotspot_btn

        notes_btn = Gtk.Button(icon_name="accessories-text-editor-symbolic")
        notes_btn.set_tooltip_text(gettext("Presenter notes (N)"))
        notes_btn.connect("clicked", lambda b: self.toggle_notes_window())
        controls_box.append(notes_btn)

        sep3 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        controls_box.append(sep3)

        fullscreen_btn = Gtk.Button(icon_name="view-fullscreen-symbolic")
        fullscreen_btn.set_tooltip_text(gettext("Toggle fullscreen (F/F11)"))
        fullscreen_btn.connect("clicked", lambda b: self.toggle_fullscreen())
        controls_box.append(fullscreen_btn)

        exit_btn = Gtk.Button(icon_name="window-close-symbolic")
        exit_btn.set_tooltip_text(gettext("Exit presentation (Escape)"))
        exit_btn.connect("clicked", lambda b: self.close())
        controls_box.append(exit_btn)

        self.controls_revealer.set_child(controls_box)
        overlay.add_overlay(self.controls_revealer)

        self.drawing_tools_revealer = Gtk.Revealer()
        self.drawing_tools_revealer.set_transition_type(
            Gtk.RevealerTransitionType.SLIDE_DOWN
        )
        self.drawing_tools_revealer.set_valign(Gtk.Align.START)
        self.drawing_tools_revealer.set_halign(Gtk.Align.CENTER)
        self.drawing_tools_revealer.set_margin_top(10)

        drawing_tools_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=3)
        drawing_tools_box.add_css_class("toolbar")
        drawing_tools_box.add_css_class("osd")

        tool_group = None
        tools = [
            ("pen", "edit-symbolic", gettext("Pen")),
            ("highlighter", "format-text-highlight-symbolic", gettext("Highlighter")),
            ("arrow", "go-next-symbolic", gettext("Arrow")),
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

        sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        drawing_tools_box.append(sep)

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

        undo_btn = Gtk.Button(icon_name="edit-undo-symbolic")
        undo_btn.set_tooltip_text(gettext("Undo (Ctrl+Z)"))
        undo_btn.connect("clicked", lambda b: self.drawing_overlay.undo_last())
        drawing_tools_box.append(undo_btn)

        self.drawing_tools_revealer.set_child(drawing_tools_box)
        overlay.add_overlay(self.drawing_tools_revealer)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        main_box.append(overlay)
        self.set_content(main_box)

        motion = Gtk.EventControllerMotion.new()
        motion.connect("motion", self._on_mouse_motion)
        self.add_controller(motion)
        self._hide_controls_timeout = None

    def _setup_keyboard(self) -> None:
        key_ctrl = Gtk.EventControllerKey.new()
        key_ctrl.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_ctrl)

    def _setup_hotspot_callbacks(self) -> None:
        self.hotspot_manager.set_navigate_callback(self._navigate_to_diagram)
        self.hotspot_manager.set_reveal_callback(self._reveal_elements)

    def _on_key_pressed(self, controller, keyval, keycode, state) -> bool:
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
        elif keyval in (Gdk.KEY_Escape,):
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
        elif keyval >= Gdk.KEY_1 and keyval <= Gdk.KEY_9:
            slide_num = keyval - Gdk.KEY_1
            self.go_to_slide(slide_num)
            return True

        return False

    def _on_mouse_motion(self, controller, x, y) -> None:
        self.controls_revealer.set_reveal_child(True)

        if self._hide_controls_timeout:
            GLib.source_remove(self._hide_controls_timeout)

        def hide_controls():
            self.controls_revealer.set_reveal_child(False)
            self._hide_controls_timeout = None
            return False

        self._hide_controls_timeout = GLib.timeout_add(3000, hide_controls)

    def _on_drawing_toggled(self, btn) -> None:
        active = btn.get_active()
        self.drawing_overlay.state.enabled = active
        self.drawing_tools_revealer.set_reveal_child(active)

    def _on_hotspot_toggled(self, btn) -> None:
        self.hotspot_overlay.toggle_hotspot_visibility()

    def _on_tool_selected(self, btn, tool_id) -> None:
        if btn.get_active():
            self.drawing_overlay.set_tool(tool_id)

    def _on_color_selected(self, btn, color_name) -> None:
        if btn.get_active():
            self.drawing_overlay.set_color(color_name)

    def show_slide(self, slide: Slide) -> None:
        """Display a slide."""
        from gaphor.diagram.painter import ItemPainter
        from gaphor.diagram.selection import Selection
        from gaphor.ui.diagramview import DiagramView

        for child in list(self.view_container):
            self.view_container.remove(child)

        view = DiagramView(slide.diagram)
        view.set_hexpand(True)
        view.set_vexpand(True)
        self.view_container.append(view)

        self.animator = ViewAnimator(view)

        if slide.region:
            GLib.idle_add(lambda: self.animator.animate_to_region(slide.region, 600))
        else:
            GLib.idle_add(lambda: self.animator.fit_to_diagram(600))

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

    def _navigate_to_diagram(self, diagram_id: str) -> None:
        """Navigate to a linked diagram."""
        diagram = self.element_factory.lookup(diagram_id)
        if diagram:
            for i, slide in enumerate(self.presentation.slides):
                if slide.diagram.id == diagram_id:
                    self.go_to_slide(i)
                    return

            from gaphor.plugins.presentationmode.model import Slide

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
