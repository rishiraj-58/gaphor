"""WebSocket client for collaboration."""

import asyncio
import logging
from typing import Callable

log = logging.getLogger(__name__)


class CollaborationClient:
    """WebSocket client for collaboration server communication."""

    def __init__(
        self,
        on_message: Callable[[str], None],
        on_connect: Callable[[], None] | None = None,
        on_disconnect: Callable[[str], None] | None = None,
    ):
        self._on_message = on_message
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect
        self._websocket = None
        self._connected = False
        self._url: str = ""
        self._reconnect_task: asyncio.Task | None = None
        self._receive_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._heartbeat_interval = 15.0
        self._reconnect_delay = 5.0
        self._max_reconnect_attempts = 5

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self, url: str) -> bool:
        self._url = url
        try:
            import websockets
            self._websocket = await websockets.connect(url)
            self._connected = True
            if self._on_connect:
                self._on_connect()
            self._receive_task = asyncio.create_task(self._receive_loop())
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            log.info(f"Connected to collaboration server: {url}")
            return True
        except ImportError:
            log.warning("websockets package not installed, using mock connection")
            self._connected = True
            if self._on_connect:
                self._on_connect()
            return True
        except Exception as e:
            log.error(f"Failed to connect to collaboration server: {e}")
            return False

    async def disconnect(self) -> None:
        self._connected = False
        if self._receive_task:
            self._receive_task.cancel()
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self._reconnect_task:
            self._reconnect_task.cancel()
        if self._websocket:
            try:
                await self._websocket.close()
            except Exception:
                pass
        self._websocket = None
        if self._on_disconnect:
            self._on_disconnect("disconnected")
        log.info("Disconnected from collaboration server")

    async def send(self, message: str) -> bool:
        if not self._connected:
            return False
        if self._websocket:
            try:
                await self._websocket.send(message)
                return True
            except Exception as e:
                log.error(f"Failed to send message: {e}")
                await self._handle_disconnect()
                return False
        return True  # Mock mode

    async def _receive_loop(self) -> None:
        if not self._websocket:
            return
        try:
            async for message in self._websocket:
                self._on_message(message)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.error(f"WebSocket receive error: {e}")
            await self._handle_disconnect()

    async def _heartbeat_loop(self) -> None:
        try:
            while self._connected:
                await asyncio.sleep(self._heartbeat_interval)
                if self._websocket:
                    try:
                        await self._websocket.ping()
                    except Exception:
                        await self._handle_disconnect()
                        break
        except asyncio.CancelledError:
            pass

    async def _handle_disconnect(self) -> None:
        if not self._connected:
            return
        self._connected = False
        if self._on_disconnect:
            self._on_disconnect("connection_lost")
        self._reconnect_task = asyncio.create_task(self._reconnect())

    async def _reconnect(self) -> None:
        attempts = 0
        while attempts < self._max_reconnect_attempts:
            attempts += 1
            log.info(f"Reconnection attempt {attempts}/{self._max_reconnect_attempts}")
            await asyncio.sleep(self._reconnect_delay * attempts)
            if await self.connect(self._url):
                return
        log.error("Failed to reconnect after maximum attempts")
