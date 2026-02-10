"""Presentation mode service - main entry point."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from gi.repository import Gio, Gtk

from gaphor.abc import ActionProvider, Service
from gaphor.action import action
from gaphor.core.modeling import Diagram
from gaphor.i18n import gettext
from gaphor.plugins.presentationmode.editor import PresentationEditor
from gaphor.plugins.presentationmode.model import Presentation, Slide, SlideRegion
from gaphor.plugins.presentationmode.presenter import PresentationWindow

if TYPE_CHECKING:
    from gaphor.core.eventmanager import EventManager
    from gaphor.core.modeling import ElementFactory
    from gaphor.ui.mainwindow import MainWindow

log = logging.getLogger(__name__)


class PresentationModeService(Service, ActionProvider):
    """Service for presentation mode functionality."""

    def __init__(
        self,
        event_manager: EventManager,
        element_factory: ElementFactory,
        main_window: MainWindow,
        diagrams,
        tools_menu,
    ):
        self.event_manager = event_manager
        self.element_factory = element_factory
        self.main_window = main_window
        self.diagrams = diagrams

        self.current_presentation: Presentation | None = None
        self.presentation_window: PresentationWindow | None = None
        self.editor_window: PresentationEditor | None = None

        tools_menu.add_actions(self)

    def shutdown(self) -> None:
        if self.presentation_window:
            self.presentation_window.close()
        if self.editor_window:
            self.editor_window.close()

    @action(
        name="presentation-mode-start",
        label=gettext("Start Presentation"),
        tooltip=gettext("Start a presentation with all diagrams"),
        shortcut="F5",
    )
    def start_presentation(self) -> None:
        """Start a presentation with all diagrams."""
        presentation = self._create_presentation_from_diagrams()
        if presentation.slides:
            self._show_presentation(presentation)

    @action(
        name="presentation-mode-current",
        label=gettext("Present Current Diagram"),
        tooltip=gettext("Start presentation from current diagram"),
        shortcut="<Shift>F5",
    )
    def present_current_diagram(self) -> None:
        """Start presentation from the current diagram."""
        diagram = self.diagrams.get_current_diagram()
        if diagram:
            presentation = Presentation(name=diagram.name or "Presentation")
            presentation.add_slide(Slide(diagram=diagram))
            self._show_presentation(presentation)

    @action(
        name="presentation-mode-edit",
        label=gettext("Edit Presentation"),
        tooltip=gettext("Create or edit a presentation"),
    )
    def edit_presentation(self) -> None:
        """Open the presentation editor."""
        if not self.current_presentation:
            self.current_presentation = self._create_presentation_from_diagrams()

        self.editor_window = PresentationEditor(
            self.main_window.window,
            self.current_presentation,
            self.element_factory,
            self._show_presentation,
        )
        self.editor_window.set_current_view(self.diagrams.get_current_view())
        self.editor_window.present()

    @action(
        name="presentation-mode-add-slide",
        label=gettext("Add Current View as Slide"),
        tooltip=gettext("Add the current diagram view as a slide"),
    )
    def add_current_as_slide(self) -> None:
        """Add the current diagram view as a slide."""
        diagram = self.diagrams.get_current_diagram()
        view = self.diagrams.get_current_view()

        if not diagram or not view:
            return

        if not self.current_presentation:
            self.current_presentation = Presentation(name="Presentation")

        region = self._capture_view_region(view)
        slide = Slide(diagram=diagram, region=region)
        self.current_presentation.add_slide(slide)

        log.info(f"Added slide for diagram: {diagram.name}")

    @action(
        name="presentation-mode-save",
        label=gettext("Save Presentation"),
        tooltip=gettext("Save the current presentation to a file"),
    )
    async def save_presentation(self) -> None:
        """Save the current presentation to a file."""
        if not self.current_presentation:
            return

        dialog = Gtk.FileDialog.new()
        dialog.set_title(gettext("Save Presentation"))

        filter_json = Gtk.FileFilter()
        filter_json.set_name(gettext("Presentation Files (*.gaphor-pres)"))
        filter_json.add_pattern("*.gaphor-pres")

        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(filter_json)
        dialog.set_filters(filters)

        try:
            file = await dialog.save(self.main_window.window, None)
            if file:
                path = Path(file.get_path())
                if not path.suffix:
                    path = path.with_suffix(".gaphor-pres")
                self._save_presentation_to_file(path)
        except Exception as e:
            log.error(f"Failed to save presentation: {e}")

    @action(
        name="presentation-mode-load",
        label=gettext("Load Presentation"),
        tooltip=gettext("Load a presentation from a file"),
    )
    async def load_presentation(self) -> None:
        """Load a presentation from a file."""
        dialog = Gtk.FileDialog.new()
        dialog.set_title(gettext("Load Presentation"))

        filter_json = Gtk.FileFilter()
        filter_json.set_name(gettext("Presentation Files (*.gaphor-pres)"))
        filter_json.add_pattern("*.gaphor-pres")

        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(filter_json)
        dialog.set_filters(filters)

        try:
            file = await dialog.open(self.main_window.window, None)
            if file:
                path = Path(file.get_path())
                presentation = self._load_presentation_from_file(path)
                if presentation:
                    self.current_presentation = presentation
                    self.edit_presentation()
        except Exception as e:
            log.error(f"Failed to load presentation: {e}")

    def _create_presentation_from_diagrams(self) -> Presentation:
        """Create a presentation from all diagrams in the model."""
        presentation = Presentation(name="Presentation")

        diagrams = list(self.element_factory.select(Diagram))
        diagrams.sort(key=lambda d: d.name or "")

        for diagram in diagrams:
            slide = Slide(diagram=diagram)
            presentation.add_slide(slide)

        return presentation

    def _show_presentation(self, presentation: Presentation) -> None:
        """Show the presentation window."""
        self.current_presentation = presentation

        if self.presentation_window:
            self.presentation_window.close()

        self.presentation_window = PresentationWindow(
            self.main_window.window,
            presentation,
            self.element_factory,
            self.event_manager,
        )
        self.presentation_window.start()

    def _capture_view_region(self, view) -> SlideRegion | None:
        """Capture the current view region."""
        matrix = view.matrix
        width = view.get_width()
        height = view.get_height()

        if width == 0 or height == 0:
            return None

        scale = matrix[0]
        offset_x = matrix[4]
        offset_y = matrix[5]

        x = -offset_x / scale
        y = -offset_y / scale
        w = width / scale
        h = height / scale

        return SlideRegion(x=x, y=y, width=w, height=h)

    def _save_presentation_to_file(self, path: Path) -> None:
        """Save presentation to a JSON file."""
        if not self.current_presentation:
            return

        data = {
            "name": self.current_presentation.name,
            "slides": [],
        }

        for slide in self.current_presentation.slides:
            slide_data = {
                "diagram_id": slide.diagram.id,
                "title": slide.title,
                "notes": slide.notes,
                "reveal_elements": slide.reveal_elements,
                "linked_diagram_id": slide.linked_diagram_id,
            }

            if slide.region:
                slide_data["region"] = {
                    "x": slide.region.x,
                    "y": slide.region.y,
                    "width": slide.region.width,
                    "height": slide.region.height,
                }

            data["slides"].append(slide_data)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        log.info(f"Saved presentation to: {path}")

    def _load_presentation_from_file(self, path: Path) -> Presentation | None:
        """Load presentation from a JSON file."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            presentation = Presentation(name=data.get("name", "Presentation"))

            for slide_data in data.get("slides", []):
                diagram_id = slide_data.get("diagram_id")
                diagram = self.element_factory.lookup(diagram_id)

                if not diagram or not isinstance(diagram, Diagram):
                    log.warning(f"Diagram not found: {diagram_id}")
                    continue

                region = None
                if "region" in slide_data:
                    r = slide_data["region"]
                    region = SlideRegion(
                        x=r["x"], y=r["y"], width=r["width"], height=r["height"]
                    )

                slide = Slide(
                    diagram=diagram,
                    region=region,
                    title=slide_data.get("title", ""),
                    notes=slide_data.get("notes", ""),
                    reveal_elements=slide_data.get("reveal_elements", []),
                    linked_diagram_id=slide_data.get("linked_diagram_id"),
                )
                presentation.add_slide(slide)

            log.info(f"Loaded presentation from: {path}")
            return presentation

        except Exception as e:
            log.error(f"Failed to load presentation: {e}")
            return None
