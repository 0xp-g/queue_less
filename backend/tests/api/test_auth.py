from sqlalchemy import update

from app.db.models import StaffUser
from tests.factories import PASSWORD, make_world


async def test_login_success_and_me(client, container):
    w = await make_world(container)
    r = await client.post("/api/auth/login", json={"email": w.admin.email, "password": PASSWORD})
    assert r.status_code == 200
    me = await client.get(
        "/api/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}
    )
    assert me.json()["role"] == "admin"


async def test_login_bad_password_is_401(client, container):
    w = await make_world(container)
    r = await client.post("/api/auth/login", json={"email": w.admin.email, "password": "nope"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_login_malformed_is_400(client):
    r = await client.post("/api/auth/login", json={"email": "not-an-email"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_missing_and_garbage_tokens_are_401(client):
    assert (await client.get("/api/me")).status_code == 401
    r = await client.get("/api/me", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401


async def test_deactivated_user_is_rejected_immediately(client, container):
    """The JWT is still valid, but the user is reloaded on every request (ADR-0009)."""
    w = await make_world(container)
    async with container.session_factory() as s:
        await s.execute(update(StaffUser).where(StaffUser.id == w.staff.id).values(is_active=False))
        await s.commit()
    assert (await client.get("/api/me", headers=w.staff_headers)).status_code == 401


async def test_only_admin_creates_staff_and_venue_comes_from_principal(client, container):
    w = await make_world(container)
    body = {"email": "new@example.com", "password": "long-enough-pw", "role": "staff"}
    assert (await client.post("/api/staff", json=body, headers=w.staff_headers)).status_code == 403
    r = await client.post("/api/staff", json=body, headers=w.admin_headers)
    assert r.status_code == 201 and r.json()["venue_id"] == w.venue_id
    dup = await client.post("/api/staff", json=body, headers=w.admin_headers)
    assert dup.status_code == 409
