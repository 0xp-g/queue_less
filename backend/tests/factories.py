"""Test data builders."""

import uuid
from dataclasses import dataclass
from datetime import date

from app.core.security import hash_password
from app.db.models import Counter, Queue, StaffUser, Venue
from app.domain.tokens import JoinTokenService, TokenSigner

PASSWORD = "correct-horse-battery"


@dataclass
class World:
    venue_id: int
    queue_id: int
    counter_ids: list[int]
    admin: StaffUser
    staff: StaffUser
    admin_headers: dict
    staff_headers: dict
    join_token: str


async def make_world(container, name="Campus", counters=2, status="open", **queue_kw) -> World:
    async with container.session_factory() as s:
        venue = Venue(name=name)
        s.add(venue)
        await s.flush()
        slug = uuid.uuid4().hex[:8]
        admin = StaffUser(
            venue_id=venue.id,
            email=f"admin-{slug}@example.com",
            password_hash=hash_password(PASSWORD),
            role="admin",
        )
        staff = StaffUser(
            venue_id=venue.id,
            email=f"staff-{slug}@example.com",
            password_hash=hash_password(PASSWORD),
            role="staff",
        )
        queue = Queue(venue_id=venue.id, name=f"{name} desk", status=status, **queue_kw)
        s.add_all([admin, staff, queue])
        await s.flush()
        cs = [Counter(queue_id=queue.id, label=f"C{i + 1}") for i in range(counters)]
        s.add_all(cs)
        await s.commit()
        ids = [c.id for c in cs]
    auth = container.auth
    join = JoinTokenService(TokenSigner(container.settings.token_secret))
    return World(
        venue_id=venue.id,
        queue_id=queue.id,
        counter_ids=ids,
        admin=admin,
        staff=staff,
        admin_headers={"Authorization": f"Bearer {auth.issue_token(admin)}"},
        staff_headers={"Authorization": f"Bearer {auth.issue_token(staff)}"},
        join_token=join.issue(queue.id, date.today()),
    )


async def join(client, world: World, rid: str | None = None, device: str | None = None):
    body = {"join_token": world.join_token, "client_request_id": rid or uuid.uuid4().hex}
    if device:
        body["device_id"] = device
    return await client.post(f"/api/queues/{world.queue_id}/tickets", json=body)
