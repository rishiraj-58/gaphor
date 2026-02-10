"""Test configuration for presentation plugin tests."""

import pytest


@pytest.fixture
def sample_presentation():
    """Create a sample presentation for testing."""
    from gaphor.plugins.presentation.model import (
        Hotspot,
        HotspotAction,
        Presentation,
        Slide,
        ViewRegion,
    )

    presentation = Presentation(title="Test Presentation")

    slide1 = Slide(
        title="Introduction",
        diagram_id="diagram-1",
        region=ViewRegion(0, 0, 800, 600, 1.0),
        notes="Welcome to the presentation",
    )
    slide1.hotspots.append(
        Hotspot(
            x=100,
            y=100,
            width=50,
            height=50,
            action=HotspotAction.NAVIGATE_SLIDE,
            target="",
            tooltip="Next slide",
        )
    )

    slide2 = Slide(
        title="Details",
        diagram_id="diagram-1",
        region=ViewRegion(200, 200, 400, 300, 2.0),
        notes="Detailed view of the system",
    )

    slide3 = Slide(
        title="Summary",
        diagram_id="diagram-2",
        region=ViewRegion(0, 0, 1920, 1080, 0.5),
        notes="Summary and conclusions",
    )

    presentation.add_slide(slide1)
    presentation.add_slide(slide2)
    presentation.add_slide(slide3)

    # Update the hotspot target to point to slide2
    slide1.hotspots[0].target = slide2.id

    return presentation
