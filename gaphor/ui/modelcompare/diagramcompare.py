"""Diagram visual comparison component."""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING

from gaphas.painter import PainterChain
from gaphas.view import GtkView
from gi.repository import Adw, Gdk, Gtk

from gaphor.core import gettext
from gaphor.core.modeling import Diagram, Presentation, StyleSheet
from gaphor.core.modeling.diagram import StyledDiagram, StyledItem
from gaphor.core.styling import PrefersColorScheme
from gaphor.diagram.painter import DiagramTypePainter, ItemPainter
from gaphor.ui.modelcompare.differ import Change, ChangeCategory, ChangeType

if TYPE_CHECKING:
    from gaphor.core.modeling import ElementFactory


class HighlightPainter:
    """Painter that highlights changed elements."""

    def __init__(
        self,
        changes: dict[str, ChangeType],
        base_painter: ItemPainter,
    ):
        self.changes = changes
        self.base_painter = base_painter

    def paint_item(self, item, cairo):
        """Paint an item with highlight based on change type."""
        self.base_painter.paint_item(item, cairo)

        change_type = self.changes.get(item.id)
        if change_type:
            self._draw_highlight(item, cairo, change_type)

    def _draw_highlight(self, item, cairo, change_type: ChangeType):
        """Draw a highlight border around the item."""
        bounds = item.bounds

        if change_type == ChangeType.ADDED:
            color = (0.2, 0.8, 0.2, 0.5)  # Green
        elif change_type == ChangeType.REMOVED:
            color = (0.8, 0.2, 0.2, 0.5)  # Red
        else:
            color = (0.8, 0.6, 0.2, 0.5)  # Orange

        cairo.save()
        cairo.set_source_rgba(*color)
        cairo.set_line_width(3)
        cairo.rectangle(
            bounds.x - 2,
            bounds.y - 2,
            bounds.width + 4,
            bounds.height + 4,
        )
        cairo.stroke()
        cairo.restore()


class DiagramCompareView(Gtk.Box):
    """Split view for comparing two versions of a diagram."""

    def __init__(
        self,
        base_diagram: Diagram,
        compare_diagram: Diagram | None,
        changes: list[Change],
        base_factory: ElementFactory,
        compare_factory: ElementFactory | None,
    ):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)

        self.base_diagram = base_diagram
        self.compare_diagram = compare_diagram
        self.changes = changes
        self.base_factory = base_factory
        self.compare_factory = compare_factory

        self._build_ui()

    def _build_ui(self):
        """Build the split view UI."""
        # Left side - base diagram (current)
        left_frame = self._create_diagram_frame(
            gettext("Current Version"),
            self.base_diagram,
            self.base_factory,
            is_base=True,
        )
        left_frame.set_hexpand(True)
        self.append(left_frame)

        # Separator
        separator = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        self.append(separator)

        # Right side - compare diagram
        if self.compare_diagram:
            right_frame = self._create_diagram_frame(
                gettext("Compare Version"),
                self.compare_diagram,
                self.compare_factory,
                is_base=False,
            )
        else:
            right_frame = self._create_placeholder_frame(
                gettext("Diagram not found in compare version")
            )
        right_frame.set_hexpand(True)
        self.append(right_frame)

    def _create_diagram_frame(
        self,
        title: str,
        diagram: Diagram,
        factory: ElementFactory,
        is_base: bool,
    ) -> Gtk.Frame:
        """Create a frame containing a diagram view."""
        frame = Gtk.Frame()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # Title
        label = Gtk.Label(label=title)
        label.add_css_class("heading")
        label.set_margin_top(6)
        label.set_margin_bottom(6)
        box.append(label)

        # Diagram view
        view = GtkView()
        view.model = diagram
        view.set_vexpand(True)
        view.set_hexpand(True)

        # Set up painter with highlights
        change_map = self._get_change_map(diagram.id, is_base)
        self._setup_painter(view, diagram, factory, change_map)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_child(view)
        box.append(scrolled)

        # Legend
        legend = self._create_legend()
        box.append(legend)

        frame.set_child(box)
        return frame

    def _create_placeholder_frame(self, message: str) -> Gtk.Frame:
        """Create a placeholder frame for missing diagram."""
        frame = Gtk.Frame()
        label = Gtk.Label(label=message)
        label.add_css_class("dim-label")
        frame.set_child(label)
        return frame

    def _get_change_map(self, diagram_id: str, is_base: bool) -> dict[str, ChangeType]:
        """Get a map of element IDs to change types for highlighting."""
        change_map: dict[str, ChangeType] = {}

        for change in self.changes:
            if change.diagram_id == diagram_id:
                if change.category in (
                    ChangeCategory.PRESENTATION,
                    ChangeCategory.ELEMENT,
                ):
                    change_map[change.element_id] = change.change_type

        return change_map

    def _setup_painter(
        self,
        view: GtkView,
        diagram: Diagram,
        factory: ElementFactory,
        change_map: dict[str, ChangeType],
    ):
        """Set up the diagram painter with highlighting."""
        style_manager = Adw.StyleManager.get_default()
        prefers_color_scheme = (
            PrefersColorScheme.DARK
            if style_manager.get_dark()
            else PrefersColorScheme.LIGHT
        )

        style_sheet = factory.style_sheet or StyleSheet()
        item_painter = ItemPainter(
            view.selection,
            functools.partial(
                style_sheet.compute_style, prefers_color_scheme=prefers_color_scheme
            ),
        )

        if change_map:
            # Wrap with highlight painter
            painter = HighlightPainter(change_map, item_painter)
        else:
            painter = item_painter

        view.bounding_box_painter = item_painter
        view.painter = (
            PainterChain()
            .append(painter)
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

    def _create_legend(self) -> Gtk.Box:
        """Create a legend for the change colors."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(6)
        box.set_margin_end(6)
        box.set_halign(Gtk.Align.CENTER)

        # Added
        added_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=3)
        added_color = Gtk.DrawingArea()
        added_color.set_size_request(16, 16)
        added_color.set_draw_func(self._draw_color_box, (0.2, 0.8, 0.2))
        added_box.append(added_color)
        added_box.append(Gtk.Label(label=gettext("Added")))
        box.append(added_box)

        # Removed
        removed_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=3)
        removed_color = Gtk.DrawingArea()
        removed_color.set_size_request(16, 16)
        removed_color.set_draw_func(self._draw_color_box, (0.8, 0.2, 0.2))
        removed_box.append(removed_color)
        removed_box.append(Gtk.Label(label=gettext("Removed")))
        box.append(removed_box)

        # Modified
        modified_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=3)
        modified_color = Gtk.DrawingArea()
        modified_color.set_size_request(16, 16)
        modified_color.set_draw_func(self._draw_color_box, (0.8, 0.6, 0.2))
        modified_box.append(modified_color)
        modified_box.append(Gtk.Label(label=gettext("Modified")))
        box.append(modified_box)

        return box

    def _draw_color_box(self, area, cairo, width, height, color):
        """Draw a colored box for the legend."""
        cairo.set_source_rgb(*color)
        cairo.rectangle(0, 0, width, height)
        cairo.fill()


class DiagramCompareWindow(Adw.Window):
    """Window for comparing two versions of a diagram."""

    def __init__(
        self,
        base_diagram: Diagram,
        compare_diagram: Diagram | None,
        changes: list[Change],
        base_factory: ElementFactory,
        compare_factory: ElementFactory | None,
        compare_filename: str,
    ):
        super().__init__()

        self.set_title(
            gettext("Compare Diagram: {name}").format(
                name=base_diagram.name or gettext("<Unnamed>")
            )
        )
        self.set_default_size(1200, 800)

        toolbar_view = Adw.ToolbarView()

        # Header bar
        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        # Compare view
        compare_view = DiagramCompareView(
            base_diagram=base_diagram,
            compare_diagram=compare_diagram,
            changes=changes,
            base_factory=base_factory,
            compare_factory=compare_factory,
        )

        toolbar_view.set_content(compare_view)
        self.set_content(toolbar_view)
