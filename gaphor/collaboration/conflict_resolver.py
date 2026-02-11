"""Conflict resolution for concurrent model operations.

When two clients edit the same diagram simultaneously their operations
may arrive at the server in an order that does not reflect their true
causal relationship.  This module detects such situations and resolves
them so that all clients converge to the same model state.

Conflict-resolution strategies
-------------------------------

Three strategies are implemented, chosen automatically based on the
*type* of the conflicting operations:

1. **Last-Writer-Wins (LWW)** – applied to attribute changes (``"a"``)
   and matrix/position updates (``"mu"``, ``"hp"``).
   Two operations conflict on the same attribute of the same element.
   The one that arrived *later at the server* (higher ``server_sequence``)
   wins; the earlier one is silently discarded.  This is the right
   choice for free-form properties like position and text because users
   who are "fighting" over an element will naturally accept the most
   recent state.

2. **Creation-before-Deletion (CBD)** – applied when one operation
   *creates* an element (``"c"``) and a concurrent operation *deletes*
   (``"u"``) the same element.  The creation is always applied first,
   then the deletion, regardless of arrival order.  This prevents the
   common race where a client tries to delete an element that a peer
   is still building.

3. **Append-Only Association (AOA)** – applied to association changes
   (``"s"``, ``"d"``).  Instead of discarding either operation both are
   kept and applied in *server-arrival order*.  Associations in UML
   models form directed graphs where ordering matters, so both user
   intentions are preserved.

Usage
-----
The ``ConflictResolver`` class is instantiated once by the server and
its ``resolve()`` method is called whenever a new ``ModelOperation``
is received.  It returns a ``Resolution`` named tuple containing the
ordered list of operations that should be applied and broadcast, plus
a human-readable description used in the ``ConflictNotification``
message sent back to the affected client.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import NamedTuple

from gaphor.collaboration.messages import ModelOperation

log = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Op-type constants (mirror gaphor.storage.recovery.Recorder)
# ------------------------------------------------------------------
_OP_CREATE = "c"
_OP_DELETE = "u"
_OP_ATTRIBUTE = "a"
_OP_ASSOC_SET = "s"
_OP_ASSOC_DEL = "d"
_OP_MATRIX = "mu"
_OP_TYPE_SWAP = "ts"
_OP_HANDLE_POS = "hp"
_OP_ITEM_CONNECT = "ic"
_OP_ITEM_DISCONNECT = "id"
_OP_ITEM_RECONNECT = "ir"
_OP_LINE_SPLIT = "ls"
_OP_LINE_MERGE = "lm"

# Ops where LWW is the safest resolution
_LWW_OPS: frozenset[str] = frozenset({
    _OP_ATTRIBUTE,
    _OP_MATRIX,
    _OP_HANDLE_POS,
})

# Ops that affect graph connectivity (keep both, ordered)
_ASSOC_OPS: frozenset[str] = frozenset({
    _OP_ASSOC_SET,
    _OP_ASSOC_DEL,
    _OP_ITEM_CONNECT,
    _OP_ITEM_DISCONNECT,
    _OP_ITEM_RECONNECT,
    _OP_LINE_SPLIT,
    _OP_LINE_MERGE,
})


class Resolution(NamedTuple):
    """Result returned by ``ConflictResolver.resolve()``."""
    ops_to_apply: list[ModelOperation]   # ordered ops for the server to apply
    conflict_detected: bool
    description: str                     # human-readable explanation


@dataclass
class _PendingOp:
    """Internal record kept in the server-side operation log."""
    op: ModelOperation
    server_sequence: int


@dataclass
class ConflictResolver:
    """Stateful conflict resolver for a single collaboration session.

    ``resolve()`` is called for *every* incoming ``ModelOperation``.
    When no conflict is detected it returns immediately.  When a
    conflict is detected it applies the appropriate strategy and
    returns the reconciled op list.

    The internal ``_log`` is intentionally bounded: we only need to
    look back as far as the maximum possible clock skew between two
    peers.  In practice the last ``_window`` operations are sufficient.
    """

    _window: int = 200   # how many recent ops to keep for conflict detection

    def __post_init__(self) -> None:
        self._log: list[_PendingOp] = []
        self._server_sequence: int = 0

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def resolve(self, incoming: ModelOperation) -> Resolution:
        """Evaluate *incoming* against the recent operation log and return
        a ``Resolution`` describing what should be applied.

        The server_sequence is advanced *inside* this method so that
        every call produces a distinct sequence number even when called
        from a synchronous event loop.
        """
        self._server_sequence += 1
        seq = self._server_sequence

        conflicts = self._find_conflicts(incoming)
        if not conflicts:
            self._record(incoming, seq)
            return Resolution(
                ops_to_apply=[incoming],
                conflict_detected=False,
                description="",
            )

        # Choose strategy based on op types involved
        result = self._apply_strategy(incoming, conflicts, seq)
        self._record(incoming, seq)
        return result

    @property
    def server_sequence(self) -> int:
        return self._server_sequence

    # ------------------------------------------------------------------
    # Conflict detection
    # ------------------------------------------------------------------

    def _find_conflicts(self, incoming: ModelOperation) -> list[_PendingOp]:
        """Return any recent ops that conflict with *incoming*."""
        conflicts: list[_PendingOp] = []
        for pending in self._log:
            if self._ops_conflict(incoming, pending.op):
                conflicts.append(pending)
        return conflicts

    @staticmethod
    def _element_id_of(op: ModelOperation) -> str | None:
        """Extract the element id from op payload regardless of op type.

        Payload layouts (mirroring gaphor.storage.recovery.Recorder):
          'c'  -> [namespace, type_name, element_id, diagram_id]   (index 2)
          all others -> [element_id, ...]                           (index 0)
        """
        if not op.payload:
            return None
        if op.op_type == _OP_CREATE:
            # payload[0] is the modeling-language namespace string
            # payload[1] is the class name
            # payload[2] is the element id
            if len(op.payload) >= 3:
                return str(op.payload[2])
            return None
        return str(op.payload[0])

    @staticmethod
    def _attribute_name_of(op: ModelOperation) -> str | None:
        """For attribute/association ops, return the property name."""
        if op.op_type in (_OP_ATTRIBUTE, _OP_ASSOC_SET, _OP_ASSOC_DEL) and len(op.payload) >= 2:
            return str(op.payload[1])
        return None

    def _ops_conflict(self, a: ModelOperation, b: ModelOperation) -> bool:
        """Return True if operations *a* and *b* operate on the same
        model element in a way that could produce divergence."""
        if a.origin_user_id == b.origin_user_id:
            # Same user: operations are causally ordered by client_sequence
            return False

        elem_a = self._element_id_of(a)
        elem_b = self._element_id_of(b)
        if elem_a is None or elem_b is None or elem_a != elem_b:
            return False

        # Same element – check if they touch the same property
        if a.op_type in _LWW_OPS and b.op_type in _LWW_OPS:
            return self._attribute_name_of(a) == self._attribute_name_of(b)

        # Create/delete race
        if {a.op_type, b.op_type} == {_OP_CREATE, _OP_DELETE}:
            return True

        # Association/connectivity ops on the same element always
        # interact, even on different properties, because the graph
        # topology may become inconsistent.
        if a.op_type in _ASSOC_OPS and b.op_type in _ASSOC_OPS:
            return True

        return False

    # ------------------------------------------------------------------
    # Strategy dispatch
    # ------------------------------------------------------------------

    def _apply_strategy(
        self,
        incoming: ModelOperation,
        conflicts: list[_PendingOp],
        seq: int,
    ) -> Resolution:
        op_type = incoming.op_type

        # ----------------------------------------------------------
        # Strategy 1: Last-Writer-Wins for attribute / position ops
        # ----------------------------------------------------------
        if op_type in _LWW_OPS:
            # The incoming op is *newer* (it just arrived); it wins.
            # All conflicting earlier ops have already been applied
            # to the model, so we need to re-apply the incoming value
            # on top.  The ops_to_apply list contains only *incoming*
            # because the conflicting ops have already been executed
            # and their effect is overwritten.
            elem_id = self._element_id_of(incoming)
            attr = self._attribute_name_of(incoming)
            log.debug(
                "LWW: incoming op from %s wins for element %s attr %s",
                incoming.origin_user_id,
                elem_id,
                attr,
            )
            return Resolution(
                ops_to_apply=[incoming],
                conflict_detected=True,
                description=(
                    f"Last-writer-wins on element {elem_id!r} attribute {attr!r}; "
                    f"your change was superseded by a concurrent edit."
                ),
            )

        # ----------------------------------------------------------
        # Strategy 2: Creation-before-Deletion
        # ----------------------------------------------------------
        if op_type in (_OP_CREATE, _OP_DELETE):
            elem_id = self._element_id_of(incoming)
            create_first: list[ModelOperation] = []
            delete_second: list[ModelOperation] = []
            for pending in conflicts:
                if pending.op.op_type == _OP_CREATE:
                    create_first.append(pending.op)
                elif pending.op.op_type == _OP_DELETE:
                    delete_second.append(pending.op)

            if incoming.op_type == _OP_CREATE:
                create_first.insert(0, incoming)
            else:
                delete_second.append(incoming)

            ordered = create_first + delete_second
            log.debug(
                "CBD: reordering create/delete ops for element %s", elem_id
            )
            return Resolution(
                ops_to_apply=ordered,
                conflict_detected=True,
                description=(
                    f"Creation-before-deletion applied for element {elem_id!r}; "
                    f"creation was applied first, deletion second."
                ),
            )

        # ----------------------------------------------------------
        # Strategy 3: Append-Only Association – keep both, in order
        # ----------------------------------------------------------
        if op_type in _ASSOC_OPS:
            elem_id = self._element_id_of(incoming)
            log.debug(
                "AOA: keeping both association ops for element %s", elem_id
            )
            # Conflict ops have already been applied; incoming is new.
            return Resolution(
                ops_to_apply=[incoming],
                conflict_detected=True,
                description=(
                    f"Append-only association: both association changes on "
                    f"element {elem_id!r} were preserved in server-arrival order."
                ),
            )

        # ----------------------------------------------------------
        # Fallback: accept as-is (unknown op type)
        # ----------------------------------------------------------
        log.warning(
            "No conflict strategy for op_type=%r; accepting incoming op", op_type
        )
        return Resolution(
            ops_to_apply=[incoming],
            conflict_detected=False,
            description="",
        )

    # ------------------------------------------------------------------
    # Internal log management
    # ------------------------------------------------------------------

    def _record(self, op: ModelOperation, seq: int) -> None:
        self._log.append(_PendingOp(op=op, server_sequence=seq))
        # Keep the window bounded
        if len(self._log) > self._window:
            del self._log[0]
