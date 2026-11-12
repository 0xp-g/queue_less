"""ORM models. Schema rationale: docs/DESIGN.md section B3 and ADR-0001.

Positions are deliberately NOT a column: they are computed from `seq` (ADR-0001).
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

TICKET_STATUSES = ("waiting", "called", "serving", "served", "cancelled", "no_show")
QUEUE_STATUSES = ("open", "paused", "closed")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Venue(Base):
    __tablename__ = "venues"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StaffUser(Base):
    __tablename__ = "staff_users"
    __table_args__ = (CheckConstraint("role IN ('staff', 'admin')", name="ck_staff_role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(10), default="staff")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Queue(Base):
    __tablename__ = "queues"
    __table_args__ = (CheckConstraint(_in("status", QUEUE_STATUSES), name="ck_queue_status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(10), default="open", server_default="open")
    # Per-queue ticket counter. Incremented under the queue row lock (ADR-0002).
    next_seq: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Per-queue event version, bumped in the same transaction as every change (ADR-0005).
    version: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    default_service_sec: Mapped[float] = mapped_column(Float, default=80.0, server_default="80")
    # Rolling estimate; NULL until the first observed service (cold start uses the default).
    est_service_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    no_show_grace_sec: Mapped[int] = mapped_column(Integer, default=120, server_default="120")
    max_requeues: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Counter(Base):
    __tablename__ = "counters"

    id: Mapped[int] = mapped_column(primary_key=True)
    queue_id: Mapped[int] = mapped_column(ForeignKey("queues.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(50))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))


class Ticket(Base):
    __tablename__ = "tickets"
    __table_args__ = (
        CheckConstraint(_in("status", TICKET_STATUSES), name="ck_ticket_status"),
        UniqueConstraint("queue_id", "seq", name="uq_ticket_queue_seq"),
        # Idempotency key: a retried join never creates a second ticket.
        UniqueConstraint("queue_id", "client_request_id", name="uq_ticket_queue_request"),
        # Serves position counting and call-next ordering.
        Index(
            "ix_tickets_waiting",
            "queue_id",
            "seq",
            postgresql_where=text("status = 'waiting'"),
        ),
        # One active ticket per device per queue (abuse control, ADR-0004).
        Index(
            "uq_ticket_active_device",
            "queue_id",
            "device_id",
            unique=True,
            postgresql_where=text(
                "device_id IS NOT NULL AND status IN ('waiting', 'called', 'serving')"
            ),
        ),
        # The no-show sweeper scans called tickets.
        Index("ix_tickets_called", "called_at", postgresql_where=text("status = 'called'")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    queue_id: Mapped[int] = mapped_column(ForeignKey("queues.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10), default="waiting", server_default="waiting")
    # Only the SHA-256 of the visitor's token is stored (ADR-0004).
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    client_request_id: Mapped[str] = mapped_column(String(64))
    device_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    counter_id: Mapped[int | None] = mapped_column(
        ForeignKey("counters.id", ondelete="SET NULL"), nullable=True
    )
    requeue_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # ETA shown at join, kept so ETA error can be measured honestly afterwards (ADR-0007).
    eta_at_join_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    called_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    served_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class QueueEvent(Base):
    """Append-only audit trail; also the data source for stats and for replaying α choices."""

    __tablename__ = "queue_events"
    __table_args__ = (Index("ix_queue_events_queue_at", "queue_id", "at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    queue_id: Mapped[int] = mapped_column(ForeignKey("queues.id", ondelete="CASCADE"))
    ticket_id: Mapped[int | None] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), nullable=True
    )
    type: Mapped[str] = mapped_column(String(30))
    actor: Mapped[str] = mapped_column(String(100))
    version: Mapped[int] = mapped_column(BigInteger)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
