"""Data model for presentations.

Defines the structure for slides, hotspots, and presentation configurations.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from gaphor.core.modeling import Diagram


class HotspotAction(Enum):
    """Actions that can be triggered by clicking a hotspot."""

    NAVIGATE_SLIDE = "navigate_slide"
    NAVIGATE_DIAGRAM = "navigate_diagram"
    REVEAL_LAYER = "reveal_layer"
    SHOW_TOOLTIP = "show_tooltip"
    EXTERNAL_LINK = "external_link"


class DrawingToolType(Enum):
    """Types of drawing tools available during presentation."""

    PEN = "pen"
    HIGHLIGHTER = "highlighter"
    ARROW = "arrow"
    RECTANGLE = "rectangle"
    ELLIPSE = "ellipse"
    TEXT = "text"
    LASER_POINTER = "laser_pointer"
    ERASER = "eraser"


@dataclass
class ViewRegion:
    """Defines a rectangular region in diagram coordinates."""

    x: float
    y: float
    width: float
    height: float
    zoom: float = 1.0

    def to_dict(self) -> dict:
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "zoom": self.zoom,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ViewRegion:
        return cls(
            x=data.get("x", 0),
            y=data.get("y", 0),
            width=data.get("width", 800),
            height=data.get("height", 600),
            zoom=data.get("zoom", 1.0),
        )


@dataclass
class Hotspot:
    """A clickable region in a slide that triggers an action."""

    id: str = field(default_factory=lambda: str(uuid4()))
    x: float = 0
    y: float = 0
    width: float = 50
    height: float = 50
    action: HotspotAction = HotspotAction.SHOW_TOOLTIP
    target: str = ""  # Slide ID, diagram ID, URL, or layer name
    tooltip: str = ""
    visible: bool = True  # Whether to show hotspot indicator

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "action": self.action.value,
            "target": self.target,
            "tooltip": self.tooltip,
            "visible": self.visible,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Hotspot:
        return cls(
            id=data.get("id", str(uuid4())),
            x=data.get("x", 0),
            y=data.get("y", 0),
            width=data.get("width", 50),
            height=data.get("height", 50),
            action=HotspotAction(data.get("action", "show_tooltip")),
            target=data.get("target", ""),
            tooltip=data.get("tooltip", ""),
            visible=data.get("visible", True),
        )

    def contains_point(self, px: float, py: float) -> bool:
        """Check if a point is within this hotspot."""
        return (
            self.x <= px <= self.x + self.width
            and self.y <= py <= self.y + self.height
        )


@dataclass
class DrawingAnnotation:
    """An annotation drawn during the presentation."""

    id: str = field(default_factory=lambda: str(uuid4()))
    tool: DrawingToolType = DrawingToolType.PEN
    color: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 1.0)
    line_width: float = 3.0
    points: list[tuple[float, float]] = field(default_factory=list)
    text: str = ""  # For text annotations

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tool": self.tool.value,
            "color": list(self.color),
            "line_width": self.line_width,
            "points": self.points,
            "text": self.text,
        }

    @classmethod
    def from_dict(cls, data: dict) -> DrawingAnnotation:
        return cls(
            id=data.get("id", str(uuid4())),
            tool=DrawingToolType(data.get("tool", "pen")),
            color=tuple(data.get("color", [1.0, 0.0, 0.0, 1.0])),
            line_width=data.get("line_width", 3.0),
            points=data.get("points", []),
            text=data.get("text", ""),
        )


@dataclass
class Slide:
    """A single slide in the presentation."""

    id: str = field(default_factory=lambda: str(uuid4()))
    title: str = ""
    diagram_id: str = ""
    region: ViewRegion = field(default_factory=lambda: ViewRegion(0, 0, 800, 600))
    notes: str = ""
    hotspots: list[Hotspot] = field(default_factory=list)
    annotations: list[DrawingAnnotation] = field(default_factory=list)
    transition_duration: float = 0.5  # seconds
    visible_layers: list[str] = field(default_factory=list)  # Empty = all visible

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "diagram_id": self.diagram_id,
            "region": self.region.to_dict(),
            "notes": self.notes,
            "hotspots": [h.to_dict() for h in self.hotspots],
            "annotations": [a.to_dict() for a in self.annotations],
            "transition_duration": self.transition_duration,
            "visible_layers": self.visible_layers,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Slide:
        return cls(
            id=data.get("id", str(uuid4())),
            title=data.get("title", ""),
            diagram_id=data.get("diagram_id", ""),
            region=ViewRegion.from_dict(data.get("region", {})),
            notes=data.get("notes", ""),
            hotspots=[Hotspot.from_dict(h) for h in data.get("hotspots", [])],
            annotations=[
                DrawingAnnotation.from_dict(a) for a in data.get("annotations", [])
            ],
            transition_duration=data.get("transition_duration", 0.5),
            visible_layers=data.get("visible_layers", []),
        )


@dataclass
class Presentation:
    """A complete presentation consisting of multiple slides."""

    id: str = field(default_factory=lambda: str(uuid4()))
    title: str = "Untitled Presentation"
    slides: list[Slide] = field(default_factory=list)
    default_transition_duration: float = 0.5
    show_hotspot_indicators: bool = True
    loop_presentation: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "slides": [s.to_dict() for s in self.slides],
            "default_transition_duration": self.default_transition_duration,
            "show_hotspot_indicators": self.show_hotspot_indicators,
            "loop_presentation": self.loop_presentation,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Presentation:
        return cls(
            id=data.get("id", str(uuid4())),
            title=data.get("title", "Untitled Presentation"),
            slides=[Slide.from_dict(s) for s in data.get("slides", [])],
            default_transition_duration=data.get("default_transition_duration", 0.5),
            show_hotspot_indicators=data.get("show_hotspot_indicators", True),
            loop_presentation=data.get("loop_presentation", False),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> Presentation:
        return cls.from_dict(json.loads(json_str))

    def add_slide(self, slide: Slide | None = None) -> Slide:
        """Add a new slide to the presentation."""
        if slide is None:
            slide = Slide()
        self.slides.append(slide)
        return slide

    def remove_slide(self, slide_id: str) -> bool:
        """Remove a slide by ID."""
        for i, slide in enumerate(self.slides):
            if slide.id == slide_id:
                self.slides.pop(i)
                return True
        return False

    def get_slide(self, slide_id: str) -> Slide | None:
        """Get a slide by ID."""
        for slide in self.slides:
            if slide.id == slide_id:
                return slide
        return None

    def get_slide_index(self, slide_id: str) -> int:
        """Get the index of a slide by ID."""
        for i, slide in enumerate(self.slides):
            if slide.id == slide_id:
                return i
        return -1

    def move_slide(self, slide_id: str, new_index: int) -> bool:
        """Move a slide to a new position."""
        old_index = self.get_slide_index(slide_id)
        if old_index < 0:
            return False
        slide = self.slides.pop(old_index)
        new_index = max(0, min(new_index, len(self.slides)))
        self.slides.insert(new_index, slide)
        return True
