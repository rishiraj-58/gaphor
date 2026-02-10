"""Data models for presentation mode."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gaphor.core.modeling import Diagram


@dataclass
class SlideRegion:
    """A region within a diagram to focus on during presentation."""

    x: float
    y: float
    width: float
    height: float


@dataclass
class Slide:
    """A single slide in the presentation."""

    diagram: Diagram
    region: SlideRegion | None = None
    notes: str = ""
    title: str = ""
    reveal_elements: list[str] = field(default_factory=list)
    linked_diagram_id: str | None = None


@dataclass
class Presentation:
    """A complete presentation consisting of multiple slides."""

    name: str = "Untitled Presentation"
    slides: list[Slide] = field(default_factory=list)
    current_index: int = 0

    def add_slide(self, slide: Slide) -> None:
        self.slides.append(slide)

    def remove_slide(self, index: int) -> None:
        if 0 <= index < len(self.slides):
            self.slides.pop(index)
            if self.current_index >= len(self.slides):
                self.current_index = max(0, len(self.slides) - 1)

    def move_slide(self, from_index: int, to_index: int) -> None:
        if 0 <= from_index < len(self.slides) and 0 <= to_index < len(self.slides):
            slide = self.slides.pop(from_index)
            self.slides.insert(to_index, slide)

    def get_current_slide(self) -> Slide | None:
        if 0 <= self.current_index < len(self.slides):
            return self.slides[self.current_index]
        return None

    def next_slide(self) -> Slide | None:
        if self.current_index < len(self.slides) - 1:
            self.current_index += 1
        return self.get_current_slide()

    def previous_slide(self) -> Slide | None:
        if self.current_index > 0:
            self.current_index -= 1
        return self.get_current_slide()

    def go_to_slide(self, index: int) -> Slide | None:
        if 0 <= index < len(self.slides):
            self.current_index = index
        return self.get_current_slide()


@dataclass
class DrawingAnnotation:
    """An annotation drawn on top of the presentation."""

    points: list[tuple[float, float]] = field(default_factory=list)
    color: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 1.0)
    line_width: float = 3.0
    tool: str = "pen"  # pen, highlighter, arrow, rectangle, ellipse
