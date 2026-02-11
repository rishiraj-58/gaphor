"""Collaboration service for real-time multi-user editing."""

import asyncio
import logging
import time
from uuid import uuid4

from gaphor.abc import ActionProvider, Service
from gaphor.action import action
from gaphor.core import event_handler
from gaphor.core.modeling.event import (
    AttributeUpdated,
    ElementCreated,
    ElementDeleted,
    AssociationSet,
)
from gaphor.event import TransactionCommit
from gaphor.services.collaboration.client import CollaborationClient
from gaphor.services.collaboration.conflict import (
    ChangeRecord,
    ConflictManager,
    ConflictStrategy,
)
from gaphor.services.collaboration.cursors import CursorManager, RemoteCursor
from gaphor.services.collaboration.events import (
    CollaborationConnected,
    CollaborationDisconnected,
    ConflictDetected,
    RemoteChange,
    UserCursorMoved,
    UserJoined,
    UserLeft,
)
from gaphor.services.collaboration.protocol import (
    Message,
    MessageType,
    create_change_message,
    create_cursor_message,
    create_join_message,
    create_leave_message,
    create_heartbeat_message,
)

log = logging.getLogger(__name__)


class CollaborationService(Service, ActionProvider):
    """Service for real-time collaboration on diagrams."""

    def __init__(self, event_manager, element_factory):
        self.event_manager = event_manager
        self.element_factory = element_factory

        self._user_id = str(uuid4())
        self._username = "User"
        self._session_id: str | None = None
        self._enabled = False
        self._applying_remote = False

        self._cursor_manager = CursorManager()
        self._conflict_manager = ConflictManager()
        self._client = CollaborationClient(
            on_message=self._on_message,
            on_connect=self._on_connected,
            on_disconnect=self._on_disconnected,
        )

        self._pending_changes: list[dict] = []
        self._cursor_throttle = 0.05  # 50ms
        self._last_cursor_send = 0.0

        event_manager.subscribe(self._on_element_created)
        event_manager.subscribe(self._on_element_deleted)
        event_manager.subscribe(self._on_attribute_updated)
        event_manager.subscribe(self._on_association_set)
        event_manager.subscribe(self._on_transaction_commit)

    def shutdown(self) -> None:
        if self._enabled:
            asyncio.create_task(self.disconnect())

        self.event_manager.unsubscribe(self._on_element_created)
        self.event_manager.unsubscribe(self._on_element_deleted)
        self.event_manager.unsubscribe(self._on_attribute_updated)
        self.event_manager.unsubscribe(self._on_association_set)
        self.event_manager.unsubscribe(self._on_transaction_commit)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def connected(self) -> bool:
        return self._client.connected

    @property
    def user_id(self) -> str:
        return self._user_id

    @property
    def username(self) -> str:
        return self._username

    @username.setter
    def username(self, value: str) -> None:
        self._username = value

    @property
    def cursor_manager(self) -> CursorManager:
        return self._cursor_manager

    @property
    def conflict_manager(self) -> ConflictManager:
        return self._conflict_manager

    def get_remote_users(self) -> list[RemoteCursor]:
        return self._cursor_manager.get_all_users()

    def set_conflict_strategy(self, strategy: ConflictStrategy) -> None:
        self._conflict_manager.set_strategy(strategy)

    @action(name="collab.connect")
    async def connect(self, server_url: str, session_id: str, username: str | None = None) -> bool:
        if username:
            self._username = username
        self._session_id = session_id

        success = await self._client.connect(server_url)
        if success:
            self._enabled = True
            join_msg = create_join_message(self._user_id, self._username, session_id)
            await self._client.send(join_msg.to_json())
        return success

    @action(name="collab.disconnect")
    async def disconnect(self) -> None:
        if self._enabled:
            leave_msg = create_leave_message(self._user_id)
            await self._client.send(leave_msg.to_json())
        await self._client.disconnect()
        self._enabled = False
        self._session_id = None

    def send_cursor_position(self, diagram_id: str, x: float, y: float) -> None:
        if not self._enabled:
            return

        now = time.time()
        if now - self._last_cursor_send < self._cursor_throttle:
            return
        self._last_cursor_send = now

        msg = create_cursor_message(self._user_id, diagram_id, x, y)
        asyncio.create_task(self._client.send(msg.to_json()))

    def _on_message(self, raw_message: str) -> None:
        try:
            message = Message.from_json(raw_message)
            self._handle_message(message)
        except Exception as e:
            log.error(f"Failed to parse message: {e}")

    def _handle_message(self, message: Message) -> None:
        if message.user_id == self._user_id:
            return

        handlers = {
            MessageType.JOIN: self._handle_join,
            MessageType.LEAVE: self._handle_leave,
            MessageType.CURSOR: self._handle_cursor,
            MessageType.CHANGE: self._handle_change,
            MessageType.ACK: self._handle_ack,
            MessageType.SYNC: self._handle_sync,
        }

        handler = handlers.get(message.type)
        if handler:
            handler(message)

    def _handle_join(self, message: Message) -> None:
        payload = message.payload
        username = payload.get("username", "Unknown")
        color = self._cursor_manager.get_next_color()
        self._cursor_manager.add_user(message.user_id, username, color)
        self.event_manager.handle(UserJoined(
            user_id=message.user_id,
            username=username,
            color=color,
        ))

    def _handle_leave(self, message: Message) -> None:
        self._cursor_manager.remove_user(message.user_id)
        self.event_manager.handle(UserLeft(user_id=message.user_id))

    def _handle_cursor(self, message: Message) -> None:
        payload = message.payload
        diagram_id = payload.get("diagram_id", "")
        x = payload.get("x", 0.0)
        y = payload.get("y", 0.0)
        self._cursor_manager.update_cursor(message.user_id, diagram_id, x, y)
        self.event_manager.handle(UserCursorMoved(
            user_id=message.user_id,
            diagram_id=diagram_id,
            x=x,
            y=y,
        ))

    def _handle_change(self, message: Message) -> None:
        payload = message.payload
        element_id = payload.get("element_id", "")
        change_type = payload.get("change_type", "")
        data = payload.get("data", {})
        version = payload.get("version", 0)

        change = ChangeRecord(
            element_id=element_id,
            property_name=data.get("property", ""),
            value=data.get("value"),
            version=version,
            timestamp=data.get("timestamp", time.time()),
            user_id=message.user_id,
        )

        conflict_result = self._conflict_manager.apply_remote_change(change)
        if conflict_result and conflict_result.winning_change != change:
            self.event_manager.handle(ConflictDetected(
                element_id=element_id,
                local_version=self._conflict_manager.get_version(element_id),
                remote_version=version,
                resolution=conflict_result.strategy_used.value,
            ))
            return

        self._applying_remote = True
        try:
            self._apply_remote_change(change_type, element_id, data)
            self.event_manager.handle(RemoteChange(
                user_id=message.user_id,
                change_type=change_type,
                element_id=element_id,
                data=data,
            ))
        finally:
            self._applying_remote = False

    def _apply_remote_change(self, change_type: str, element_id: str, data: dict) -> None:
        if change_type == "create":
            self._apply_create(element_id, data)
        elif change_type == "update":
            self._apply_update(element_id, data)
        elif change_type == "delete":
            self._apply_delete(element_id)

    def _apply_create(self, element_id: str, data: dict) -> None:
        element_type_name = data.get("type")
        if not element_type_name:
            return

        # TODO: Lookup element type and create
        log.info(f"Remote create: {element_type_name} ({element_id})")

    def _apply_update(self, element_id: str, data: dict) -> None:
        element = self.element_factory.lookup(element_id)
        if not element:
            return

        property_name = data.get("property")
        value = data.get("value")
        if property_name and hasattr(element, property_name):
            setattr(element, property_name, value)

    def _apply_delete(self, element_id: str) -> None:
        element = self.element_factory.lookup(element_id)
        if element:
            element.unlink()

    def _handle_ack(self, message: Message) -> None:
        payload = message.payload
        element_id = payload.get("element_id", "")
        version = payload.get("version", 0)
        self._conflict_manager.acknowledge_change(element_id, version)

    def _handle_sync(self, message: Message) -> None:
        # TODO: Full state sync
        pass

    def _on_connected(self) -> None:
        self.event_manager.handle(CollaborationConnected(
            session_id=self._session_id or "",
            user_id=self._user_id,
        ))

    def _on_disconnected(self, reason: str) -> None:
        self.event_manager.handle(CollaborationDisconnected(reason=reason))

    @event_handler(ElementCreated)
    def _on_element_created(self, event: ElementCreated) -> None:
        if not self._enabled or self._applying_remote:
            return
        self._pending_changes.append({
            "type": "create",
            "element_id": event.element.id,
            "data": {
                "type": type(event.element).__name__,
                "timestamp": time.time(),
            },
        })

    @event_handler(ElementDeleted)
    def _on_element_deleted(self, event: ElementDeleted) -> None:
        if not self._enabled or self._applying_remote:
            return
        self._pending_changes.append({
            "type": "delete",
            "element_id": event.element.id,
            "data": {"timestamp": time.time()},
        })

    @event_handler(AttributeUpdated)
    def _on_attribute_updated(self, event: AttributeUpdated) -> None:
        if not self._enabled or self._applying_remote:
            return
        self._pending_changes.append({
            "type": "update",
            "element_id": event.element.id,
            "data": {
                "property": event.property.name,
                "value": event.new_value,
                "old_value": event.old_value,
                "timestamp": time.time(),
            },
        })

    @event_handler(AssociationSet)
    def _on_association_set(self, event: AssociationSet) -> None:
        if not self._enabled or self._applying_remote:
            return
        self._pending_changes.append({
            "type": "update",
            "element_id": event.element.id,
            "data": {
                "property": event.property.name,
                "value": event.new_value.id if event.new_value else None,
                "old_value": event.old_value.id if event.old_value else None,
                "timestamp": time.time(),
            },
        })

    @event_handler(TransactionCommit)
    def _on_transaction_commit(self, event: TransactionCommit) -> None:
        if not self._enabled or not self._pending_changes:
            return

        for change in self._pending_changes:
            element_id = change["element_id"]
            version = self._conflict_manager.record_local_change(
                ChangeRecord(
                    element_id=element_id,
                    property_name=change["data"].get("property", ""),
                    value=change["data"].get("value"),
                    version=0,
                    timestamp=change["data"].get("timestamp", time.time()),
                    user_id=self._user_id,
                )
            )
            msg = create_change_message(
                self._user_id,
                change["type"],
                element_id,
                change["data"],
                version,
            )
            asyncio.create_task(self._client.send(msg.to_json()))

        self._pending_changes.clear()
