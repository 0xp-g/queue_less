from fastapi import APIRouter, Depends, Query

from app.api.deps import get_container, get_current_staff, require_role
from app.api.schemas import CallNextIn, CounterUpdateIn, QueueCreateIn, QueueUpdateIn

router = APIRouter(prefix="/api", tags=["queues"])


@router.post("/queues", status_code=201)
async def create_queue(
    body: QueueCreateIn, admin=Depends(require_role("admin")), c=Depends(get_container)
):
    return await c.queues.create(admin, **body.model_dump())


@router.get("/queues")
async def list_queues(staff=Depends(get_current_staff), c=Depends(get_container)):
    return await c.queues.list(staff)


@router.get("/queues/{queue_id}")
async def get_queue(queue_id: int, staff=Depends(get_current_staff), c=Depends(get_container)):
    return await c.queues.get(staff, queue_id)


@router.patch("/queues/{queue_id}")
async def update_queue(
    queue_id: int,
    body: QueueUpdateIn,
    admin=Depends(require_role("admin")),
    c=Depends(get_container),
):
    return await c.queues.update(admin, queue_id, body.model_dump(exclude_none=True))


@router.patch("/counters/{counter_id}")
async def update_counter(
    counter_id: int,
    body: CounterUpdateIn,
    admin=Depends(require_role("admin")),
    c=Depends(get_container),
):
    return await c.queues.set_counter_active(admin, counter_id, body.active)


@router.get("/queues/{queue_id}/public")
async def public_queue(queue_id: int, c=Depends(get_container)):
    """No auth: the join page and display board show name, status and now serving."""
    return await c.queues.public(queue_id)


@router.get("/queues/{queue_id}/tickets")
async def list_tickets(
    queue_id: int,
    status: list[str] = Query(default=["waiting", "called", "serving"]),
    staff=Depends(get_current_staff),
    c=Depends(get_container),
):
    return await c.staff.list_tickets(staff, queue_id, tuple(status))


@router.post("/queues/{queue_id}/call-next")
async def call_next(
    queue_id: int,
    body: CallNextIn | None = None,
    staff=Depends(get_current_staff),
    c=Depends(get_container),
):
    return await c.staff.call_next(staff, queue_id, body.counter_id if body else None)
