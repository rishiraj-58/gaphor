"""Operation types and transformation for collaborative editing.

This module implements Operational Transformation (OT) for conflict resolution
in collaborative editing scenarios.
"""

from __future__ import annotations

import copy
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

log = logging.getLogger(__name__)


class OperationType(Enum):
    """Types of operations that can be performed on diagram elements."""

    CREATE = "create"
    DELETE = "delete"
    UPDATE_ATTRIBUTE = "update_attribute"
    UPDATE_POSITION = "update_position"
    UPDATE_SIZE = "update_size"
    ADD_CONNECTION = "add_connection"
    REMOVE_CONNECTION = "remove_connection"
    REORDER = "reorder"


@dataclass
class Operation:
    """Represents a single operation in the collaboration system."""

    operation_id: str
    operation_type: OperationType
    element_id: str
    diagram_id: str
    user_id: str
    timestamp: float
    data: dict[str, Any] = field(default_factory=dict)
    vector_clock: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize operation to dictionary."""
        return {
            "operation_id": self.operation_id,
            "operation_type": self.operation_type.value,
            "element_id": self.element_id,
            "diagram_id": self.diagram_id,
            "user_id": self.user_id,
            "timestamp": self.timestamp,
            "data": self.data,
            "vector_clock": self.vector_clock,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Operation:
        """Deserialize operation from dictionary."""
        return cls(
            operation_id=data["operation_id"],
            operation_type=OperationType(data["operation_type"]),
            element_id=data["element_id"],
            diagram_id=data["diagram_id"],
            user_id=data["user_id"],
            timestamp=data["timestamp"],
            data=data.get("data", {}),
            vector_clock=data.get("vector_clock", {}),
        )


class OperationTransformer(ABC):
    """Abstract base class for operation transformers."""

    @abstractmethod
    def transform(self, op1: Operation, op2: Operation) -> tuple[Operation, Operation]:
        """Transform two concurrent operations for OT."""


class DefaultOperationTransformer(OperationTransformer):
    """Default operation transformer implementing basic OT logic."""

    def transform(self, op1: Operation, op2: Operation) -> tuple[Operation, Operation]:
        """Transform two concurrent operations.

        Returns transformed versions of both operations that can be applied
        in either order to achieve the same final state.
        """
        # If operations are on different elements, no transformation needed
        if op1.element_id != op2.element_id:
            return op1, op2

        # Handle same-element operations
        if op1.operation_type == OperationType.DELETE:
            return self._transform_with_delete(op1, op2)

        if op2.operation_type == OperationType.DELETE:
            transformed_op2, transformed_op1 = self._transform_with_delete(op2, op1)
            return transformed_op1, transformed_op2

        if op1.operation_type == OperationType.UPDATE_POSITION:
            return self._transform_position_updates(op1, op2)

        if op1.operation_type == OperationType.UPDATE_ATTRIBUTE:
            return self._transform_attribute_updates(op1, op2)

        return op1, op2

    def _transform_with_delete(
        self, delete_op: Operation, other_op: Operation
    ) -> tuple[Operation, Operation]:
        """Transform an operation against a delete operation."""
        # Delete wins - the other operation becomes a no-op
        noop = copy.deepcopy(other_op)
        noop.data["_noop"] = True
        return delete_op, noop

    def _transform_position_updates(
        self, op1: Operation, op2: Operation
    ) -> tuple[Operation, Operation]:
        """Transform two position update operations."""
        if op2.operation_type != OperationType.UPDATE_POSITION:
            return op1, op2

        # Last-writer-wins based on timestamp
        if op1.timestamp > op2.timestamp:
            noop = copy.deepcopy(op2)
            noop.data["_noop"] = True
            return op1, noop
        else:
            noop = copy.deepcopy(op1)
            noop.data["_noop"] = True
            return noop, op2

    def _transform_attribute_updates(
        self, op1: Operation, op2: Operation
    ) -> tuple[Operation, Operation]:
        """Transform two attribute update operations."""
        if op2.operation_type != OperationType.UPDATE_ATTRIBUTE:
            return op1, op2

        # Check if same attribute
        attr1 = op1.data.get("attribute_name")
        attr2 = op2.data.get("attribute_name")

        if attr1 != attr2:
            return op1, op2

        # Same attribute - last-writer-wins
        if op1.timestamp > op2.timestamp:
            noop = copy.deepcopy(op2)
            noop.data["_noop"] = True
            return op1, noop
        else:
            noop = copy.deepcopy(op1)
            noop.data["_noop"] = True
            return noop, op2


class ConflictResolver:
    """Resolves conflicts between concurrent operations."""

    def __init__(self, transformer: OperationTransformer | None = None):
        self.transformer = transformer or DefaultOperationTransformer()

    def resolve(
        self,
        local_ops: list[Operation],
        remote_ops: list[Operation],
    ) -> list[Operation]:
        """Resolve conflicts between local and remote operations.

        Returns a list of operations that should be applied locally.
        """
        if not remote_ops:
            return []

        if not local_ops:
            return remote_ops

        transformed_remote = []
        for remote_op in remote_ops:
            transformed = remote_op
            for local_op in local_ops:
                _, transformed = self.transformer.transform(local_op, transformed)
            transformed_remote.append(transformed)

        return [op for op in transformed_remote if not op.data.get("_noop")]


class VectorClock:
    """Vector clock for tracking causality in distributed operations."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self._clock: dict[str, int] = {user_id: 0}

    def increment(self) -> dict[str, int]:
        """Increment the local clock and return current state."""
        self._clock[self.user_id] = self._clock.get(self.user_id, 0) + 1
        return self._clock.copy()

    def update(self, other_clock: dict[str, int]) -> None:
        """Update this clock with values from another clock."""
        for user_id, timestamp in other_clock.items():
            self._clock[user_id] = max(self._clock.get(user_id, 0), timestamp)

    def is_concurrent(self, other_clock: dict[str, int]) -> bool:
        """Check if this clock is concurrent with another clock."""
        self_greater = False
        other_greater = False

        all_users = set(self._clock.keys()) | set(other_clock.keys())
        for user_id in all_users:
            self_val = self._clock.get(user_id, 0)
            other_val = other_clock.get(user_id, 0)
            if self_val > other_val:
                self_greater = True
            if other_val > self_val:
                other_greater = True

        return self_greater and other_greater

    def happens_before(self, other_clock: dict[str, int]) -> bool:
        """Check if this clock happens before another clock."""
        for user_id, timestamp in self._clock.items():
            if timestamp > other_clock.get(user_id, 0):
                return False
        return any(
            self._clock.get(user_id, 0) < timestamp
            for user_id, timestamp in other_clock.items()
        )

    @property
    def clock(self) -> dict[str, int]:
        """Get current clock state."""
        return self._clock.copy()
