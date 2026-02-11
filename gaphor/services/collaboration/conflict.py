"""Conflict resolution strategies for real-time collaboration."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any

log = logging.getLogger(__name__)


class ConflictStrategy(str, Enum):
    LAST_WRITE_WINS = "last_write_wins"
    FIRST_WRITE_WINS = "first_write_wins"
    SERVER_WINS = "server_wins"
    MERGE = "merge"


@dataclass
class ChangeRecord:
    element_id: str
    property_name: str
    value: Any
    version: int
    timestamp: float
    user_id: str


@dataclass
class ConflictResult:
    resolved: bool
    winning_change: ChangeRecord | None
    strategy_used: ConflictStrategy
    merged_value: Any = None


class ConflictResolver(ABC):
    @abstractmethod
    def resolve(
        self, local: ChangeRecord, remote: ChangeRecord
    ) -> ConflictResult:
        pass


class LastWriteWinsResolver(ConflictResolver):
    def resolve(self, local: ChangeRecord, remote: ChangeRecord) -> ConflictResult:
        if remote.timestamp >= local.timestamp:
            return ConflictResult(
                resolved=True,
                winning_change=remote,
                strategy_used=ConflictStrategy.LAST_WRITE_WINS,
            )
        return ConflictResult(
            resolved=True,
            winning_change=local,
            strategy_used=ConflictStrategy.LAST_WRITE_WINS,
        )


class FirstWriteWinsResolver(ConflictResolver):
    def resolve(self, local: ChangeRecord, remote: ChangeRecord) -> ConflictResult:
        if local.timestamp <= remote.timestamp:
            return ConflictResult(
                resolved=True,
                winning_change=local,
                strategy_used=ConflictStrategy.FIRST_WRITE_WINS,
            )
        return ConflictResult(
            resolved=True,
            winning_change=remote,
            strategy_used=ConflictStrategy.FIRST_WRITE_WINS,
        )


class ServerWinsResolver(ConflictResolver):
    def resolve(self, local: ChangeRecord, remote: ChangeRecord) -> ConflictResult:
        return ConflictResult(
            resolved=True,
            winning_change=remote,
            strategy_used=ConflictStrategy.SERVER_WINS,
        )


class VersionVector:
    """Simple version vector for tracking element versions."""

    def __init__(self):
        self._versions: dict[str, int] = {}

    def get(self, element_id: str) -> int:
        return self._versions.get(element_id, 0)

    def increment(self, element_id: str) -> int:
        version = self._versions.get(element_id, 0) + 1
        self._versions[element_id] = version
        return version

    def set(self, element_id: str, version: int) -> None:
        current = self._versions.get(element_id, 0)
        if version > current:
            self._versions[element_id] = version

    def has_conflict(self, element_id: str, remote_version: int) -> bool:
        local_version = self.get(element_id)
        return remote_version <= local_version and local_version > 0


class OperationalTransform:
    """Basic operational transformation for concurrent edits."""

    @staticmethod
    def transform_position(
        local_pos: tuple[float, float],
        remote_op: dict,
    ) -> tuple[float, float]:
        if remote_op.get("type") == "move":
            return local_pos
        return local_pos

    @staticmethod
    def transform_text(local_text: str, remote_op: dict) -> str:
        if remote_op.get("type") != "text_edit":
            return local_text

        pos = remote_op.get("position", 0)
        insert = remote_op.get("insert", "")
        delete = remote_op.get("delete", 0)

        result = local_text[:pos] + insert + local_text[pos + delete:]
        return result


class ConflictManager:
    """Manages conflict detection and resolution."""

    def __init__(self, strategy: ConflictStrategy = ConflictStrategy.LAST_WRITE_WINS):
        self._strategy = strategy
        self._versions = VersionVector()
        self._pending_changes: dict[str, ChangeRecord] = {}
        self._resolver = self._get_resolver(strategy)

    def _get_resolver(self, strategy: ConflictStrategy) -> ConflictResolver:
        resolvers = {
            ConflictStrategy.LAST_WRITE_WINS: LastWriteWinsResolver(),
            ConflictStrategy.FIRST_WRITE_WINS: FirstWriteWinsResolver(),
            ConflictStrategy.SERVER_WINS: ServerWinsResolver(),
        }
        return resolvers.get(strategy, LastWriteWinsResolver())

    def set_strategy(self, strategy: ConflictStrategy) -> None:
        self._strategy = strategy
        self._resolver = self._get_resolver(strategy)

    def record_local_change(self, change: ChangeRecord) -> int:
        version = self._versions.increment(change.element_id)
        change.version = version
        self._pending_changes[change.element_id] = change
        return version

    def apply_remote_change(self, change: ChangeRecord) -> ConflictResult | None:
        element_id = change.element_id

        if self._versions.has_conflict(element_id, change.version):
            local_change = self._pending_changes.get(element_id)
            if local_change:
                result = self._resolver.resolve(local_change, change)
                if result.winning_change == change:
                    self._versions.set(element_id, change.version)
                    self._pending_changes.pop(element_id, None)
                return result

        self._versions.set(element_id, change.version)
        self._pending_changes.pop(element_id, None)
        return None

    def acknowledge_change(self, element_id: str, version: int) -> None:
        self._versions.set(element_id, version)
        if element_id in self._pending_changes:
            if self._pending_changes[element_id].version <= version:
                del self._pending_changes[element_id]

    def get_version(self, element_id: str) -> int:
        return self._versions.get(element_id)
