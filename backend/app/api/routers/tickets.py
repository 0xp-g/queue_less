from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import client_ip, get_container, get_current_staff
from app.api.schemas import JoinIn

router = APIRouter(prefix="/api", tags=["tickets"])


@router.post("/queues/{queue_id}/tickets", status_code=201)
async def join_queue(
    queue_id: int, body: JoinIn, request: Request, response: Response, c=Depends(get_container)
):
    snapshot, created = await c.tickets.join(
        queue_id, body.join_token, body.client_request_id, body.device_id, client_ip(request)
    )
    if not created:
        response.status_code = 200  # idempotent replay of an earlier join
    return snapshot


@router.get("/tickets/{token}")
async def ticket_status(token: str, c=Depends(get_container)):
    return await c.tickets.status(token)


@router.delete("/tickets/{token}")
async def cancel_ticket(token: str, c=Depends(get_container)):
    return await c.tickets.cancel(token)


# --- staff lifecycle actions (ticket id, bearer token) ---------------------------------------
@router.post("/tickets/{ticket_id}/complete")
async def complete(ticket_id: int, staff=Depends(get_current_staff), c=Depends(get_container)):
    return await c.staff.complete(staff, ticket_id)


@router.post("/tickets/{ticket_id}/no-show")
async def no_show(ticket_id: int, staff=Depends(get_current_staff), c=Depends(get_container)):
    return await c.staff.mark_no_show(staff, ticket_id)


@router.post("/tickets/{ticket_id}/cancel")
async def staff_cancel(ticket_id: int, staff=Depends(get_current_staff), c=Depends(get_container)):
    return await c.staff.cancel(staff, ticket_id)
