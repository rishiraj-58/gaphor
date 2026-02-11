"""Wire-format message definitions for the collaboration protocol.

Every message that travels between the server and any client is an
instance of one of the dataclasses below.  Serialisation/deserialisation
uses the lightweight helpers at the bottom of the module so the rest of
the codebase never has to import ``json`` directly.

Message taxonomy
----------------
Direction labels:
  S→C  server sends to one or all clients
  C→S  client sends to server

SessionJoin (C→S / S→C)
    Initial handshake.  The client sends it to claim a seat; the server
    echoes it back with the ``user_color`` field filled in so the client
    knows what colour it was assigned.

SessionLeave (S→C)
    Broadcast when a peer disconnects so every remaining client can
    remove their cursor overlay.

CursorMove (C→S / S→C)
    Real-time cursor position on a specific diagram canvas.
    ``x`` / ``y`` are in *diagram* coordinates (not screen pixels).

ModelOperation (C→S / S→C)
    A single, atomic model change produced by Gaphor's
    ``Recorder``.  The ``op_type`` and ``payload`` fields mirror the
    tuple format used in ``gaphor.storage.recovery.Recorder`` so that
    the same ``replay_events`` function can be called on the receiver
    side.  The ``vector_clock`` field enables conflict detection.

OperationAck (S→C)
    Sent back to the *originating* client only to confirm the server has
    accepted and applied an operation.  Carries the authoritative
    ``server_sequence`` number so the client can advance its own clock.

ConflictNotification (S→C)
    Sent to a client whose operation was rejected or transformed.
    ``resolution`` is a human-readable description of how the conflict
    was resolved, e.g. ``"last-writer-wins; your change was discarded"``.

FullStateSync (S→C)
    Sent to a freshly-joined client that missed earlier operations.
    The ``operations`` list is an ordered sequence of all recorded
    operations in the session so far, in chronological order.

UserListUpdate (S→C)
    Broadcast whenever the set of connected users changes so every
    client can redraw its participant list / avatar strip.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _now() -> float:
    return time.monotonic()


# ---------------------------------------------------------------------------
# Message dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SessionJoin:
    """A client announces itself to the collaboration server."""

    type: str = field(default="session_join", init=False)
    user_id: str = ""
    display_name: str = ""
    diagram_id: str = ""
    # Filled by the server when echoing back to the joining client:
    user_color: str = ""          # CSS colour string, e.g. "rgb(56, 135, 235)"
    timestamp: float = field(default_factory=_now)


@dataclass
class SessionLeave:
    """Broadcast by the server when a peer disconnects."""

    type: str = field(default="session_leave", init=False)
    user_id: str = ""
    display_name: str = ""
    timestamp: float = field(default_factory=_now)


@dataclass
class CursorMove:
    """Real-time cursor position sent by a client while editing a diagram."""

    type: str = field(default="cursor_move", init=False)
    user_id: str = ""
    diagram_id: str = ""
    x: float = 0.0       # diagram-space X
    y: float = 0.0       # diagram-space Y
    timestamp: float = field(default_factory=_now)


@dataclass
class ModelOperation:
    """One recorded model change, ready for replay on other clients.

    ``op_type`` is the single-character code used by
    ``gaphor.storage.recovery.Recorder`` (e.g. ``"a"`` for attribute
    change, ``"c"`` for element created, ``"u"`` for element deleted …).

    ``payload`` is the full tuple as recorded, serialised to a list so
    it survives JSON round-trips.

    ``vector_clock`` maps user_id → logical-time so the server can
    detect concurrency between operations from different peers.

    ``origin_user_id`` identifies who produced the operation; the
    server uses this to avoid echoing it back to the originating client.
    """

    type: str = field(default="model_operation", init=False)
    op_type: str = ""
    payload: list[Any] = field(default_factory=list)
    origin_user_id: str = ""
    client_sequence: int = 0      # monotonically increasing per-client counter
    vector_clock: dict[str, int] = field(default_factory=dict)
    diagram_id: str = ""
    timestamp: float = field(default_factory=_now)


@dataclass
class OperationAck:
    """Server acknowledges a received ModelOperation to its originator."""

    type: str = field(default="operation_ack", init=False)
    client_sequence: int = 0
    server_sequence: int = 0
    timestamp: float = field(default_factory=_now)


@dataclass
class ConflictNotification:
    """Server informs a client that one of its operations caused a conflict."""

    type: str = field(default="conflict_notification", init=False)
    client_sequence: int = 0
    resolution: str = ""          # human-readable description
    accepted: bool = False        # True if the op was kept, False if discarded
    timestamp: float = field(default_factory=_now)


@dataclass
class FullStateSync:
    """Server sends the full operation log to a newly-joined client."""

    type: str = field(default="full_state_sync", init=False)
    operations: list[dict[str, Any]] = field(default_factory=list)
    server_sequence: int = 0
    timestamp: float = field(default_factory=_now)


@dataclass
class UserListUpdate:
    """Broadcast when the set of active collaborators changes."""

    type: str = field(default="user_list_update", init=False)
    users: list[dict[str, str]] = field(default_factory=list)
    # Each entry: {"user_id": "…", "display_name": "…", "color": "rgb(…)"}
    timestamp: float = field(default_factory=_now)


# ---------------------------------------------------------------------------
# Serialisation / deserialisation
# ---------------------------------------------------------------------------

_MESSAGE_TYPES: dict[str, type] = {
    "session_join": SessionJoin,
    "session_leave": SessionLeave,
    "cursor_move": CursorMove,
    "model_operation": ModelOperation,
    "operation_ack": OperationAck,
    "conflict_notification": ConflictNotification,
    "full_state_sync": FullStateSync,
    "user_list_update": UserListUpdate,
}


def encode(message: object) -> str:
    """Serialise a message dataclass to a JSON string."""
    return json.dumps(asdict(message))  # type: ignore[call-overload]


def decode(raw: str) -> object:
    """Deserialise a JSON string into the appropriate message dataclass.

    Raises ``ValueError`` if the ``type`` field is unknown or missing.
    """
    data: dict[str, Any] = json.loads(raw)
    msg_type = data.get("type")
    cls = _MESSAGE_TYPES.get(msg_type, None)
    if cls is None:
        raise ValueError(f"Unknown collaboration message type: {msg_type!r}")
    # Remove the read-only default field before constructing so the
    # dataclass __init__ does not get it as a duplicate kwarg.
    data.pop("type", None)
    return cls(**data)
