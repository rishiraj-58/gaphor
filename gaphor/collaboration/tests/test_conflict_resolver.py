"""Tests for ConflictResolver – one test class per strategy."""

import pytest

from gaphor.collaboration.conflict_resolver import ConflictResolver
from gaphor.collaboration.messages import ModelOperation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_op(
    op_type: str,
    element_id: str = "elem-1",
    extra_payload=None,     # type: list or None
    user_id: str = "alice",
    client_seq: int = 1,
    vector_clock=None,      # type: dict or None
) -> ModelOperation:
    """Build a minimal ModelOperation for testing."""
    payload: list
    if op_type in ("a",):
        # ("a", element_id, attr_name, value)
        payload = [element_id, "name", "SomeValue"]
    elif op_type in ("mu", "hp"):
        payload = [element_id] + (extra_payload or [])
    elif op_type in ("c",):
        payload = ["UML", "Class", element_id, "diag-1"]
    elif op_type in ("u",):
        payload = [element_id, "diag-1"]
    elif op_type in ("s", "d"):
        payload = [element_id, "ownedElement", "other-elem"]
    elif op_type in ("ic", "id", "ir"):
        payload = [element_id, 0, "connected-elem", 0]
    elif op_type in ("ls", "lm"):
        payload = [element_id, 1, 2]
    else:
        payload = [element_id]

    if extra_payload:
        payload = payload[:1] + extra_payload + payload[1:]

    return ModelOperation(
        op_type=op_type,
        payload=payload,
        origin_user_id=user_id,
        client_sequence=client_seq,
        vector_clock=vector_clock or {user_id: client_seq},
        diagram_id="diag-1",
    )


# ---------------------------------------------------------------------------
# No-conflict baseline
# ---------------------------------------------------------------------------

class TestNoConflict:
    def test_single_op_accepted(self):
        resolver = ConflictResolver()
        op = make_op("a")
        result = resolver.resolve(op)
        assert not result.conflict_detected
        assert result.ops_to_apply == [op]
        assert result.description == ""

    def test_ops_from_same_user_are_never_conflicting(self):
        """Causally-ordered ops from the same user must not trigger resolution."""
        resolver = ConflictResolver()
        op1 = make_op("a", element_id="e1", user_id="alice", client_seq=1)
        op2 = make_op("a", element_id="e1", user_id="alice", client_seq=2)
        resolver.resolve(op1)
        result = resolver.resolve(op2)
        assert not result.conflict_detected

    def test_ops_on_different_elements_no_conflict(self):
        resolver = ConflictResolver()
        op1 = make_op("a", element_id="elem-A", user_id="alice")
        op2 = make_op("a", element_id="elem-B", user_id="bob")
        resolver.resolve(op1)
        result = resolver.resolve(op2)
        assert not result.conflict_detected

    def test_server_sequence_increments(self):
        resolver = ConflictResolver()
        assert resolver.server_sequence == 0
        resolver.resolve(make_op("a", user_id="alice"))
        assert resolver.server_sequence == 1
        resolver.resolve(make_op("a", element_id="e2", user_id="bob"))
        assert resolver.server_sequence == 2

    def test_different_attributes_on_same_element_no_conflict(self):
        """Attribute ops on different properties of the same element do not conflict."""
        resolver = ConflictResolver()
        # "name" attribute op
        op1 = ModelOperation(
            op_type="a",
            payload=["elem-1", "name", "Alice"],
            origin_user_id="alice",
            client_sequence=1,
        )
        # "note" attribute op – different property
        op2 = ModelOperation(
            op_type="a",
            payload=["elem-1", "note", "some note"],
            origin_user_id="bob",
            client_sequence=1,
        )
        resolver.resolve(op1)
        result = resolver.resolve(op2)
        assert not result.conflict_detected


# ---------------------------------------------------------------------------
# Strategy 1 – Last-Writer-Wins (LWW)
# ---------------------------------------------------------------------------

class TestLastWriterWins:
    def _setup_conflict(self, op_type="a", attr="name"):
        """Return a resolver that already has Alice's op in its log."""
        resolver = ConflictResolver()
        alice_op = ModelOperation(
            op_type=op_type,
            payload=["elem-1", attr, "Alice's value"],
            origin_user_id="alice",
            client_sequence=1,
            vector_clock={"alice": 1},
        )
        resolver.resolve(alice_op)
        return resolver, alice_op

    def test_attribute_conflict_detected(self):
        resolver, _ = self._setup_conflict("a", "name")
        bob_op = ModelOperation(
            op_type="a",
            payload=["elem-1", "name", "Bob's value"],
            origin_user_id="bob",
            client_sequence=1,
            vector_clock={"bob": 1},
        )
        result = resolver.resolve(bob_op)
        assert result.conflict_detected

    def test_incoming_op_wins(self):
        """The newly-arriving op (later at the server) is applied."""
        resolver, _ = self._setup_conflict("a", "name")
        bob_op = ModelOperation(
            op_type="a",
            payload=["elem-1", "name", "Bob's value"],
            origin_user_id="bob",
            client_sequence=1,
        )
        result = resolver.resolve(bob_op)
        assert result.ops_to_apply == [bob_op]

    def test_description_mentions_lww(self):
        resolver, _ = self._setup_conflict("a", "name")
        bob_op = ModelOperation(
            op_type="a",
            payload=["elem-1", "name", "Bob's value"],
            origin_user_id="bob",
            client_sequence=1,
        )
        result = resolver.resolve(bob_op)
        assert "last-writer-wins" in result.description.lower() or "superseded" in result.description.lower()

    def test_matrix_update_lww(self):
        resolver = ConflictResolver()
        alice_op = ModelOperation(
            op_type="mu",
            payload=["elem-1", (1, 0, 0, 1, 10, 20)],
            origin_user_id="alice",
            client_sequence=1,
        )
        resolver.resolve(alice_op)
        bob_op = ModelOperation(
            op_type="mu",
            payload=["elem-1", (1, 0, 0, 1, 30, 40)],
            origin_user_id="bob",
            client_sequence=1,
        )
        result = resolver.resolve(bob_op)
        assert result.conflict_detected
        assert result.ops_to_apply == [bob_op]

    def test_handle_position_lww(self):
        resolver = ConflictResolver()
        alice_op = ModelOperation(
            op_type="hp",
            payload=["line-1", 0, (5.0, 10.0)],
            origin_user_id="alice",
            client_sequence=1,
        )
        resolver.resolve(alice_op)
        bob_op = ModelOperation(
            op_type="hp",
            payload=["line-1", 0, (50.0, 80.0)],
            origin_user_id="bob",
            client_sequence=1,
        )
        result = resolver.resolve(bob_op)
        assert result.conflict_detected
        assert result.ops_to_apply == [bob_op]

    def test_multiple_prior_ops_same_attr_still_lww(self):
        """Multiple prior ops on the same attribute still trigger exactly one LWW."""
        resolver = ConflictResolver()
        for i in range(3):
            resolver.resolve(ModelOperation(
                op_type="a",
                payload=["elem-1", "name", f"val-{i}"],
                origin_user_id="alice",
                client_sequence=i + 1,
            ))
        bob_op = ModelOperation(
            op_type="a",
            payload=["elem-1", "name", "Bob's final"],
            origin_user_id="bob",
            client_sequence=1,
        )
        result = resolver.resolve(bob_op)
        assert result.conflict_detected
        assert len(result.ops_to_apply) == 1


# ---------------------------------------------------------------------------
# Strategy 2 – Creation-before-Deletion (CBD)
# ---------------------------------------------------------------------------

class TestCreationBeforeDeletion:
    def test_delete_after_create_detected(self):
        resolver = ConflictResolver()
        # Alice creates the element
        create_op = ModelOperation(
            op_type="c",
            payload=["UML", "Class", "elem-1", "diag-1"],
            origin_user_id="alice",
            client_sequence=1,
        )
        resolver.resolve(create_op)
        # Bob tries to delete the same element concurrently
        delete_op = ModelOperation(
            op_type="u",
            payload=["elem-1", "diag-1"],
            origin_user_id="bob",
            client_sequence=1,
        )
        result = resolver.resolve(delete_op)
        assert result.conflict_detected

    def test_create_before_delete_in_resolved_order(self):
        resolver = ConflictResolver()
        create_op = ModelOperation(
            op_type="c",
            payload=["UML", "Class", "elem-1", "diag-1"],
            origin_user_id="alice",
            client_sequence=1,
        )
        resolver.resolve(create_op)
        delete_op = ModelOperation(
            op_type="u",
            payload=["elem-1", "diag-1"],
            origin_user_id="bob",
            client_sequence=1,
        )
        result = resolver.resolve(delete_op)
        # Result should have create before delete
        types = [op.op_type for op in result.ops_to_apply]
        create_idx = types.index("c")
        delete_idx = types.index("u")
        assert create_idx < delete_idx

    def test_description_mentions_creation_deletion(self):
        resolver = ConflictResolver()
        create_op = ModelOperation(
            op_type="c",
            payload=["UML", "Class", "elem-1", "diag-1"],
            origin_user_id="alice",
            client_sequence=1,
        )
        resolver.resolve(create_op)
        delete_op = ModelOperation(
            op_type="u",
            payload=["elem-1", "diag-1"],
            origin_user_id="bob",
            client_sequence=1,
        )
        result = resolver.resolve(delete_op)
        desc = result.description.lower()
        assert "creation" in desc or "create" in desc
        assert "delet" in desc

    def test_delete_without_prior_create_no_conflict(self):
        """An isolated delete (no prior create in the window) is not a conflict."""
        resolver = ConflictResolver()
        delete_op = ModelOperation(
            op_type="u",
            payload=["elem-unknown", "diag-1"],
            origin_user_id="bob",
            client_sequence=1,
        )
        result = resolver.resolve(delete_op)
        assert not result.conflict_detected


# ---------------------------------------------------------------------------
# Strategy 3 – Append-Only Association (AOA)
# ---------------------------------------------------------------------------

class TestAppendOnlyAssociation:
    def test_concurrent_assoc_set_detected(self):
        resolver = ConflictResolver()
        alice_op = ModelOperation(
            op_type="s",
            payload=["elem-1", "ownedElement", "child-A"],
            origin_user_id="alice",
            client_sequence=1,
        )
        resolver.resolve(alice_op)
        bob_op = ModelOperation(
            op_type="s",
            payload=["elem-1", "ownedElement", "child-B"],
            origin_user_id="bob",
            client_sequence=1,
        )
        result = resolver.resolve(bob_op)
        assert result.conflict_detected

    def test_both_ops_kept(self):
        resolver = ConflictResolver()
        alice_op = ModelOperation(
            op_type="s",
            payload=["elem-1", "ownedElement", "child-A"],
            origin_user_id="alice",
            client_sequence=1,
        )
        resolver.resolve(alice_op)
        bob_op = ModelOperation(
            op_type="s",
            payload=["elem-1", "ownedElement", "child-B"],
            origin_user_id="bob",
            client_sequence=1,
        )
        result = resolver.resolve(bob_op)
        # Bob's incoming op should be in the apply list
        assert bob_op in result.ops_to_apply

    def test_description_mentions_association(self):
        resolver = ConflictResolver()
        alice_op = ModelOperation(
            op_type="d",
            payload=["elem-1", "ownedElement", "child-A"],
            origin_user_id="alice",
            client_sequence=1,
        )
        resolver.resolve(alice_op)
        bob_op = ModelOperation(
            op_type="d",
            payload=["elem-1", "ownedElement", "child-A"],
            origin_user_id="bob",
            client_sequence=1,
        )
        result = resolver.resolve(bob_op)
        assert "association" in result.description.lower()

    def test_item_connect_aoa(self):
        resolver = ConflictResolver()
        op1 = ModelOperation(
            op_type="ic",
            payload=["line-1", 0, "elem-X", 0],
            origin_user_id="alice",
            client_sequence=1,
        )
        resolver.resolve(op1)
        op2 = ModelOperation(
            op_type="ic",
            payload=["line-1", 0, "elem-Y", 1],
            origin_user_id="bob",
            client_sequence=1,
        )
        result = resolver.resolve(op2)
        assert result.conflict_detected
        assert op2 in result.ops_to_apply


# ---------------------------------------------------------------------------
# Log windowing
# ---------------------------------------------------------------------------

class TestLogWindow:
    def test_window_does_not_exceed_limit(self):
        resolver = ConflictResolver(_window=10)
        for i in range(25):
            resolver.resolve(ModelOperation(
                op_type="a",
                payload=[f"elem-{i}", "name", f"v{i}"],
                origin_user_id="alice",
                client_sequence=i + 1,
            ))
        # The internal log should be bounded by the window
        assert len(resolver._log) <= 10

    def test_old_ops_evicted_and_no_conflict(self):
        """After the window evicts Alice's op, Bob's matching op should NOT conflict."""
        resolver = ConflictResolver(_window=3)
        # Alice's op on elem-target
        alice_op = ModelOperation(
            op_type="a",
            payload=["elem-target", "name", "Alice"],
            origin_user_id="alice",
            client_sequence=1,
        )
        resolver.resolve(alice_op)
        # Fill the window with unrelated ops to push alice's op out
        for i in range(3):
            resolver.resolve(ModelOperation(
                op_type="a",
                payload=[f"filler-{i}", "note", "x"],
                origin_user_id="charlie",
                client_sequence=i + 1,
            ))
        # Now Bob's op on the same element should NOT trigger a conflict
        bob_op = ModelOperation(
            op_type="a",
            payload=["elem-target", "name", "Bob"],
            origin_user_id="bob",
            client_sequence=1,
        )
        result = resolver.resolve(bob_op)
        assert not result.conflict_detected
