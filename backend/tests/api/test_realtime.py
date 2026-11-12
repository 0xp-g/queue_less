"""Realtime path end to end over real sockets (uvicorn + websockets client).

The multi-instance test is the important one: a staff action handled by instance A reaches a
visitor connected to instance B through Redis pub/sub (ADR-0005).
"""

import asyncio
import contextlib
import json
import socket
import time
import uuid

import httpx
import pytest
import uvicorn
import websockets

from app.main import create_app
from tests.factories import make_world


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.asynccontextmanager
async def live_server(settings):
    app = create_app(settings)
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", ws="websockets-sansio")
    )
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.02)
    listener = app.state.container.extras.get("listener")
    if listener is not None:
        await asyncio.wait_for(listener.connected.wait(), 5)
    try:
        yield f"127.0.0.1:{port}", app
    finally:
        server.should_exit = True
        await task


async def _recv(ws, predicate=lambda m: m["type"] != "ping", timeout=3.0) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        msg = json.loads(await asyncio.wait_for(ws.recv(), deadline - time.monotonic()))
        if predicate(msg):
            return msg


async def _join(http, w):
    r = await http.post(
        f"/api/queues/{w.queue_id}/tickets",
        json={"join_token": w.join_token, "client_request_id": uuid.uuid4().hex},
    )
    return r.json()


@pytest.mark.parametrize("transport", ["memory", "redis"])
async def test_snapshot_on_connect_then_live_update(settings, engine, transport):
    s = settings.model_copy(update={"event_transport": transport})
    async with live_server(s) as (host, app):
        w = await make_world(app.state.container)
        async with httpx.AsyncClient(base_url=f"http://{host}") as http:
            tickets = [await _join(http, w) for _ in range(3)]
            mine = tickets[2]
            async with websockets.connect(
                f"ws://{host}/ws/queues/{w.queue_id}?ticket={mine['token']}"
            ) as ws:
                snap = await _recv(ws)
                assert snap["type"] == "snapshot" and snap["position"] == 3
                assert snap["now_serving"] is None

                await http.post(f"/api/queues/{w.queue_id}/call-next", headers=w.staff_headers)
                upd = await _recv(ws, lambda m: m["type"] == "update")
                assert upd["position"] == 2 and upd["now_serving"] == tickets[0]["seq"]
                assert upd["event"] == "called" and upd["version"] > snap["version"]

                # resync request returns a fresh snapshot (used after a version gap)
                await ws.send(json.dumps({"type": "resync"}))
                again = await _recv(ws, lambda m: m["type"] == "snapshot")
                assert again["version"] == upd["version"]


async def test_display_board_receives_counter_view(settings, engine):
    async with live_server(settings) as (host, app):
        w = await make_world(app.state.container)
        async with httpx.AsyncClient(base_url=f"http://{host}") as http:
            t = await _join(http, w)
            async with websockets.connect(f"ws://{host}/ws/queues/{w.queue_id}") as ws:
                assert (await _recv(ws))["waiting_count"] == 1
                await http.post(
                    f"/api/queues/{w.queue_id}/call-next",
                    json={"counter_id": w.counter_ids[1]},
                    headers=w.staff_headers,
                )
                upd = await _recv(ws, lambda m: m["type"] == "update")
                by_label = {c["label"]: c["seq"] for c in upd["counters"]}
                assert by_label == {"C1": None, "C2": t["seq"]}


async def test_unknown_ticket_or_queue_closes_4404(settings, engine):
    async with live_server(settings) as (host, app):
        w = await make_world(app.state.container)
        for url in (
            f"ws://{host}/ws/queues/{w.queue_id}?ticket=bogus",
            f"ws://{host}/ws/queues/999999",
        ):
            async with websockets.connect(url) as ws:
                with pytest.raises(websockets.ConnectionClosed) as exc:
                    await ws.recv()
                assert exc.value.rcvd.code == 4404


async def test_cross_instance_fanout_via_redis(settings, engine):
    """Visitor on instance B sees a call-next handled by instance A."""
    s = settings.model_copy(update={"event_transport": "redis"})
    async with live_server(s) as (host_a, app_a), live_server(s) as (host_b, _):
        w = await make_world(app_a.state.container)
        async with httpx.AsyncClient(base_url=f"http://{host_a}") as http_a:
            first, mine = await _join(http_a, w), await _join(http_a, w)
            async with websockets.connect(
                f"ws://{host_b}/ws/queues/{w.queue_id}?ticket={mine['token']}"
            ) as ws:
                assert (await _recv(ws))["position"] == 2
                t0 = time.perf_counter()
                await http_a.post(f"/api/queues/{w.queue_id}/call-next", headers=w.staff_headers)
                upd = await _recv(ws, lambda m: m["type"] == "update" and m["position"] == 1)
                assert upd["now_serving"] == first["seq"]
                assert time.perf_counter() - t0 < 1.0
