"""User colour registry.

Every collaborating peer is assigned a distinct, visually pleasing
colour.  The palette is wide enough that up to 12 simultaneous users
all receive different hues before colours start repeating.

The colour is expressed as an (R, G, B) tuple of floats in [0.0, 1.0],
matching the convention used everywhere else in the Cairo / Gaphor
drawing pipeline.  The same (R, G, B) is also converted to a CSS
``rgb(...)`` string so it can be applied to GTK CSS providers directly.
"""

from __future__ import annotations

from typing import NamedTuple


class UserColor(NamedTuple):
    """Immutable colour descriptor for a single collaborator."""

    red: float
    green: float
    blue: float
    css: str       # pre-computed "rgb(r, g, b)" ready for GTK CSS

    @property
    def cairo_rgba(self) -> tuple[float, float, float, float]:
        """Return a (r, g, b, a) tuple suitable for cairo.set_source_rgba."""
        return (self.red, self.green, self.blue, 1.0)


# 12 perceptually distinct colours drawn from the same lightness band so
# that no colour "pops" more than another.  The list intentionally avoids
# pure red (0xff0000) because that is used by the selection / error
# indicators already present in Gaphor.
_PALETTE: list[tuple[float, float, float]] = [
    (0.22, 0.53, 0.92),   # 0 – cornflower blue
    (0.20, 0.74, 0.55),   # 1 – emerald
    (0.96, 0.49, 0.13),   # 2 – tangerine
    (0.75, 0.25, 0.80),   # 3 – orchid
    (0.95, 0.78, 0.06),   # 4 – golden yellow
    (0.08, 0.67, 0.82),   # 5 – cerulean
    (0.87, 0.27, 0.49),   # 6 – crimson rose
    (0.38, 0.74, 0.18),   # 7 – lime green
    (0.95, 0.33, 0.33),   # 8 – salmon red (not saturated pure red)
    (0.35, 0.45, 0.88),   # 9 – cobalt blue
    (0.91, 0.62, 0.18),   # 10 – amber
    (0.25, 0.72, 0.71),   # 11 – teal
]


def _make_user_color(r: float, g: float, b: float) -> UserColor:
    css = f"rgb({int(r * 255)}, {int(g * 255)}, {int(b * 255)})"
    return UserColor(red=r, green=g, blue=b, css=css)


_PREBUILT: list[UserColor] = [_make_user_color(*rgb) for rgb in _PALETTE]


class ColorRegistry:
    """Assign and release colours for collaborating users.

    Colours are allocated in round-robin order from the palette.
    When a user disconnects their slot is freed and can be reused.

    Thread-safety: all public methods are intentionally synchronous
    because the WebSocket server already serialises access on the
    asyncio event loop; no additional locking is needed.
    """

    def __init__(self) -> None:
        # Maps user_id -> UserColor
        self._assignments: dict[str, UserColor] = {}
        # Tracks which palette indices are currently in use
        self._used_indices: set[int] = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def assign(self, user_id: str) -> UserColor:
        """Return the colour already assigned to *user_id*, or allocate a
        new one.  If every colour in the palette is occupied the cycle
        wraps so the palette can never be exhausted."""
        if user_id in self._assignments:
            return self._assignments[user_id]

        # Find the lowest free index, wrapping if needed.
        index = self._next_free_index()
        color = _PREBUILT[index]
        self._assignments[user_id] = color
        self._used_indices.add(index)
        return color

    def release(self, user_id: str) -> None:
        """Free the colour slot held by *user_id*."""
        if user_id not in self._assignments:
            return
        color = self._assignments.pop(user_id)
        # Recover the palette index so it can be reused.
        for idx, prebuilt in enumerate(_PREBUILT):
            if prebuilt is color:
                self._used_indices.discard(idx)
                break

    def get(self, user_id: str) -> UserColor | None:
        """Return the colour currently assigned to *user_id*, or None."""
        return self._assignments.get(user_id)

    @property
    def assignments(self) -> dict[str, UserColor]:
        """Read-only snapshot of all current assignments."""
        return dict(self._assignments)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _next_free_index(self) -> int:
        palette_size = len(_PREBUILT)
        for i in range(palette_size):
            if i not in self._used_indices:
                return i
        # All colours taken – wrap around and reuse index 0 (allocate
        # duplicates rather than blocking indefinitely).
        return 0
