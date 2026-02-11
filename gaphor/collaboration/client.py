"""Collaboration WebSocket client.

The ``CollaborationClient`` runs entirely inside the Gaphor process that
opens or joins a collaborative session from the *user* side.  It lives
on a background asyncio event loop so that it never blocks the GTK main
thread.  Communication between the asyncio side and the GTK side is done
through thread-safe queues and ``GLib.idle_add``.

What the client does
--------------------
* Connects to the ``CollaborationServer`` and sends ``SessionJoin``.
* Receives the ``FullStateSync`` and replays all historical ops through
  ``gaphor.storage.recovery.replay_events`` wrapped in a Transaction so
  the UndoManager sees the correct undo stack.
* Listens for ``ModelOperation`` messages broadcast by the server and
  immediately replays them on the local model (inside a Transaction).
* Forwards local model changes (captured by subscribing to the same
  events as ``gaphor.storage.recovery.Recorder``) to the server as
  ``ModelOperation`` messages.
* Captures pointer-motion events from the ``GtkView`` and sends
  ``CursorMove`` messages at a throttled rate (at most every
  ``CURSOR_THROTTLE_MS`` milliseconds) to avoid flooding the server.
* Receives ``CursorMove`` messages for remote peers and notifies the
  ``CursorOverlayManager`` so it can repaint remote cursor overlays.
* Maintains a per-peer vector clock to give the ``ConflictResolver``
  the causal ordering information it needs.

Integration with the Gaphor event system
-----------------------------------------
Local model changes are detected by subscribing to the standard Gaphor
modeling events.  The subscription list mirrors the one in
``gaphor.storage.recovery.Recorder`` so that every type of atomic change
is captured.  When a change arrives *from the server* the client sets a
re-entrancy guard (``_applying_remote``) to suppress re-transmission of
the same change back to the server.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from gaphor.collaboration.messages import (
    ConflictNotification,
    CursorMove,
    FullStateSync,
    ModelOperation,
    OperationAck,
    SessionJoin,
    UserListUpdate,
    decode,
    encode,
)

log = logging.getLogger(__name__)

try:
    import websockets
    import websockets.client
    _WEBSOCKETS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _WEBSOCKETS_AVAILABLE = False

# Minimum interval between consecutive CursorMove messages (milliseconds).
CURSOR_THROTTLE_MS: int = 50


@dataclass
class RemotePeer:
    """Live information about one remote collaborator."""

    user_id: str
    display_name: str
    color_css: str        # e.g. "rgb(56, 135, 235)"
    diagram_id: str = ""
    cursor_x: float = 0.0
    cursor_y: float = 0.0
    last_seen: float = field(default_factory=time.monotonic)


class CollaborationClient:
    """WebSocket client for real-time collaboration.

    Designed to be used by ``CollaborationService``.  All public methods
    are safe to call from the GTK thread.  Asyncio work is dispatched to
    an internal background thread.

    Parameters
    ----------
    user_id:
        Stable identifier for the local user (e.g. a UUID persisted in
        settings so it survives restarts).
    display_name:
        Human-readable name shown as a tooltip on remote cursor overlays.
    diagram_id:
        The Gaphor diagram element id that this client is currently
        editing.  Must be supplied so the server can route diagram-scoped
        messages.
    url:
        WebSocket URL of the ``CollaborationServer``, e.g.
        ``"ws://127.0.0.1:4765"``.
    on_remote_op:
        Called (in the GTK thread via GLib.idle_add) with a
        ``ModelOperation`` whenever a remote change must be applied.
    on_cursor_update:
        Called (in the GTK thread) with a ``RemotePeer`` whose cursor
        position has changed.
    on_peer_left:
        Called (in the GTK thread) with the departing ``user_id``.
    on_user_list:
        Called (in the GTK thread) with the updated ``list[RemotePeer]``.
    on_conflict:
        Called (in the GTK thread) with a ``ConflictNotification``.
    """

    def __init__(
        self,
        user_id: str,
        display_name: str,
        diagram_id: str,
        url: str,
        on_remote_op,
        on_cursor_update,
        on_peer_left,
        on_user_list,
        on_conflict,
    ) -> None:
        self._user_id = user_id
        self._display_name = display_name
        self._diagram_id = diagram_id
        self._url = url

        # Callbacks into the GTK layer
        self._on_remote_op = on_remote_op
        self._on_cursor_update = on_cursor_update
        self._on_peer_left = on_peer_left
        self._on_user_list = on_user_list
        self._on_conflict = on_conflict

        # Set to True while the local model is being mutated as a result
        # of a remote operation so we do not re-broadcast those changes.
        self._applying_remote: bool = False

        # Monotonically increasing counter for outgoing ops
        self._client_sequence: int = 0
        # vector_clock[user_id] = logical time.  Updated when we send
        # and when we receive acks.
        self._vector_clock: dict[str, int] = {user_id: 0}

        # Queue of outgoing messages (from GTK thread → asyncio)
        self._send_queue: queue.Queue[str] = queue.Queue()

        # Rate-limiting for cursor moves
        self._last_cursor_send: float = 0.0

        # Known remote peers
        self._peers: dict[str, RemotePeer] = {}

        # Assigned colour from server (filled on SessionJoin echo)
        self.local_color_css: str = ""

        # Background thread running the asyncio event loop
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._connected: bool = False

    # ------------------------------------------------------------------
    # Public API (GTK thread)
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Start the background asyncio loop and connect to the server."""
        if not _WEBSOCKETS_AVAILABLE:
            log.error(
                "Cannot connect to collaboration server: 'websockets' not installed."
            )
            return
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="CollaborationClient"
        )
        self._thread.start()

    def disconnect(self) -> None:
        """Disconnect from the server and stop the background thread."""
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=3.0)
        self._connected = False

    def send_cursor_move(self, x: float, y: float) -> None:
        """Enqueue a throttled cursor-position update.

        Can be called from the GTK thread on every pointer-motion event.
        """
        now = time.monotonic()
        if (now - self._last_cursor_send) * 1000 < CURSOR_THROTTLE_MS:
            return
        self._last_cursor_send = now
        msg = CursorMove(
            user_id=self._user_id,
            diagram_id=self._diagram_id,
            x=x,
            y=y,
        )
        self._enqueue(encode(msg))

    def send_model_operation(self, op_type: str, payload: list[Any]) -> None:
        """Send a local model change to the server.

        Called by ``CollaborationService._on_recorder_event()`` for every
        change captured by the local Recorder, *unless* the change
        originated from a remote operation (guarded by
        ``_applying_remote``).
        """
        if self._applying_remote:
            return   # don't echo remote ops back to the server

        self._client_sequence += 1
        self._vector_clock[self._user_id] = self._client_sequence
        msg = ModelOperation(
            op_type=op_type,
            payload=payload,
            origin_user_id=self._user_id,
            client_sequence=self._client_sequence,
            vector_clock=dict(self._vector_clock),
            diagram_id=self._diagram_id,
        )
        self._enqueue(encode(msg))

    @property
    def is_applying_remote(self) -> bool:
        """True while the client is replaying a remote operation locally."""
        return self._applying_remote

    @property
    def peers(self) -> dict[str, RemotePeer]:
        return dict(self._peers)

    # ------------------------------------------------------------------
    # Background asyncio thread
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        """Entry point for the background thread.  Runs its own event loop."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self._connect_and_listen())
        except Exception:
            log.exception("Collaboration client loop terminated with error.")
        finally:
            loop.close()

    async def _connect_and_listen(self) -> None:
        """Establish the WebSocket connection and handle all messages."""
        async with websockets.client.connect(self._url) as ws:
            self._connected = True
            log.info("Connected to collaboration server at %s", self._url)

            # Send SessionJoin
            join = SessionJoin(
                user_id=self._user_id,
                display_name=self._display_name,
                diagram_id=self._diagram_id,
            )
            await ws.send(encode(join))

            # Run send-queue flusher and receiver concurrently
            await asyncio.gather(
                self._sender(ws),
                self._receiver(ws),
            )

    async def _sender(self, ws) -> None:
        """Drain the outgoing queue and write to the WebSocket."""
        loop = asyncio.get_running_loop()
        while True:
            # Poll the thread-safe queue without blocking the loop
            try:
                raw = self._send_queue.get_nowait()
                await ws.send(raw)
            except queue.Empty:
                await asyncio.sleep(0.005)
            except Exception:
                log.exception("Error in collaboration sender.")
                break

    async def _receiver(self, ws) -> None:
        """Read incoming messages from the WebSocket and dispatch them."""
        async for raw in ws:
            try:
                message = decode(raw)
            except Exception as exc:
                log.warning("Could not decode incoming message: %s", exc)
                continue

            self._dispatch(message)

    # ------------------------------------------------------------------
    # Message dispatch (still on asyncio thread; callbacks via idle_add)
    # ------------------------------------------------------------------

    def _dispatch(self, message: object) -> None:
        """Route a decoded message to the appropriate handler.

        All callbacks that touch GTK state are marshalled through
        ``GLib.idle_add`` so they execute on the GTK main thread.
        """
        if isinstance(message, SessionJoin):
            # Server echoing back with our assigned colour
            self.local_color_css = message.user_color
            log.debug("Assigned colour: %s", self.local_color_css)

        elif isinstance(message, FullStateSync):
            self._schedule_gtk(self._on_full_state_sync, message)

        elif isinstance(message, ModelOperation):
            self._schedule_gtk(self._on_remote_model_op, message)

        elif isinstance(message, CursorMove):
            self._schedule_gtk(self._on_remote_cursor, message)

        elif isinstance(message, UserListUpdate):
            self._schedule_gtk(self._on_user_list_update, message)

        elif isinstance(message, OperationAck):
            # Advance our acknowledged server sequence counter
            log.debug(
                "Op ack: client_seq=%d server_seq=%d",
                message.client_sequence,
                message.server_sequence,
            )
            self._vector_clock[self._user_id] = message.server_sequence

        elif isinstance(message, ConflictNotification):
            self._schedule_gtk(self._on_conflict, message)

    # ------------------------------------------------------------------
    # GTK-thread callbacks (must only touch GTK/Gaphor state here)
    # ------------------------------------------------------------------

    def _on_full_state_sync(self, message: FullStateSync) -> None:
        """Replay historical ops from the server onto the local model."""
        log.info("Replaying %d historical ops.", len(message.operations))
        self._applying_remote = True
        try:
            for op_dict in message.operations:
                self._on_remote_op(op_dict)
        finally:
            self._applying_remote = False

    def _on_remote_model_op(self, message: ModelOperation) -> None:
        """Apply a single remote operation to the local model."""
        self._applying_remote = True
        try:
            # Update our view of the remote peer's clock
            peer_id = message.origin_user_id
            if peer_id:
                self._vector_clock[peer_id] = message.vector_clock.get(peer_id, 0)
            self._on_remote_op({"op_type": message.op_type, "payload": message.payload})
        finally:
            self._applying_remote = False

    def _on_remote_cursor(self, message: CursorMove) -> None:
        peer_id = message.user_id
        if peer_id not in self._peers:
            return
        peer = self._peers[peer_id]
        peer.cursor_x = message.x
        peer.cursor_y = message.y
        peer.last_seen = time.monotonic()
        self._on_cursor_update(peer)

    def _on_user_list_update(self, message: UserListUpdate) -> None:
        """Sync the peer map then fire the user-list callback."""
        incoming_ids = {u["user_id"] for u in message.users}
        # Remove peers that are no longer present
        for uid in list(self._peers):
            if uid not in incoming_ids and uid != self._user_id:
                self._on_peer_left(uid)
                del self._peers[uid]

        # Add / update
        for entry in message.users:
            uid = entry["user_id"]
            if uid == self._user_id:
                continue
            if uid not in self._peers:
                self._peers[uid] = RemotePeer(
                    user_id=uid,
                    display_name=entry.get("display_name", uid),
                    color_css=entry.get("color", ""),
                )
            else:
                peer = self._peers[uid]
                peer.display_name = entry.get("display_name", uid)
                peer.color_css = entry.get("color", peer.color_css)

        self._on_user_list(list(self._peers.values()))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _enqueue(self, raw: str) -> None:
        """Thread-safe enqueue for the asyncio sender."""
        self._send_queue.put_nowait(raw)

    @staticmethod
    def _schedule_gtk(callback, *args) -> None:
        """Schedule *callback* on the GTK main loop.

        We avoid importing GLib at module level so that unit tests that
        run without a display can still import this module.
        """
        try:
            from gi.repository import GLib  # noqa: PLC0415
            GLib.idle_add(callback, *args)
        except ImportError:
            # Running outside GTK (e.g. tests): call directly
            callback(*args)
