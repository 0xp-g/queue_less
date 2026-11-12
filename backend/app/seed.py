"""Create a demo venue, admin, staff member and queue; print the tokens the load test needs.

python -m app.seed            # idempotent: reuses the demo venue if it exists
"""

import asyncio
import json
from datetime import date

from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.models import Counter, Queue, StaffUser, Venue
from app.db.session import build_engine, build_session_factory
from app.domain.tokens import JoinTokenService, TokenSigner
from app.services.auth_service import AuthService

ADMIN_EMAIL = "admin@queueless.dev"
STAFF_EMAIL = "staff@queueless.dev"
DEMO_PASSWORD = "queueless-demo"


async def seed(counters: int = 2, default_service_sec: float = 80.0) -> dict:
    settings = get_settings()
    engine = build_engine(settings)
    sessions = build_session_factory(engine)
    async with sessions() as s:
        admin = await s.scalar(select(StaffUser).where(StaffUser.email == ADMIN_EMAIL))
        if admin is None:
            venue = Venue(name="Chennai Institute of Technology - Admissions")
            s.add(venue)
            await s.flush()
            admin = StaffUser(
                venue_id=venue.id,
                email=ADMIN_EMAIL,
                password_hash=hash_password(DEMO_PASSWORD),
                role="admin",
            )
            s.add_all(
                [
                    admin,
                    StaffUser(
                        venue_id=venue.id,
                        email=STAFF_EMAIL,
                        password_hash=hash_password(DEMO_PASSWORD),
                        role="staff",
                    ),
                ]
            )
            queue = Queue(
                venue_id=venue.id, name="Admissions desk", default_service_sec=default_service_sec
            )
            s.add(queue)
            await s.flush()
            s.add_all(
                [Counter(queue_id=queue.id, label=f"Counter {i + 1}") for i in range(counters)]
            )
            await s.commit()
        queue = await s.scalar(
            select(Queue).where(Queue.venue_id == admin.venue_id).order_by(Queue.id)
        )
    await engine.dispose()

    join_token = JoinTokenService(TokenSigner(settings.token_secret)).issue(queue.id, date.today())
    staff_token = AuthService(sessions, settings).issue_token(admin)
    return {
        "admin_email": ADMIN_EMAIL,
        "staff_email": STAFF_EMAIL,
        "password": DEMO_PASSWORD,
        "queue_id": queue.id,
        "join_token": join_token,
        "join_url": f"{settings.public_base_url}/join/{queue.id}?t={join_token}",
        "board_url": f"{settings.public_base_url}/board/{queue.id}",
        "staff_token": staff_token,
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(seed()), indent=2))
