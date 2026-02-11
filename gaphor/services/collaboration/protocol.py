"""WebSocket protocol for collaboration."""

import json
import logging
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

log = logging.getLogger(__name__)


class MessageType(str, Enum):
    JOIN = "join"
    LEAVE = "leave"
    CURSOR = "cursor"
    CHANGE = "change"
    SYNC = "sync"
    ACK = "ack"
    CONFLICT = "conflict"
    HEARTBEAT = "heartbeat"


@dataclass
class Message:
    type: MessageType
    user_id: str
    payload: dict

    def to_json(self) -> str:
        return json.dumps({
            "type": self.type.value,
            "user_id": self.user_id,
            "payload": self.payload,
        })

    @classmethod
    def from_json(cls, data: str) -> "Message":
        obj = json.loads(data)
        return cls(
            type=MessageType(obj["type"]),
            user_id=obj["user_id"],
            payload=obj.get("payload", {}),
        )


def create_join_message(user_id: str, username: str, session_id: str) -> Message:
    return Message(
        type=MessageType.JOIN,
        user_id=user_id,
        payload={"username": username, "session_id": session_id},
    )


def create_leave_message(user_id: str) -> Message:
    return Message(
        type=MessageType.LEAVE,
        user_id=user_id,
        payload={},
    )


def create_cursor_message(user_id: str, diagram_id: str, x: float, y: float) -> Message:
    return Message(
        type=MessageType.CURSOR,
        user_id=user_id,
        payload={"diagram_id": diagram_id, "x": x, "y": y},
    )


def create_change_message(
    user_id: str,
    change_type: str,
    element_id: str,
    data: dict,
    version: int,
) -> Message:
    return Message(
        type=MessageType.CHANGE,
        user_id=user_id,
        payload={
            "change_type": change_type,
            "element_id": element_id,
            "data": data,
            "version": version,
        },
    )


def create_sync_message(user_id: str, elements: list[dict]) -> Message:
    return Message(
        type=MessageType.SYNC,
        user_id=user_id,
        payload={"elements": elements},
    )


def create_ack_message(user_id: str, element_id: str, version: int) -> Message:
    return Message(
        type=MessageType.ACK,
        user_id=user_id,
        payload={"element_id": element_id, "version": version},
    )


def create_heartbeat_message(user_id: str) -> Message:
    return Message(
        type=MessageType.HEARTBEAT,
        user_id=user_id,
        payload={},
    )
