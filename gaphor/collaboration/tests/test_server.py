"""Tests for CollaborationServer message routing and state management.

All tests run without a real WebSocket connection.  Instead they call the
private handler methods directly so that every routing decision and
state-mutation can be verified deterministically without asyncio overhead.
"""

import asyncio
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
from gaphor.collaboration.server import CollaborationServer, _ClientSession


# ---------------------------------------------------------------------------
# Async test helper
# ---------------------------------------------------------------------------

def run(coro):
    """Run a coroutine synchronously in a fresh event loop."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Stub WebSocket
# ---------------------------------------------------------------------------

class _StubWebSocket:
    """Captures all ``send()`` calls without touching the network."""

    def __init__(self):
        self.sent: list[str] = []

    async def send(self, raw: str) -> None:
        self.sent.append(raw)

    def last_decoded(self):
        return decode(self.sent[-1])

    def all_decoded(self):
        return [decode(s) for s in self.sent]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def server():
    return CollaborationServer(host="127.0.0.1", port=9999)


def _make_client(server, user_id="alice", name="Alice", diagram_id="d1"):
    ws = _StubWebSocket()
    client = _ClientSession(
        user_id=user_id,
        display_name=name,
        websocket=ws,
        diagram_id=diagram_id,
        color_css="rgb(56, 135, 235)",
    )
    server._clients[user_id] = client
    return client, ws


# ---------------------------------------------------------------------------
# Join / leave
# ---------------------------------------------------------------------------

class TestJoin:
    def test_join_assigns_colour(self, server):
        msg = SessionJoin(user_id="alice", display_name="Alice", diagram_id="d1")
        ws = _StubWebSocket()
        client = run(server._handle_join(msg, ws))
        assert client.color_css != ""

    def test_join_sends_session_join_ack(self, server):
        msg = SessionJoin(user_id="alice", display_name="Alice", diagram_id="d1")
        ws = _StubWebSocket()
        run(server._handle_join(msg, ws))
        types = [decode(m).type for m in ws.sent]
        assert "session_join" in types

    def test_join_sends_full_state_sync(self, server):
        msg = SessionJoin(user_id="alice", display_name="Alice", diagram_id="d1")
        ws = _StubWebSocket()
        run(server._handle_join(msg, ws))
        types = [decode(m).type for m in ws.sent]
        assert "full_state_sync" in types

    def test_join_sends_user_list_update(self, server):
        msg = SessionJoin(user_id="alice", display_name="Alice", diagram_id="d1")
        ws = _StubWebSocket()
        run(server._handle_join(msg, ws))
        types = [decode(m).type for m in ws.sent]
        assert "user_list_update" in types

    def test_join_stores_client(self, server):
        msg = SessionJoin(user_id="alice", display_name="Alice", diagram_id="d1")
        ws = _StubWebSocket()
        run(server._handle_join(msg, ws))
        assert "alice" in server._clients

    def test_join_ack_includes_colour(self, server):
        msg = SessionJoin(user_id="alice", display_name="Alice", diagram_id="d1")
        ws = _StubWebSocket()
        run(server._handle_join(msg, ws))
        for raw in ws.sent:
            decoded = decode(raw)
            if isinstance(decoded, SessionJoin):
                assert decoded.user_color != ""
                return
        pytest.fail("No SessionJoin ack found")

    def test_state_sync_operations_empty_initially(self, server):
        msg = SessionJoin(user_id="alice", display_name="Alice", diagram_id="d1")
        ws = _StubWebSocket()
        run(server._handle_join(msg, ws))
        for raw in ws.sent:
            decoded = decode(raw)
            if isinstance(decoded, FullStateSync):
                assert decoded.operations == []
                return
        pytest.fail("No FullStateSync found")


class TestDisconnect:
    def test_disconnect_removes_client(self, server):
        client, ws = _make_client(server, "alice")
        run(server._handle_disconnect(client))
        assert "alice" not in server._clients

    def test_disconnect_broadcasts_leave(self, server):
        client, ws_alice = _make_client(server, "alice")
        bob_client, ws_bob = _make_client(server, "bob")
        run(server._handle_disconnect(client))
        types = [decode(m).type for m in ws_bob.sent]
        assert "session_leave" in types

    def test_disconnect_includes_user_id_in_leave(self, server):
        client, _ = _make_client(server, "alice")
        bob_client, ws_bob = _make_client(server, "bob")
        run(server._handle_disconnect(client))
        leave_msgs = [decode(m) for m in ws_bob.sent if decode(m).type == "session_leave"]
        assert any(m.user_id == "alice" for m in leave_msgs)

    def test_disconnect_broadcasts_user_list(self, server):
        client, _ = _make_client(server, "alice")
        bob_client, ws_bob = _make_client(server, "bob")
        run(server._handle_disconnect(client))
        types = [decode(m).type for m in ws_bob.sent]
        assert "user_list_update" in types


# ---------------------------------------------------------------------------
# Cursor move routing
# ---------------------------------------------------------------------------

class TestCursorMove:
    def test_cursor_forwarded_to_same_diagram(self, server):
        alice, ws_alice = _make_client(server, "alice", diagram_id="d1")
        bob, ws_bob = _make_client(server, "bob", diagram_id="d1")
        msg = CursorMove(user_id="alice", diagram_id="d1", x=10.0, y=20.0)
        run(server._handle_cursor_move(msg, alice))
        types = [decode(m).type for m in ws_bob.sent]
        assert "cursor_move" in types

    def test_cursor_not_echoed_to_sender(self, server):
        alice, ws_alice = _make_client(server, "alice", diagram_id="d1")
        bob, ws_bob = _make_client(server, "bob", diagram_id="d1")
        msg = CursorMove(user_id="alice", diagram_id="d1", x=5.0, y=5.0)
        run(server._handle_cursor_move(msg, alice))
        # Alice should NOT receive her own cursor move
        assert not ws_alice.sent

    def test_cursor_not_forwarded_to_different_diagram(self, server):
        alice, ws_alice = _make_client(server, "alice", diagram_id="d1")
        carol, ws_carol = _make_client(server, "carol", diagram_id="d2")
        msg = CursorMove(user_id="alice", diagram_id="d1", x=5.0, y=5.0)
        run(server._handle_cursor_move(msg, alice))
        assert not ws_carol.sent

    def test_cursor_user_id_set_by_server(self, server):
        alice, ws_alice = _make_client(server, "alice", diagram_id="d1")
        bob, ws_bob = _make_client(server, "bob", diagram_id="d1")
        msg = CursorMove(user_id="impersonator", diagram_id="d1", x=1.0, y=1.0)
        run(server._handle_cursor_move(msg, alice))
        forwarded = decode(ws_bob.sent[-1])
        assert isinstance(forwarded, CursorMove)
        assert forwarded.user_id == "alice"  # Server enforces the real user_id


# ---------------------------------------------------------------------------
# Model operation routing
# ---------------------------------------------------------------------------

class TestModelOperation:
    def _op(self, user_id="alice", seq=1, element_id="e1", attr="name", val="X"):
        return ModelOperation(
            op_type="a",
            payload=[element_id, attr, val],
            origin_user_id=user_id,
            client_sequence=seq,
            vector_clock={user_id: seq},
            diagram_id="d1",
        )

    def test_op_broadcast_to_peers(self, server):
        alice, ws_alice = _make_client(server, "alice", diagram_id="d1")
        bob, ws_bob = _make_client(server, "bob", diagram_id="d1")
        op = self._op("alice")
        run(server._handle_model_operation(op, alice))
        types = [decode(m).type for m in ws_bob.sent]
        assert "model_operation" in types

    def test_op_not_echoed_to_originator(self, server):
        alice, ws_alice = _make_client(server, "alice", diagram_id="d1")
        bob, ws_bob = _make_client(server, "bob", diagram_id="d1")
        op = self._op("alice")
        run(server._handle_model_operation(op, alice))
        types = [decode(m).type for m in ws_alice.sent]
        # Alice should receive only an OperationAck, not a ModelOperation
        assert "model_operation" not in types
        assert "operation_ack" in types

    def test_ack_sent_to_originator(self, server):
        alice, ws_alice = _make_client(server, "alice", diagram_id="d1")
        op = self._op("alice", seq=7)
        run(server._handle_model_operation(op, alice))
        acks = [decode(m) for m in ws_alice.sent if decode(m).type == "operation_ack"]
        assert len(acks) == 1
        assert acks[0].client_sequence == 7

    def test_ack_server_sequence_advances(self, server):
        alice, ws_alice = _make_client(server, "alice", diagram_id="d1")
        for i in range(3):
            run(server._handle_model_operation(self._op("alice", seq=i + 1), alice))
        acks = [decode(m) for m in ws_alice.sent if decode(m).type == "operation_ack"]
        server_seqs = [a.server_sequence for a in acks]
        assert server_seqs == sorted(server_seqs)
        assert server_seqs[-1] == 3

    def test_op_saved_to_operation_log(self, server):
        alice, ws_alice = _make_client(server, "alice", diagram_id="d1")
        op = self._op("alice")
        run(server._handle_model_operation(op, alice))
        assert len(server._operation_log) == 1

    def test_op_not_forwarded_to_different_diagram(self, server):
        alice, ws_alice = _make_client(server, "alice", diagram_id="d1")
        carol, ws_carol = _make_client(server, "carol", diagram_id="d2")
        op = self._op("alice")
        run(server._handle_model_operation(op, alice))
        assert not ws_carol.sent

    def test_conflict_notification_sent_on_conflict(self, server):
        """Concurrently editing the same attribute triggers a conflict notification."""
        alice, ws_alice = _make_client(server, "alice", diagram_id="d1")
        bob, ws_bob = _make_client(server, "bob", diagram_id="d1")
        # Alice edits first
        op1 = self._op("alice", seq=1, element_id="e1", attr="name", val="Alice")
        run(server._handle_model_operation(op1, alice))
        ws_alice.sent.clear()
        # Bob edits the same attribute concurrently
        op2 = self._op("bob", seq=1, element_id="e1", attr="name", val="Bob")
        run(server._handle_model_operation(op2, bob))
        types = [decode(m).type for m in ws_bob.sent]
        assert "conflict_notification" in types


# ---------------------------------------------------------------------------
# State sync for late joiners
# ---------------------------------------------------------------------------

class TestStateSyncForLateJoiner:
    def test_late_joiner_receives_prior_ops(self, server):
        # Alice joins and performs operations
        alice_ws = _StubWebSocket()
        alice_join = SessionJoin(user_id="alice", display_name="Alice", diagram_id="d1")
        alice_client = run(server._handle_join(alice_join, alice_ws))

        for i in range(3):
            op = ModelOperation(
                op_type="a",
                payload=[f"e{i}", "name", f"v{i}"],
                origin_user_id="alice",
                client_sequence=i + 1,
                diagram_id="d1",
            )
            run(server._handle_model_operation(op, alice_client))

        # Bob joins late
        bob_ws = _StubWebSocket()
        bob_join = SessionJoin(user_id="bob", display_name="Bob", diagram_id="d1")
        run(server._handle_join(bob_join, bob_ws))

        sync_msgs = [decode(m) for m in bob_ws.sent if decode(m).type == "full_state_sync"]
        assert len(sync_msgs) == 1
        assert len(sync_msgs[0].operations) == 3
