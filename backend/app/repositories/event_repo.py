from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import QueueEvent


class EventRepository:
    """Append-only queue_events writer (audit trail + stats source)."""

    def __init__(self, session: AsyncSession):
        self._s = session

    def append(
        self,
        queue_id: int,
        type_: str,
        version: int,
        actor: str,
        ticket_id: int | None = None,
        payload: dict | None = None,
    ) -> None:
        self._s.add(
            QueueEvent(
                queue_id=queue_id,
                ticket_id=ticket_id,
                type=type_,
                version=version,
                actor=actor,
                payload=payload or {},
            )
        )
