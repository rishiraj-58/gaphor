"""Remote cursor management and rendering."""

import time
from dataclasses import dataclass, field
from typing import Callable

from gaphas.painter import Painter


USER_COLORS = [
    "#FF6B6B",  # Red
    "#4ECDC4",  # Teal
    "#45B7D1",  # Blue
    "#96CEB4",  # Green
    "#FFEAA7",  # Yellow
    "#DDA0DD",  # Plum
    "#98D8C8",  # Mint
    "#F7DC6F",  # Gold
    "#BB8FCE",  # Purple
    "#85C1E9",  # Light Blue
]


@dataclass
class RemoteCursor:
    user_id: str
    username: str
    color: str
    diagram_id: str = ""
    x: float = 0.0
    y: float = 0.0
    last_update: float = field(default_factory=time.time)


class CursorManager:
    def __init__(self):
        self._cursors: dict[str, RemoteCursor] = {}
        self._color_index = 0
        self._cursor_timeout = 30.0  # seconds

    def get_next_color(self) -> str:
        color = USER_COLORS[self._color_index % len(USER_COLORS)]
        self._color_index += 1
        return color

    def add_user(self, user_id: str, username: str, color: str | None = None) -> RemoteCursor:
        if color is None:
            color = self.get_next_color()
        cursor = RemoteCursor(user_id=user_id, username=username, color=color)
        self._cursors[user_id] = cursor
        return cursor

    def remove_user(self, user_id: str) -> None:
        self._cursors.pop(user_id, None)

    def update_cursor(self, user_id: str, diagram_id: str, x: float, y: float) -> None:
        if user_id in self._cursors:
            cursor = self._cursors[user_id]
            cursor.diagram_id = diagram_id
            cursor.x = x
            cursor.y = y
            cursor.last_update = time.time()

    def get_cursor(self, user_id: str) -> RemoteCursor | None:
        return self._cursors.get(user_id)

    def get_cursors_for_diagram(self, diagram_id: str) -> list[RemoteCursor]:
        now = time.time()
        return [
            c for c in self._cursors.values()
            if c.diagram_id == diagram_id and (now - c.last_update) < self._cursor_timeout
        ]

    def get_all_users(self) -> list[RemoteCursor]:
        return list(self._cursors.values())

    def cleanup_stale_cursors(self) -> list[str]:
        now = time.time()
        stale = [
            uid for uid, cursor in self._cursors.items()
            if (now - cursor.last_update) > self._cursor_timeout
        ]
        for uid in stale:
            del self._cursors[uid]
        return stale


class RemoteCursorPainter(Painter):
    """Painter for rendering remote user cursors on the diagram."""

    def __init__(self, cursor_manager: CursorManager, diagram_id: str):
        self._cursor_manager = cursor_manager
        self._diagram_id = diagram_id

    def paint(self, items, cr):
        cursors = self._cursor_manager.get_cursors_for_diagram(self._diagram_id)
        for cursor in cursors:
            self._draw_cursor(cr, cursor)

    def _draw_cursor(self, cr, cursor: RemoteCursor):
        x, y = cursor.x, cursor.y

        cr.save()
        try:
            # Parse hex color
            color = cursor.color.lstrip("#")
            r = int(color[0:2], 16) / 255.0
            g = int(color[2:4], 16) / 255.0
            b = int(color[4:6], 16) / 255.0

            # Draw cursor pointer (triangle)
            cr.move_to(x, y)
            cr.line_to(x + 12, y + 10)
            cr.line_to(x + 4, y + 10)
            cr.line_to(x, y + 14)
            cr.close_path()
            cr.set_source_rgba(r, g, b, 0.9)
            cr.fill_preserve()
            cr.set_source_rgba(0, 0, 0, 0.8)
            cr.set_line_width(1)
            cr.stroke()

            # Draw username label
            cr.set_font_size(10)
            cr.select_font_face("Sans")
            text_extents = cr.text_extents(cursor.username)

            label_x = x + 14
            label_y = y + 10
            padding = 3

            # Label background
            cr.rectangle(
                label_x - padding,
                label_y - text_extents.height - padding,
                text_extents.width + padding * 2,
                text_extents.height + padding * 2,
            )
            cr.set_source_rgba(r, g, b, 0.85)
            cr.fill()

            # Label text
            cr.move_to(label_x, label_y)
            cr.set_source_rgba(1, 1, 1, 1)
            cr.show_text(cursor.username)

        finally:
            cr.restore()
