"""Collaboration session management."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Protocol
from uuid import uuid4

try:
    from gaphor.collaboration.events import (
        CollaborationEvent,
        ConflictDetected,
        CursorMoved,
        OperationReceived,
        SyncCompleted,
        UserJoined,
        UserLeft,
    )
    from gaphor.collaboration.operations import (
        ConflictResolver,
        Operation,
        OperationType,
        VectorClock,
    )
    from gaphor.collaboration.user import CollaborationUser
except ImportError:
    from collaboration.events import (
        CollaborationEvent,
        ConflictDetected,
        CursorMoved,
        OperationReceived,
        SyncCompleted,
        UserJoined,
        UserLeft,
    )
    from collaboration.operations import (
        ConflictResolver,
        Operation,
        OperationType,
        VectorClock,
    )
    from collaboration.user import CollaborationUser


class EventManagerProtocol(Protocol):
    """Protocol for event managers."""
    def handle(self, event: Any) -> None: ...


log = logging.getLogger(__name__)


@dataclass
class SessionState:
    """Represents the state of a collaboration session."""

    version: int = 0
    operation_history: list[Operation] = field(default_factory=list)
    pending_operations: list[Operation] = field(default_factory=list)


class CollaborationSession:
    """Manages a single collaboration session with multiple users."""

    def __init__(
        self,
        session_id: str,
        local_user: CollaborationUser,
        event_manager: EventManagerProtocol | None = None,
    ):
        self.session_id = session_id
        self.local_user = local_user
        self.event_manager = event_manager
        self._users: dict[str, CollaborationUser] = {local_user.user_id: local_user}
        self._state = SessionState()
        self._vector_clock = VectorClock(local_user.user_id)
        self._conflict_resolver = ConflictResolver()
        self._message_handlers: list[Callable[[dict], None]] = []
        self._connected = False

    @property
    def users(self) -> dict[str, CollaborationUser]:
        """Get all users in the session."""
        return self._users.copy()

    @property
    def is_connected(self) -> bool:
        """Check if the session is connected."""
        return self._connected

    @property
    def version(self) -> int:
        """Get current session version."""
        return self._state.version

    def connect(self) -> None:
        """Connect to the collaboration session."""
        self._connected = True
        self._broadcast_user_joined()

    def disconnect(self) -> None:
        """Disconnect from the collaboration session."""
        if self._connected:
            self._broadcast_user_left()
            self._connected = False

    def add_message_handler(self, handler: Callable[[dict], None]) -> None:
        """Add a handler for outgoing messages."""
        self._message_handlers.append(handler)

    def remove_message_handler(self, handler: Callable[[dict], None]) -> None:
        """Remove a message handler."""
        if handler in self._message_handlers:
            self._message_handlers.remove(handler)

    def handle_remote_message(self, message: dict) -> None:
        """Handle an incoming message from a remote user."""
        message_type = message.get("type")

        if message_type == "user_joined":
            self._handle_user_joined(message)
        elif message_type == "user_left":
            self._handle_user_left(message)
        elif message_type == "cursor_moved":
            self._handle_cursor_moved(message)
        elif message_type == "operation":
            self._handle_operation(message)
        elif message_type == "sync_request":
            self._handle_sync_request(message)
        elif message_type == "sync_response":
            self._handle_sync_response(message)

    def broadcast_cursor_position(
        self, diagram_id: str, x: float, y: float, selected_items: list[str] | None = None
    ) -> None:
        """Broadcast local cursor position to other users."""
        if not self._connected:
            return

        self.local_user.update_cursor(diagram_id, x, y, selected_items)
        message = {
            "type": "cursor_moved",
            "session_id": self.session_id,
            "user_id": self.local_user.user_id,
            "diagram_id": diagram_id,
            "x": x,
            "y": y,
            "selected_item_ids": selected_items or [],
            "timestamp": time.time(),
        }
        self._send_message(message)

    def create_operation(
        self,
        operation_type: OperationType,
        element_id: str,
        diagram_id: str,
        data: dict[str, Any] | None = None,
    ) -> Operation:
        """Create and broadcast a new operation."""
        operation = Operation(
            operation_id=str(uuid4()),
            operation_type=operation_type,
            element_id=element_id,
            diagram_id=diagram_id,
            user_id=self.local_user.user_id,
            timestamp=time.time(),
            data=data or {},
            vector_clock=self._vector_clock.increment(),
        )

        self._state.operation_history.append(operation)
        self._state.version += 1

        if self._connected:
            self._broadcast_operation(operation)

        return operation

    def request_sync(self) -> None:
        """Request synchronization with the server."""
        if not self._connected:
            return

        message = {
            "type": "sync_request",
            "session_id": self.session_id,
            "user_id": self.local_user.user_id,
            "from_version": self._state.version,
            "timestamp": time.time(),
        }
        self._send_message(message)

    def get_user_color(self, user_id: str) -> tuple[float, float, float, float] | None:
        """Get the color for a specific user."""
        user = self._users.get(user_id)
        return user.color if user else None

    def _broadcast_user_joined(self) -> None:
        """Broadcast that the local user has joined."""
        message = {
            "type": "user_joined",
            "session_id": self.session_id,
            "user": self.local_user.to_dict(),
            "timestamp": time.time(),
        }
        self._send_message(message)

    def _broadcast_user_left(self) -> None:
        """Broadcast that the local user is leaving."""
        message = {
            "type": "user_left",
            "session_id": self.session_id,
            "user_id": self.local_user.user_id,
            "timestamp": time.time(),
        }
        self._send_message(message)

    def _broadcast_operation(self, operation: Operation) -> None:
        """Broadcast an operation to other users."""
        message = {
            "type": "operation",
            "session_id": self.session_id,
            "operation": operation.to_dict(),
            "timestamp": time.time(),
        }
        self._send_message(message)

    def _handle_user_joined(self, message: dict) -> None:
        """Handle a user joining the session."""
        user_data = message.get("user", {})
        user = CollaborationUser.from_dict(user_data)

        if user.user_id not in self._users:
            self._users[user.user_id] = user
            self._emit_event(UserJoined(
                session_id=self.session_id,
                timestamp=message.get("timestamp", time.time()),
                user=user,
            ))

    def _handle_user_left(self, message: dict) -> None:
        """Handle a user leaving the session."""
        user_id = message.get("user_id")
        if user_id and user_id in self._users:
            del self._users[user_id]
            self._emit_event(UserLeft(
                session_id=self.session_id,
                timestamp=message.get("timestamp", time.time()),
                user_id=user_id,
            ))

    def _handle_cursor_moved(self, message: dict) -> None:
        """Handle a cursor move from a remote user."""
        user_id = message.get("user_id")
        if not user_id or user_id == self.local_user.user_id:
            return

        user = self._users.get(user_id)
        if user:
            user.update_cursor(
                message.get("diagram_id", ""),
                message.get("x", 0),
                message.get("y", 0),
                message.get("selected_item_ids", []),
            )
            self._emit_event(CursorMoved(
                session_id=self.session_id,
                timestamp=message.get("timestamp", time.time()),
                user_id=user_id,
                diagram_id=message.get("diagram_id", ""),
                x=message.get("x", 0),
                y=message.get("y", 0),
                selected_item_ids=message.get("selected_item_ids", []),
            ))

    def _handle_operation(self, message: dict) -> None:
        """Handle a remote operation."""
        op_data = message.get("operation", {})
        operation = Operation.from_dict(op_data)

        if operation.user_id == self.local_user.user_id:
            return

        # Check for conflicts
        if self._vector_clock.is_concurrent(operation.vector_clock):
            local_pending = [
                op for op in self._state.pending_operations
                if op.element_id == operation.element_id
            ]
            if local_pending:
                resolved = self._conflict_resolver.resolve(local_pending, [operation])
                if resolved:
                    operation = resolved[0]
                    self._emit_event(ConflictDetected(
                        session_id=self.session_id,
                        timestamp=time.time(),
                        local_operation=local_pending[0].to_dict(),
                        remote_operation=op_data,
                        resolution="transformed",
                    ))

        self._vector_clock.update(operation.vector_clock)
        self._state.operation_history.append(operation)
        self._state.version += 1

        self._emit_event(OperationReceived(
            session_id=self.session_id,
            timestamp=message.get("timestamp", time.time()),
            user_id=operation.user_id,
            operation_type=operation.operation_type.value,
            operation_data=operation.data,
            vector_clock=operation.vector_clock,
        ))

    def _handle_sync_request(self, message: dict) -> None:
        """Handle a sync request from another user."""
        from_version = message.get("from_version", 0)
        user_id = message.get("user_id")

        ops_to_send = [
            op.to_dict() for op in self._state.operation_history
            if self._state.operation_history.index(op) >= from_version
        ]

        response = {
            "type": "sync_response",
            "session_id": self.session_id,
            "to_user_id": user_id,
            "operations": ops_to_send,
            "current_version": self._state.version,
            "timestamp": time.time(),
        }
        self._send_message(response)

    def _handle_sync_response(self, message: dict) -> None:
        """Handle a sync response."""
        operations = message.get("operations", [])
        for op_data in operations:
            operation = Operation.from_dict(op_data)
            if operation not in self._state.operation_history:
                self._state.operation_history.append(operation)
                self._vector_clock.update(operation.vector_clock)

        self._state.version = message.get("current_version", self._state.version)

        self._emit_event(SyncCompleted(
            session_id=self.session_id,
            timestamp=message.get("timestamp", time.time()),
            new_version=self._state.version,
            operations_applied=len(operations),
        ))

    def _send_message(self, message: dict) -> None:
        """Send a message to all registered handlers."""
        for handler in self._message_handlers:
            try:
                handler(message)
            except Exception as e:
                log.error(f"Error sending message: {e}")

    def _emit_event(self, event: CollaborationEvent) -> None:
        """Emit a collaboration event through the event manager."""
        if self.event_manager:
            self.event_manager.handle(event)
