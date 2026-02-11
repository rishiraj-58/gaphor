"""Collaboration events."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CollaborationEvent:
    """Base class for collaboration events."""
    pass


@dataclass
class UserJoined(CollaborationEvent):
    """Emitted when a user joins the collaboration session."""
    user_id: str
    username: str
    color: str


@dataclass
class UserLeft(CollaborationEvent):
    """Emitted when a user leaves the collaboration session."""
    user_id: str


@dataclass
class UserCursorMoved(CollaborationEvent):
    """Emitted when a remote user's cursor moves."""
    user_id: str
    diagram_id: str
    x: float
    y: float


@dataclass
class RemoteChange(CollaborationEvent):
    """Emitted when a remote change is received."""
    user_id: str
    change_type: str  # 'create', 'update', 'delete'
    element_id: str
    data: dict = field(default_factory=dict)


@dataclass
class CollaborationConnected(CollaborationEvent):
    """Emitted when connected to collaboration server."""
    session_id: str
    user_id: str


@dataclass
class CollaborationDisconnected(CollaborationEvent):
    """Emitted when disconnected from collaboration server."""
    reason: str = ""


@dataclass
class ConflictDetected(CollaborationEvent):
    """Emitted when a conflict is detected."""
    element_id: str
    local_version: int
    remote_version: int
    resolution: str = "last_write_wins"
