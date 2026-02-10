"""Animation utilities for smooth transitions in presentation mode."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Callable

from gi.repository import GLib

if TYPE_CHECKING:
    from gaphas.view import GtkView

    from gaphor.plugins.presentationmode.model import SlideRegion


def ease_in_out_cubic(t: float) -> float:
    """Cubic ease-in-out function for smooth animations."""
    if t < 0.5:
        return 4 * t * t * t
    return 1 - pow(-2 * t + 2, 3) / 2


def ease_out_quad(t: float) -> float:
    """Quadratic ease-out function."""
    return 1 - (1 - t) * (1 - t)


class ViewAnimator:
    """Handles smooth animated transitions for the diagram view."""

    def __init__(self, view: GtkView):
        self.view = view
        self._animation_id: int | None = None
        self._on_complete: Callable[[], None] | None = None

    def stop_animation(self) -> None:
        """Stop any running animation."""
        if self._animation_id is not None:
            GLib.source_remove(self._animation_id)
            self._animation_id = None

    def animate_to_region(
        self,
        region: SlideRegion,
        duration_ms: int = 500,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        """Animate the view to focus on a specific region."""
        self.stop_animation()
        self._on_complete = on_complete

        view = self.view
        view_width = view.get_width()
        view_height = view.get_height()

        if view_width == 0 or view_height == 0:
            return

        target_scale_x = view_width / region.width if region.width > 0 else 1.0
        target_scale_y = view_height / region.height if region.height > 0 else 1.0
        target_scale = min(target_scale_x, target_scale_y) * 0.9

        target_center_x = region.x + region.width / 2
        target_center_y = region.y + region.height / 2
        target_offset_x = view_width / 2 - target_center_x * target_scale
        target_offset_y = view_height / 2 - target_center_y * target_scale

        matrix = view.matrix
        start_scale = matrix[0]
        start_offset_x = matrix[4]
        start_offset_y = matrix[5]

        start_time = GLib.get_monotonic_time()
        duration_us = duration_ms * 1000

        def animate_step() -> bool:
            elapsed = GLib.get_monotonic_time() - start_time
            progress = min(1.0, elapsed / duration_us)
            eased = ease_in_out_cubic(progress)

            current_scale = start_scale + (target_scale - start_scale) * eased
            current_offset_x = start_offset_x + (target_offset_x - start_offset_x) * eased
            current_offset_y = start_offset_y + (target_offset_y - start_offset_y) * eased

            view.matrix.set(
                current_scale, 0, 0, current_scale, current_offset_x, current_offset_y
            )

            if progress >= 1.0:
                self._animation_id = None
                if self._on_complete:
                    self._on_complete()
                return False

            return True

        self._animation_id = GLib.timeout_add(16, animate_step)

    def animate_zoom(
        self,
        target_scale: float,
        center_x: float,
        center_y: float,
        duration_ms: int = 300,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        """Animate zoom to a specific scale centered on a point."""
        self.stop_animation()
        self._on_complete = on_complete

        view = self.view
        matrix = view.matrix
        start_scale = matrix[0]
        start_offset_x = matrix[4]
        start_offset_y = matrix[5]

        view_width = view.get_width()
        view_height = view.get_height()
        view_center_x = view_width / 2
        view_center_y = view_height / 2

        diagram_center_x = (view_center_x - start_offset_x) / start_scale
        diagram_center_y = (view_center_y - start_offset_y) / start_scale

        target_offset_x = view_center_x - diagram_center_x * target_scale
        target_offset_y = view_center_y - diagram_center_y * target_scale

        start_time = GLib.get_monotonic_time()
        duration_us = duration_ms * 1000

        def animate_step() -> bool:
            elapsed = GLib.get_monotonic_time() - start_time
            progress = min(1.0, elapsed / duration_us)
            eased = ease_out_quad(progress)

            current_scale = start_scale + (target_scale - start_scale) * eased
            current_offset_x = start_offset_x + (target_offset_x - start_offset_x) * eased
            current_offset_y = start_offset_y + (target_offset_y - start_offset_y) * eased

            view.matrix.set(
                current_scale, 0, 0, current_scale, current_offset_x, current_offset_y
            )

            if progress >= 1.0:
                self._animation_id = None
                if self._on_complete:
                    self._on_complete()
                return False

            return True

        self._animation_id = GLib.timeout_add(16, animate_step)

    def animate_pan(
        self,
        target_x: float,
        target_y: float,
        duration_ms: int = 300,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        """Animate panning to a specific position."""
        self.stop_animation()
        self._on_complete = on_complete

        view = self.view
        matrix = view.matrix
        start_offset_x = matrix[4]
        start_offset_y = matrix[5]
        scale = matrix[0]

        start_time = GLib.get_monotonic_time()
        duration_us = duration_ms * 1000

        def animate_step() -> bool:
            elapsed = GLib.get_monotonic_time() - start_time
            progress = min(1.0, elapsed / duration_us)
            eased = ease_in_out_cubic(progress)

            current_offset_x = start_offset_x + (target_x - start_offset_x) * eased
            current_offset_y = start_offset_y + (target_y - start_offset_y) * eased

            view.matrix.set(scale, 0, 0, scale, current_offset_x, current_offset_y)

            if progress >= 1.0:
                self._animation_id = None
                if self._on_complete:
                    self._on_complete()
                return False

            return True

        self._animation_id = GLib.timeout_add(16, animate_step)

    def fit_to_diagram(
        self, duration_ms: int = 500, on_complete: Callable[[], None] | None = None
    ) -> None:
        """Animate to fit the entire diagram in view."""
        view = self.view
        if not view.model:
            return

        items = list(view.model.get_all_items())
        if not items:
            return

        min_x = min_y = float("inf")
        max_x = max_y = float("-inf")

        for item in items:
            bounds = view.get_item_bounding_box(item)
            if bounds:
                min_x = min(min_x, bounds.x)
                min_y = min(min_y, bounds.y)
                max_x = max(max_x, bounds.x + bounds.width)
                max_y = max(max_y, bounds.y + bounds.height)

        if min_x == float("inf"):
            return

        padding = 50
        region = SlideRegion(
            x=min_x - padding,
            y=min_y - padding,
            width=max_x - min_x + 2 * padding,
            height=max_y - min_y + 2 * padding,
        )

        self.animate_to_region(region, duration_ms, on_complete)
