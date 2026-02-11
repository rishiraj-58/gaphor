"""Tests for collaboration service."""

import time
import pytest

from gaphor.services.collaboration.conflict import (
    ChangeRecord,
    ConflictManager,
    ConflictStrategy,
    VersionVector,
)
from gaphor.services.collaboration.cursors import CursorManager, RemoteCursor
from gaphor.services.collaboration.protocol import (
    Message,
    MessageType,
    create_cursor_message,
    create_join_message,
    create_change_message,
)


class TestVersionVector:
    def test_initial_version_is_zero(self):
        vv = VersionVector()
        assert vv.get("element1") == 0

    def test_increment_version(self):
        vv = VersionVector()
        v1 = vv.increment("element1")
        assert v1 == 1
        v2 = vv.increment("element1")
        assert v2 == 2

    def test_set_version(self):
        vv = VersionVector()
        vv.set("element1", 5)
        assert vv.get("element1") == 5

    def test_set_version_only_increases(self):
        vv = VersionVector()
        vv.set("element1", 5)
        vv.set("element1", 3)
        assert vv.get("element1") == 5

    def test_has_conflict(self):
        vv = VersionVector()
        vv.increment("element1")
        assert vv.has_conflict("element1", 1)
        assert not vv.has_conflict("element1", 2)


class TestConflictManager:
    def test_record_local_change(self):
        cm = ConflictManager()
        change = ChangeRecord(
            element_id="e1",
            property_name="name",
            value="test",
            version=0,
            timestamp=time.time(),
            user_id="user1",
        )
        version = cm.record_local_change(change)
        assert version == 1
        assert cm.get_version("e1") == 1

    def test_apply_remote_change_no_conflict(self):
        cm = ConflictManager()
        change = ChangeRecord(
            element_id="e1",
            property_name="name",
            value="test",
            version=1,
            timestamp=time.time(),
            user_id="user2",
        )
        result = cm.apply_remote_change(change)
        assert result is None
        assert cm.get_version("e1") == 1

    def test_last_write_wins_strategy(self):
        cm = ConflictManager(strategy=ConflictStrategy.LAST_WRITE_WINS)
        now = time.time()

        local_change = ChangeRecord(
            element_id="e1",
            property_name="name",
            value="local",
            version=1,
            timestamp=now - 1,
            user_id="user1",
        )
        cm.record_local_change(local_change)

        remote_change = ChangeRecord(
            element_id="e1",
            property_name="name",
            value="remote",
            version=1,
            timestamp=now,
            user_id="user2",
        )
        result = cm.apply_remote_change(remote_change)

        assert result is not None
        assert result.winning_change == remote_change
        assert result.strategy_used == ConflictStrategy.LAST_WRITE_WINS


class TestCursorManager:
    def test_add_user(self):
        cm = CursorManager()
        cursor = cm.add_user("user1", "Alice", "#FF0000")
        assert cursor.user_id == "user1"
        assert cursor.username == "Alice"
        assert cursor.color == "#FF0000"

    def test_remove_user(self):
        cm = CursorManager()
        cm.add_user("user1", "Alice")
        cm.remove_user("user1")
        assert cm.get_cursor("user1") is None

    def test_update_cursor(self):
        cm = CursorManager()
        cm.add_user("user1", "Alice")
        cm.update_cursor("user1", "diagram1", 100.0, 200.0)
        cursor = cm.get_cursor("user1")
        assert cursor.diagram_id == "diagram1"
        assert cursor.x == 100.0
        assert cursor.y == 200.0

    def test_get_cursors_for_diagram(self):
        cm = CursorManager()
        cm.add_user("user1", "Alice")
        cm.add_user("user2", "Bob")
        cm.update_cursor("user1", "diagram1", 0, 0)
        cm.update_cursor("user2", "diagram2", 0, 0)

        cursors = cm.get_cursors_for_diagram("diagram1")
        assert len(cursors) == 1
        assert cursors[0].user_id == "user1"

    def test_auto_color_assignment(self):
        cm = CursorManager()
        cursor1 = cm.add_user("user1", "Alice")
        cursor2 = cm.add_user("user2", "Bob")
        assert cursor1.color != cursor2.color


class TestProtocol:
    def test_join_message(self):
        msg = create_join_message("user1", "Alice", "session1")
        assert msg.type == MessageType.JOIN
        assert msg.user_id == "user1"
        assert msg.payload["username"] == "Alice"
        assert msg.payload["session_id"] == "session1"

    def test_cursor_message(self):
        msg = create_cursor_message("user1", "diagram1", 100.0, 200.0)
        assert msg.type == MessageType.CURSOR
        assert msg.payload["diagram_id"] == "diagram1"
        assert msg.payload["x"] == 100.0
        assert msg.payload["y"] == 200.0

    def test_message_serialization(self):
        msg = create_cursor_message("user1", "diagram1", 100.0, 200.0)
        json_str = msg.to_json()
        parsed = Message.from_json(json_str)
        assert parsed.type == msg.type
        assert parsed.user_id == msg.user_id
        assert parsed.payload == msg.payload

    def test_change_message(self):
        msg = create_change_message(
            "user1", "update", "element1",
            {"property": "name", "value": "test"}, 1
        )
        assert msg.type == MessageType.CHANGE
        assert msg.payload["change_type"] == "update"
        assert msg.payload["element_id"] == "element1"
        assert msg.payload["version"] == 1
