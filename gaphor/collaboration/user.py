"""User representation for collaboration sessions."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import ClassVar


# Predefined color palette for user cursors (distinct, visually pleasing colors)
USER_COLORS: list[tuple[float, float, float, float]] = [
    (0.2, 0.6, 1.0, 1.0),    # Blue
    (0.9, 0.3, 0.3, 1.0),    # Red
    (0.3, 0.8, 0.3, 1.0),    # Green
    (0.9, 0.6, 0.1, 1.0),    # Orange
    (0.7, 0.3, 0.9, 1.0),    # Purple
    (0.1, 0.8, 0.8, 1.0),    # Cyan
    (0.9, 0.2, 0.6, 1.0),    # Pink
    (0.6, 0.8, 0.2, 1.0),    # Lime
    (0.4, 0.4, 0.9, 1.0),    # Indigo
    (0.9, 0.9, 0.2, 1.0),    # Yellow
]


@dataclass
class CursorPosition:
    """Represents a user's cursor position on a diagram."""

    diagram_id: str
    x: float
    y: float
    selected_item_ids: list[str] = field(default_factory=list)


@dataclass
class CollaborationUser:
    """Represents a user in a collaboration session."""

    user_id: str
    display_name: str
    color: tuple[float, float, float, float] = field(default_factory=lambda: USER_COLORS[0])
    cursor_position: CursorPosition | None = None
    is_local: bool = False

    _color_index: ClassVar[int] = 0

    @classmethod
    def create(
        cls,
        user_id: str,
        display_name: str,
        is_local: bool = False,
    ) -> CollaborationUser:
        """Create a new collaboration user with an assigned color."""
        color = cls._get_color_for_user(user_id)
        return cls(
            user_id=user_id,
            display_name=display_name,
            color=color,
            is_local=is_local,
        )

    @classmethod
    def _get_color_for_user(cls, user_id: str) -> tuple[float, float, float, float]:
        """Get a consistent color for a user based on their ID."""
        hash_value = int(hashlib.md5(user_id.encode()).hexdigest()[:8], 16)
        color_index = hash_value % len(USER_COLORS)
        return USER_COLORS[color_index]

    def update_cursor(self, diagram_id: str, x: float, y: float, selected_items: list[str] | None = None) -> None:
        """Update the user's cursor position."""
        self.cursor_position = CursorPosition(
            diagram_id=diagram_id,
            x=x,
            y=y,
            selected_item_ids=selected_items or [],
        )

    def clear_cursor(self) -> None:
        """Clear the user's cursor position."""
        self.cursor_position = None

    @property
    def color_hex(self) -> str:
        """Get the user's color as a hex string."""
        r, g, b, _ = self.color
        return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"

    def to_dict(self) -> dict:
        """Serialize user to dictionary."""
        return {
            "user_id": self.user_id,
            "display_name": self.display_name,
            "color": list(self.color),
            "cursor_position": {
                "diagram_id": self.cursor_position.diagram_id,
                "x": self.cursor_position.x,
                "y": self.cursor_position.y,
                "selected_item_ids": self.cursor_position.selected_item_ids,
            } if self.cursor_position else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CollaborationUser:
        """Deserialize user from dictionary."""
        user = cls(
            user_id=data["user_id"],
            display_name=data["display_name"],
            color=tuple(data["color"]),
        )
        if data.get("cursor_position"):
            cp = data["cursor_position"]
            user.cursor_position = CursorPosition(
                diagram_id=cp["diagram_id"],
                x=cp["x"],
                y=cp["y"],
                selected_item_ids=cp.get("selected_item_ids", []),
            )
        return user
