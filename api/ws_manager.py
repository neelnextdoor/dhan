from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger("ws_manager")


class ConnectionManager:
    """Manages WebSocket connections and broadcasts messages."""

    def __init__(self):
        self._connections: dict[str, list[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, channel: str = "default"):
        await websocket.accept()
        async with self._lock:
            if channel not in self._connections:
                self._connections[channel] = []
            self._connections[channel].append(websocket)
        logger.info("WS connected: channel=%s, total=%d", channel, len(self._connections.get(channel, [])))

    async def disconnect(self, websocket: WebSocket, channel: str = "default"):
        async with self._lock:
            if channel in self._connections:
                self._connections[channel] = [c for c in self._connections[channel] if c != websocket]
        logger.info("WS disconnected: channel=%s", channel)

    async def broadcast(self, channel: str, message_type: str, data: Any):
        msg = json.dumps({
            "type": message_type,
            "data": data,
            "timestamp": datetime.now().isoformat(),
        })
        async with self._lock:
            connections = list(self._connections.get(channel, []))

        dead = []
        for ws in connections:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)

        if dead:
            async with self._lock:
                for ws in dead:
                    if channel in self._connections:
                        self._connections[channel] = [c for c in self._connections[channel] if c != ws]

    def broadcast_sync(self, channel: str, message_type: str, data: Any):
        """Thread-safe broadcast from sync context (e.g., engine thread)."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self.broadcast(channel, message_type, data))
            else:
                loop.run_until_complete(self.broadcast(channel, message_type, data))
        except RuntimeError:
            pass

    @property
    def connection_count(self) -> int:
        return sum(len(conns) for conns in self._connections.values())


ws_manager = ConnectionManager()
