import asyncio
import uuid

from tests.factories import join, make_world


async def test_join_returns_ticket_with_position_eta_and_token(client, container):
    w = await make_world(container, counters=1, default_service_sec=60)
    first = (await join(client, w)).json()
    r = await join(client, w)
    assert r.status_code == 201
    body = r.json()
    assert body["seq"] == 2 and body["position"] == 2 and body["status"] == "waiting"
    # The single counter is idle, so #1 is called immediately and #2 waits one service.
    assert first["eta_seconds"] == 0.0
    assert body["eta_seconds"] == 60.0
    assert len(body["token"]) == 22
    status = await client.get(f"/api/tickets/{body['token']}")
    assert status.json()["position"] == 2


async def test_retried_join_is_idempotent(client, container):
    w = await make_world(container)
    rid = uuid.uuid4().hex
    a, b = await join(client, w, rid), await join(client, w, rid)
    assert a.status_code == 201 and b.status_code == 200
    assert a.json()["token"] == b.json()["token"] and a.json()["seq"] == b.json()["seq"]


async def test_concurrent_identical_retries_create_one_ticket(client, container):
    w = await make_world(container)
    rid = uuid.uuid4().hex
    results = await asyncio.gather(*[join(client, w, rid) for _ in range(5)])
    assert {r.status_code for r in results} <= {200, 201}
    assert len({r.json()["ticket_id"] for r in results}) == 1


async def test_bad_join_token_is_403(client, container):
    w = await make_world(container)
    w.join_token = "forged"
    r = await join(client, w)
    assert r.status_code == 403 and r.json()["error"]["code"] == "INVALID_TOKEN"


async def test_paused_queue_rejects_joins(client, container):
    w = await make_world(container, status="paused")
    r = await join(client, w)
    assert r.status_code == 409 and r.json()["error"]["code"] == "QUEUE_NOT_OPEN"


async def test_one_active_ticket_per_device(client, container):
    w = await make_world(container)
    assert (await join(client, w, device="device-aaaa")).status_code == 201
    r = await join(client, w, device="device-aaaa")
    assert r.status_code == 409 and r.json()["error"]["code"] == "ACTIVE_TICKET_EXISTS"


async def test_cancel_moves_everyone_behind_up(client, container):
    w = await make_world(container)
    t1, t2, t3 = [(await join(client, w)).json() for _ in range(3)]
    r = await client.delete(f"/api/tickets/{t1['token']}")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert (await client.get(f"/api/tickets/{t3['token']}")).json()["position"] == 2
    again = await client.delete(f"/api/tickets/{t1['token']}")
    assert again.status_code == 409


async def test_unknown_ticket_token_is_404(client):
    assert (await client.get("/api/tickets/nope")).status_code == 404
