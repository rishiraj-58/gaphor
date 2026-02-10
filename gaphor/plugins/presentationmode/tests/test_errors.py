"""Tests for error handling utilities."""

import pytest

from gaphor.plugins.presentationmode.errors import (
    AnimationError,
    DiagramNotFoundError,
    PresentationError,
    PresentationLoadError,
    PresentationSaveError,
    SlideLoadError,
    safe_call,
)


class TestPresentationErrors:
    """Tests for presentation error classes."""

    def test_presentation_error_base(self):
        """Test base PresentationError."""
        error = PresentationError("Test error", "Some details")
        assert error.message == "Test error"
        assert error.details == "Some details"
        assert str(error) == "Test error"

    def test_presentation_error_no_details(self):
        """Test PresentationError without details."""
        error = PresentationError("Test error")
        assert error.message == "Test error"
        assert error.details is None

    def test_slide_load_error(self):
        """Test SlideLoadError."""
        error = SlideLoadError("Failed to load slide", "Diagram not found")
        assert isinstance(error, PresentationError)
        assert error.message == "Failed to load slide"
        assert error.details == "Diagram not found"

    def test_diagram_not_found_error(self):
        """Test DiagramNotFoundError."""
        error = DiagramNotFoundError("Diagram missing", "ID: abc123")
        assert isinstance(error, PresentationError)
        assert error.message == "Diagram missing"

    def test_presentation_save_error(self):
        """Test PresentationSaveError."""
        error = PresentationSaveError("Cannot save", "Permission denied")
        assert isinstance(error, PresentationError)
        assert error.message == "Cannot save"

    def test_presentation_load_error(self):
        """Test PresentationLoadError."""
        error = PresentationLoadError("Cannot load", "File corrupted")
        assert isinstance(error, PresentationError)
        assert error.message == "Cannot load"

    def test_animation_error(self):
        """Test AnimationError."""
        error = AnimationError("Animation failed", "Invalid target")
        assert isinstance(error, PresentationError)
        assert error.message == "Animation failed"


class TestSafeCall:
    """Tests for safe_call utility."""

    def test_safe_call_success(self):
        """Test safe_call with successful function."""

        def add(a, b):
            return a + b

        result = safe_call(add, 2, 3)
        assert result == 5

    def test_safe_call_with_exception(self):
        """Test safe_call with function that raises exception."""

        def failing():
            raise ValueError("Something went wrong")

        result = safe_call(failing, default="fallback")
        assert result == "fallback"

    def test_safe_call_default_none(self):
        """Test safe_call with default None."""

        def failing():
            raise Exception("Error")

        result = safe_call(failing)
        assert result is None

    def test_safe_call_with_kwargs(self):
        """Test safe_call with keyword arguments."""

        def greet(name, greeting="Hello"):
            return f"{greeting}, {name}!"

        result = safe_call(greet, "World", greeting="Hi")
        assert result == "Hi, World!"

    def test_safe_call_preserves_return_type(self):
        """Test safe_call preserves return type."""

        def get_list():
            return [1, 2, 3]

        result = safe_call(get_list, default=[])
        assert result == [1, 2, 3]
        assert isinstance(result, list)


class TestErrorInheritance:
    """Tests for error class inheritance."""

    def test_all_errors_inherit_from_base(self):
        """Test all error classes inherit from PresentationError."""
        error_classes = [
            SlideLoadError,
            DiagramNotFoundError,
            PresentationSaveError,
            PresentationLoadError,
            AnimationError,
        ]

        for cls in error_classes:
            error = cls("Test")
            assert isinstance(error, PresentationError)
            assert isinstance(error, Exception)

    def test_errors_can_be_caught_by_base(self):
        """Test errors can be caught by base class."""

        def raise_slide_error():
            raise SlideLoadError("Test")

        try:
            raise_slide_error()
            assert False, "Should have raised"
        except PresentationError as e:
            assert e.message == "Test"

    def test_errors_preserve_traceback(self):
        """Test errors preserve traceback info."""
        try:
            raise PresentationLoadError("Test", "Details")
        except PresentationLoadError as e:
            import traceback

            tb = traceback.format_exc()
            assert "PresentationLoadError" in tb
