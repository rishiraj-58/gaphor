"""Simple WebSocket collaboration server for testing/development."""

import asyncio
import json
import logging
from typing import Set

log = logging.getLogger(__name__)


class CollaborationServer:
    """Simple collaboration server for development/testing."""

    def __init__(self, host: str = "localhost", port: int = 8765):
        self.host = host
        self.port = port
        self._sessions: dict[str, Set] = {}  # session_id -> set of websockets
        self._users: dict = {}  # websocket -> user_info

    async def start(self):
        try:
            import websockets
            async with websockets.serve(self._handler, self.host, self.port):
                log.info(f"Collaboration server started on ws://{self.host}:{self.port}")
                await asyncio.Future()  # run forever
        except ImportError:
            log.error("websockets package not installed")

    async def _handler(self, websocket):
        session_id = None
        try:
            async for message in websocket:
                data = json.loads(message)
                msg_type = data.get("type")
                user_id = data.get("user_id")
                payload = data.get("payload", {})

                if msg_type == "join":
                    session_id = payload.get("session_id")
                    username = payload.get("username")
                    if session_id not in self._sessions:
                        self._sessions[session_id] = set()
                    self._sessions[session_id].add(websocket)
                    self._users[websocket] = {
                        "user_id": user_id,
                        "username": username,
                        "session_id": session_id,
                    }
                    await self._broadcast(session_id, message, exclude=websocket)
                    log.info(f"User {username} joined session {session_id}")

                elif msg_type == "leave":
                    if session_id:
                        await self._broadcast(session_id, message, exclude=websocket)
                        self._sessions[session_id].discard(websocket)
                        self._users.pop(websocket, None)

                elif msg_type in ("cursor", "change", "sync"):
                    if session_id:
                        await self._broadcast(session_id, message, exclude=websocket)

                elif msg_type == "heartbeat":
                    pass

        except Exception as e:
            log.error(f"WebSocket error: {e}")
        finally:
            if session_id and session_id in self._sessions:
                self._sessions[session_id].discard(websocket)
                user_info = self._users.pop(websocket, {})
                if user_info:
                    leave_msg = json.dumps({
                        "type": "leave",
                        "user_id": user_info.get("user_id"),
                        "payload": {},
                    })
                    await self._broadcast(session_id, leave_msg)

    async def _broadcast(self, session_id: str, message: str, exclude=None):
        if session_id not in self._sessions:
            return
        for ws in self._sessions[session_id]:
            if ws != exclude:
                try:
                    await ws.send(message)
                except Exception:
                    pass


def run_server(host: str = "localhost", port: int = 8765):
    """Run the collaboration server."""
    server = CollaborationServer(host, port)
    asyncio.run(server.start())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_server()
