"""Collaboration WebSocket server.

This module runs an ``asyncio``-based WebSocket server (one per Gaphor
process) that acts as the hub for all real-time collaboration traffic.
Each connected client is represented by a ``ClientSession`` instance.

Lifecycle
---------
1. ``CollaborationServer`` is instantiated by the ``CollaborationService``
   (a Gaphor ``Service``) and started via ``start()``.
2. Clients connect; the server calls ``_on_client_connected()``.
3. Each client sends a ``SessionJoin`` message; the server assigns a
   colour, sends back the enriched ``SessionJoin``, broadcasts a
   ``UserListUpdate``, and sends a ``FullStateSync`` with the current
   operation log.
4. Clients broadcast ``CursorMove`` and ``ModelOperation`` messages.
   ``ModelOperation`` messages are run through ``ConflictResolver``
   before being applied and broadcast.
5. When a client disconnects the server broadcasts ``SessionLeave`` and
   ``UserListUpdate``.

All network I/O is done with the ``websockets`` library (pure-Python,
no GTK dependency).  The server thread runs its own asyncio loop that
is bridged to the GTK main loop via ``GLib.idle_add``.

Message routing rules
----------------------
- ``CursorMove`` : forwarded verbatim to all *other* clients on the
  same diagram.  The server does not persist cursor positions.
- ``ModelOperation`` : run through ``ConflictResolver``; the resolved
  op(s) are broadcast to all *other* clients; an ``OperationAck`` (or
  ``ConflictNotification``) is sent back to the originator.
- ``SessionJoin`` / ``SessionLeave`` / ``UserListUpdate`` : managed
  entirely by the server; clients never construct these themselves.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from gaphor.collaboration.color_registry import ColorRegistry
from gaphor.collaboration.conflict_resolver import ConflictResolver
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

log = logging.getLogger(__name__)

try:
    import websockets
    import websockets.server
    _WEBSOCKETS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _WEBSOCKETS_AVAILABLE = False
    log.warning(
        "The 'websockets' package is not installed. "
        "Real-time collaboration is disabled. "
        "Install it with: pip install websockets"
    )


@dataclass
class _ClientSession:
    """Server-side state for a single connected WebSocket client."""

    user_id: str
    display_name: str
    websocket: Any   # websockets.WebSocketServerProtocol
    diagram_id: str = ""
    color_css: str = ""
    # Number of operations this client has acknowledged receiving
    acked_seq: int = 0


class CollaborationServer:
    """Central WebSocket hub for all collaboration messages.

    One instance is shared across all open diagrams within a single
    Gaphor process.  Diagram isolation is enforced at the
    ``CursorMove`` / ``ModelOperation`` routing level (messages are
    only forwarded to peers on the same diagram).
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 4765) -> None:
        self.host = host
        self.port = port

        self._color_registry = ColorRegistry()
        self._conflict_resolver = ConflictResolver()
        self._operation_log: list[dict[str, Any]] = []

        # user_id → _ClientSession
        self._clients: dict[str, _ClientSession] = {}

        self._server: Any = None        # websockets server handle
        self._loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the WebSocket server (must be awaited inside an asyncio loop)."""
        if not _WEBSOCKETS_AVAILABLE:
            log.error("Cannot start collaboration server: 'websockets' not installed.")
            return

        self._loop = asyncio.get_running_loop()
        self._server = await websockets.server.serve(
            self._on_client_connected,
            self.host,
            self.port,
        )
        log.info(
            "Collaboration server listening on ws://%s:%d", self.host, self.port
        )

    async def stop(self) -> None:
        """Gracefully stop the WebSocket server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            log.info("Collaboration server stopped.")

    # ------------------------------------------------------------------
    # Connection handler
    # ------------------------------------------------------------------

    async def _on_client_connected(self, websocket: Any) -> None:
        """Entry point called by websockets for every new TCP connection."""
        client: _ClientSession | None = None
        try:
            async for raw_message in websocket:
                try:
                    message = decode(raw_message)
                except (ValueError, json.JSONDecodeError) as exc:
                    log.warning("Dropping malformed message: %s", exc)
                    continue

                if isinstance(message, SessionJoin):
                    client = await self._handle_join(message, websocket)
                elif client is None:
                    # Must join before sending anything else
                    log.warning(
                        "Received %s before SessionJoin; ignoring.",
                        type(message).__name__,
                    )
                elif isinstance(message, CursorMove):
                    await self._handle_cursor_move(message, client)
                elif isinstance(message, ModelOperation):
                    await self._handle_model_operation(message, client)
                else:
                    log.debug("Unhandled message type: %s", type(message).__name__)

        except Exception:  # pylint: disable=broad-except
            log.exception("Error in client message loop for user=%s", client and client.user_id)
        finally:
            if client:
                await self._handle_disconnect(client)

    # ------------------------------------------------------------------
    # Message handlers
    # ------------------------------------------------------------------

    async def _handle_join(
        self, message: SessionJoin, websocket: Any
    ) -> _ClientSession:
        user_id = message.user_id
        display_name = message.display_name or user_id
        diagram_id = message.diagram_id

        # Assign a colour
        color = self._color_registry.assign(user_id)

        client = _ClientSession(
            user_id=user_id,
            display_name=display_name,
            websocket=websocket,
            diagram_id=diagram_id,
            color_css=color.css,
        )
        self._clients[user_id] = client

        # Echo the enriched SessionJoin back to the joiner
        ack = SessionJoin(
            user_id=user_id,
            display_name=display_name,
            diagram_id=diagram_id,
            user_color=color.css,
        )
        await self._send(client, ack)

        # Send the full operation log so the client can catch up
        sync = FullStateSync(
            operations=self._operation_log,
            server_sequence=self._conflict_resolver.server_sequence,
        )
        await self._send(client, sync)

        # Broadcast updated user list to everyone (including the new joiner)
        await self._broadcast_user_list()
        log.info("User %r (%s) joined diagram %r", user_id, display_name, diagram_id)
        return client

    async def _handle_disconnect(self, client: _ClientSession) -> None:
        user_id = client.user_id
        self._clients.pop(user_id, None)
        self._color_registry.release(user_id)

        leave = SessionLeave(
            user_id=user_id,
            display_name=client.display_name,
        )
        await self._broadcast(leave, exclude=user_id)
        await self._broadcast_user_list()
        log.info("User %r disconnected.", user_id)

    async def _handle_cursor_move(
        self, message: CursorMove, client: _ClientSession
    ) -> None:
        """Forward cursor position to all other clients on the same diagram."""
        message.user_id = client.user_id   # authoritative: set server-side
        await self._broadcast_to_diagram(
            message,
            diagram_id=client.diagram_id,
            exclude=client.user_id,
        )

    async def _handle_model_operation(
        self, message: ModelOperation, client: _ClientSession
    ) -> None:
        """Run the operation through the conflict resolver and broadcast."""
        message.origin_user_id = client.user_id  # authoritative

        resolution = self._conflict_resolver.resolve(message)
        server_seq = self._conflict_resolver.server_sequence

        if resolution.conflict_detected:
            notify = ConflictNotification(
                client_sequence=message.client_sequence,
                resolution=resolution.description,
                accepted=bool(resolution.ops_to_apply),
            )
            await self._send(client, notify)
            log.info(
                "Conflict resolved for user %r seq %d: %s",
                client.user_id,
                message.client_sequence,
                resolution.description,
            )

        # Apply / broadcast all ops decided by the resolver
        for op in resolution.ops_to_apply:
            # Persist to the session-wide log so late-joining clients
            # can replay the full history
            op_dict = json.loads(encode(op))
            self._operation_log.append(op_dict)

            # Broadcast to all other clients on the same diagram
            await self._broadcast_to_diagram(
                op,
                diagram_id=client.diagram_id,
                exclude=client.user_id,
            )

        # Acknowledge to the originating client
        ack = OperationAck(
            client_sequence=message.client_sequence,
            server_sequence=server_seq,
        )
        await self._send(client, ack)

    # ------------------------------------------------------------------
    # Broadcast helpers
    # ------------------------------------------------------------------

    async def _broadcast(self, message: object, exclude: str | None = None) -> None:
        """Send *message* to all connected clients except *exclude*."""
        raw = encode(message)
        targets = [
            c for uid, c in self._clients.items() if uid != exclude
        ]
        if targets:
            await asyncio.gather(
                *(self._send_raw(c, raw) for c in targets),
                return_exceptions=True,
            )

    async def _broadcast_to_diagram(
        self, message: object, diagram_id: str, exclude: str | None = None
    ) -> None:
        """Send *message* only to clients editing the given *diagram_id*."""
        raw = encode(message)
        targets = [
            c
            for uid, c in self._clients.items()
            if uid != exclude and c.diagram_id == diagram_id
        ]
        if targets:
            await asyncio.gather(
                *(self._send_raw(c, raw) for c in targets),
                return_exceptions=True,
            )

    async def _broadcast_user_list(self) -> None:
        users = [
            {
                "user_id": c.user_id,
                "display_name": c.display_name,
                "color": c.color_css,
            }
            for c in self._clients.values()
        ]
        update = UserListUpdate(users=users)
        await self._broadcast(update)

    async def _send(self, client: _ClientSession, message: object) -> None:
        await self._send_raw(client, encode(message))

    @staticmethod
    async def _send_raw(client: _ClientSession, raw: str) -> None:
        try:
            await client.websocket.send(raw)
        except Exception:  # pragma: no cover – transport errors
            log.debug(
                "Failed to send to user %r; they may have disconnected.", client.user_id
            )
