"""Collaboration module for real-time multi-user editing.

This module provides support for collaborative editing of Gaphor diagrams,
including cursor synchronization, operation broadcasting, and conflict resolution.
"""

from gaphor.collaboration.events import (
    CollaborationEvent,
    CursorMoved,
    OperationReceived,
    UserJoined,
    UserLeft,
)
from gaphor.collaboration.session import CollaborationSession
from gaphor.collaboration.user import CollaborationUser

__all__ = [
    "CollaborationEvent",
    "CollaborationSession",
    "CollaborationUser",
    "CursorMoved",
    "OperationReceived",
    "UserJoined",
    "UserLeft",
]
