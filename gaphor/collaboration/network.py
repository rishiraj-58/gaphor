"""Network transport for collaboration."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from abc import ABC, abstractmethod
from typing import Any, Callable

log = logging.getLogger(__name__)


class NetworkTransport(ABC):
    """Abstract base class for network transports."""

    on_message: Callable[[dict], None] | None = None
    on_connect: Callable[[], None] | None = None
    on_disconnect: Callable[[str], None] | None = None

    @abstractmethod
    def connect(self) -> None:
        """Connect to the server."""

    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect from the server."""

    @abstractmethod
    def send(self, message: dict) -> None:
        """Send a message to the server."""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Check if connected."""


class WebSocketTransport(NetworkTransport):
    """WebSocket-based network transport."""

    def __init__(self, url: str):
        self.url = url
        self._websocket = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._connected = False
        self._message_queue: asyncio.Queue | None = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        """Connect to the WebSocket server."""
        self._thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self._thread.start()

    def disconnect(self) -> None:
        """Disconnect from the WebSocket server."""
        if self._loop and self._connected:
            asyncio.run_coroutine_threadsafe(self._disconnect_async(), self._loop)

    def send(self, message: dict) -> None:
        """Send a message to the server."""
        if self._loop and self._message_queue:
            asyncio.run_coroutine_threadsafe(
                self._message_queue.put(message), self._loop
            )

    def _run_event_loop(self) -> None:
        """Run the asyncio event loop in a background thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._message_queue = asyncio.Queue()

        try:
            self._loop.run_until_complete(self._connect_and_run())
        except Exception as e:
            log.error(f"Event loop error: {e}")
        finally:
            self._loop.close()

    async def _connect_and_run(self) -> None:
        """Connect and run the WebSocket client."""
        try:
            import websockets

            async with websockets.connect(self.url) as websocket:
                self._websocket = websocket
                self._connected = True

                if self.on_connect:
                    self.on_connect()

                receive_task = asyncio.create_task(self._receive_messages())
                send_task = asyncio.create_task(self._send_messages())

                done, pending = await asyncio.wait(
                    [receive_task, send_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                for task in pending:
                    task.cancel()

        except ImportError:
            log.error("websockets library not installed")
            if self.on_disconnect:
                self.on_disconnect("websockets library not installed")
        except Exception as e:
            log.error(f"WebSocket connection error: {e}")
            if self.on_disconnect:
                self.on_disconnect(str(e))
        finally:
            self._connected = False

    async def _receive_messages(self) -> None:
        """Receive messages from the WebSocket."""
        while self._connected and self._websocket:
            try:
                message = await self._websocket.recv()
                data = json.loads(message)
                if self.on_message:
                    self.on_message(data)
            except Exception as e:
                log.error(f"Error receiving message: {e}")
                break

    async def _send_messages(self) -> None:
        """Send messages from the queue to the WebSocket."""
        while self._connected and self._websocket and self._message_queue:
            try:
                message = await self._message_queue.get()
                await self._websocket.send(json.dumps(message))
            except Exception as e:
                log.error(f"Error sending message: {e}")
                break

    async def _disconnect_async(self) -> None:
        """Async disconnect."""
        self._connected = False
        if self._websocket:
            await self._websocket.close()


class LocalTransport(NetworkTransport):
    """Local transport for testing - connects directly to another transport."""

    _instances: dict[str, LocalTransport] = {}

    def __init__(self, channel: str, user_id: str):
        self.channel = channel
        self.user_id = user_id
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        """Connect to the local channel."""
        if self.channel not in LocalTransport._instances:
            LocalTransport._instances[self.channel] = {}
        LocalTransport._instances[self.channel][self.user_id] = self
        self._connected = True
        if self.on_connect:
            self.on_connect()

    def disconnect(self) -> None:
        """Disconnect from the local channel."""
        self._connected = False
        if self.channel in LocalTransport._instances:
            LocalTransport._instances[self.channel].pop(self.user_id, None)
        if self.on_disconnect:
            self.on_disconnect("")

    def send(self, message: dict) -> None:
        """Send a message to other transports on the same channel."""
        if not self._connected:
            return

        channel_transports = LocalTransport._instances.get(self.channel, {})
        for uid, transport in channel_transports.items():
            if uid != self.user_id and transport.on_message:
                transport.on_message(message)

    @classmethod
    def clear_all(cls) -> None:
        """Clear all local transport instances."""
        cls._instances.clear()
