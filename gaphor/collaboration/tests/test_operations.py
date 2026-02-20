"""Tests for collaboration operations."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import time

import pytest

from collaboration.operations import (
    ConflictResolver,
    DefaultOperationTransformer,
    Operation,
    OperationType,
    VectorClock,
)


class TestOperation:
    def test_create_operation(self):
        op = Operation(
            operation_id="op-1",
            operation_type=OperationType.CREATE,
            element_id="elem-1",
            diagram_id="diagram-1",
            user_id="user-1",
            timestamp=1000.0,
            data={"key": "value"},
        )

        assert op.operation_id == "op-1"
        assert op.operation_type == OperationType.CREATE
        assert op.data["key"] == "value"

    def test_to_dict(self):
        op = Operation(
            operation_id="op-1",
            operation_type=OperationType.UPDATE_ATTRIBUTE,
            element_id="elem-1",
            diagram_id="diagram-1",
            user_id="user-1",
            timestamp=1000.0,
            data={"attribute_name": "name"},
        )

        data = op.to_dict()

        assert data["operation_id"] == "op-1"
        assert data["operation_type"] == "update_attribute"

    def test_from_dict(self):
        data = {
            "operation_id": "op-1",
            "operation_type": "delete",
            "element_id": "elem-1",
            "diagram_id": "diagram-1",
            "user_id": "user-1",
            "timestamp": 1000.0,
            "data": {},
            "vector_clock": {"user-1": 1},
        }

        op = Operation.from_dict(data)

        assert op.operation_type == OperationType.DELETE
        assert op.vector_clock == {"user-1": 1}


class TestVectorClock:
    def test_increment(self):
        clock = VectorClock("user-1")
        result = clock.increment()

        assert result["user-1"] == 1

        result = clock.increment()
        assert result["user-1"] == 2

    def test_update(self):
        clock = VectorClock("user-1")
        clock.increment()

        clock.update({"user-1": 5, "user-2": 3})

        assert clock.clock["user-1"] == 5
        assert clock.clock["user-2"] == 3

    def test_is_concurrent(self):
        clock1 = VectorClock("user-1")
        clock1.increment()
        clock1.increment()

        other_clock = {"user-1": 1, "user-2": 2}

        assert clock1.is_concurrent(other_clock)

    def test_happens_before(self):
        clock = VectorClock("user-1")
        clock.increment()

        other_clock = {"user-1": 2, "user-2": 1}

        assert clock.happens_before(other_clock)


class TestDefaultOperationTransformer:
    def test_transform_different_elements(self):
        transformer = DefaultOperationTransformer()

        op1 = Operation(
            operation_id="op-1",
            operation_type=OperationType.UPDATE_POSITION,
            element_id="elem-1",
            diagram_id="diagram-1",
            user_id="user-1",
            timestamp=1000.0,
        )
        op2 = Operation(
            operation_id="op-2",
            operation_type=OperationType.UPDATE_POSITION,
            element_id="elem-2",
            diagram_id="diagram-1",
            user_id="user-2",
            timestamp=1001.0,
        )

        t1, t2 = transformer.transform(op1, op2)

        assert t1 == op1
        assert t2 == op2

    def test_transform_delete_wins(self):
        transformer = DefaultOperationTransformer()

        delete_op = Operation(
            operation_id="op-1",
            operation_type=OperationType.DELETE,
            element_id="elem-1",
            diagram_id="diagram-1",
            user_id="user-1",
            timestamp=1000.0,
        )
        update_op = Operation(
            operation_id="op-2",
            operation_type=OperationType.UPDATE_ATTRIBUTE,
            element_id="elem-1",
            diagram_id="diagram-1",
            user_id="user-2",
            timestamp=1001.0,
        )

        t1, t2 = transformer.transform(delete_op, update_op)

        assert t1 == delete_op
        assert t2.data.get("_noop") is True

    def test_transform_position_last_writer_wins(self):
        transformer = DefaultOperationTransformer()

        op1 = Operation(
            operation_id="op-1",
            operation_type=OperationType.UPDATE_POSITION,
            element_id="elem-1",
            diagram_id="diagram-1",
            user_id="user-1",
            timestamp=1000.0,
            data={"x": 100, "y": 100},
        )
        op2 = Operation(
            operation_id="op-2",
            operation_type=OperationType.UPDATE_POSITION,
            element_id="elem-1",
            diagram_id="diagram-1",
            user_id="user-2",
            timestamp=1001.0,
            data={"x": 200, "y": 200},
        )

        t1, t2 = transformer.transform(op1, op2)

        assert t1.data.get("_noop") is True
        assert t2.data.get("x") == 200


class TestConflictResolver:
    def test_no_conflicts(self):
        resolver = ConflictResolver()

        local_ops = [
            Operation(
                operation_id="op-1",
                operation_type=OperationType.UPDATE_ATTRIBUTE,
                element_id="elem-1",
                diagram_id="diagram-1",
                user_id="user-1",
                timestamp=1000.0,
            )
        ]
        remote_ops = [
            Operation(
                operation_id="op-2",
                operation_type=OperationType.UPDATE_ATTRIBUTE,
                element_id="elem-2",
                diagram_id="diagram-1",
                user_id="user-2",
                timestamp=1001.0,
            )
        ]

        result = resolver.resolve(local_ops, remote_ops)

        assert len(result) == 1
        assert result[0].element_id == "elem-2"

    def test_empty_remote_ops(self):
        resolver = ConflictResolver()

        result = resolver.resolve([Operation(
            operation_id="op-1",
            operation_type=OperationType.CREATE,
            element_id="elem-1",
            diagram_id="diagram-1",
            user_id="user-1",
            timestamp=1000.0,
        )], [])

        assert len(result) == 0

    def test_conflict_resolution(self):
        resolver = ConflictResolver()

        local_ops = [
            Operation(
                operation_id="op-1",
                operation_type=OperationType.UPDATE_POSITION,
                element_id="elem-1",
                diagram_id="diagram-1",
                user_id="user-1",
                timestamp=1002.0,
            )
        ]
        remote_ops = [
            Operation(
                operation_id="op-2",
                operation_type=OperationType.UPDATE_POSITION,
                element_id="elem-1",
                diagram_id="diagram-1",
                user_id="user-2",
                timestamp=1001.0,
            )
        ]

        result = resolver.resolve(local_ops, remote_ops)

        # Remote op should be transformed to noop since local is newer
        assert len(result) == 0
