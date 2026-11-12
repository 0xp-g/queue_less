"""WS /ws/queues/{id}?ticket=<token>  - live updates for visitors (with ticket) or boards.

Protocol (server -> client): {"type": "snapshot" | "update" | "ping", "version", ...view}
Protocol (client -> server): {"type": "resync"}  when the client detects a version gap.
"""

import asyncio
import contextlib

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.errors import NotFound
from app.realtime.hub import Connection

router = APIRouter()

CLOSE_NOT_FOUND = 4404


async def _heartbeat(conn: Connection, interval: float) -> None:
    while conn.alive:
        await asyncio.sleep(interval)
        if not await conn.send({"type": "ping"}, timeout=5):
            with contextlib.suppress(Exception):
                await conn.ws.close()
            return


@router.websocket("/ws/queues/{queue_id}")
async def queue_socket(ws: WebSocket, queue_id: int, ticket: str | None = None):
    container = ws.app.state.container
    await ws.accept()

    ticket_id = None
    try:
        if ticket:
            t = await container.tickets.ticket_for_token(ticket)
            if t.queue_id != queue_id:
                raise NotFound()
            ticket_id = t.id
        else:
            await container.queues.public(queue_id)  # raises NotFound for unknown queues
    except NotFound:
        await ws.close(code=CLOSE_NOT_FOUND, reason="queue or ticket not found")
        return

    conn = Connection(ws=ws, queue_id=queue_id, ticket_id=ticket_id)
    hub = container.hub
    await hub.connect(conn)
    beat = asyncio.create_task(_heartbeat(conn, container.settings.ws_ping_interval_sec))
    try:
        while True:
            message = await ws.receive_json()
            if isinstance(message, dict) and message.get("type") == "resync":
                await hub.send_snapshot(conn)
    except (WebSocketDisconnect, RuntimeError, ValueError):
        pass
    finally:
        conn.alive = False
        beat.cancel()
        hub.disconnect(conn)
