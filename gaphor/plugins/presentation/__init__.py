"""Presentation Mode Plugin for Gaphor.

This plugin provides interactive slideshow functionality for presenting
diagrams during reviews or stakeholder presentations.

Features:
- Smooth zoom/pan animations between diagram regions
- Presenter notes for each slide
- Clickable hotspots for navigation and revealing information
- Keyboard navigation
- Drawing tools for annotations
"""

from gaphor.plugins.presentation.service import PresentationService

__all__ = ["PresentationService"]
