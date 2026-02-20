"""Collaboration service for managing real-time editing sessions."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from gaphor.abc import ActionProvider, Service
from gaphor.action import action
from gaphor.collaboration.events import (
    ConnectionStatusChanged,
    CursorMoved,
    OperationReceived,
    UserJoined,
    UserLeft,
)
from gaphor.collaboration.network import NetworkTransport, WebSocketTransport
from gaphor.collaboration.operations import Operation, OperationType
from gaphor.collaboration.session import CollaborationSession
from gaphor.collaboration.user import CollaborationUser
from gaphor.core import event_handler
from gaphor.core.modeling.event import (
    AssociationAdded,
    AssociationDeleted,
    AttributeUpdated,
    ElementCreated,
    ElementDeleted,
)
from gaphor.diagram.presentation import HandlePositionEvent
from gaphor.event import Notification

if TYPE_CHECKING:
    from gaphor.core.eventmanager import EventManager
    from gaphor.core.modeling import ElementFactory

log = logging.getLogger(__name__)


class CollaborationService(Service, ActionProvider):
    """Service for managing collaboration sessions."""

    def __init__(
        self,
        event_manager: EventManager,
        element_factory: ElementFactory,
    ):
        self.event_manager = event_manager
        self.element_factory = element_factory
        self._session: CollaborationSession | None = None
        self._transport: NetworkTransport | None = None
        self._local_user: CollaborationUser | None = None
        self._applying_remote_operation = False

        self.event_manager.subscribe(self._on_element_created)
        self.event_manager.subscribe(self._on_element_deleted)
        self.event_manager.subscribe(self._on_attribute_updated)
        self.event_manager.subscribe(self._on_association_added)
        self.event_manager.subscribe(self._on_association_deleted)
        self.event_manager.subscribe(self._on_handle_position_event)
        self.event_manager.subscribe(self._on_operation_received)

    def shutdown(self) -> None:
        """Shutdown the collaboration service."""
        self.disconnect()
        self.event_manager.unsubscribe(self._on_element_created)
        self.event_manager.unsubscribe(self._on_element_deleted)
        self.event_manager.unsubscribe(self._on_attribute_updated)
        self.event_manager.unsubscribe(self._on_association_added)
        self.event_manager.unsubscribe(self._on_association_deleted)
        self.event_manager.unsubscribe(self._on_handle_position_event)
        self.event_manager.unsubscribe(self._on_operation_received)

    @property
    def is_connected(self) -> bool:
        """Check if connected to a collaboration session."""
        return self._session is not None and self._session.is_connected

    @property
    def session(self) -> CollaborationSession | None:
        """Get the current collaboration session."""
        return self._session

    @property
    def users(self) -> dict[str, CollaborationUser]:
        """Get all users in the current session."""
        if self._session:
            return self._session.users
        return {}

    @action(name="collab.connect", shortcut="<Primary><Shift>c")
    def connect_action(self) -> None:
        """Connect to a collaboration session."""
        self.connect("ws://localhost:8765", f"session_{uuid4().hex[:8]}")

    @action(name="collab.disconnect")
    def disconnect_action(self) -> None:
        """Disconnect from the collaboration session."""
        self.disconnect()

    def connect(
        self,
        server_url: str,
        session_id: str,
        user_name: str | None = None,
    ) -> bool:
        """Connect to a collaboration server and join/create a session."""
        if self._session and self._session.is_connected:
            log.warning("Already connected to a session")
            return False

        user_id = str(uuid4())
        display_name = user_name or f"User_{user_id[:8]}"
        self._local_user = CollaborationUser.create(
            user_id=user_id,
            display_name=display_name,
            is_local=True,
        )

        self._session = CollaborationSession(
            session_id=session_id,
            local_user=self._local_user,
            event_manager=self.event_manager,
        )

        self._transport = WebSocketTransport(server_url)
        self._transport.on_message = self._handle_network_message
        self._transport.on_connect = self._handle_connect
        self._transport.on_disconnect = self._handle_disconnect

        self._session.add_message_handler(self._send_to_network)

        try:
            self._transport.connect()
            return True
        except Exception as e:
            log.error(f"Failed to connect: {e}")
            self._cleanup_session()
            return False

    def disconnect(self) -> None:
        """Disconnect from the current collaboration session."""
        if self._session:
            self._session.disconnect()

        if self._transport:
            self._transport.disconnect()

        self._cleanup_session()

    def broadcast_cursor(
        self,
        diagram_id: str,
        x: float,
        y: float,
        selected_items: list[str] | None = None,
    ) -> None:
        """Broadcast cursor position to other users."""
        if self._session:
            self._session.broadcast_cursor_position(diagram_id, x, y, selected_items)

    def get_remote_cursors(self, diagram_id: str) -> list[tuple[CollaborationUser, float, float]]:
        """Get cursor positions of remote users on a specific diagram."""
        if not self._session:
            return []

        cursors = []
        for user in self._session.users.values():
            if not user.is_local and user.cursor_position:
                if user.cursor_position.diagram_id == diagram_id:
                    cursors.append((
                        user,
                        user.cursor_position.x,
                        user.cursor_position.y,
                    ))
        return cursors

    def _cleanup_session(self) -> None:
        """Clean up session resources."""
        self._session = None
        self._transport = None
        self._local_user = None

    def _handle_network_message(self, message: dict) -> None:
        """Handle a message received from the network."""
        if self._session:
            self._session.handle_remote_message(message)

    def _send_to_network(self, message: dict) -> None:
        """Send a message to the network."""
        if self._transport:
            self._transport.send(message)

    def _handle_connect(self) -> None:
        """Handle successful connection."""
        if self._session:
            self._session.connect()
            self.event_manager.handle(ConnectionStatusChanged(
                session_id=self._session.session_id,
                timestamp=time.time(),
                connected=True,
            ))
            self.event_manager.handle(Notification(
                message=f"Connected to collaboration session"
            ))

    def _handle_disconnect(self, reason: str = "") -> None:
        """Handle disconnection."""
        if self._session:
            self.event_manager.handle(ConnectionStatusChanged(
                session_id=self._session.session_id,
                timestamp=time.time(),
                connected=False,
                reason=reason,
            ))
            self.event_manager.handle(Notification(
                message=f"Disconnected from collaboration session"
            ))
        self._cleanup_session()

    @event_handler(ElementCreated)
    def _on_element_created(self, event: ElementCreated) -> None:
        """Handle element creation."""
        if self._applying_remote_operation or not self._session:
            return

        diagram = event.diagram
        element = event.element

        self._session.create_operation(
            operation_type=OperationType.CREATE,
            element_id=element.id,
            diagram_id=diagram.id if diagram else "",
            data={
                "element_type": type(element).__name__,
                "element_data": self._serialize_element(element),
            },
        )

    @event_handler(ElementDeleted)
    def _on_element_deleted(self, event: ElementDeleted) -> None:
        """Handle element deletion."""
        if self._applying_remote_operation or not self._session:
            return

        diagram = event.diagram

        self._session.create_operation(
            operation_type=OperationType.DELETE,
            element_id=event.element.id,
            diagram_id=diagram.id if diagram else "",
            data={},
        )

    @event_handler(AttributeUpdated)
    def _on_attribute_updated(self, event: AttributeUpdated) -> None:
        """Handle attribute updates."""
        if self._applying_remote_operation or not self._session:
            return

        element = event.element
        diagram = getattr(element, "diagram", None)

        self._session.create_operation(
            operation_type=OperationType.UPDATE_ATTRIBUTE,
            element_id=element.id,
            diagram_id=diagram.id if diagram else "",
            data={
                "attribute_name": event.property.name,
                "old_value": event.old_value,
                "new_value": event.new_value,
            },
        )

    @event_handler(AssociationAdded)
    def _on_association_added(self, event: AssociationAdded) -> None:
        """Handle association additions."""
        if self._applying_remote_operation or not self._session:
            return

        element = event.element
        diagram = getattr(element, "diagram", None)

        self._session.create_operation(
            operation_type=OperationType.ADD_CONNECTION,
            element_id=element.id,
            diagram_id=diagram.id if diagram else "",
            data={
                "association_name": event.property.name,
                "new_value_id": event.new_value.id if event.new_value else None,
            },
        )

    @event_handler(AssociationDeleted)
    def _on_association_deleted(self, event: AssociationDeleted) -> None:
        """Handle association deletions."""
        if self._applying_remote_operation or not self._session:
            return

        element = event.element
        diagram = getattr(element, "diagram", None)

        self._session.create_operation(
            operation_type=OperationType.REMOVE_CONNECTION,
            element_id=element.id,
            diagram_id=diagram.id if diagram else "",
            data={
                "association_name": event.property.name,
                "old_value_id": event.old_value.id if event.old_value else None,
            },
        )

    @event_handler(HandlePositionEvent)
    def _on_handle_position_event(self, event: HandlePositionEvent) -> None:
        """Handle position updates."""
        if self._applying_remote_operation or not self._session:
            return

        element = event.element
        diagram = getattr(element, "diagram", None)

        self._session.create_operation(
            operation_type=OperationType.UPDATE_POSITION,
            element_id=element.id,
            diagram_id=diagram.id if diagram else "",
            data={
                "handle_index": event.handle_index,
                "old_value": event.old_value,
                "new_value": event.new_value,
            },
        )

    @event_handler(OperationReceived)
    def _on_operation_received(self, event: OperationReceived) -> None:
        """Apply a received remote operation to the local model."""
        self._applying_remote_operation = True
        try:
            self._apply_operation(event)
        finally:
            self._applying_remote_operation = False

    def _apply_operation(self, event: OperationReceived) -> None:
        """Apply a remote operation to the local model."""
        operation_type = event.operation_type
        data = event.operation_data

        if data.get("_noop"):
            return

        if operation_type == OperationType.CREATE.value:
            self._apply_create(data)
        elif operation_type == OperationType.DELETE.value:
            self._apply_delete(data)
        elif operation_type == OperationType.UPDATE_ATTRIBUTE.value:
            self._apply_attribute_update(data)
        elif operation_type == OperationType.UPDATE_POSITION.value:
            self._apply_position_update(data)

    def _apply_create(self, data: dict) -> None:
        """Apply a create operation."""
        # Element creation from remote would need more complex handling
        pass

    def _apply_delete(self, data: dict) -> None:
        """Apply a delete operation."""
        pass

    def _apply_attribute_update(self, data: dict) -> None:
        """Apply an attribute update operation."""
        pass

    def _apply_position_update(self, data: dict) -> None:
        """Apply a position update operation."""
        pass

    def _serialize_element(self, element) -> dict:
        """Serialize an element for transmission."""
        return {
            "id": element.id,
            "type": type(element).__name__,
        }
