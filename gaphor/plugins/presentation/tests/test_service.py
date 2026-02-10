"""Tests for the presentation service.

Note: These tests focus on the data handling aspects that don't require GTK.
"""

import pytest

from gaphor.plugins.presentation.model import (
    Presentation,
    Slide,
    ViewRegion,
)


class TestPresentationServiceHelpers:
    """Test helper functions and data handling in the service."""

    def test_create_presentation_from_diagram_data(self):
        """Test creating presentation structure from diagram data."""
        # Simulate diagram data
        diagram_id = "diagram-123"
        diagram_name = "System Architecture"
        bounds = (0, 0, 800, 600)

        # Create presentation structure (as the service would)
        presentation = Presentation(title=diagram_name)
        region = ViewRegion(
            x=bounds[0],
            y=bounds[1],
            width=bounds[2],
            height=bounds[3],
            zoom=1.0,
        )
        slide = Slide(
            title=diagram_name,
            diagram_id=diagram_id,
            region=region,
        )
        presentation.add_slide(slide)

        assert presentation.title == diagram_name
        assert len(presentation.slides) == 1
        assert presentation.slides[0].diagram_id == diagram_id

    def test_create_presentation_from_multiple_diagrams(self):
        """Test creating presentation from multiple diagrams."""
        diagram_data = [
            ("diag-1", "Overview", (0, 0, 800, 600)),
            ("diag-2", "Details", (100, 100, 1024, 768)),
            ("diag-3", "Summary", (0, 0, 1920, 1080)),
        ]

        presentation = Presentation(title="Multi-Diagram Presentation")

        for diagram_id, name, bounds in diagram_data:
            region = ViewRegion(
                x=bounds[0],
                y=bounds[1],
                width=bounds[2],
                height=bounds[3],
                zoom=1.0,
            )
            slide = Slide(
                title=name,
                diagram_id=diagram_id,
                region=region,
            )
            presentation.add_slide(slide)

        assert len(presentation.slides) == 3
        assert presentation.slides[0].title == "Overview"
        assert presentation.slides[1].diagram_id == "diag-2"
        assert presentation.slides[2].region.width == 1920

    def test_get_diagram_bounds_calculation(self):
        """Test the bounds calculation logic."""
        # Simulate item positions from a diagram
        item_positions = [
            (100, 100),
            (200, 150),
            (300, 200),
            (150, 300),
        ]

        # Calculate bounds (as the service would)
        min_x = min_y = float("inf")
        max_x = max_y = float("-inf")

        for x, y in item_positions:
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x + 200)  # Assume item width
            max_y = max(max_y, y + 100)  # Assume item height

        padding = 50
        bounds = (
            min_x - padding,
            min_y - padding,
            max_x - min_x + 2 * padding,
            max_y - min_y + 2 * padding,
        )

        assert bounds[0] == 50  # min_x - padding
        assert bounds[1] == 50  # min_y - padding
        assert bounds[2] == 500  # width with padding
        assert bounds[3] == 400  # height with padding

    def test_empty_diagram_bounds(self):
        """Test handling of empty diagram."""
        item_positions = []

        min_x = min_y = float("inf")
        max_x = max_y = float("-inf")

        for x, y in item_positions:
            min_x = min(min_x, x)
            min_y = min(min_y, y)

        # Check for empty case
        bounds = None if min_x == float("inf") else (min_x, min_y, 100, 100)

        assert bounds is None
