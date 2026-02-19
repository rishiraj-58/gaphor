"""Service for diagram comparison functionality.

Provides the "Compare with..." action for diagrams and handles loading
comparison versions from files.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from gi.repository import Adw, Gio, GLib, Gtk

from gaphor.abc import ActionProvider, Service
from gaphor.core import action, event_handler, gettext
from gaphor.core.modeling import Diagram, ElementFactory
from gaphor.diagram.event import DiagramOpened
from gaphor.event import Notification
from gaphor.storage import load as storage_load
from gaphor.ui.diagramcompare.compareview import DiagramCompareView
from gaphor.ui.event import CurrentDiagramChanged
from gaphor.ui.filedialog import GAPHOR_FILTER, open_file_dialog


class DiagramCompareService(Service, ActionProvider):
    """Service that provides diagram comparison functionality."""

    def __init__(
        self,
        event_manager,
        element_factory,
        modeling_language,
        main_window,
        properties,
    ):
        self.event_manager = event_manager
        self.element_factory = element_factory
        self.modeling_language = modeling_language
        self.main_window = main_window
        self.properties = properties
        self._current_diagram: Diagram | None = None
        self._compare_window: Gtk.Window | None = None

        event_manager.subscribe(self._on_current_diagram_changed)

    def shutdown(self):
        self.event_manager.unsubscribe(self._on_current_diagram_changed)
        if self._compare_window:
            self._compare_window.destroy()
            self._compare_window = None

    @event_handler(CurrentDiagramChanged)
    def _on_current_diagram_changed(self, event: CurrentDiagramChanged):
        self._current_diagram = event.diagram

    @property
    def parent_window(self):
        return self.main_window.window if self.main_window else None

    @action(name="diagram-compare", label="Compare with...")
    async def compare_diagram_action(self):
        """Open a file dialog to select a version to compare with."""
        if not self._current_diagram:
            self.event_manager.handle(
                Notification(gettext("No diagram selected for comparison"))
            )
            return

        # Show file picker for the comparison version
        filename = await open_file_dialog(
            gettext("Select Model to Compare"),
            parent=self.parent_window,
            filters=GAPHOR_FILTER,
            multiple=False,
        )

        if not filename:
            return

        await self._perform_comparison(filename)

    async def _perform_comparison(self, compare_file: Path):
        """Load the comparison file and show the diff view."""
        # Load the comparison model into a separate element factory
        compare_factory = ElementFactory()

        try:
            with compare_file.open(encoding="utf-8", errors="replace") as f:
                for _ in storage_load.load_generator(
                    f, compare_factory, self.modeling_language
                ):
                    pass
        except Exception as e:
            self.event_manager.handle(
                Notification(
                    gettext("Failed to load comparison file: {error}").format(error=str(e))
                )
            )
            return

        # Find the matching diagram in the comparison model
        compare_diagram = self._find_matching_diagram(compare_factory)

        if not compare_diagram:
            # Show dialog asking user to select a diagram
            compare_diagram = await self._select_diagram_dialog(compare_factory)
            if not compare_diagram:
                return

        # Show the comparison view
        self._show_compare_view(self._current_diagram, compare_diagram)

    def _find_matching_diagram(self, compare_factory: ElementFactory) -> Diagram | None:
        """Find a diagram in the comparison model that matches the current diagram."""
        if not self._current_diagram:
            return None

        # First, try to find by ID
        compare_diagram = compare_factory.lookup(self._current_diagram.id)
        if isinstance(compare_diagram, Diagram):
            return compare_diagram

        # Then try to find by name
        current_name = self._current_diagram.name
        if current_name:
            for diagram in compare_factory.select(Diagram):
                if diagram.name == current_name:
                    return diagram

        # Return first diagram if only one exists
        diagrams = list(compare_factory.select(Diagram))
        if len(diagrams) == 1:
            return diagrams[0]

        return None

    async def _select_diagram_dialog(
        self, compare_factory: ElementFactory
    ) -> Diagram | None:
        """Show a dialog to select which diagram to compare with."""
        diagrams = list(compare_factory.select(Diagram))

        if not diagrams:
            self.event_manager.handle(
                Notification(gettext("No diagrams found in comparison file"))
            )
            return None

        # Create selection dialog
        dialog = Adw.AlertDialog.new(
            gettext("Select Diagram to Compare"),
            gettext(
                "The selected file contains multiple diagrams. Please select the one to compare with."
            ),
        )

        dialog.add_response("cancel", gettext("Cancel"))
        dialog.set_close_response("cancel")

        # Add buttons for each diagram
        for i, diagram in enumerate(diagrams):
            name = diagram.name or f"Diagram {i + 1}"
            response_id = f"diagram-{i}"
            dialog.add_response(response_id, name)

        response = await dialog.choose(self.parent_window)

        if response.startswith("diagram-"):
            index = int(response.split("-")[1])
            return diagrams[index]

        return None

    def _show_compare_view(
        self, base_diagram: Diagram | None, compare_diagram: Diagram | None
    ):
        """Show the comparison view in a new window."""
        if self._compare_window:
            self._compare_window.destroy()

        self._compare_window = Gtk.Window()
        self._compare_window.set_title(
            gettext("Compare: {name}").format(
                name=base_diagram.name if base_diagram else gettext("Untitled")
            )
        )
        self._compare_window.set_default_size(1200, 800)

        if self.parent_window:
            self._compare_window.set_transient_for(self.parent_window)

        # Create the comparison view
        compare_view = DiagramCompareView(
            base_diagram, compare_diagram, self.element_factory
        )

        self._compare_window.set_child(compare_view)
        self._compare_window.present()

    @action(name="compare-with-version")
    async def compare_with_specific_version(self, version_id: str):
        """Compare with a specific version (for future version control integration)."""
        # This is a placeholder for future version control integration
        # Could integrate with Git, SVN, or other VCS
        self.event_manager.handle(
            Notification(gettext("Version control comparison not yet implemented"))
        )
