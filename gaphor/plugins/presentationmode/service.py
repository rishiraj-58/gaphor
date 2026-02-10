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
from gaphor.event import Notification
from gaphor.i18n import gettext
from gaphor.plugins.presentationmode.editor import PresentationEditor
from gaphor.plugins.presentationmode.errors import (
    PresentationLoadError,
    PresentationSaveError,
    handle_errors,
    handle_errors_async,
    show_error_dialog,
    show_warning_dialog,
)
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
        """Shut down the service and clean up resources."""
        self._close_presentation_window()
        self._close_editor_window()

    def _close_presentation_window(self) -> None:
        """Safely close the presentation window."""
        if self.presentation_window:
            try:
                self.presentation_window.close()
            except Exception as e:
                log.warning(f"Error closing presentation window: {e}")
            finally:
                self.presentation_window = None

    def _close_editor_window(self) -> None:
        """Safely close the editor window."""
        if self.editor_window:
            try:
                self.editor_window.close()
            except Exception as e:
                log.warning(f"Error closing editor window: {e}")
            finally:
                self.editor_window = None

    def _get_parent_window(self) -> Gtk.Window | None:
        """Get the parent window for dialogs."""
        return self.main_window.window if self.main_window else None

    @action(
        name="presentation-mode-start",
        label=gettext("Start Presentation"),
        tooltip=gettext("Start a presentation with all diagrams"),
        shortcut="F5",
    )
    @handle_errors(error_title=gettext("Presentation Error"))
    def start_presentation(self) -> None:
        """Start a presentation with all diagrams."""
        presentation = self._create_presentation_from_diagrams()

        if not presentation.slides:
            show_warning_dialog(
                self._get_parent_window(),
                gettext("No Diagrams"),
                gettext("There are no diagrams in the model to present."),
            )
            return

        self._show_presentation(presentation)

    @action(
        name="presentation-mode-current",
        label=gettext("Present Current Diagram"),
        tooltip=gettext("Start presentation from current diagram"),
        shortcut="<Shift>F5",
    )
    @handle_errors(error_title=gettext("Presentation Error"))
    def present_current_diagram(self) -> None:
        """Start presentation from the current diagram."""
        diagram = self.diagrams.get_current_diagram()

        if not diagram:
            show_warning_dialog(
                self._get_parent_window(),
                gettext("No Diagram"),
                gettext("Please open a diagram first."),
            )
            return

        presentation = Presentation(name=diagram.name or "Presentation")
        presentation.add_slide(Slide(diagram=diagram))
        self._show_presentation(presentation)

    @action(
        name="presentation-mode-edit",
        label=gettext("Edit Presentation"),
        tooltip=gettext("Create or edit a presentation"),
    )
    @handle_errors(error_title=gettext("Editor Error"))
    def edit_presentation(self) -> None:
        """Open the presentation editor."""
        if not self.current_presentation:
            self.current_presentation = self._create_presentation_from_diagrams()

        self._close_editor_window()

        self.editor_window = PresentationEditor(
            self._get_parent_window(),
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
    @handle_errors(error_title=gettext("Add Slide Error"))
    def add_current_as_slide(self) -> None:
        """Add the current diagram view as a slide."""
        diagram = self.diagrams.get_current_diagram()
        view = self.diagrams.get_current_view()

        if not diagram:
            show_warning_dialog(
                self._get_parent_window(),
                gettext("No Diagram"),
                gettext("Please open a diagram first."),
            )
            return

        if not self.current_presentation:
            self.current_presentation = Presentation(name="Presentation")

        region = self._capture_view_region(view) if view else None
        slide = Slide(diagram=diagram, region=region)
        self.current_presentation.add_slide(slide)

        self.event_manager.handle(
            Notification(
                gettext("Slide added: {name}").format(name=diagram.name or "Untitled")
            )
        )

    @action(
        name="presentation-mode-save",
        label=gettext("Save Presentation"),
        tooltip=gettext("Save the current presentation to a file"),
    )
    @handle_errors_async(error_title=gettext("Save Error"))
    async def save_presentation(self) -> None:
        """Save the current presentation to a file."""
        if not self.current_presentation:
            show_warning_dialog(
                self._get_parent_window(),
                gettext("No Presentation"),
                gettext("There is no presentation to save. Create one first."),
            )
            return

        if not self.current_presentation.slides:
            show_warning_dialog(
                self._get_parent_window(),
                gettext("Empty Presentation"),
                gettext("The presentation has no slides to save."),
            )
            return

        dialog = Gtk.FileDialog.new()
        dialog.set_title(gettext("Save Presentation"))

        filter_pres = Gtk.FileFilter()
        filter_pres.set_name(gettext("Presentation Files (*.gaphor-pres)"))
        filter_pres.add_pattern("*.gaphor-pres")

        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(filter_pres)
        dialog.set_filters(filters)

        try:
            file = await dialog.save(self._get_parent_window(), None)
            if file:
                path = Path(file.get_path())
                if not path.suffix:
                    path = path.with_suffix(".gaphor-pres")
                self._save_presentation_to_file(path)
                self.event_manager.handle(
                    Notification(gettext("Presentation saved: {path}").format(path=path.name))
                )
        except GLib.Error as e:
            if e.code != Gtk.DialogError.DISMISSED:
                raise PresentationSaveError(
                    gettext("Failed to save presentation"),
                    str(e),
                )

    @action(
        name="presentation-mode-load",
        label=gettext("Load Presentation"),
        tooltip=gettext("Load a presentation from a file"),
    )
    @handle_errors_async(error_title=gettext("Load Error"))
    async def load_presentation(self) -> None:
        """Load a presentation from a file."""
        dialog = Gtk.FileDialog.new()
        dialog.set_title(gettext("Load Presentation"))

        filter_pres = Gtk.FileFilter()
        filter_pres.set_name(gettext("Presentation Files (*.gaphor-pres)"))
        filter_pres.add_pattern("*.gaphor-pres")

        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(filter_pres)
        dialog.set_filters(filters)

        try:
            file = await dialog.open(self._get_parent_window(), None)
            if file:
                path = Path(file.get_path())
                presentation = self._load_presentation_from_file(path)
                if presentation:
                    self.current_presentation = presentation
                    self.event_manager.handle(
                        Notification(
                            gettext("Presentation loaded: {path}").format(path=path.name)
                        )
                    )
                    self.edit_presentation()
        except GLib.Error as e:
            if e.code != Gtk.DialogError.DISMISSED:
                raise PresentationLoadError(
                    gettext("Failed to load presentation"),
                    str(e),
                )

    def _create_presentation_from_diagrams(self) -> Presentation:
        """Create a presentation from all diagrams in the model."""
        presentation = Presentation(name="Presentation")

        try:
            diagrams = list(self.element_factory.select(Diagram))
            diagrams.sort(key=lambda d: d.name or "")

            for diagram in diagrams:
                slide = Slide(diagram=diagram)
                presentation.add_slide(slide)

        except Exception as e:
            log.error(f"Error creating presentation from diagrams: {e}")

        return presentation

    def _show_presentation(self, presentation: Presentation) -> None:
        """Show the presentation window."""
        self.current_presentation = presentation
        self._close_presentation_window()

        try:
            self.presentation_window = PresentationWindow(
                self._get_parent_window(),
                presentation,
                self.element_factory,
                self.event_manager,
            )
            self.presentation_window.start()
        except Exception as e:
            log.error(f"Failed to start presentation: {e}")
            show_error_dialog(
                self._get_parent_window(),
                gettext("Presentation Error"),
                gettext("Failed to start the presentation."),
                str(e),
            )

    def _capture_view_region(self, view) -> SlideRegion | None:
        """Capture the current view region."""
        if not view:
            return None

        try:
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

            return SlideRegion(x=x, y=y, width=w, height=h)

        except Exception as e:
            log.warning(f"Failed to capture view region: {e}")
            return None

    def _save_presentation_to_file(self, path: Path) -> None:
        """Save presentation to a JSON file."""
        if not self.current_presentation:
            raise PresentationSaveError(
                gettext("No presentation to save"),
                gettext("Create a presentation first."),
            )

        try:
            data = {
                "version": "1.0",
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

        except OSError as e:
            raise PresentationSaveError(
                gettext("Failed to write file"),
                str(e),
            )
        except Exception as e:
            raise PresentationSaveError(
                gettext("Error saving presentation"),
                str(e),
            )

    def _load_presentation_from_file(self, path: Path) -> Presentation | None:
        """Load presentation from a JSON file."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            presentation = Presentation(name=data.get("name", "Presentation"))
            missing_diagrams = []

            for slide_data in data.get("slides", []):
                diagram_id = slide_data.get("diagram_id")
                diagram = self.element_factory.lookup(diagram_id)

                if not diagram or not isinstance(diagram, Diagram):
                    missing_diagrams.append(diagram_id)
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

            if missing_diagrams:
                show_warning_dialog(
                    self._get_parent_window(),
                    gettext("Missing Diagrams"),
                    gettext(
                        "{count} slide(s) were skipped because their diagrams were not found in the model."
                    ).format(count=len(missing_diagrams)),
                )

            if not presentation.slides:
                raise PresentationLoadError(
                    gettext("No valid slides"),
                    gettext("None of the slides in the presentation file could be loaded."),
                )

            log.info(f"Loaded presentation from: {path}")
            return presentation

        except json.JSONDecodeError as e:
            raise PresentationLoadError(
                gettext("Invalid file format"),
                gettext("The file is not a valid presentation file: {error}").format(
                    error=str(e)
                ),
            )
        except OSError as e:
            raise PresentationLoadError(
                gettext("Failed to read file"),
                str(e),
            )
        except PresentationLoadError:
            raise
        except Exception as e:
            raise PresentationLoadError(
                gettext("Error loading presentation"),
                str(e),
            )
