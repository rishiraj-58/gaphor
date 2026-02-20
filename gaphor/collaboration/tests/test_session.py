"""Tests for CollaborationSession."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import time

import pytest

from collaboration.events import CursorMoved, OperationReceived, UserJoined
from collaboration.operations import OperationType
from collaboration.session import CollaborationSession
from collaboration.user import CollaborationUser


class MockEventManager:
    def __init__(self):
        self.events = []

    def handle(self, event):
        self.events.append(event)


class TestCollaborationSession:
    def test_create_session(self):
        user = CollaborationUser.create("user-1", "Test User", is_local=True)
        session = CollaborationSession("session-1", user)

        assert session.session_id == "session-1"
        assert session.local_user == user
        assert "user-1" in session.users

    def test_connect_disconnect(self):
        user = CollaborationUser.create("user-1", "Test User", is_local=True)
        session = CollaborationSession("session-1", user)

        messages = []
        session.add_message_handler(lambda m: messages.append(m))

        session.connect()
        assert session.is_connected

        session.disconnect()
        assert not session.is_connected

    def test_broadcast_cursor_position(self):
        user = CollaborationUser.create("user-1", "Test User", is_local=True)
        session = CollaborationSession("session-1", user)

        messages = []
        session.add_message_handler(lambda m: messages.append(m))
        session.connect()

        session.broadcast_cursor_position("diagram-1", 100.0, 200.0, ["item-1"])

        assert len(messages) == 2  # user_joined + cursor_moved
        cursor_msg = messages[1]
        assert cursor_msg["type"] == "cursor_moved"
        assert cursor_msg["x"] == 100.0
        assert cursor_msg["y"] == 200.0

    def test_create_operation(self):
        user = CollaborationUser.create("user-1", "Test User", is_local=True)
        session = CollaborationSession("session-1", user)

        messages = []
        session.add_message_handler(lambda m: messages.append(m))
        session.connect()

        operation = session.create_operation(
            OperationType.CREATE,
            "elem-1",
            "diagram-1",
            {"element_type": "Class"},
        )

        assert operation.user_id == "user-1"
        assert operation.element_id == "elem-1"
        assert session.version == 1

    def test_handle_user_joined(self):
        user = CollaborationUser.create("user-1", "Test User", is_local=True)
        event_manager = MockEventManager()
        session = CollaborationSession("session-1", user, event_manager)
        session.connect()

        remote_user_data = {
            "type": "user_joined",
            "session_id": "session-1",
            "user": {
                "user_id": "user-2",
                "display_name": "Remote User",
                "color": [0.5, 0.5, 0.5, 1.0],
                "cursor_position": None,
            },
            "timestamp": time.time(),
        }

        session.handle_remote_message(remote_user_data)

        assert "user-2" in session.users
        assert any(isinstance(e, UserJoined) for e in event_manager.events)

    def test_handle_cursor_moved(self):
        user = CollaborationUser.create("user-1", "Test User", is_local=True)
        event_manager = MockEventManager()
        session = CollaborationSession("session-1", user, event_manager)
        session.connect()

        # Add remote user first
        session._users["user-2"] = CollaborationUser.create("user-2", "Remote")

        cursor_msg = {
            "type": "cursor_moved",
            "session_id": "session-1",
            "user_id": "user-2",
            "diagram_id": "diagram-1",
            "x": 150.0,
            "y": 250.0,
            "selected_item_ids": [],
            "timestamp": time.time(),
        }

        session.handle_remote_message(cursor_msg)

        remote_user = session.users["user-2"]
        assert remote_user.cursor_position.x == 150.0
        assert remote_user.cursor_position.y == 250.0

    def test_handle_operation(self):
        user = CollaborationUser.create("user-1", "Test User", is_local=True)
        event_manager = MockEventManager()
        session = CollaborationSession("session-1", user, event_manager)
        session.connect()

        op_msg = {
            "type": "operation",
            "session_id": "session-1",
            "operation": {
                "operation_id": "op-1",
                "operation_type": "update_attribute",
                "element_id": "elem-1",
                "diagram_id": "diagram-1",
                "user_id": "user-2",
                "timestamp": time.time(),
                "data": {"attribute_name": "name", "new_value": "Test"},
                "vector_clock": {"user-2": 1},
            },
            "timestamp": time.time(),
        }

        session.handle_remote_message(op_msg)

        assert session.version == 1
        assert any(isinstance(e, OperationReceived) for e in event_manager.events)

    def test_ignore_own_cursor_updates(self):
        user = CollaborationUser.create("user-1", "Test User", is_local=True)
        event_manager = MockEventManager()
        session = CollaborationSession("session-1", user, event_manager)
        session.connect()

        cursor_msg = {
            "type": "cursor_moved",
            "session_id": "session-1",
            "user_id": "user-1",  # Same as local user
            "diagram_id": "diagram-1",
            "x": 100.0,
            "y": 200.0,
            "selected_item_ids": [],
            "timestamp": time.time(),
        }

        initial_events = len(event_manager.events)
        session.handle_remote_message(cursor_msg)

        # No CursorMoved event should be emitted
        cursor_events = [e for e in event_manager.events[initial_events:] if isinstance(e, CursorMoved)]
        assert len(cursor_events) == 0

    def test_get_user_color(self):
        user = CollaborationUser.create("user-1", "Test User", is_local=True)
        session = CollaborationSession("session-1", user)

        color = session.get_user_color("user-1")
        assert color is not None
        assert len(color) == 4

        color = session.get_user_color("nonexistent")
        assert color is None
