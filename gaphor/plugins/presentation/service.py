"""Presentation service for Gaphor.

This service provides the main entry points for the presentation feature,
including creating, editing, and running presentations.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from gi.repository import Gtk

from gaphor.abc import ActionProvider, Service
from gaphor.action import action
from gaphor.core import event_handler
from gaphor.core.modeling import Diagram
from gaphor.diagram.event import DiagramOpened
from gaphor.event import ActionEnabled
from gaphor.i18n import gettext
from gaphor.plugins.presentation.editor import PresentationEditor
from gaphor.plugins.presentation.model import Presentation, Slide, ViewRegion
from gaphor.plugins.presentation.window import PresentationWindow
from gaphor.ui.filedialog import open_file_dialog, save_file_dialog

if TYPE_CHECKING:
    from gaphor.core.modeling import ElementFactory

log = logging.getLogger(__name__)


class PresentationService(Service, ActionProvider):
    """Service for managing diagram presentations.

    This service provides functionality to:
    - Create new presentations from diagrams
    - Edit existing presentations
    - Run presentations in slideshow mode
    - Save and load presentations to/from files
    """

    def __init__(
        self,
        event_manager,
        element_factory: ElementFactory,
        diagrams=None,
        main_window=None,
        tools_menu=None,
    ):
        self.event_manager = event_manager
        self.element_factory = element_factory
        self.diagrams = diagrams
        self.main_window = main_window
        self._current_presentation: Presentation | None = None
        self._presentation_window: PresentationWindow | None = None
        self._editor_window: PresentationEditor | None = None

        if tools_menu:
            tools_menu.add_actions(self)

        event_manager.subscribe(self._on_diagram_state_changed)

    def shutdown(self) -> None:
        """Shutdown the service."""
        self.event_manager.unsubscribe(self._on_diagram_state_changed)

        if self._presentation_window:
            self._presentation_window.close()
            self._presentation_window = None

        if self._editor_window:
            self._editor_window.close()
            self._editor_window = None

    @property
    def parent_window(self) -> Gtk.Window | None:
        """Get the parent window for dialogs."""
        return self.main_window.window if self.main_window else None

    @event_handler(DiagramOpened)
    def _on_diagram_state_changed(self, event):
        """Update action state when diagrams change."""
        has_diagrams = bool(list(self.element_factory.select(Diagram)))
        self.event_manager.handle(
            ActionEnabled("win.presentation-new", has_diagrams)
        )
        self.event_manager.handle(
            ActionEnabled("win.presentation-from-diagram", has_diagrams)
        )

    @action(
        name="presentation-new",
        label=gettext("New Presentation"),
        tooltip=gettext("Create a new presentation"),
    )
    def new_presentation(self) -> None:
        """Create a new empty presentation."""
        self._current_presentation = Presentation(title=gettext("New Presentation"))
        self._open_editor()

    @action(
        name="presentation-from-diagram",
        label=gettext("Presentation from Diagram"),
        tooltip=gettext("Create a presentation from the current diagram"),
    )
    def presentation_from_diagram(self) -> None:
        """Create a presentation from the current diagram."""
        diagram = self.diagrams.get_current_diagram() if self.diagrams else None

        if not diagram:
            log.warning("No diagram selected for presentation")
            return

        self._current_presentation = self._create_presentation_from_diagram(diagram)
        self._open_editor()

    @action(
        name="presentation-from-all-diagrams",
        label=gettext("Presentation from All Diagrams"),
        tooltip=gettext("Create a presentation with slides from all diagrams"),
    )
    def presentation_from_all_diagrams(self) -> None:
        """Create a presentation from all diagrams."""
        diagrams = list(self.element_factory.select(Diagram))

        if not diagrams:
            log.warning("No diagrams available for presentation")
            return

        presentation = Presentation(title=gettext("All Diagrams Presentation"))

        for diagram in diagrams:
            slide = self._create_slide_from_diagram(diagram)
            presentation.add_slide(slide)

        self._current_presentation = presentation
        self._open_editor()

    @action(
        name="presentation-open",
        label=gettext("Open Presentation"),
        tooltip=gettext("Open a presentation file"),
    )
    async def open_presentation(self) -> None:
        """Open a presentation from a file."""
        filename = await open_file_dialog(
            gettext("Open Presentation"),
            Path.home() / "presentation.json",
            parent=self.parent_window,
            filters=[
                (gettext("Presentation Files"), ".json", "application/json"),
            ],
        )

        if filename:
            try:
                with open(filename, encoding="utf-8") as f:
                    data = json.load(f)
                self._current_presentation = Presentation.from_dict(data)
                self._open_editor()
            except Exception as e:
                log.error(f"Failed to load presentation: {e}")

    @action(
        name="presentation-start",
        label=gettext("Start Presentation"),
        tooltip=gettext("Start the current presentation"),
    )
    def start_presentation(self) -> None:
        """Start the current presentation in slideshow mode."""
        if not self._current_presentation:
            self.presentation_from_diagram()

        if self._current_presentation:
            self._start_presentation(self._current_presentation)

    @action(
        name="presentation-quick-start",
        label=gettext("Quick Present"),
        tooltip=gettext("Quickly present the current diagram"),
    )
    def quick_present(self) -> None:
        """Quick present the current diagram without editing."""
        diagram = self.diagrams.get_current_diagram() if self.diagrams else None

        if not diagram:
            log.warning("No diagram selected for quick presentation")
            return

        presentation = self._create_presentation_from_diagram(diagram)
        self._start_presentation(presentation)

    def _create_presentation_from_diagram(self, diagram: Diagram) -> Presentation:
        """Create a presentation from a single diagram."""
        title = diagram.name or gettext("Diagram Presentation")
        presentation = Presentation(title=title)
        slide = self._create_slide_from_diagram(diagram)
        presentation.add_slide(slide)
        return presentation

    def _create_slide_from_diagram(self, diagram: Diagram) -> Slide:
        """Create a slide from a diagram."""
        bounds = self._get_diagram_bounds(diagram)

        region = ViewRegion(
            x=bounds[0] if bounds else 0,
            y=bounds[1] if bounds else 0,
            width=bounds[2] if bounds else 800,
            height=bounds[3] if bounds else 600,
            zoom=1.0,
        )

        return Slide(
            title=diagram.name or gettext("Untitled"),
            diagram_id=diagram.id,
            region=region,
            notes="",
        )

    def _get_diagram_bounds(
        self, diagram: Diagram
    ) -> tuple[float, float, float, float] | None:
        """Get the bounding box of all items in a diagram."""
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

    def _open_editor(self) -> None:
        """Open the presentation editor."""
        if self._editor_window:
            self._editor_window.close()

        if not self._current_presentation:
            return

        self._editor_window = PresentationEditor(
            self._current_presentation,
            self.element_factory,
            self.parent_window,
            on_save=self._save_presentation,
            on_present=self._start_presentation,
        )
        self._editor_window.open()

    def _start_presentation(self, presentation: Presentation) -> None:
        """Start a presentation in slideshow mode."""
        if self._presentation_window:
            self._presentation_window.close()

        self._presentation_window = PresentationWindow(
            presentation,
            self.element_factory,
            self.parent_window,
        )
        self._presentation_window.open()

    async def _save_presentation(self, presentation: Presentation) -> None:
        """Save a presentation to a file."""
        filename = await save_file_dialog(
            gettext("Save Presentation"),
            Path.home() / f"{presentation.title}.json",
            parent=self.parent_window,
            filters=[
                (gettext("Presentation Files"), ".json", "application/json"),
            ],
        )

        if filename:
            try:
                with open(filename, "w", encoding="utf-8") as f:
                    json.dump(presentation.to_dict(), f, indent=2)
                log.info(f"Presentation saved to {filename}")
            except Exception as e:
                log.error(f"Failed to save presentation: {e}")
