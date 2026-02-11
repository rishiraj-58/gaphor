"""Tests for the collaboration wire-format messages."""

import json
import pytest

from gaphor.collaboration.messages import (
    ConflictNotification,
    CursorMove,
    FullStateSync,
    ModelOperation,
    OperationAck,
    SessionJoin,
    SessionLeave,
    UserListUpdate,
    decode,
    encode,
)


# ---------------------------------------------------------------------------
# Round-trip helpers
# ---------------------------------------------------------------------------

def roundtrip(msg):
    """Encode then decode a message and return the result."""
    return decode(encode(msg))


# ---------------------------------------------------------------------------
# SessionJoin
# ---------------------------------------------------------------------------

class TestSessionJoin:
    def test_defaults(self):
        msg = SessionJoin()
        assert msg.type == "session_join"
        assert msg.user_id == ""
        assert msg.user_color == ""

    def test_with_values(self):
        msg = SessionJoin(
            user_id="alice",
            display_name="Alice",
            diagram_id="d1",
            user_color="rgb(56, 135, 235)",
        )
        assert msg.user_id == "alice"
        assert msg.user_color == "rgb(56, 135, 235)"

    def test_roundtrip(self):
        msg = SessionJoin(user_id="alice", display_name="Alice", diagram_id="d1")
        result = roundtrip(msg)
        assert isinstance(result, SessionJoin)
        assert result.user_id == "alice"
        assert result.display_name == "Alice"
        assert result.diagram_id == "d1"

    def test_type_field_is_preserved(self):
        msg = SessionJoin(user_id="u1")
        raw = encode(msg)
        data = json.loads(raw)
        assert data["type"] == "session_join"


class TestSessionLeave:
    def test_roundtrip(self):
        msg = SessionLeave(user_id="bob", display_name="Bob")
        result = roundtrip(msg)
        assert isinstance(result, SessionLeave)
        assert result.user_id == "bob"

    def test_type_field(self):
        assert SessionLeave().type == "session_leave"


class TestCursorMove:
    def test_roundtrip(self):
        msg = CursorMove(user_id="u1", diagram_id="d1", x=123.4, y=567.8)
        result = roundtrip(msg)
        assert isinstance(result, CursorMove)
        assert result.x == pytest.approx(123.4)
        assert result.y == pytest.approx(567.8)
        assert result.diagram_id == "d1"

    def test_type_field(self):
        assert CursorMove().type == "cursor_move"


class TestModelOperation:
    def test_roundtrip_attribute_op(self):
        msg = ModelOperation(
            op_type="a",
            payload=["elem-1", "name", "MyClass"],
            origin_user_id="alice",
            client_sequence=5,
            vector_clock={"alice": 5},
            diagram_id="d1",
        )
        result = roundtrip(msg)
        assert isinstance(result, ModelOperation)
        assert result.op_type == "a"
        assert result.payload == ["elem-1", "name", "MyClass"]
        assert result.client_sequence == 5
        assert result.vector_clock == {"alice": 5}

    def test_roundtrip_create_op(self):
        msg = ModelOperation(
            op_type="c",
            payload=["UML", "Class", "elem-2", "diag-1"],
            origin_user_id="bob",
            client_sequence=1,
        )
        result = roundtrip(msg)
        assert isinstance(result, ModelOperation)
        assert result.op_type == "c"
        assert result.payload[2] == "elem-2"

    def test_default_vector_clock(self):
        msg = ModelOperation(op_type="a", payload=[])
        assert msg.vector_clock == {}

    def test_type_field(self):
        assert ModelOperation().type == "model_operation"


class TestOperationAck:
    def test_roundtrip(self):
        msg = OperationAck(client_sequence=3, server_sequence=10)
        result = roundtrip(msg)
        assert isinstance(result, OperationAck)
        assert result.client_sequence == 3
        assert result.server_sequence == 10

    def test_type_field(self):
        assert OperationAck().type == "operation_ack"


class TestConflictNotification:
    def test_roundtrip(self):
        msg = ConflictNotification(
            client_sequence=7,
            resolution="Last-writer-wins; your change was discarded.",
            accepted=False,
        )
        result = roundtrip(msg)
        assert isinstance(result, ConflictNotification)
        assert result.client_sequence == 7
        assert result.accepted is False
        assert "discarded" in result.resolution

    def test_accepted_true(self):
        msg = ConflictNotification(client_sequence=1, resolution="kept", accepted=True)
        result = roundtrip(msg)
        assert result.accepted is True

    def test_type_field(self):
        assert ConflictNotification().type == "conflict_notification"


class TestFullStateSync:
    def test_roundtrip_empty(self):
        msg = FullStateSync(operations=[], server_sequence=0)
        result = roundtrip(msg)
        assert isinstance(result, FullStateSync)
        assert result.operations == []
        assert result.server_sequence == 0

    def test_roundtrip_with_ops(self):
        ops = [
            {"type": "model_operation", "op_type": "a", "payload": ["e1", "name", "X"]},
            {"type": "model_operation", "op_type": "c", "payload": ["UML", "Class", "e2", None]},
        ]
        msg = FullStateSync(operations=ops, server_sequence=2)
        result = roundtrip(msg)
        assert len(result.operations) == 2
        assert result.server_sequence == 2

    def test_type_field(self):
        assert FullStateSync().type == "full_state_sync"


class TestUserListUpdate:
    def test_roundtrip(self):
        msg = UserListUpdate(users=[
            {"user_id": "alice", "display_name": "Alice", "color": "rgb(56, 135, 235)"},
            {"user_id": "bob",   "display_name": "Bob",   "color": "rgb(51, 188, 140)"},
        ])
        result = roundtrip(msg)
        assert isinstance(result, UserListUpdate)
        assert len(result.users) == 2
        assert result.users[0]["user_id"] == "alice"

    def test_empty_users(self):
        msg = UserListUpdate(users=[])
        result = roundtrip(msg)
        assert result.users == []

    def test_type_field(self):
        assert UserListUpdate().type == "user_list_update"


# ---------------------------------------------------------------------------
# decode() error handling
# ---------------------------------------------------------------------------

class TestDecode:
    def test_unknown_type_raises(self):
        raw = json.dumps({"type": "made_up_type", "data": 1})
        with pytest.raises(ValueError, match="Unknown collaboration message type"):
            decode(raw)

    def test_missing_type_raises(self):
        raw = json.dumps({"user_id": "alice"})
        with pytest.raises(ValueError):
            decode(raw)

    def test_invalid_json_raises(self):
        with pytest.raises(Exception):
            decode("{not json}")

    def test_encode_produces_valid_json(self):
        msg = CursorMove(user_id="u1", diagram_id="d1", x=1.0, y=2.0)
        raw = encode(msg)
        data = json.loads(raw)
        assert data["type"] == "cursor_move"
        assert data["x"] == pytest.approx(1.0)
