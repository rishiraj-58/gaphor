"""Search result data structures for advanced search functionality."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gaphor.core.modeling import Base, Diagram
    from gaphor.core.modeling.presentation import Presentation


class SearchResultType(enum.Enum):
    """Types of search results that can be returned."""

    ELEMENT_NAME = "element_name"
    ELEMENT_TYPE = "element_type"
    ATTRIBUTE_NAME = "attribute_name"
    ATTRIBUTE_VALUE = "attribute_value"
    RELATIONSHIP_TYPE = "relationship_type"
    DIAGRAM_NAME = "diagram_name"


@dataclass
class DiagramLocation:
    """Represents a location where an element appears in a diagram."""

    diagram: Diagram
    presentation: Presentation | None = None

    @property
    def diagram_name(self) -> str:
        if self.diagram is None:
            return "<Unknown>"
        try:
            return self.diagram.name or "<Unnamed Diagram>"
        except Exception:
            return "<Error>"

    @property
    def diagram_id(self) -> str:
        if self.diagram is None:
            return ""
        try:
            return self.diagram.id
        except Exception:
            return ""


@dataclass
class SearchResult:
    """Represents a single search result with full context information."""

    element: Base
    result_type: SearchResultType
    match_field: str
    match_value: str
    relevance_score: float = 1.0
    diagram_locations: list[DiagramLocation] = field(default_factory=list)

    @property
    def element_id(self) -> str:
        if self.element is None:
            return ""
        try:
            return self.element.id
        except Exception:
            return ""

    @property
    def element_name(self) -> str:
        if self.element is None:
            return "<None>"
        try:
            name = getattr(self.element, "name", None)
            return name if name else f"<{self.element_type_name}>"
        except Exception:
            return "<Error>"

    @property
    def element_type_name(self) -> str:
        if self.element is None:
            return "Unknown"
        try:
            return type(self.element).__name__
        except Exception:
            return "Unknown"

    @property
    def description(self) -> str:
        """Human-readable description of what was matched."""
        try:
            if self.result_type == SearchResultType.ELEMENT_NAME:
                return f"Name: {self.match_value}"
            elif self.result_type == SearchResultType.ELEMENT_TYPE:
                return f"Type: {self.match_value}"
            elif self.result_type == SearchResultType.ATTRIBUTE_NAME:
                return f"Attribute: {self.match_field}"
            elif self.result_type == SearchResultType.ATTRIBUTE_VALUE:
                return f"{self.match_field}: {self.match_value}"
            elif self.result_type == SearchResultType.RELATIONSHIP_TYPE:
                return f"Relationship: {self.match_value}"
            elif self.result_type == SearchResultType.DIAGRAM_NAME:
                return f"Diagram: {self.match_value}"
            return str(self.match_value)
        except Exception:
            return "<Error>"

    @property
    def location_summary(self) -> str:
        """Summary of where this element appears in diagrams."""
        if not self.diagram_locations:
            return "Not in any diagram"

        count = len(self.diagram_locations)
        if count == 1:
            return f"In: {self.diagram_locations[0].diagram_name}"

        names = [loc.diagram_name for loc in self.diagram_locations[:3]]
        summary = ", ".join(names)
        if count > 3:
            summary += f" (+{count - 3} more)"
        return f"In: {summary}"

    def __hash__(self) -> int:
        return hash((self.element_id, self.result_type, self.match_field))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SearchResult):
            return False
        return (
            self.element_id == other.element_id
            and self.result_type == other.result_type
            and self.match_field == other.match_field
        )
