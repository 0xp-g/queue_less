from sqlalchemy import text

from tests.factories import join, make_world


async def test_call_next_then_complete_updates_estimate(client, container):
    w = await make_world(container, default_service_sec=80)
    t = (await join(client, w)).json()
    called = await client.post(
        f"/api/queues/{w.queue_id}/call-next",
        json={"counter_id": w.counter_ids[0]},
        headers=w.staff_headers,
    )
    assert called.status_code == 200 and called.json()["seq"] == t["seq"]
    status = (await client.get(f"/api/tickets/{t['token']}")).json()
    assert status["status"] == "called" and status["counter"] == "C1"
    assert status["now_serving"] == t["seq"]

    # pretend the service took 180 s, then complete
    async with container.session_factory() as s:
        await s.execute(
            text("UPDATE tickets SET called_at = now() - interval '180 seconds' WHERE id = :i"),
            {"i": t["ticket_id"]},
        )
        await s.commit()
    done = await client.post(f"/api/tickets/{t['ticket_id']}/complete", headers=w.staff_headers)
    assert done.status_code == 200 and done.json()["status"] == "served"
    q = (await client.get(f"/api/queues/{w.queue_id}", headers=w.staff_headers)).json()
    assert 99 < q["est_service_sec"] < 101  # 0.2 * 180 + 0.8 * 80 = 100


async def test_call_next_on_empty_queue_is_404(client, container):
    w = await make_world(container)
    r = await client.post(f"/api/queues/{w.queue_id}/call-next", headers=w.staff_headers)
    assert r.status_code == 404 and r.json()["error"]["code"] == "QUEUE_EMPTY"


async def test_illegal_transition_is_409(client, container):
    w = await make_world(container)
    t = (await join(client, w)).json()
    r = await client.post(f"/api/tickets/{t['ticket_id']}/complete", headers=w.staff_headers)
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_TRANSITION"


async def test_staff_cannot_see_other_venues(client, container):
    """Tenant isolation: another venue's resources are 404, not 403 (no existence leak)."""
    mine = await make_world(container, name="Venue A")
    other = await make_world(container, name="Venue B")
    t = (await join(client, other)).json()
    h = mine.staff_headers
    assert (await client.get(f"/api/queues/{other.queue_id}", headers=h)).status_code == 404
    r = await client.post(f"/api/queues/{other.queue_id}/call-next", headers=h)
    assert r.status_code == 404
    r = await client.post(f"/api/tickets/{t['ticket_id']}/no-show", headers=h)
    assert r.status_code == 404
    listing = (await client.get("/api/queues", headers=h)).json()
    assert [q["id"] for q in listing] == [mine.queue_id]


async def test_admin_only_queue_management(client, container):
    w = await make_world(container)
    body = {"name": "Canteen", "counters": 3}
    assert (await client.post("/api/queues", json=body, headers=w.staff_headers)).status_code == 403
    r = await client.post("/api/queues", json=body, headers=w.admin_headers)
    assert r.status_code == 201 and len(r.json()["counters"]) == 3
    p = await client.patch(
        f"/api/queues/{w.queue_id}", json={"status": "paused"}, headers=w.admin_headers
    )
    assert p.json()["status"] == "paused"
    bad = await client.patch(
        f"/api/queues/{w.queue_id}", json={"status": "exploded"}, headers=w.admin_headers
    )
    assert bad.status_code == 400


async def test_closed_queue_rejects_call_next_but_paused_still_serves(client, container):
    w = await make_world(container)
    await join(client, w)
    await join(client, w)
    url = f"/api/queues/{w.queue_id}"
    await client.patch(url, json={"status": "paused"}, headers=w.admin_headers)
    assert (await client.post(f"{url}/call-next", headers=w.staff_headers)).status_code == 200
    await client.patch(url, json={"status": "closed"}, headers=w.admin_headers)
    r = await client.post(f"{url}/call-next", headers=w.staff_headers)
    assert r.status_code == 409


async def test_events_are_published_after_commit(client, container):
    w = await make_world(container)
    await join(client, w)
    await client.post(f"/api/queues/{w.queue_id}/call-next", headers=w.staff_headers)
    types = [e.type for e in container.publisher.published]
    assert types == ["joined", "called"]
    versions = [e.version for e in container.publisher.published]
    assert versions == sorted(versions) and len(set(versions)) == 2
