import time

from app.domain.tokens import CounterNonceService, TokenSigner
from tests.factories import join, make_world


async def test_join_qr_is_admin_only_and_valid(client, container):
    w = await make_world(container)
    url = f"/api/queues/{w.queue_id}/qr"
    assert (await client.get(url, headers=w.staff_headers)).status_code == 403
    qr = (await client.get(url, headers=w.admin_headers)).json()
    assert qr["join_token"] == w.join_token and qr["png_base64"]


async def test_visitor_check_in_requires_fresh_counter_nonce(client, container):
    w = await make_world(container)
    t = (await join(client, w)).json()
    cid = w.counter_ids[0]
    await client.post(
        f"/api/queues/{w.queue_id}/call-next", json={"counter_id": cid}, headers=w.staff_headers
    )
    url = f"/api/tickets/{t['ticket_id']}/check-in"
    nonces = CounterNonceService(TokenSigner(container.settings.token_secret), 30)
    stale = nonces.issue(cid, time.time() - 120)
    r = await client.post(url, json={"token": t["token"], "counter_id": cid, "nonce": stale})
    assert r.status_code == 403
    wrong = nonces.issue(w.counter_ids[1], time.time())
    r = await client.post(
        url, json={"token": t["token"], "counter_id": w.counter_ids[1], "nonce": wrong}
    )
    assert r.status_code == 403  # called to counter 1, scanned counter 2
    fresh = (await client.get(f"/api/counters/{cid}/nonce", headers=w.staff_headers)).json()
    r = await client.post(
        url, json={"token": t["token"], "counter_id": cid, "nonce": fresh["nonce"]}
    )
    assert r.status_code == 200 and r.json()["status"] == "serving"


async def test_check_in_without_credentials_is_403(client, container):
    w = await make_world(container)
    t = (await join(client, w)).json()
    r = await client.post(f"/api/tickets/{t['ticket_id']}/check-in", json={})
    assert r.status_code == 403
