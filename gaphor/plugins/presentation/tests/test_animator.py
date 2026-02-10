"""Tests for the animation utilities."""

import pytest

from gaphor.plugins.presentation.animator import (
    EasingFunction,
    ViewAnimator,
    ViewState,
    ease_in_cubic,
    ease_in_out_cubic,
    ease_in_out_quad,
    ease_in_quad,
    ease_linear,
    ease_out_cubic,
    ease_out_quad,
)


class TestEasingFunctions:
    def test_ease_linear(self):
        assert ease_linear(0.0) == 0.0
        assert ease_linear(0.5) == 0.5
        assert ease_linear(1.0) == 1.0

    def test_ease_in_quad(self):
        assert ease_in_quad(0.0) == 0.0
        assert ease_in_quad(0.5) == 0.25
        assert ease_in_quad(1.0) == 1.0

    def test_ease_out_quad(self):
        assert ease_out_quad(0.0) == 0.0
        assert ease_out_quad(0.5) == 0.75
        assert ease_out_quad(1.0) == 1.0

    def test_ease_in_out_quad(self):
        assert ease_in_out_quad(0.0) == 0.0
        assert ease_in_out_quad(0.5) == 0.5
        assert ease_in_out_quad(1.0) == 1.0
        # Should be slower at start and end
        assert ease_in_out_quad(0.25) < 0.25
        assert ease_in_out_quad(0.75) > 0.75

    def test_ease_in_cubic(self):
        assert ease_in_cubic(0.0) == 0.0
        assert ease_in_cubic(0.5) == 0.125
        assert ease_in_cubic(1.0) == 1.0

    def test_ease_out_cubic(self):
        assert ease_out_cubic(0.0) == 0.0
        assert ease_out_cubic(1.0) == 1.0
        # Should be faster at start
        assert ease_out_cubic(0.5) > 0.5

    def test_ease_in_out_cubic(self):
        assert ease_in_out_cubic(0.0) == 0.0
        assert ease_in_out_cubic(0.5) == 0.5
        assert ease_in_out_cubic(1.0) == 1.0


class TestViewState:
    def test_create_view_state(self):
        state = ViewState(x=100, y=200, zoom=1.5)

        assert state.x == 100
        assert state.y == 200
        assert state.zoom == 1.5

    def test_interpolate_same_state(self):
        state = ViewState(x=100, y=200, zoom=1.0)

        result = state.interpolate(state, 0.5)

        assert result.x == 100
        assert result.y == 200
        assert result.zoom == 1.0

    def test_interpolate_start(self):
        start = ViewState(x=0, y=0, zoom=1.0)
        end = ViewState(x=100, y=200, zoom=2.0)

        result = start.interpolate(end, 0.0)

        assert result.x == 0
        assert result.y == 0
        assert result.zoom == 1.0

    def test_interpolate_end(self):
        start = ViewState(x=0, y=0, zoom=1.0)
        end = ViewState(x=100, y=200, zoom=2.0)

        result = start.interpolate(end, 1.0)

        assert result.x == 100
        assert result.y == 200
        assert result.zoom == 2.0

    def test_interpolate_middle(self):
        start = ViewState(x=0, y=0, zoom=1.0)
        end = ViewState(x=100, y=200, zoom=2.0)

        result = start.interpolate(end, 0.5)

        assert result.x == 50
        assert result.y == 100
        assert result.zoom == 1.5


class TestViewAnimator:
    def test_create_animator(self):
        updates = []
        animator = ViewAnimator(lambda state: updates.append(state))

        assert not animator.is_animating

    def test_immediate_animation(self):
        updates = []
        completes = []

        animator = ViewAnimator(
            lambda state: updates.append(state),
            lambda: completes.append(True),
        )

        from_state = ViewState(0, 0, 1.0)
        to_state = ViewState(100, 100, 2.0)

        animator.animate_to(from_state, to_state, duration=0)

        assert len(updates) == 1
        assert updates[0].x == 100
        assert updates[0].zoom == 2.0
        assert len(completes) == 1

    def test_cancel_animation(self):
        animator = ViewAnimator(lambda state: None)

        from_state = ViewState(0, 0, 1.0)
        to_state = ViewState(100, 100, 2.0)

        animator.animate_to(from_state, to_state, duration=1.0)
        animator.cancel()

        assert not animator.is_animating
