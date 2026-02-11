"""CollaborationService – Gaphor Service wiring.

This is the single integration point between the real-time collaboration
subsystem and the rest of Gaphor.  It is a standard Gaphor ``Service``
and participates in the dependency-injection lifecycle exactly like
``UndoManager``, ``Recovery``, and similar services.

Responsibilities
----------------
1. **Server mode** – start and stop the ``CollaborationServer`` using
   Gaphor's ``EventManager`` asyncio bridge.
2. **Client mode** – create a ``CollaborationClient`` for the local user,
   wire it to the model event system, and tear it down on session close.
3. **Local change capture** – subscribe to the same Gaphor model events
   as ``gaphor.storage.recovery.Recorder``.  On each commit, the
   accumulated op-tuples are forwarded to the client, unless the change
   came from a remote replay (``_applying_remote`` guard).
4. **Remote change application** – the client's ``on_remote_op`` callback
   calls ``replay_events`` inside a ``Transaction(context="collab")`` so:
   a) The UndoManager records the change and it can be undone locally.
   b) All other Gaphor event subscribers (diagram redraw, model browser,
      etc.) are notified through the normal event pipeline.
5. **Cursor overlay** – patch the ``CursorOverlayPainter`` into the
   ``PainterChain`` of every open ``DiagramPage`` and keep it updated
   as remote cursors move.
6. **User list** – maintain a live ``dict[user_id, RemotePeer]`` and emit
   a ``CollaborationPeersChanged`` event so the UI can show / hide the
   collaborator panel.

Transaction context
-------------------
Remote ops are wrapped in ``Transaction(event_manager, context="collab")``.
The UndoManager already handles the ``"rollback"`` and ``"editing"``
contexts; ``"collab"`` is treated as a normal transaction so undo works.

Recorder events captured
------------------------
The service subscribes to every event that ``Recorder`` handles
(``ElementCreated``, ``ElementDeleted``, ``AttributeUpdated``,
``AssociationAdded``, ``AssociationSet``, ``AssociationDeleted``,
``MatrixUpdated``, ``ElementTypeUpdated``, ``HandlePositionEvent``,
``ItemConnected``, ``ItemDisconnected``, ``ItemReconnected``,
``LineSplitSegmentEvent``, ``LineMergeSegmentEvent``).  The same
``event_handler`` decorator pattern used throughout Gaphor is used here.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from typing import Any

from gaphor.abc import Service
from gaphor.collaboration.client import CollaborationClient, RemotePeer
from gaphor.collaboration.conflict_resolver import ConflictResolver
from gaphor.collaboration.cursor_overlay import CursorOverlayPainter
from gaphor.collaboration.messages import ConflictNotification
from gaphor.collaboration.server import CollaborationServer
from gaphor.core import event_handler
from gaphor.core.modeling import (
    AssociationAdded,
    AssociationDeleted,
    AssociationSet,
    AttributeUpdated,
    DerivedUpdated,
    ElementCreated,
    ElementDeleted,
    ElementTypeUpdated,
    ModelReady,
    RedefinedAdded,
    RedefinedDeleted,
    RedefinedSet,
    swap_element_type,
)
from gaphor.core.modeling.presentation import MatrixUpdated
from gaphor.diagram.connectors import (
    ItemConnected,
    ItemDisconnected,
    ItemReconnected,
)
from gaphor.diagram.presentation import HandlePositionEvent
from gaphor.diagram.segment import LineMergeSegmentEvent, LineSplitSegmentEvent
from gaphor.event import SessionShutdown, TransactionCommit, TransactionRollback
from gaphor.storage.recovery import replay_events
from gaphor.transaction import Transaction

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public event emitted on the Gaphor event bus
# ---------------------------------------------------------------------------

@dataclass
class CollaborationPeersChanged:
    """Emitted whenever the set of remote collaborators changes."""
    peers: list[RemotePeer]


@dataclass
class CollaborationConflict:
    """Emitted when the server reports a conflict for a local operation."""
    notification: ConflictNotification


# ---------------------------------------------------------------------------
# CollaborationService
# ---------------------------------------------------------------------------

class CollaborationService(Service):
    """Gaphor service providing real-time multi-user diagram editing.

    Instantiate via the dependency-injection framework; the constructor
    receives the required services automatically.

    Parameters
    ----------
    event_manager:
        Gaphor's central event bus.
    element_factory:
        Model element repository.
    modeling_language:
        Used by ``replay_events`` to look up element types by name.
    user_id:
        Stable identifier for the local user.  Pass e.g. a UUID loaded
        from settings.
    display_name:
        Human-readable name shown in the collaboration participant list
        and as a tooltip on the local user's cursor as seen by peers.
    server_host / server_port:
        Where to bind the WebSocket server.
    client_url:
        Where to connect the local client.  Defaults to the same host/port
        as the server so a single-machine session works out of the box.
    """

    def __init__(
        self,
        event_manager,
        element_factory,
        modeling_language,
        user_id: str = "local-user",
        display_name: str = "Local User",
        server_host: str = "127.0.0.1",
        server_port: int = 4765,
        client_url: str = "",
        diagram_id: str = "",
    ) -> None:
        self.event_manager = event_manager
        self.element_factory = element_factory
        self.modeling_language = modeling_language

        self._user_id = user_id
        self._display_name = display_name
        self._diagram_id = diagram_id
        self._server_host = server_host
        self._server_port = server_port
        self._client_url = client_url or f"ws://{server_host}:{server_port}"

        # Pending ops accumulated within the current transaction
        self._pending_ops: list[tuple[str, list[Any]]] = []

        # Set while replaying remote ops to block re-transmission
        self._applying_remote: bool = False

        # Remote peer state keyed by user_id
        self._peers: dict[str, RemotePeer] = {}

        # Server and client instances
        self._server: CollaborationServer = CollaborationServer(
            host=server_host, port=server_port
        )
        self._client: CollaborationClient | None = None

        # The asyncio loop running the server (lives in its own thread)
        self._server_loop: asyncio.AbstractEventLoop | None = None
        self._server_thread: threading.Thread | None = None

        # Subscribe to model change events
        self._subscribe_model_events()

        # Subscribe to session lifecycle events
        event_manager.subscribe(self._on_transaction_commit)
        event_manager.subscribe(self._on_transaction_rollback)
        event_manager.subscribe(self._on_session_shutdown)
        event_manager.subscribe(self._on_model_ready)

    # ------------------------------------------------------------------
    # Service lifecycle
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """Disconnect client and stop server."""
        self._unsubscribe_model_events()
        self.event_manager.unsubscribe(self._on_transaction_commit)
        self.event_manager.unsubscribe(self._on_transaction_rollback)
        self.event_manager.unsubscribe(self._on_session_shutdown)
        self.event_manager.unsubscribe(self._on_model_ready)

        self._stop_client()
        self._stop_server()

    def start_server(self) -> None:
        """Start the collaboration WebSocket server in a background thread."""
        self._server_thread = threading.Thread(
            target=self._run_server_loop, daemon=True, name="CollaborationServer"
        )
        self._server_thread.start()
        log.info(
            "Collaboration server thread started (ws://%s:%d).",
            self._server_host,
            self._server_port,
        )

    def start_client(self, diagram_id: str = "") -> None:
        """Connect the local user as a collaboration client.

        Call *after* the server is running.
        """
        if diagram_id:
            self._diagram_id = diagram_id

        self._client = CollaborationClient(
            user_id=self._user_id,
            display_name=self._display_name,
            diagram_id=self._diagram_id,
            url=self._client_url,
            on_remote_op=self._on_remote_op,
            on_cursor_update=self._on_cursor_update,
            on_peer_left=self._on_peer_left,
            on_user_list=self._on_user_list,
            on_conflict=self._on_conflict,
        )
        self._client.connect()
        log.info(
            "Collaboration client started for user %r on diagram %r.",
            self._user_id,
            self._diagram_id,
        )

    def build_cursor_overlay_painter(self) -> CursorOverlayPainter:
        """Create a ``CursorOverlayPainter`` bound to this service's peers.

        The caller (``DiagramPage``) appends the returned painter to its
        ``PainterChain``.
        """
        def _cursor_provider():
            for peer in self._peers.values():
                if peer.diagram_id == self._diagram_id:
                    yield (
                        peer.user_id,
                        peer.display_name,
                        peer.color_css,
                        peer.cursor_x,
                        peer.cursor_y,
                        peer.last_seen,
                    )

        return CursorOverlayPainter(_cursor_provider)

    def send_cursor_position(self, x: float, y: float) -> None:
        """Forward a cursor position update from the local GTK view.

        Should be called from the ``motion-notify-event`` handler in
        ``DiagramPage`` (or ``DiagramView``).
        """
        if self._client:
            self._client.send_cursor_move(x, y)

    @property
    def peers(self) -> list[RemotePeer]:
        return list(self._peers.values())

    @property
    def local_color_css(self) -> str:
        return self._client.local_color_css if self._client else ""

    # ------------------------------------------------------------------
    # Model event subscriptions  (mirror Recorder's list exactly)
    # ------------------------------------------------------------------

    def _subscribe_model_events(self) -> None:
        em = self.event_manager
        em.subscribe(self._on_create_element)
        em.subscribe(self._on_delete_element)
        em.subscribe(self._on_attribute_change)
        em.subscribe(self._on_association_set)
        em.subscribe(self._on_association_delete)
        em.subscribe(self._on_matrix_updated)
        em.subscribe(self._on_type_swapped)
        em.subscribe(self._on_handle_position)
        em.subscribe(self._on_item_connected)
        em.subscribe(self._on_item_disconnected)
        em.subscribe(self._on_item_reconnected)
        em.subscribe(self._on_line_split)
        em.subscribe(self._on_line_merge)

    def _unsubscribe_model_events(self) -> None:
        em = self.event_manager
        em.unsubscribe(self._on_create_element)
        em.unsubscribe(self._on_delete_element)
        em.unsubscribe(self._on_attribute_change)
        em.unsubscribe(self._on_association_set)
        em.unsubscribe(self._on_association_delete)
        em.unsubscribe(self._on_matrix_updated)
        em.unsubscribe(self._on_type_swapped)
        em.unsubscribe(self._on_handle_position)
        em.unsubscribe(self._on_item_connected)
        em.unsubscribe(self._on_item_disconnected)
        em.unsubscribe(self._on_item_reconnected)
        em.unsubscribe(self._on_line_split)
        em.unsubscribe(self._on_line_merge)

    # ------------------------------------------------------------------
    # Recorder-equivalent event handlers
    # Each handler appends a tuple to self._pending_ops.  The tuples use
    # exactly the same format as gaphor.storage.recovery.Recorder so the
    # replay_events() function on the receiver side can consume them
    # without modification.
    # ------------------------------------------------------------------

    @event_handler(ElementCreated)
    def _on_create_element(self, event: ElementCreated) -> None:
        if self._applying_remote:
            return
        self._pending_ops.append((
            "c",
            [
                type(event.element).__modeling_language__,
                type(event.element).__name__,
                event.element.id,
                event.diagram.id if event.diagram else None,
            ],
        ))

    @event_handler(ElementDeleted)
    def _on_delete_element(self, event: ElementDeleted) -> None:
        if self._applying_remote:
            return
        self._pending_ops.append((
            "u",
            [event.element.id, event.diagram.id if event.diagram else None],
        ))

    @event_handler(AttributeUpdated)
    def _on_attribute_change(self, event: AttributeUpdated) -> None:
        if self._applying_remote:
            return
        self._pending_ops.append((
            "a",
            [event.element.id, event.property.name, event.new_value],
        ))

    @event_handler(AssociationAdded, AssociationSet)
    def _on_association_set(self, event) -> None:
        if self._applying_remote:
            return
        if isinstance(event, (DerivedUpdated, RedefinedAdded, RedefinedSet)):
            return
        self._pending_ops.append((
            "s",
            [
                event.element.id,
                event.property.name,
                event.new_value.id if event.new_value else None,
            ],
        ))

    @event_handler(AssociationDeleted)
    def _on_association_delete(self, event: AssociationDeleted) -> None:
        if self._applying_remote:
            return
        if isinstance(event, (DerivedUpdated, RedefinedDeleted)):
            return
        self._pending_ops.append((
            "d",
            [
                event.element.id,
                event.property.name,
                event.old_value.id if event.old_value else None,
            ],
        ))

    @event_handler(MatrixUpdated)
    def _on_matrix_updated(self, event: MatrixUpdated) -> None:
        if self._applying_remote:
            return
        self._pending_ops.append(("mu", [event.element.id, event.new_value]))

    @event_handler(ElementTypeUpdated)
    def _on_type_swapped(self, event: ElementTypeUpdated) -> None:
        if self._applying_remote:
            return
        self._pending_ops.append(("ts", [event.element.id, event.new_class.__name__]))

    @event_handler(HandlePositionEvent)
    def _on_handle_position(self, event: HandlePositionEvent) -> None:
        if self._applying_remote:
            return
        self._pending_ops.append(
            ("hp", [event.element.id, event.handle_index, event.new_value])
        )

    @event_handler(ItemConnected)
    def _on_item_connected(self, event: ItemConnected) -> None:
        if self._applying_remote:
            return
        self._pending_ops.append(
            ("ic", [event.element.id, event.handle_index, event.connected_id, event.port_index])
        )

    @event_handler(ItemDisconnected)
    def _on_item_disconnected(self, event: ItemDisconnected) -> None:
        if self._applying_remote:
            return
        self._pending_ops.append(
            ("id", [event.element.id, event.handle_index, event.connected_id, event.port_index])
        )

    @event_handler(ItemReconnected)
    def _on_item_reconnected(self, event: ItemReconnected) -> None:
        if self._applying_remote:
            return
        self._pending_ops.append(
            ("ir", [event.element.id, event.handle_index, event.connected_id, event.port_index])
        )

    @event_handler(LineSplitSegmentEvent)
    def _on_line_split(self, event: LineSplitSegmentEvent) -> None:
        if self._applying_remote:
            return
        self._pending_ops.append(("ls", [event.element.id, event.segment, event.count]))

    @event_handler(LineMergeSegmentEvent)
    def _on_line_merge(self, event: LineMergeSegmentEvent) -> None:
        if self._applying_remote:
            return
        self._pending_ops.append(("lm", [event.element.id, event.segment, event.count]))

    # ------------------------------------------------------------------
    # Transaction lifecycle handlers
    # ------------------------------------------------------------------

    @event_handler(TransactionCommit)
    def _on_transaction_commit(self, event: TransactionCommit) -> None:
        """Flush pending ops to the server when a transaction commits."""
        if event.context in ("rollback", "undo", "redo", "recover", "collab"):
            self._pending_ops.clear()
            return
        if not self._client or not self._pending_ops:
            self._pending_ops.clear()
            return
        ops = list(self._pending_ops)
        self._pending_ops.clear()
        for op_type, payload in ops:
            self._client.send_model_operation(op_type, payload)

    @event_handler(TransactionRollback)
    def _on_transaction_rollback(self, _event) -> None:
        self._pending_ops.clear()

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    @event_handler(SessionShutdown)
    def _on_session_shutdown(self, _event: SessionShutdown) -> None:
        self._stop_client()
        self._stop_server()

    @event_handler(ModelReady)
    def _on_model_ready(self, _event) -> None:
        # Reset pending ops when a new model loads; any buffered ops from
        # the old model must not be forwarded.
        self._pending_ops.clear()

    # ------------------------------------------------------------------
    # Callbacks from CollaborationClient (GTK thread)
    # ------------------------------------------------------------------

    def _on_remote_op(self, op_dict: dict[str, Any]) -> None:
        """Apply a single remote operation to the local model."""
        op_type = op_dict.get("op_type", "")
        payload = op_dict.get("payload", [])
        # replay_events expects the same tuple format as Recorder
        event_tuple = tuple([op_type] + payload)

        self._applying_remote = True
        try:
            with Transaction(self.event_manager, context="collab"):
                replay_events(
                    [event_tuple],
                    self.element_factory,
                    self.modeling_language,
                )
        except Exception:
            log.exception(
                "Failed to apply remote operation: op_type=%r payload=%r",
                op_type,
                payload,
            )
        finally:
            self._applying_remote = False

    def _on_cursor_update(self, peer: RemotePeer) -> None:
        """Update peer cursor position and request a view refresh."""
        self._peers[peer.user_id] = peer
        # Request a diagram redraw so the cursor overlay is repainted.
        # We use the element_factory to find the current diagram and
        # request an update on it.
        try:
            from gaphor.core.modeling.diagram import Diagram  # noqa: PLC0415
            from gaphor.core.modeling.event import DiagramUpdateRequested  # noqa: PLC0415
            for diagram in self.element_factory.select(Diagram):
                if diagram.id == self._diagram_id:
                    self.event_manager.handle(DiagramUpdateRequested(diagram))
                    break
        except Exception:
            log.debug("Could not request diagram update for cursor repaint.", exc_info=True)

    def _on_peer_left(self, user_id: str) -> None:
        self._peers.pop(user_id, None)
        self.event_manager.handle(CollaborationPeersChanged(list(self._peers.values())))

    def _on_user_list(self, peers: list[RemotePeer]) -> None:
        for peer in peers:
            existing = self._peers.get(peer.user_id)
            if existing:
                existing.display_name = peer.display_name
                existing.color_css = peer.color_css
            else:
                self._peers[peer.user_id] = peer
        # Remove peers no longer in the list
        current_ids = {p.user_id for p in peers}
        for uid in list(self._peers):
            if uid not in current_ids:
                del self._peers[uid]
        self.event_manager.handle(CollaborationPeersChanged(list(self._peers.values())))

    def _on_conflict(self, notification: ConflictNotification) -> None:
        self.event_manager.handle(CollaborationConflict(notification))
        log.warning(
            "Conflict on client_seq=%d: %s",
            notification.client_sequence,
            notification.resolution,
        )

    # ------------------------------------------------------------------
    # Server thread management
    # ------------------------------------------------------------------

    def _run_server_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._server_loop = loop
        try:
            loop.run_until_complete(self._server.start())
            loop.run_forever()
        finally:
            loop.run_until_complete(self._server.stop())
            loop.close()

    def _stop_server(self) -> None:
        if self._server_loop and not self._server_loop.is_closed():
            self._server_loop.call_soon_threadsafe(self._server_loop.stop)
        if self._server_thread:
            self._server_thread.join(timeout=3.0)
            self._server_thread = None

    def _stop_client(self) -> None:
        if self._client:
            self._client.disconnect()
            self._client = None
