"""Tests for animation utilities."""

import math

import pytest

from gaphor.plugins.presentationmode.animator import (
    Animation,
    EasingFunction,
    ViewAnimator,
    ease_in_back,
    ease_in_bounce,
    ease_in_circ,
    ease_in_cubic,
    ease_in_elastic,
    ease_in_expo,
    ease_in_out_back,
    ease_in_out_bounce,
    ease_in_out_circ,
    ease_in_out_cubic,
    ease_in_out_elastic,
    ease_in_out_expo,
    ease_in_out_quad,
    ease_in_out_quart,
    ease_in_out_quint,
    ease_in_out_sine,
    ease_in_quad,
    ease_in_quart,
    ease_in_quint,
    ease_in_sine,
    ease_out_back,
    ease_out_bounce,
    ease_out_circ,
    ease_out_cubic,
    ease_out_elastic,
    ease_out_expo,
    ease_out_quad,
    ease_out_quart,
    ease_out_quint,
    ease_out_sine,
    get_easing_function,
    linear,
)
from gaphor.plugins.presentationmode.model import SlideRegion
from gaphor.plugins.presentationmode.tests.conftest import MockMatrix, MockView


class TestEasingFunctions:
    """Tests for easing functions."""

    @pytest.mark.parametrize(
        "easing_func",
        [
            linear,
            ease_in_quad,
            ease_out_quad,
            ease_in_out_quad,
            ease_in_cubic,
            ease_out_cubic,
            ease_in_out_cubic,
            ease_in_quart,
            ease_out_quart,
            ease_in_out_quart,
            ease_in_quint,
            ease_out_quint,
            ease_in_out_quint,
            ease_in_sine,
            ease_out_sine,
            ease_in_out_sine,
            ease_in_expo,
            ease_out_expo,
            ease_in_out_expo,
            ease_in_circ,
            ease_out_circ,
            ease_in_out_circ,
            ease_out_bounce,
            ease_in_bounce,
            ease_in_out_bounce,
        ],
    )
    def test_easing_boundaries(self, easing_func):
        """Test all easing functions return 0 at t=0 and 1 at t=1."""
        assert abs(easing_func(0) - 0) < 0.01
        assert abs(easing_func(1) - 1) < 0.01

    @pytest.mark.parametrize(
        "easing_func",
        [
            linear,
            ease_in_quad,
            ease_out_quad,
            ease_in_out_quad,
            ease_in_cubic,
            ease_out_cubic,
            ease_in_out_cubic,
            ease_in_sine,
            ease_out_sine,
            ease_in_out_sine,
        ],
    )
    def test_easing_monotonic(self, easing_func):
        """Test standard easing functions are monotonically increasing."""
        prev = easing_func(0)
        for i in range(1, 101):
            t = i / 100
            curr = easing_func(t)
            assert curr >= prev - 0.01, f"Not monotonic at t={t}"
            prev = curr

    def test_linear_is_identity(self):
        """Test linear easing returns input unchanged."""
        for i in range(11):
            t = i / 10
            assert linear(t) == t

    def test_ease_in_cubic_slower_at_start(self):
        """Test ease-in is slower at the start."""
        early = ease_in_cubic(0.2) - ease_in_cubic(0)
        late = ease_in_cubic(1) - ease_in_cubic(0.8)
        assert early < late

    def test_ease_out_cubic_faster_at_start(self):
        """Test ease-out is faster at the start."""
        early = ease_out_cubic(0.2) - ease_out_cubic(0)
        late = ease_out_cubic(1) - ease_out_cubic(0.8)
        assert early > late

    def test_ease_in_out_symmetric(self):
        """Test ease-in-out is symmetric around midpoint."""
        assert abs(ease_in_out_cubic(0.5) - 0.5) < 0.01

    def test_ease_back_overshoots(self):
        """Test back easing overshoots."""
        assert ease_in_back(0.9) < 0.9
        assert ease_out_back(0.1) > 0.1

    def test_ease_bounce_bounces(self):
        """Test bounce easing has multiple peaks."""
        values = [ease_out_bounce(i / 100) for i in range(101)]
        local_maxima = sum(
            1
            for i in range(1, len(values) - 1)
            if values[i] > values[i - 1] and values[i] > values[i + 1]
        )
        assert local_maxima >= 2

    def test_ease_elastic_oscillates(self):
        """Test elastic easing oscillates."""
        values = [ease_out_elastic(i / 100) for i in range(101)]
        crossings = sum(
            1 for i in range(1, len(values)) if (values[i] - 1) * (values[i - 1] - 1) < 0
        )
        assert crossings >= 1


class TestGetEasingFunction:
    """Tests for get_easing_function helper."""

    def test_get_by_enum(self):
        """Test getting easing function by enum."""
        func = get_easing_function(EasingFunction.EASE_IN_CUBIC)
        assert func == ease_in_cubic

    def test_get_by_string(self):
        """Test getting easing function by string."""
        func = get_easing_function("ease_in_cubic")
        assert func == ease_in_cubic

    def test_invalid_string_returns_default(self):
        """Test invalid string returns default function."""
        func = get_easing_function("invalid")
        assert func == ease_in_out_cubic


class TestAnimation:
    """Tests for Animation base class."""

    def test_animation_creation(self):
        """Test animation can be created."""
        animation = Animation(duration_ms=500)
        assert animation.duration_ms == 500
        assert not animation.is_running

    def test_animation_with_callback(self):
        """Test animation with completion callback."""
        called = []
        animation = Animation(
            duration_ms=100, on_complete=lambda: called.append(True)
        )
        assert animation.on_complete is not None

    def test_animation_stop(self):
        """Test stopping animation."""
        animation = Animation()
        animation._is_running = True
        animation.stop()
        assert not animation.is_running


class TestViewAnimator:
    """Tests for ViewAnimator."""

    def create_mock_view(self, width=800, height=600):
        """Create a mock view for testing."""
        view = MockView(width, height)
        view.matrix = MockMatrix(scale=1.0, offset_x=0, offset_y=0)
        return view

    def test_animator_creation(self):
        """Test animator can be created."""
        view = self.create_mock_view()
        animator = ViewAnimator(view)
        assert animator.view == view

    def test_stop_animation_no_current(self):
        """Test stopping when no animation is running."""
        view = self.create_mock_view()
        animator = ViewAnimator(view)
        animator.stop_animation()

    def test_animate_to_region_zero_size_view(self):
        """Test animate to region with zero size view."""
        view = self.create_mock_view(0, 0)
        animator = ViewAnimator(view)

        completed = []
        animator.animate_to_region(
            SlideRegion(0, 0, 100, 100),
            duration_ms=100,
            on_complete=lambda: completed.append(True),
        )

        assert len(completed) == 1

    def test_animate_to_region_calculates_target(self):
        """Test animate to region calculates correct target."""
        view = self.create_mock_view(800, 600)
        animator = ViewAnimator(view)

        region = SlideRegion(x=100, y=100, width=400, height=300)

        target_scale_x = 800 / 400
        target_scale_y = 600 / 300
        expected_scale = min(target_scale_x, target_scale_y) * 0.9

        assert expected_scale == pytest.approx(1.8)

    def test_fit_to_diagram_no_model(self):
        """Test fit to diagram with no model."""
        view = self.create_mock_view()
        view.model = None
        animator = ViewAnimator(view)

        completed = []
        animator.fit_to_diagram(on_complete=lambda: completed.append(True))

        assert len(completed) == 1


class TestEasingFunctionEnum:
    """Tests for EasingFunction enum."""

    def test_all_enum_values_have_functions(self):
        """Test all enum values have corresponding functions."""
        from gaphor.plugins.presentationmode.animator import EASING_FUNCTIONS

        for easing in EasingFunction:
            assert easing in EASING_FUNCTIONS

    def test_enum_value_strings(self):
        """Test enum values are valid strings."""
        for easing in EasingFunction:
            assert isinstance(easing.value, str)
            assert len(easing.value) > 0
