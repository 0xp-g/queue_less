from fastapi import APIRouter, Depends

from app.api.deps import get_container, get_current_staff, require_role
from app.api.schemas import LoginIn, StaffCreateIn, TokenOut
from app.db.models import StaffUser

router = APIRouter(prefix="/api", tags=["auth"])


def staff_dict(u: StaffUser) -> dict:
    return {"id": u.id, "email": u.email, "role": u.role, "venue_id": u.venue_id}


@router.post("/auth/login", response_model=TokenOut)
async def login(body: LoginIn, c=Depends(get_container)):
    return TokenOut(access_token=await c.auth.login(body.email, body.password))


@router.get("/me")
async def me(staff: StaffUser = Depends(get_current_staff)):
    return staff_dict(staff)


@router.post("/staff", status_code=201)
async def create_staff(
    body: StaffCreateIn, admin=Depends(require_role("admin")), c=Depends(get_container)
):
    return staff_dict(await c.auth.create_staff(admin, body.email, body.password, body.role))
