"""Tests for animation utilities."""

import pytest

from gaphor.plugins.presentationmode.animator import (
    ease_in_out_cubic,
    ease_out_quad,
)


def test_ease_in_out_cubic_start():
    assert ease_in_out_cubic(0) == 0


def test_ease_in_out_cubic_end():
    assert ease_in_out_cubic(1) == 1


def test_ease_in_out_cubic_midpoint():
    result = ease_in_out_cubic(0.5)
    assert 0.4 < result < 0.6


def test_ease_in_out_cubic_smooth():
    prev = ease_in_out_cubic(0)
    for i in range(1, 11):
        t = i / 10
        curr = ease_in_out_cubic(t)
        assert curr >= prev
        prev = curr


def test_ease_out_quad_start():
    assert ease_out_quad(0) == 0


def test_ease_out_quad_end():
    assert ease_out_quad(1) == 1


def test_ease_out_quad_faster_at_start():
    early = ease_out_quad(0.2) - ease_out_quad(0)
    late = ease_out_quad(1) - ease_out_quad(0.8)
    assert early > late
