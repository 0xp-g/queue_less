"""Builds the small read models pushed to visitors and display boards (design B9).

Visitor payload: queue header + the visitor's own ticket (position, ETA). Positions are computed
with one ranked query per queue (ADR-0001), so pushing to N sockets costs one query, not N.
"""

from app.db.models import Ticket
from app.domain.estimator import EtaEstimator
from app.services.unit_of_work import UnitOfWork


class SnapshotService:
    def __init__(self, estimator: EtaEstimator):
        self._estimator = estimator

    @staticmethod
    def service_sec(header: dict) -> float:
        return header["est_service_sec"] or header["default_service_sec"]

    @staticmethod
    def queue_view(header: dict) -> dict:
        return {
            "queue_id": header["id"],
            "queue_name": header["name"],
            "queue_status": header["status"],
            "version": header["version"],
            "now_serving": header["now_serving"],
            "waiting_count": header["waiting"],
            "active_counters": header["active_counters"],
            "est_service_sec": round(SnapshotService.service_sec(header), 1),
        }

    def eta_for(self, header: dict, position: int | None, status: str) -> float | None:
        if status == "called":
            return 0.0
        if status != "waiting" or position is None:
            return None
        return self._estimator.eta(
            position, self.service_sec(header), header["active_counters"], header["busy"]
        )

    def ticket_view(self, header: dict, row: dict) -> dict:
        return {
            **self.queue_view(header),
            "ticket_id": row["id"],
            "seq": row["seq"],
            "status": row["status"],
            "position": row["position"],
            "eta_seconds": self.eta_for(header, row["position"], row["status"]),
            "counter": row["counter"],
        }

    async def for_ticket(self, uow: UnitOfWork, ticket: Ticket) -> dict:
        views = await self.for_tickets(uow, ticket.queue_id, [ticket.id])
        return views[1][ticket.id]

    async def for_tickets(
        self, uow: UnitOfWork, queue_id: int, ticket_ids: list[int]
    ) -> tuple[dict | None, dict[int, dict]]:
        header = await uow.queues.header(queue_id)
        if header is None:
            return None, {}
        rows = await uow.tickets.positions_for(queue_id, ticket_ids)
        return header, {tid: self.ticket_view(header, row) for tid, row in rows.items()}

    async def board(self, uow: UnitOfWork, queue_id: int) -> dict | None:
        header = await uow.queues.header(queue_id)
        if header is None:
            return None
        return {
            **self.queue_view(header),
            "counters": await uow.queues.serving_by_counter(queue_id),
        }
