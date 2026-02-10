"""Animation utilities for smooth transitions in presentations.

Handles smooth zoom/pan animations between slides.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from gi.repository import GLib


class EasingFunction(Enum):
    """Available easing functions for animations."""

    LINEAR = "linear"
    EASE_IN = "ease_in"
    EASE_OUT = "ease_out"
    EASE_IN_OUT = "ease_in_out"
    EASE_IN_CUBIC = "ease_in_cubic"
    EASE_OUT_CUBIC = "ease_out_cubic"
    EASE_IN_OUT_CUBIC = "ease_in_out_cubic"


def ease_linear(t: float) -> float:
    return t


def ease_in_quad(t: float) -> float:
    return t * t


def ease_out_quad(t: float) -> float:
    return 1 - (1 - t) * (1 - t)


def ease_in_out_quad(t: float) -> float:
    if t < 0.5:
        return 2 * t * t
    return 1 - pow(-2 * t + 2, 2) / 2


def ease_in_cubic(t: float) -> float:
    return t * t * t


def ease_out_cubic(t: float) -> float:
    return 1 - pow(1 - t, 3)


def ease_in_out_cubic(t: float) -> float:
    if t < 0.5:
        return 4 * t * t * t
    return 1 - pow(-2 * t + 2, 3) / 2


EASING_FUNCTIONS = {
    EasingFunction.LINEAR: ease_linear,
    EasingFunction.EASE_IN: ease_in_quad,
    EasingFunction.EASE_OUT: ease_out_quad,
    EasingFunction.EASE_IN_OUT: ease_in_out_quad,
    EasingFunction.EASE_IN_CUBIC: ease_in_cubic,
    EasingFunction.EASE_OUT_CUBIC: ease_out_cubic,
    EasingFunction.EASE_IN_OUT_CUBIC: ease_in_out_cubic,
}


@dataclass
class ViewState:
    """Represents the current view state (position, zoom)."""

    x: float
    y: float
    zoom: float

    def interpolate(self, target: ViewState, t: float) -> ViewState:
        """Interpolate between this state and a target state."""
        return ViewState(
            x=self.x + (target.x - self.x) * t,
            y=self.y + (target.y - self.y) * t,
            zoom=self.zoom + (target.zoom - self.zoom) * t,
        )


class ViewAnimator:
    """Handles smooth animated transitions between view states."""

    def __init__(
        self,
        update_callback: Callable[[ViewState], None],
        complete_callback: Callable[[], None] | None = None,
    ):
        self._update_callback = update_callback
        self._complete_callback = complete_callback
        self._animation_id: int | None = None
        self._start_state: ViewState | None = None
        self._target_state: ViewState | None = None
        self._start_time: float = 0
        self._duration: float = 0
        self._easing: EasingFunction = EasingFunction.EASE_IN_OUT_CUBIC

    def animate_to(
        self,
        from_state: ViewState,
        to_state: ViewState,
        duration: float = 0.5,
        easing: EasingFunction = EasingFunction.EASE_IN_OUT_CUBIC,
    ) -> None:
        """Start an animation from one view state to another."""
        self.cancel()

        if duration <= 0:
            self._update_callback(to_state)
            if self._complete_callback:
                self._complete_callback()
            return

        self._start_state = from_state
        self._target_state = to_state
        self._start_time = time.monotonic()
        self._duration = duration
        self._easing = easing

        self._animation_id = GLib.timeout_add(16, self._tick)

    def _tick(self) -> bool:
        """Animation tick function called by GLib timer."""
        if self._start_state is None or self._target_state is None:
            return False

        elapsed = time.monotonic() - self._start_time
        progress = min(elapsed / self._duration, 1.0)

        easing_func = EASING_FUNCTIONS.get(self._easing, ease_linear)
        eased_progress = easing_func(progress)

        current_state = self._start_state.interpolate(
            self._target_state, eased_progress
        )
        self._update_callback(current_state)

        if progress >= 1.0:
            self._animation_id = None
            self._start_state = None
            self._target_state = None
            if self._complete_callback:
                self._complete_callback()
            return False

        return True

    def cancel(self) -> None:
        """Cancel any running animation."""
        if self._animation_id is not None:
            GLib.source_remove(self._animation_id)
            self._animation_id = None
        self._start_state = None
        self._target_state = None

    @property
    def is_animating(self) -> bool:
        """Check if an animation is currently running."""
        return self._animation_id is not None


class LaserPointerAnimator:
    """Animates a laser pointer effect that fades out."""

    def __init__(
        self,
        update_callback: Callable[[list[tuple[float, float, float]]], None],
        max_points: int = 50,
        fade_duration: float = 1.0,
    ):
        self._update_callback = update_callback
        self._max_points = max_points
        self._fade_duration = fade_duration
        self._points: list[tuple[float, float, float]] = []  # x, y, timestamp
        self._animation_id: int | None = None

    def add_point(self, x: float, y: float) -> None:
        """Add a point to the laser pointer trail."""
        current_time = time.monotonic()
        self._points.append((x, y, current_time))

        if len(self._points) > self._max_points:
            self._points = self._points[-self._max_points :]

        if self._animation_id is None:
            self._animation_id = GLib.timeout_add(16, self._tick)

    def _tick(self) -> bool:
        """Update the laser pointer trail."""
        current_time = time.monotonic()
        cutoff_time = current_time - self._fade_duration

        self._points = [(x, y, t) for x, y, t in self._points if t > cutoff_time]

        points_with_alpha = []
        for x, y, t in self._points:
            age = current_time - t
            alpha = max(0, 1 - age / self._fade_duration)
            points_with_alpha.append((x, y, alpha))

        self._update_callback(points_with_alpha)

        if not self._points:
            self._animation_id = None
            return False

        return True

    def clear(self) -> None:
        """Clear all points and stop the animation."""
        self._points.clear()
        if self._animation_id is not None:
            GLib.source_remove(self._animation_id)
            self._animation_id = None
        self._update_callback([])
