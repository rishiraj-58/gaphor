"""Presentation window for full-screen slideshow mode.

This module provides the main presentation window that displays slides
with animations, hotspots, and drawing tools.
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING

from gi.repository import Gdk, GLib, Gtk, Pango

from gaphor.core.modeling import Diagram, StyleSheet
from gaphor.core.modeling.diagram import StyledDiagram
from gaphor.diagram.painter import ItemPainter
from gaphor.plugins.presentation.animator import (
    EasingFunction,
    LaserPointerAnimator,
    ViewAnimator,
    ViewState,
)
from gaphor.plugins.presentation.drawing import (
    DrawingToolHandler,
    draw_laser_pointer,
)
from gaphor.plugins.presentation.model import (
    DrawingToolType,
    Hotspot,
    HotspotAction,
    Presentation,
    Slide,
    ViewRegion,
)

if TYPE_CHECKING:
    from cairo import Context as CairoContext

    from gaphor.core.modeling import ElementFactory

log = logging.getLogger(__name__)


class PresentationWindow:
    """Window for displaying presentations in slideshow mode."""

    def __init__(
        self,
        presentation: Presentation,
        element_factory: ElementFactory,
        parent_window: Gtk.Window | None = None,
    ):
        self.presentation = presentation
        self.element_factory = element_factory
        self.parent_window = parent_window

        self._window: Gtk.Window | None = None
        self._drawing_area: Gtk.DrawingArea | None = None
        self._notes_revealer: Gtk.Revealer | None = None
        self._notes_label: Gtk.Label | None = None
        self._toolbar_revealer: Gtk.Revealer | None = None
        self._slide_label: Gtk.Label | None = None
        self._progress_bar: Gtk.ProgressBar | None = None

        self._current_slide_index: int = 0
        self._current_view_state: ViewState = ViewState(0, 0, 1.0)

        self._animator = ViewAnimator(
            self._on_animation_update,
            self._on_animation_complete,
        )
        self._laser_animator = LaserPointerAnimator(self._on_laser_update)
        self._laser_points: list[tuple[float, float, float]] = []

        self._drawing_handler = DrawingToolHandler()
        self._is_drawing_mode = False
        self._show_notes = False
        self._show_toolbar = True
        self._show_hotspots = True

        self._cached_diagram: Diagram | None = None
        self._style_sheet: StyleSheet | None = None

    @property
    def current_slide(self) -> Slide | None:
        """Get the current slide."""
        if 0 <= self._current_slide_index < len(self.presentation.slides):
            return self.presentation.slides[self._current_slide_index]
        return None

    def open(self) -> None:
        """Open the presentation window."""
        self._window = Gtk.Window()
        self._window.set_title(self.presentation.title)
        self._window.set_default_size(1280, 720)

        if self.parent_window:
            self._window.set_transient_for(self.parent_window)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._window.set_child(main_box)

        self._toolbar_revealer = Gtk.Revealer()
        self._toolbar_revealer.set_transition_type(
            Gtk.RevealerTransitionType.SLIDE_DOWN
        )
        self._toolbar_revealer.set_reveal_child(True)
        self._toolbar_revealer.set_child(self._create_toolbar())
        main_box.append(self._toolbar_revealer)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content_box.set_vexpand(True)
        main_box.append(content_box)

        overlay = Gtk.Overlay()
        content_box.append(overlay)
        overlay.set_vexpand(True)

        self._drawing_area = Gtk.DrawingArea()
        self._drawing_area.set_draw_func(self._on_draw)
        self._drawing_area.set_hexpand(True)
        self._drawing_area.set_vexpand(True)
        overlay.set_child(self._drawing_area)

        self._notes_revealer = Gtk.Revealer()
        self._notes_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)
        self._notes_revealer.set_valign(Gtk.Align.END)
        self._notes_revealer.set_halign(Gtk.Align.FILL)
        overlay.add_overlay(self._notes_revealer)

        notes_frame = Gtk.Frame()
        notes_frame.add_css_class("presentation-notes")
        self._notes_revealer.set_child(notes_frame)

        notes_scroll = Gtk.ScrolledWindow()
        notes_scroll.set_max_content_height(150)
        notes_scroll.set_propagate_natural_height(True)
        notes_frame.set_child(notes_scroll)

        self._notes_label = Gtk.Label()
        self._notes_label.set_wrap(True)
        self._notes_label.set_xalign(0)
        self._notes_label.set_margin_start(12)
        self._notes_label.set_margin_end(12)
        self._notes_label.set_margin_top(8)
        self._notes_label.set_margin_bottom(8)
        notes_scroll.set_child(self._notes_label)

        self._progress_bar = Gtk.ProgressBar()
        self._progress_bar.add_css_class("presentation-progress")
        main_box.append(self._progress_bar)

        self._setup_event_controllers()
        self._apply_css()

        self._window.connect("close-request", self._on_close_request)

        if self.presentation.slides:
            self._go_to_slide(0)

        self._window.present()

    def _create_toolbar(self) -> Gtk.Box:
        """Create the presentation toolbar."""
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        toolbar.set_margin_start(6)
        toolbar.set_margin_end(6)
        toolbar.set_margin_top(6)
        toolbar.set_margin_bottom(6)

        prev_btn = Gtk.Button.new_from_icon_name("go-previous-symbolic")
        prev_btn.set_tooltip_text("Previous slide (←, PageUp)")
        prev_btn.connect("clicked", lambda b: self.previous_slide())
        toolbar.append(prev_btn)

        self._slide_label = Gtk.Label()
        self._slide_label.set_hexpand(False)
        self._slide_label.set_width_chars(10)
        toolbar.append(self._slide_label)

        next_btn = Gtk.Button.new_from_icon_name("go-next-symbolic")
        next_btn.set_tooltip_text("Next slide (→, PageDown, Space)")
        next_btn.connect("clicked", lambda b: self.next_slide())
        toolbar.append(next_btn)

        toolbar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        drawing_tools = [
            ("edit-symbolic", DrawingToolType.PEN, "Pen (P)"),
            ("format-text-highlight-symbolic", DrawingToolType.HIGHLIGHTER, "Highlighter (H)"),
            ("media-playback-stop-symbolic", DrawingToolType.LASER_POINTER, "Laser pointer (L)"),
            ("go-up-symbolic", DrawingToolType.ARROW, "Arrow (A)"),
            ("view-fullscreen-symbolic", DrawingToolType.RECTANGLE, "Rectangle (R)"),
            ("media-record-symbolic", DrawingToolType.ELLIPSE, "Ellipse (E)"),
            ("edit-clear-symbolic", DrawingToolType.ERASER, "Eraser (X)"),
        ]

        for icon_name, tool, tooltip in drawing_tools:
            btn = Gtk.ToggleButton()
            btn.set_child(Gtk.Image.new_from_icon_name(icon_name))
            btn.set_tooltip_text(tooltip)
            btn.connect("toggled", self._on_tool_toggled, tool)
            btn.tool_type = tool
            toolbar.append(btn)

        toolbar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        color_box = Gtk.Box(spacing=2)
        colors = ["red", "green", "blue", "yellow", "black"]
        for color_name in colors:
            btn = Gtk.Button()
            btn.set_size_request(24, 24)
            btn.add_css_class(f"color-{color_name}")
            btn.connect("clicked", self._on_color_selected, color_name)
            color_box.append(btn)
        toolbar.append(color_box)

        toolbar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        clear_btn = Gtk.Button.new_from_icon_name("edit-clear-all-symbolic")
        clear_btn.set_tooltip_text("Clear drawings (C)")
        clear_btn.connect("clicked", lambda b: self._clear_drawings())
        toolbar.append(clear_btn)

        undo_btn = Gtk.Button.new_from_icon_name("edit-undo-symbolic")
        undo_btn.set_tooltip_text("Undo (Ctrl+Z)")
        undo_btn.connect("clicked", lambda b: self._undo_drawing())
        toolbar.append(undo_btn)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        toolbar.append(spacer)

        notes_btn = Gtk.ToggleButton()
        notes_btn.set_child(Gtk.Image.new_from_icon_name("accessories-text-editor-symbolic"))
        notes_btn.set_tooltip_text("Toggle notes (N)")
        notes_btn.connect("toggled", self._on_notes_toggled)
        toolbar.append(notes_btn)

        fullscreen_btn = Gtk.Button.new_from_icon_name("view-fullscreen-symbolic")
        fullscreen_btn.set_tooltip_text("Toggle fullscreen (F)")
        fullscreen_btn.connect("clicked", lambda b: self._toggle_fullscreen())
        toolbar.append(fullscreen_btn)

        close_btn = Gtk.Button.new_from_icon_name("window-close-symbolic")
        close_btn.set_tooltip_text("Exit presentation (Escape)")
        close_btn.connect("clicked", lambda b: self.close())
        toolbar.append(close_btn)

        return toolbar

    def _setup_event_controllers(self) -> None:
        """Set up event controllers for keyboard and mouse input."""
        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_key_pressed)
        self._window.add_controller(key_controller)

        click_controller = Gtk.GestureClick()
        click_controller.connect("pressed", self._on_click_pressed)
        click_controller.connect("released", self._on_click_released)
        self._drawing_area.add_controller(click_controller)

        motion_controller = Gtk.EventControllerMotion()
        motion_controller.connect("motion", self._on_motion)
        self._drawing_area.add_controller(motion_controller)

        scroll_controller = Gtk.EventControllerScroll()
        scroll_controller.set_flags(Gtk.EventControllerScrollFlags.VERTICAL)
        scroll_controller.connect("scroll", self._on_scroll)
        self._drawing_area.add_controller(scroll_controller)

    def _apply_css(self) -> None:
        """Apply CSS styling to the presentation window."""
        css_provider = Gtk.CssProvider()
        css_provider.load_from_string("""
            .presentation-notes {
                background-color: rgba(0, 0, 0, 0.85);
                color: white;
                border-radius: 8px 8px 0 0;
                margin: 0 20px;
            }
            .presentation-notes label {
                color: white;
                font-size: 14px;
            }
            .presentation-progress {
                min-height: 4px;
            }
            .color-red { background-color: #ff0000; }
            .color-green { background-color: #00cc00; }
            .color-blue { background-color: #0066ff; }
            .color-yellow { background-color: #ffee00; }
            .color-black { background-color: #000000; }
        """)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def _on_draw(
        self, area: Gtk.DrawingArea, cr: CairoContext, width: int, height: int
    ) -> None:
        """Draw the current slide content."""
        cr.set_source_rgb(0.2, 0.2, 0.2)
        cr.paint()

        slide = self.current_slide
        if not slide:
            self._draw_no_slides_message(cr, width, height)
            return

        diagram = self._get_diagram(slide.diagram_id)
        if not diagram:
            self._draw_no_diagram_message(cr, width, height)
            return

        self._draw_diagram(cr, diagram, width, height, slide)
        self._draw_hotspots(cr, slide)
        self._draw_annotations(cr)
        self._draw_laser_pointer(cr)

    def _draw_no_slides_message(
        self, cr: CairoContext, width: int, height: int
    ) -> None:
        """Draw a message when there are no slides."""
        cr.set_source_rgb(0.8, 0.8, 0.8)
        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(24)
        text = "No slides in presentation"
        extents = cr.text_extents(text)
        cr.move_to(
            (width - extents.width) / 2,
            (height + extents.height) / 2,
        )
        cr.show_text(text)

    def _draw_no_diagram_message(
        self, cr: CairoContext, width: int, height: int
    ) -> None:
        """Draw a message when the diagram is not found."""
        cr.set_source_rgb(0.8, 0.8, 0.8)
        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(24)
        text = "Diagram not found"
        extents = cr.text_extents(text)
        cr.move_to(
            (width - extents.width) / 2,
            (height + extents.height) / 2,
        )
        cr.show_text(text)

    def _draw_diagram(
        self,
        cr: CairoContext,
        diagram: Diagram,
        width: int,
        height: int,
        slide: Slide,
    ) -> None:
        """Draw the diagram content for the current slide."""
        style_sheet = self.element_factory.style_sheet or StyleSheet()
        painter = ItemPainter(compute_style=style_sheet.compute_style)

        region = slide.region
        view_state = self._current_view_state

        scale_x = width / region.width if region.width > 0 else 1
        scale_y = height / region.height if region.height > 0 else 1
        scale = min(scale_x, scale_y) * view_state.zoom

        offset_x = (width - region.width * scale) / 2
        offset_y = (height - region.height * scale) / 2

        cr.save()
        cr.translate(offset_x, offset_y)
        cr.scale(scale, scale)
        cr.translate(-region.x - view_state.x, -region.y - view_state.y)

        bg_color = style_sheet.compute_style(StyledDiagram(diagram)).get(
            "background-color", (1.0, 1.0, 1.0, 1.0)
        )
        if bg_color and bg_color[3]:
            items_bounds = self._get_items_bounds(diagram)
            if items_bounds:
                cr.rectangle(*items_bounds)
                cr.set_source_rgba(*bg_color)
                cr.fill()

        items = list(diagram.get_all_items())
        painter.paint(items, cr)

        cr.restore()

    def _get_items_bounds(self, diagram: Diagram) -> tuple[float, float, float, float] | None:
        """Get the bounding box of all items in the diagram."""
        items = list(diagram.get_all_items())
        if not items:
            return None

        min_x = min_y = float("inf")
        max_x = max_y = float("-inf")

        for item in items:
            try:
                x, y = item.matrix[4], item.matrix[5]
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x + 200)
                max_y = max(max_y, y + 100)
            except Exception:
                pass

        if min_x == float("inf"):
            return None

        padding = 50
        return (
            min_x - padding,
            min_y - padding,
            max_x - min_x + 2 * padding,
            max_y - min_y + 2 * padding,
        )

    def _draw_hotspots(self, cr: CairoContext, slide: Slide) -> None:
        """Draw hotspot indicators."""
        if not self._show_hotspots or not self.presentation.show_hotspot_indicators:
            return

        for hotspot in slide.hotspots:
            if not hotspot.visible:
                continue

            cr.save()
            cr.set_source_rgba(0.2, 0.6, 1.0, 0.3)
            cr.rectangle(hotspot.x, hotspot.y, hotspot.width, hotspot.height)
            cr.fill()

            cr.set_source_rgba(0.2, 0.6, 1.0, 0.8)
            cr.set_line_width(2)
            cr.rectangle(hotspot.x, hotspot.y, hotspot.width, hotspot.height)
            cr.stroke()
            cr.restore()

    def _draw_annotations(self, cr: CairoContext) -> None:
        """Draw presentation annotations."""
        self._drawing_handler.draw(cr)

    def _draw_laser_pointer(self, cr: CairoContext) -> None:
        """Draw the laser pointer trail."""
        if self._laser_points:
            draw_laser_pointer(cr, self._laser_points)

    def _get_diagram(self, diagram_id: str) -> Diagram | None:
        """Get a diagram by ID."""
        if not diagram_id:
            return None
        element = self.element_factory.lookup(diagram_id)
        if isinstance(element, Diagram):
            return element
        return None

    def _on_key_pressed(
        self,
        controller: Gtk.EventControllerKey,
        keyval: int,
        keycode: int,
        state: Gdk.ModifierType,
    ) -> bool:
        """Handle keyboard input."""
        ctrl = state & Gdk.ModifierType.CONTROL_MASK

        if keyval in (Gdk.KEY_Right, Gdk.KEY_space, Gdk.KEY_Page_Down):
            self.next_slide()
            return True
        elif keyval in (Gdk.KEY_Left, Gdk.KEY_Page_Up):
            self.previous_slide()
            return True
        elif keyval == Gdk.KEY_Home:
            self._go_to_slide(0)
            return True
        elif keyval == Gdk.KEY_End:
            self._go_to_slide(len(self.presentation.slides) - 1)
            return True
        elif keyval == Gdk.KEY_Escape:
            if self._window.is_fullscreen():
                self._window.unfullscreen()
            else:
                self.close()
            return True
        elif keyval in (Gdk.KEY_f, Gdk.KEY_F):
            self._toggle_fullscreen()
            return True
        elif keyval in (Gdk.KEY_n, Gdk.KEY_N):
            self._toggle_notes()
            return True
        elif keyval in (Gdk.KEY_t, Gdk.KEY_T):
            self._toggle_toolbar()
            return True
        elif keyval in (Gdk.KEY_p, Gdk.KEY_P):
            self._set_drawing_tool(DrawingToolType.PEN)
            return True
        elif keyval in (Gdk.KEY_h, Gdk.KEY_H):
            self._set_drawing_tool(DrawingToolType.HIGHLIGHTER)
            return True
        elif keyval in (Gdk.KEY_l, Gdk.KEY_L):
            self._set_drawing_tool(DrawingToolType.LASER_POINTER)
            return True
        elif keyval in (Gdk.KEY_a, Gdk.KEY_A):
            self._set_drawing_tool(DrawingToolType.ARROW)
            return True
        elif keyval in (Gdk.KEY_r, Gdk.KEY_R):
            self._set_drawing_tool(DrawingToolType.RECTANGLE)
            return True
        elif keyval in (Gdk.KEY_e, Gdk.KEY_E):
            self._set_drawing_tool(DrawingToolType.ELLIPSE)
            return True
        elif keyval in (Gdk.KEY_x, Gdk.KEY_X):
            self._set_drawing_tool(DrawingToolType.ERASER)
            return True
        elif keyval in (Gdk.KEY_c, Gdk.KEY_C) and not ctrl:
            self._clear_drawings()
            return True
        elif keyval in (Gdk.KEY_z, Gdk.KEY_Z) and ctrl:
            self._undo_drawing()
            return True
        elif keyval in (Gdk.KEY_y, Gdk.KEY_Y) and ctrl:
            self._redo_drawing()
            return True
        elif keyval in (Gdk.KEY_1, Gdk.KEY_2, Gdk.KEY_3, Gdk.KEY_4, Gdk.KEY_5):
            colors = ["red", "green", "blue", "yellow", "black"]
            index = keyval - Gdk.KEY_1
            if 0 <= index < len(colors):
                self._drawing_handler.set_color(colors[index])
            return True

        return False

    def _on_click_pressed(
        self, gesture: Gtk.GestureClick, n_press: int, x: float, y: float
    ) -> None:
        """Handle mouse click."""
        slide = self.current_slide
        if not slide:
            return

        diagram_x, diagram_y = self._screen_to_diagram(x, y)

        for hotspot in slide.hotspots:
            if hotspot.contains_point(diagram_x, diagram_y):
                self._handle_hotspot_click(hotspot)
                return

        if self._is_drawing_mode:
            if self._drawing_handler.state.active_tool == DrawingToolType.LASER_POINTER:
                self._laser_animator.add_point(x, y)
            else:
                self._drawing_handler.start_drawing(x, y)
                self._drawing_area.queue_draw()

    def _on_click_released(
        self, gesture: Gtk.GestureClick, n_press: int, x: float, y: float
    ) -> None:
        """Handle mouse release."""
        if self._is_drawing_mode and self._drawing_handler.state.is_drawing:
            self._drawing_handler.end_drawing(x, y)
            self._drawing_area.queue_draw()

    def _on_motion(
        self, controller: Gtk.EventControllerMotion, x: float, y: float
    ) -> None:
        """Handle mouse motion."""
        if self._is_drawing_mode:
            if self._drawing_handler.state.active_tool == DrawingToolType.LASER_POINTER:
                if controller.get_widget().get_state_flags() & Gtk.StateFlags.ACTIVE:
                    self._laser_animator.add_point(x, y)
            elif self._drawing_handler.state.is_drawing:
                self._drawing_handler.continue_drawing(x, y)
                self._drawing_area.queue_draw()

    def _on_scroll(
        self, controller: Gtk.EventControllerScroll, dx: float, dy: float
    ) -> bool:
        """Handle scroll events for zooming."""
        if dy < 0:
            self._current_view_state.zoom *= 1.1
        else:
            self._current_view_state.zoom /= 1.1

        self._current_view_state.zoom = max(0.1, min(10.0, self._current_view_state.zoom))
        self._drawing_area.queue_draw()
        return True

    def _screen_to_diagram(self, x: float, y: float) -> tuple[float, float]:
        """Convert screen coordinates to diagram coordinates."""
        slide = self.current_slide
        if not slide or not self._drawing_area:
            return x, y

        width = self._drawing_area.get_width()
        height = self._drawing_area.get_height()
        region = slide.region
        view_state = self._current_view_state

        scale_x = width / region.width if region.width > 0 else 1
        scale_y = height / region.height if region.height > 0 else 1
        scale = min(scale_x, scale_y) * view_state.zoom

        offset_x = (width - region.width * scale) / 2
        offset_y = (height - region.height * scale) / 2

        diagram_x = (x - offset_x) / scale + region.x + view_state.x
        diagram_y = (y - offset_y) / scale + region.y + view_state.y

        return diagram_x, diagram_y

    def _handle_hotspot_click(self, hotspot: Hotspot) -> None:
        """Handle clicking on a hotspot."""
        action = hotspot.action

        if action == HotspotAction.NAVIGATE_SLIDE:
            slide_id = hotspot.target
            index = self.presentation.get_slide_index(slide_id)
            if index >= 0:
                self._go_to_slide(index)

        elif action == HotspotAction.NAVIGATE_DIAGRAM:
            diagram_id = hotspot.target
            for i, slide in enumerate(self.presentation.slides):
                if slide.diagram_id == diagram_id:
                    self._go_to_slide(i)
                    break

        elif action == HotspotAction.SHOW_TOOLTIP:
            self._show_tooltip(hotspot.tooltip, hotspot.x, hotspot.y)

        elif action == HotspotAction.REVEAL_LAYER:
            pass

        elif action == HotspotAction.EXTERNAL_LINK:
            import webbrowser
            webbrowser.open(hotspot.target)

    def _show_tooltip(self, text: str, x: float, y: float) -> None:
        """Show a tooltip at the specified position."""
        log.debug(f"Showing tooltip: {text} at ({x}, {y})")

    def _go_to_slide(self, index: int) -> None:
        """Navigate to a specific slide with animation."""
        if not self.presentation.slides:
            return

        index = max(0, min(index, len(self.presentation.slides) - 1))

        if index == self._current_slide_index:
            self._update_ui()
            return

        old_slide = self.current_slide
        self._current_slide_index = index
        new_slide = self.current_slide

        if not new_slide:
            return

        duration = new_slide.transition_duration

        if old_slide and old_slide.diagram_id == new_slide.diagram_id and duration > 0:
            from_state = ViewState(
                x=old_slide.region.x,
                y=old_slide.region.y,
                zoom=old_slide.region.zoom,
            )
            to_state = ViewState(
                x=new_slide.region.x,
                y=new_slide.region.y,
                zoom=new_slide.region.zoom,
            )
            self._animator.animate_to(
                from_state, to_state, duration, EasingFunction.EASE_IN_OUT_CUBIC
            )
        else:
            self._current_view_state = ViewState(
                x=0, y=0, zoom=new_slide.region.zoom
            )
            self._drawing_area.queue_draw()

        self._update_ui()

    def _update_ui(self) -> None:
        """Update UI elements after slide change."""
        slide = self.current_slide
        total = len(self.presentation.slides)

        if self._slide_label:
            self._slide_label.set_text(
                f"{self._current_slide_index + 1} / {total}" if total > 0 else "0 / 0"
            )

        if self._progress_bar and total > 0:
            self._progress_bar.set_fraction(
                (self._current_slide_index + 1) / total
            )

        if self._notes_label and slide:
            self._notes_label.set_text(slide.notes or "")

    def _on_animation_update(self, state: ViewState) -> None:
        """Handle animation frame updates."""
        self._current_view_state = state
        self._drawing_area.queue_draw()

    def _on_animation_complete(self) -> None:
        """Handle animation completion."""
        pass

    def _on_laser_update(self, points: list[tuple[float, float, float]]) -> None:
        """Handle laser pointer updates."""
        self._laser_points = points
        self._drawing_area.queue_draw()

    def _on_tool_toggled(self, button: Gtk.ToggleButton, tool: DrawingToolType) -> None:
        """Handle drawing tool toggle."""
        if button.get_active():
            self._set_drawing_tool(tool)

    def _set_drawing_tool(self, tool: DrawingToolType) -> None:
        """Set the active drawing tool."""
        self._is_drawing_mode = True
        self._drawing_handler.set_tool(tool)

        if tool == DrawingToolType.LASER_POINTER:
            self._laser_animator.clear()

    def _on_color_selected(self, button: Gtk.Button, color_name: str) -> None:
        """Handle color selection."""
        self._drawing_handler.set_color(color_name)

    def _on_notes_toggled(self, button: Gtk.ToggleButton) -> None:
        """Handle notes visibility toggle."""
        self._toggle_notes()

    def _toggle_notes(self) -> None:
        """Toggle notes panel visibility."""
        self._show_notes = not self._show_notes
        if self._notes_revealer:
            self._notes_revealer.set_reveal_child(self._show_notes)

    def _toggle_toolbar(self) -> None:
        """Toggle toolbar visibility."""
        self._show_toolbar = not self._show_toolbar
        if self._toolbar_revealer:
            self._toolbar_revealer.set_reveal_child(self._show_toolbar)

    def _toggle_fullscreen(self) -> None:
        """Toggle fullscreen mode."""
        if self._window:
            if self._window.is_fullscreen():
                self._window.unfullscreen()
            else:
                self._window.fullscreen()

    def _clear_drawings(self) -> None:
        """Clear all drawings."""
        self._drawing_handler.clear()
        self._laser_animator.clear()
        self._drawing_area.queue_draw()

    def _undo_drawing(self) -> None:
        """Undo the last drawing."""
        self._drawing_handler.undo()
        self._drawing_area.queue_draw()

    def _redo_drawing(self) -> None:
        """Redo the last undone drawing."""
        self._drawing_handler.redo()
        self._drawing_area.queue_draw()

    def next_slide(self) -> None:
        """Go to the next slide."""
        if self._current_slide_index < len(self.presentation.slides) - 1:
            self._go_to_slide(self._current_slide_index + 1)
        elif self.presentation.loop_presentation:
            self._go_to_slide(0)

    def previous_slide(self) -> None:
        """Go to the previous slide."""
        if self._current_slide_index > 0:
            self._go_to_slide(self._current_slide_index - 1)
        elif self.presentation.loop_presentation:
            self._go_to_slide(len(self.presentation.slides) - 1)

    def _on_close_request(self, window: Gtk.Window) -> bool:
        """Handle window close request."""
        self.close()
        return True

    def close(self) -> None:
        """Close the presentation window."""
        self._animator.cancel()
        self._laser_animator.clear()
        if self._window:
            self._window.destroy()
            self._window = None
