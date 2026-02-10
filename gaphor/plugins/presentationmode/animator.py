"""Animation utilities for smooth transitions in presentation mode."""

from __future__ import annotations

import math
from enum import Enum
from typing import TYPE_CHECKING, Callable

from gi.repository import GLib

if TYPE_CHECKING:
    from gaphas.view import GtkView

    from gaphor.plugins.presentationmode.model import SlideRegion


class EasingFunction(Enum):
    """Available easing functions for animations."""

    LINEAR = "linear"
    EASE_IN_QUAD = "ease_in_quad"
    EASE_OUT_QUAD = "ease_out_quad"
    EASE_IN_OUT_QUAD = "ease_in_out_quad"
    EASE_IN_CUBIC = "ease_in_cubic"
    EASE_OUT_CUBIC = "ease_out_cubic"
    EASE_IN_OUT_CUBIC = "ease_in_out_cubic"
    EASE_IN_QUART = "ease_in_quart"
    EASE_OUT_QUART = "ease_out_quart"
    EASE_IN_OUT_QUART = "ease_in_out_quart"
    EASE_IN_QUINT = "ease_in_quint"
    EASE_OUT_QUINT = "ease_out_quint"
    EASE_IN_OUT_QUINT = "ease_in_out_quint"
    EASE_IN_SINE = "ease_in_sine"
    EASE_OUT_SINE = "ease_out_sine"
    EASE_IN_OUT_SINE = "ease_in_out_sine"
    EASE_IN_EXPO = "ease_in_expo"
    EASE_OUT_EXPO = "ease_out_expo"
    EASE_IN_OUT_EXPO = "ease_in_out_expo"
    EASE_IN_CIRC = "ease_in_circ"
    EASE_OUT_CIRC = "ease_out_circ"
    EASE_IN_OUT_CIRC = "ease_in_out_circ"
    EASE_IN_BACK = "ease_in_back"
    EASE_OUT_BACK = "ease_out_back"
    EASE_IN_OUT_BACK = "ease_in_out_back"
    EASE_IN_ELASTIC = "ease_in_elastic"
    EASE_OUT_ELASTIC = "ease_out_elastic"
    EASE_IN_OUT_ELASTIC = "ease_in_out_elastic"
    EASE_IN_BOUNCE = "ease_in_bounce"
    EASE_OUT_BOUNCE = "ease_out_bounce"
    EASE_IN_OUT_BOUNCE = "ease_in_out_bounce"


def linear(t: float) -> float:
    """Linear interpolation - no easing."""
    return t


def ease_in_quad(t: float) -> float:
    """Quadratic ease-in."""
    return t * t


def ease_out_quad(t: float) -> float:
    """Quadratic ease-out."""
    return 1 - (1 - t) * (1 - t)


def ease_in_out_quad(t: float) -> float:
    """Quadratic ease-in-out."""
    if t < 0.5:
        return 2 * t * t
    return 1 - pow(-2 * t + 2, 2) / 2


def ease_in_cubic(t: float) -> float:
    """Cubic ease-in."""
    return t * t * t


def ease_out_cubic(t: float) -> float:
    """Cubic ease-out."""
    return 1 - pow(1 - t, 3)


def ease_in_out_cubic(t: float) -> float:
    """Cubic ease-in-out function for smooth animations."""
    if t < 0.5:
        return 4 * t * t * t
    return 1 - pow(-2 * t + 2, 3) / 2


def ease_in_quart(t: float) -> float:
    """Quartic ease-in."""
    return t * t * t * t


def ease_out_quart(t: float) -> float:
    """Quartic ease-out."""
    return 1 - pow(1 - t, 4)


def ease_in_out_quart(t: float) -> float:
    """Quartic ease-in-out."""
    if t < 0.5:
        return 8 * t * t * t * t
    return 1 - pow(-2 * t + 2, 4) / 2


def ease_in_quint(t: float) -> float:
    """Quintic ease-in."""
    return t * t * t * t * t


def ease_out_quint(t: float) -> float:
    """Quintic ease-out."""
    return 1 - pow(1 - t, 5)


def ease_in_out_quint(t: float) -> float:
    """Quintic ease-in-out."""
    if t < 0.5:
        return 16 * t * t * t * t * t
    return 1 - pow(-2 * t + 2, 5) / 2


def ease_in_sine(t: float) -> float:
    """Sine ease-in."""
    return 1 - math.cos((t * math.pi) / 2)


def ease_out_sine(t: float) -> float:
    """Sine ease-out."""
    return math.sin((t * math.pi) / 2)


def ease_in_out_sine(t: float) -> float:
    """Sine ease-in-out."""
    return -(math.cos(math.pi * t) - 1) / 2


def ease_in_expo(t: float) -> float:
    """Exponential ease-in."""
    return 0 if t == 0 else pow(2, 10 * t - 10)


def ease_out_expo(t: float) -> float:
    """Exponential ease-out."""
    return 1 if t == 1 else 1 - pow(2, -10 * t)


def ease_in_out_expo(t: float) -> float:
    """Exponential ease-in-out."""
    if t == 0:
        return 0
    if t == 1:
        return 1
    if t < 0.5:
        return pow(2, 20 * t - 10) / 2
    return (2 - pow(2, -20 * t + 10)) / 2


def ease_in_circ(t: float) -> float:
    """Circular ease-in."""
    return 1 - math.sqrt(1 - pow(t, 2))


def ease_out_circ(t: float) -> float:
    """Circular ease-out."""
    return math.sqrt(1 - pow(t - 1, 2))


def ease_in_out_circ(t: float) -> float:
    """Circular ease-in-out."""
    if t < 0.5:
        return (1 - math.sqrt(1 - pow(2 * t, 2))) / 2
    return (math.sqrt(1 - pow(-2 * t + 2, 2)) + 1) / 2


def ease_in_back(t: float) -> float:
    """Back ease-in (overshoots then returns)."""
    c1 = 1.70158
    c3 = c1 + 1
    return c3 * t * t * t - c1 * t * t


def ease_out_back(t: float) -> float:
    """Back ease-out."""
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * pow(t - 1, 3) + c1 * pow(t - 1, 2)


def ease_in_out_back(t: float) -> float:
    """Back ease-in-out."""
    c1 = 1.70158
    c2 = c1 * 1.525
    if t < 0.5:
        return (pow(2 * t, 2) * ((c2 + 1) * 2 * t - c2)) / 2
    return (pow(2 * t - 2, 2) * ((c2 + 1) * (t * 2 - 2) + c2) + 2) / 2


def ease_in_elastic(t: float) -> float:
    """Elastic ease-in."""
    if t == 0:
        return 0
    if t == 1:
        return 1
    c4 = (2 * math.pi) / 3
    return -pow(2, 10 * t - 10) * math.sin((t * 10 - 10.75) * c4)


def ease_out_elastic(t: float) -> float:
    """Elastic ease-out."""
    if t == 0:
        return 0
    if t == 1:
        return 1
    c4 = (2 * math.pi) / 3
    return pow(2, -10 * t) * math.sin((t * 10 - 0.75) * c4) + 1


def ease_in_out_elastic(t: float) -> float:
    """Elastic ease-in-out."""
    if t == 0:
        return 0
    if t == 1:
        return 1
    c5 = (2 * math.pi) / 4.5
    if t < 0.5:
        return -(pow(2, 20 * t - 10) * math.sin((20 * t - 11.125) * c5)) / 2
    return (pow(2, -20 * t + 10) * math.sin((20 * t - 11.125) * c5)) / 2 + 1


def ease_out_bounce(t: float) -> float:
    """Bounce ease-out."""
    n1 = 7.5625
    d1 = 2.75
    if t < 1 / d1:
        return n1 * t * t
    elif t < 2 / d1:
        t -= 1.5 / d1
        return n1 * t * t + 0.75
    elif t < 2.5 / d1:
        t -= 2.25 / d1
        return n1 * t * t + 0.9375
    else:
        t -= 2.625 / d1
        return n1 * t * t + 0.984375


def ease_in_bounce(t: float) -> float:
    """Bounce ease-in."""
    return 1 - ease_out_bounce(1 - t)


def ease_in_out_bounce(t: float) -> float:
    """Bounce ease-in-out."""
    if t < 0.5:
        return (1 - ease_out_bounce(1 - 2 * t)) / 2
    return (1 + ease_out_bounce(2 * t - 1)) / 2


EASING_FUNCTIONS: dict[EasingFunction, Callable[[float], float]] = {
    EasingFunction.LINEAR: linear,
    EasingFunction.EASE_IN_QUAD: ease_in_quad,
    EasingFunction.EASE_OUT_QUAD: ease_out_quad,
    EasingFunction.EASE_IN_OUT_QUAD: ease_in_out_quad,
    EasingFunction.EASE_IN_CUBIC: ease_in_cubic,
    EasingFunction.EASE_OUT_CUBIC: ease_out_cubic,
    EasingFunction.EASE_IN_OUT_CUBIC: ease_in_out_cubic,
    EasingFunction.EASE_IN_QUART: ease_in_quart,
    EasingFunction.EASE_OUT_QUART: ease_out_quart,
    EasingFunction.EASE_IN_OUT_QUART: ease_in_out_quart,
    EasingFunction.EASE_IN_QUINT: ease_in_quint,
    EasingFunction.EASE_OUT_QUINT: ease_out_quint,
    EasingFunction.EASE_IN_OUT_QUINT: ease_in_out_quint,
    EasingFunction.EASE_IN_SINE: ease_in_sine,
    EasingFunction.EASE_OUT_SINE: ease_out_sine,
    EasingFunction.EASE_IN_OUT_SINE: ease_in_out_sine,
    EasingFunction.EASE_IN_EXPO: ease_in_expo,
    EasingFunction.EASE_OUT_EXPO: ease_out_expo,
    EasingFunction.EASE_IN_OUT_EXPO: ease_in_out_expo,
    EasingFunction.EASE_IN_CIRC: ease_in_circ,
    EasingFunction.EASE_OUT_CIRC: ease_out_circ,
    EasingFunction.EASE_IN_OUT_CIRC: ease_in_out_circ,
    EasingFunction.EASE_IN_BACK: ease_in_back,
    EasingFunction.EASE_OUT_BACK: ease_out_back,
    EasingFunction.EASE_IN_OUT_BACK: ease_in_out_back,
    EasingFunction.EASE_IN_ELASTIC: ease_in_elastic,
    EasingFunction.EASE_OUT_ELASTIC: ease_out_elastic,
    EasingFunction.EASE_IN_OUT_ELASTIC: ease_in_out_elastic,
    EasingFunction.EASE_IN_BOUNCE: ease_in_bounce,
    EasingFunction.EASE_OUT_BOUNCE: ease_out_bounce,
    EasingFunction.EASE_IN_OUT_BOUNCE: ease_in_out_bounce,
}


def get_easing_function(easing: EasingFunction | str) -> Callable[[float], float]:
    """Get an easing function by name or enum value."""
    if isinstance(easing, str):
        try:
            easing = EasingFunction(easing)
        except ValueError:
            return ease_in_out_cubic
    return EASING_FUNCTIONS.get(easing, ease_in_out_cubic)


class Animation:
    """Base class for animations."""

    def __init__(
        self,
        duration_ms: int = 500,
        easing: EasingFunction = EasingFunction.EASE_IN_OUT_CUBIC,
        on_complete: Callable[[], None] | None = None,
    ):
        self.duration_ms = duration_ms
        self.easing_func = get_easing_function(easing)
        self.on_complete = on_complete
        self._animation_id: int | None = None
        self._is_running = False

    @property
    def is_running(self) -> bool:
        return self._is_running

    def stop(self) -> None:
        """Stop the animation."""
        if self._animation_id is not None:
            GLib.source_remove(self._animation_id)
            self._animation_id = None
        self._is_running = False

    def _finish(self) -> None:
        """Called when animation completes."""
        self._is_running = False
        self._animation_id = None
        if self.on_complete:
            self.on_complete()


class ViewAnimator:
    """Handles smooth animated transitions for the diagram view."""

    def __init__(self, view: GtkView):
        self.view = view
        self._current_animation: Animation | None = None

    def stop_animation(self) -> None:
        """Stop any running animation."""
        if self._current_animation:
            self._current_animation.stop()
            self._current_animation = None

    def animate_to_region(
        self,
        region: SlideRegion,
        duration_ms: int = 500,
        easing: EasingFunction = EasingFunction.EASE_IN_OUT_CUBIC,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        """Animate the view to focus on a specific region."""
        self.stop_animation()

        view = self.view
        view_width = view.get_width()
        view_height = view.get_height()

        if view_width == 0 or view_height == 0:
            if on_complete:
                on_complete()
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

        animation = Animation(duration_ms, easing, on_complete)
        self._current_animation = animation

        start_time = GLib.get_monotonic_time()
        duration_us = duration_ms * 1000

        def animate_step() -> bool:
            if not animation.is_running:
                return False

            elapsed = GLib.get_monotonic_time() - start_time
            progress = min(1.0, elapsed / duration_us)
            eased = animation.easing_func(progress)

            current_scale = start_scale + (target_scale - start_scale) * eased
            current_offset_x = start_offset_x + (target_offset_x - start_offset_x) * eased
            current_offset_y = start_offset_y + (target_offset_y - start_offset_y) * eased

            view.matrix.set(
                current_scale, 0, 0, current_scale, current_offset_x, current_offset_y
            )

            if progress >= 1.0:
                animation._finish()
                return False

            return True

        animation._is_running = True
        animation._animation_id = GLib.timeout_add(16, animate_step)

    def animate_zoom(
        self,
        target_scale: float,
        center_x: float,
        center_y: float,
        duration_ms: int = 300,
        easing: EasingFunction = EasingFunction.EASE_OUT_QUAD,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        """Animate zoom to a specific scale centered on a point."""
        self.stop_animation()

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

        animation = Animation(duration_ms, easing, on_complete)
        self._current_animation = animation

        start_time = GLib.get_monotonic_time()
        duration_us = duration_ms * 1000

        def animate_step() -> bool:
            if not animation.is_running:
                return False

            elapsed = GLib.get_monotonic_time() - start_time
            progress = min(1.0, elapsed / duration_us)
            eased = animation.easing_func(progress)

            current_scale = start_scale + (target_scale - start_scale) * eased
            current_offset_x = start_offset_x + (target_offset_x - start_offset_x) * eased
            current_offset_y = start_offset_y + (target_offset_y - start_offset_y) * eased

            view.matrix.set(
                current_scale, 0, 0, current_scale, current_offset_x, current_offset_y
            )

            if progress >= 1.0:
                animation._finish()
                return False

            return True

        animation._is_running = True
        animation._animation_id = GLib.timeout_add(16, animate_step)

    def animate_pan(
        self,
        target_x: float,
        target_y: float,
        duration_ms: int = 300,
        easing: EasingFunction = EasingFunction.EASE_IN_OUT_CUBIC,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        """Animate panning to a specific position."""
        self.stop_animation()

        view = self.view
        matrix = view.matrix
        start_offset_x = matrix[4]
        start_offset_y = matrix[5]
        scale = matrix[0]

        animation = Animation(duration_ms, easing, on_complete)
        self._current_animation = animation

        start_time = GLib.get_monotonic_time()
        duration_us = duration_ms * 1000

        def animate_step() -> bool:
            if not animation.is_running:
                return False

            elapsed = GLib.get_monotonic_time() - start_time
            progress = min(1.0, elapsed / duration_us)
            eased = animation.easing_func(progress)

            current_offset_x = start_offset_x + (target_x - start_offset_x) * eased
            current_offset_y = start_offset_y + (target_y - start_offset_y) * eased

            view.matrix.set(scale, 0, 0, scale, current_offset_x, current_offset_y)

            if progress >= 1.0:
                animation._finish()
                return False

            return True

        animation._is_running = True
        animation._animation_id = GLib.timeout_add(16, animate_step)

    def fit_to_diagram(
        self,
        duration_ms: int = 500,
        easing: EasingFunction = EasingFunction.EASE_IN_OUT_CUBIC,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        """Animate to fit the entire diagram in view."""
        view = self.view
        if not view.model:
            if on_complete:
                on_complete()
            return

        items = list(view.model.get_all_items())
        if not items:
            if on_complete:
                on_complete()
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
            if on_complete:
                on_complete()
            return

        padding = 50
        from gaphor.plugins.presentationmode.model import SlideRegion

        region = SlideRegion(
            x=min_x - padding,
            y=min_y - padding,
            width=max_x - min_x + 2 * padding,
            height=max_y - min_y + 2 * padding,
        )

        self.animate_to_region(region, duration_ms, easing, on_complete)

    def animate_shake(
        self,
        intensity: float = 10.0,
        duration_ms: int = 500,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        """Animate a shake effect (for emphasis or error indication)."""
        self.stop_animation()

        view = self.view
        matrix = view.matrix
        base_offset_x = matrix[4]
        base_offset_y = matrix[5]
        scale = matrix[0]

        animation = Animation(duration_ms, EasingFunction.LINEAR, on_complete)
        self._current_animation = animation

        start_time = GLib.get_monotonic_time()
        duration_us = duration_ms * 1000
        shake_frequency = 30

        def animate_step() -> bool:
            if not animation.is_running:
                return False

            elapsed = GLib.get_monotonic_time() - start_time
            progress = min(1.0, elapsed / duration_us)

            decay = 1 - progress
            shake = math.sin(progress * shake_frequency * math.pi) * intensity * decay

            view.matrix.set(scale, 0, 0, scale, base_offset_x + shake, base_offset_y)

            if progress >= 1.0:
                view.matrix.set(scale, 0, 0, scale, base_offset_x, base_offset_y)
                animation._finish()
                return False

            return True

        animation._is_running = True
        animation._animation_id = GLib.timeout_add(16, animate_step)

    def animate_pulse(
        self,
        scale_factor: float = 1.05,
        duration_ms: int = 300,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        """Animate a pulse effect (zoom in and out)."""
        self.stop_animation()

        view = self.view
        matrix = view.matrix
        base_scale = matrix[0]
        base_offset_x = matrix[4]
        base_offset_y = matrix[5]

        view_width = view.get_width()
        view_height = view.get_height()

        animation = Animation(duration_ms, EasingFunction.EASE_IN_OUT_SINE, on_complete)
        self._current_animation = animation

        start_time = GLib.get_monotonic_time()
        duration_us = duration_ms * 1000

        def animate_step() -> bool:
            if not animation.is_running:
                return False

            elapsed = GLib.get_monotonic_time() - start_time
            progress = min(1.0, elapsed / duration_us)

            pulse = math.sin(progress * math.pi)
            current_scale = base_scale * (1 + (scale_factor - 1) * pulse)

            center_x = view_width / 2
            center_y = view_height / 2
            diagram_x = (center_x - base_offset_x) / base_scale
            diagram_y = (center_y - base_offset_y) / base_scale

            current_offset_x = center_x - diagram_x * current_scale
            current_offset_y = center_y - diagram_y * current_scale

            view.matrix.set(
                current_scale, 0, 0, current_scale, current_offset_x, current_offset_y
            )

            if progress >= 1.0:
                view.matrix.set(base_scale, 0, 0, base_scale, base_offset_x, base_offset_y)
                animation._finish()
                return False

            return True

        animation._is_running = True
        animation._animation_id = GLib.timeout_add(16, animate_step)
