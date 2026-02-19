"""Model comparison service for Gaphor.

This service handles loading models for comparison and coordinating
the diff computation and UI display.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

from gi.repository import Gio, Gtk

from gaphor.abc import ActionProvider, Service
from gaphor.core import action, event_handler, gettext
from gaphor.core.modeling import Diagram, ElementFactory, ModelReady
from gaphor.event import Notification
from gaphor.storage import load_generator
from gaphor.ui.filedialog import GAPHOR_FILTER, open_file_dialog
from gaphor.ui.modelcompare.differ import ModelDiff, compute_model_diff
from gaphor.ui.statuswindow import StatusWindow

if TYPE_CHECKING:
    from gaphor.core.modeling.modelinglanguage import ModelingLanguage

log = logging.getLogger(__name__)


class ModelCompareService(Service, ActionProvider):
    """Service for comparing model versions."""

    def __init__(
        self,
        event_manager,
        element_factory: ElementFactory,
        modeling_language: "ModelingLanguage",
        main_window,
        diagrams,
    ):
        self.event_manager = event_manager
        self.element_factory = element_factory
        self.modeling_language = modeling_language
        self.main_window = main_window
        self.diagrams = diagrams
        self._current_diff: ModelDiff | None = None
        self._compare_factory: ElementFactory | None = None
        self._compare_window = None

        event_manager.subscribe(self._on_model_ready)

    def shutdown(self):
        """Clean up resources."""
        self.event_manager.unsubscribe(self._on_model_ready)
        if self._compare_factory:
            try:
                self._compare_factory.shutdown()
            except Exception:
                pass
        self._compare_factory = None
        self._current_diff = None
        self._close_compare_window()

    @property
    def parent_window(self):
        """Get the parent window for dialogs."""
        return self.main_window.window if self.main_window else None

    @property
    def current_diagram(self) -> Diagram | None:
        """Get the currently open diagram."""
        if not self.diagrams:
            return None
        try:
            return self.diagrams.get_current_diagram()
        except Exception:
            return None

    @property
    def has_comparison(self) -> bool:
        """Check if a comparison is currently active."""
        return self._current_diff is not None and self._current_diff.has_changes

    @action(name="compare-with-file", shortcut="<Primary><Shift>d")
    async def compare_with_file(self):
        """Open file dialog and compare current model with selected file."""
        if not self.parent_window:
            log.warning("No parent window available for file dialog")
            return

        try:
            filename = await open_file_dialog(
                gettext("Select Model to Compare With"),
                parent=self.parent_window,
                filters=GAPHOR_FILTER,
                multiple=False,
            )

            if filename:
                await self._load_and_compare(filename)
        except Exception as e:
            log.exception("Error in compare_with_file")
            self.event_manager.handle(
                Notification(gettext("Error comparing models: {error}").format(error=e))
            )

    async def _load_and_compare(self, compare_path: Path):
        """Load the comparison model and compute the diff."""
        if not compare_path or not compare_path.exists():
            self.event_manager.handle(
                Notification(
                    gettext("File not found: {path}").format(path=compare_path)
                )
            )
            return

        status_window = StatusWindow(
            gettext("Comparing Models..."),
            gettext("Loading model from {filename}").format(filename=compare_path.name),
            parent=self.parent_window,
        )

        try:
            # Create a new element factory for the comparison model
            compare_factory = ElementFactory()

            await self._load_model_async(
                compare_path, compare_factory, status_window.progress
            )

            # Compute the diff
            self._current_diff = compute_model_diff(
                self.element_factory,
                compare_factory,
                base_path=None,  # Current model in memory
                compare_path=str(compare_path),
            )

            self._compare_factory = compare_factory

            if self._current_diff.errors:
                for error in self._current_diff.errors:
                    log.warning("Diff error: %s", error)

            # Show comparison results
            self._show_comparison_results()

        except Exception as e:
            log.exception("Error loading comparison model")
            self.event_manager.handle(
                Notification(
                    gettext("Error loading model: {error}").format(error=str(e))
                )
            )
        finally:
            status_window.done()

    async def _load_model_async(
        self,
        filepath: Path,
        factory: ElementFactory,
        progress: Callable[[float], Awaitable[None]] | None = None,
    ):
        """Load a model file into the given element factory."""
        if not filepath.exists():
            raise FileNotFoundError(f"Model file not found: {filepath}")

        try:
            with filepath.open(encoding="utf-8", errors="replace") as file_obj:
                for percentage in load_generator(
                    file_obj,
                    factory,
                    self.modeling_language,
                ):
                    if progress:
                        await progress(percentage)
        except Exception as e:
            log.exception("Error loading model file %s", filepath)
            raise RuntimeError(f"Failed to load model: {e}") from e

    def _show_comparison_results(self):
        """Display the comparison results in a new window."""
        if not self._current_diff:
            self.event_manager.handle(
                Notification(gettext("No comparison results available."))
            )
            return

        if not self._current_diff.has_changes:
            self.event_manager.handle(
                Notification(gettext("No differences found between models."))
            )
            return

        # Import here to avoid circular imports
        from gaphor.ui.modelcompare.window import ModelCompareWindow

        self._close_compare_window()

        self._compare_window = ModelCompareWindow(
            diff=self._current_diff,
            base_factory=self.element_factory,
            compare_factory=self._compare_factory,
            parent=self.parent_window,
            on_close=self._on_compare_window_closed,
            on_navigate=self._navigate_to_element,
        )
        self._compare_window.show()

    def _close_compare_window(self):
        """Close the comparison window if open."""
        if self._compare_window:
            try:
                self._compare_window.close()
            except Exception:
                pass
            self._compare_window = None

    def _on_compare_window_closed(self):
        """Handle comparison window being closed."""
        self._compare_window = None

    def _navigate_to_element(self, element_id: str):
        """Navigate to an element in the main editor."""
        if not element_id:
            return

        element = self.element_factory.lookup(element_id)
        if not element:
            self.event_manager.handle(
                Notification(
                    gettext("Element not found in current model.")
                )
            )
            return

        # If it's a diagram, open it
        if isinstance(element, Diagram):
            from gaphor.diagram.event import DiagramOpened

            self.event_manager.handle(DiagramOpened(element))
            return

        # If it's a presentation, try to select it
        if hasattr(element, "diagram") and element.diagram:
            from gaphor.diagram.event import DiagramOpened

            self.event_manager.handle(DiagramOpened(element.diagram))

        # Notify about the element
        self.event_manager.handle(
            Notification(
                gettext("Navigated to element: {name}").format(
                    name=getattr(element, "name", element_id[:8])
                )
            )
        )

    @event_handler(ModelReady)
    def _on_model_ready(self, event):
        """Clear comparison when a new model is loaded."""
        self._current_diff = None
        if self._compare_factory:
            try:
                self._compare_factory.shutdown()
            except Exception:
                pass
            self._compare_factory = None
        self._close_compare_window()

    def get_current_diff(self) -> ModelDiff | None:
        """Get the current comparison diff, if any."""
        return self._current_diff

    def clear_comparison(self):
        """Clear the current comparison."""
        self._current_diff = None
        if self._compare_factory:
            try:
                self._compare_factory.shutdown()
            except Exception:
                pass
            self._compare_factory = None
        self._close_compare_window()
