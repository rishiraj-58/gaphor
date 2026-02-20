"""Events for the collaboration module."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from gaphor.collaboration.user import CollaborationUser


@dataclass
class CollaborationEvent:
    """Base class for all collaboration events."""

    session_id: str
    timestamp: float


@dataclass
class UserJoined(CollaborationEvent):
    """Event emitted when a user joins a collaboration session."""

    user: CollaborationUser


@dataclass
class UserLeft(CollaborationEvent):
    """Event emitted when a user leaves a collaboration session."""

    user_id: str


@dataclass
class CursorMoved(CollaborationEvent):
    """Event emitted when a user's cursor position changes."""

    user_id: str
    diagram_id: str
    x: float
    y: float
    selected_item_ids: list[str] = field(default_factory=list)


@dataclass
class OperationReceived(CollaborationEvent):
    """Event emitted when a remote operation is received."""

    user_id: str
    operation_type: str
    operation_data: dict[str, Any]
    vector_clock: dict[str, int]


@dataclass
class ConflictDetected(CollaborationEvent):
    """Event emitted when a conflict is detected between operations."""

    local_operation: dict[str, Any]
    remote_operation: dict[str, Any]
    resolution: str


@dataclass
class SyncRequested(CollaborationEvent):
    """Event emitted when synchronization is requested."""

    from_version: int


@dataclass
class SyncCompleted(CollaborationEvent):
    """Event emitted when synchronization is completed."""

    new_version: int
    operations_applied: int


@dataclass
class ConnectionStatusChanged(CollaborationEvent):
    """Event emitted when connection status changes."""

    connected: bool
    reason: str = ""
