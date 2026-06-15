import asyncio
import logging
from collections import defaultdict
from typing import Dict, Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    In-process WebSocket connection manager.
    Maps call_id -> set of connected WebSocket clients.
    """

    def __init__(self) -> None:
        self._connections: Dict[str, Set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, call_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[call_id].add(websocket)
        logger.info("WS connected: call=%s", call_id)

    async def disconnect(self, call_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections[call_id].discard(websocket)
            if not self._connections[call_id]:
                del self._connections[call_id]
        logger.info("WS disconnected: call=%s", call_id)

    async def broadcast(self, call_id: str, message: dict) -> None:
        async with self._lock:
            snapshot = set(self._connections.get(call_id, set()))

        dead: Set[WebSocket] = set()
        for ws in snapshot:
            try:
                await ws.send_json(message)
            except Exception as exc:
                logger.warning("WS send failed call=%s: %s", call_id, exc)
                dead.add(ws)

        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections[call_id].discard(ws)

    def active_count(self, call_id: str) -> int:
        return len(self._connections.get(call_id, set()))


# Singleton used across the application
manager = ConnectionManager()
