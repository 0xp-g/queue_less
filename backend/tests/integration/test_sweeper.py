import asyncio

from sqlalchemy import text

from app.workers.no_show_sweeper import NoShowSweeper
from tests.factories import join, make_world


async def test_sweeper_marks_overdue_called_tickets_once(client, container):
    w = await make_world(container, no_show_grace_sec=60)
    t1, t2 = (await join(client, w)).json(), (await join(client, w)).json()
    for _ in range(2):
        await client.post(f"/api/queues/{w.queue_id}/call-next", headers=w.staff_headers)
    async with container.session_factory() as s:  # only t1 is overdue
        await s.execute(
            text("UPDATE tickets SET called_at = now() - interval '5 minutes' WHERE id = :i"),
            {"i": t1["ticket_id"]},
        )
        await s.commit()

    sweeper = NoShowSweeper(container.uow, 10)
    # Several "instances" sweeping at once: exactly one marks the ticket.
    counts = await asyncio.gather(*[sweeper.sweep_once() for _ in range(3)])
    assert sum(counts) == 1
    assert (await client.get(f"/api/tickets/{t1['token']}")).json()["status"] == "no_show"
    assert (await client.get(f"/api/tickets/{t2['token']}")).json()["status"] == "called"


async def test_requeue_once_goes_to_back(client, container):
    w = await make_world(container, max_requeues=1)
    a, b = (await join(client, w)).json(), (await join(client, w)).json()
    await client.post(f"/api/queues/{w.queue_id}/call-next", headers=w.staff_headers)
    await client.post(f"/api/tickets/{a['ticket_id']}/no-show", headers=w.staff_headers)
    r = await client.post(f"/api/tickets/{a['ticket_id']}/requeue", headers=w.staff_headers)
    assert r.status_code == 200 and r.json()["seq"] > b["seq"]
    status = (await client.get(f"/api/tickets/{a['token']}")).json()
    assert status["status"] == "waiting" and status["position"] == 2

    await client.post(f"/api/queues/{w.queue_id}/call-next", headers=w.staff_headers)
    await client.post(f"/api/queues/{w.queue_id}/call-next", headers=w.staff_headers)
    await client.post(f"/api/tickets/{a['ticket_id']}/no-show", headers=w.staff_headers)
    again = await client.post(f"/api/tickets/{a['ticket_id']}/requeue", headers=w.staff_headers)
    assert again.status_code == 409 and again.json()["error"]["code"] == "REQUEUE_LIMIT"
