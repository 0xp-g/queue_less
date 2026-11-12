"""The two concurrency-critical operations under real PostgreSQL contention (ADR-0002).

Mirrors the blueprint test: 45 concurrent joins (40 visitors + 5 retries of the same request),
then two counters each pressing "call next" 20 times concurrently.
"""

import asyncio
import hashlib

from sqlalchemy import text

from app.db.models import Queue, Venue
from app.repositories.queue_repo import QueueRepository
from app.repositories.ticket_repo import TicketRepository


async def _make_queue(session_factory, status="open") -> int:
    async with session_factory() as s:
        venue = Venue(name="Campus")
        s.add(venue)
        await s.flush()
        q = Queue(venue_id=venue.id, name="Admissions desk", status=status)
        s.add(q)
        await s.commit()
        return q.id


async def _join(session_factory, qid: int, rid: str):
    async with session_factory() as s:
        repo = TicketRepository(s)
        res = await repo.join_ticket(qid, rid, None, hashlib.sha256(rid.encode()).hexdigest())
        await s.commit()
        return res


async def _call(session_factory, qid: int, counter: int | None = None):
    async with session_factory() as s:
        res = await TicketRepository(s).call_next(qid, counter)
        await s.commit()
        return res


async def test_concurrent_joins_are_unique_and_idempotent(session_factory):
    qid = await _make_queue(session_factory)
    results = await asyncio.gather(
        *[_join(session_factory, qid, f"req-{i % 40}") for i in range(45)]
    )

    created = [r for r in results if r is not None]
    assert len(created) == 40  # the 5 retries did not create tickets
    async with session_factory() as s:
        n, distinct = (
            await s.execute(text("SELECT count(*), count(DISTINCT seq) FROM tickets"))
        ).one()
    assert n == distinct == 40


async def test_two_counters_never_call_the_same_ticket(session_factory):
    qid = await _make_queue(session_factory)
    await asyncio.gather(*[_join(session_factory, qid, f"r{i}") for i in range(40)])

    async def counter():
        got = []
        for _ in range(20):
            r = await _call(session_factory, qid)
            if r:
                got.append(r.seq)
        return got

    c1, c2 = await asyncio.gather(counter(), counter())
    called = c1 + c2
    assert len(called) == 40
    assert len(set(called)) == 40  # zero double calls
    assert await _call(session_factory, qid) is None  # nobody left


async def test_positions_are_computed_and_shift_after_cancel(session_factory):
    qid = await _make_queue(session_factory)
    for i in range(4):
        await _join(session_factory, qid, f"r{i}")
    async with session_factory() as s:
        await s.execute(text("UPDATE tickets SET status = 'cancelled' WHERE seq = 2"))
        await s.commit()
        repo = TicketRepository(s)
        tickets = await repo.list_for_queue(qid, ("waiting",))
        positions = {t.seq: await repo.position(t) for t in tickets}
    assert positions == {1: 1, 3: 2, 4: 3}  # nobody's row was rewritten


async def test_join_rejected_when_queue_not_open(session_factory):
    qid = await _make_queue(session_factory, status="paused")
    assert await _join(session_factory, qid, "x") is None


async def test_compare_and_set_has_exactly_one_winner(session_factory):
    qid = await _make_queue(session_factory)
    joined = await _join(session_factory, qid, "only")
    await _call(session_factory, qid)

    async def attempt(new_status):
        async with session_factory() as s:
            ok = await TicketRepository(s).transition(joined.ticket_id, "called", new_status)
            await s.commit()
            return ok

    results = await asyncio.gather(attempt("served"), attempt("no_show"), attempt("cancelled"))
    assert sorted(results) == [False, False, True]


async def test_version_bumps_on_join(session_factory):
    qid = await _make_queue(session_factory)
    a = await _join(session_factory, qid, "a")
    b = await _join(session_factory, qid, "b")
    assert b.version == a.version + 1
    async with session_factory() as s:
        assert await QueueRepository(s).bump_version(qid) == b.version + 1
