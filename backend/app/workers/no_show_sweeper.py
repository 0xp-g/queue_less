"""Periodic no-show sweep (ADR-0008).

A single idempotent UPDATE marks called tickets whose grace period expired. Running it on every
API instance is safe: the second run in the same instant matches zero rows.
"""

import asyncio
import logging
from collections import Counter

from app.domain.events import QueueEventType
from app.services.unit_of_work import UowFactory

log = logging.getLogger(__name__)


class NoShowSweeper:
    def __init__(self, uow: UowFactory, interval_sec: float):
        self._uow = uow
        self._interval = interval_sec

    async def sweep_once(self) -> int:
        async with self._uow() as uow:
            swept = await uow.tickets.sweep_no_shows()
            for ticket_id, queue_id in swept:
                await uow.emit(
                    queue_id, QueueEventType.NO_SHOW, actor="system:sweeper", ticket_id=ticket_id
                )
            await uow.commit()
        if swept:
            log.info("marked no-show: %s", dict(Counter(q for _, q in swept)))
        return len(swept)

    async def run(self) -> None:
        while True:
            try:
                await self.sweep_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("no-show sweep failed; will retry")
            await asyncio.sleep(self._interval)
