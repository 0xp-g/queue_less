"""FastAPI dependencies (DI): the container, the current staff member, and RBAC."""

from collections.abc import Callable

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.errors import AuthError, Forbidden
from app.db.models import StaffUser

_bearer = HTTPBearer(auto_error=False)


def get_container(request: Request):
    return request.app.state.container


async def get_current_staff(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    container=Depends(get_container),
) -> StaffUser:
    if creds is None:
        raise AuthError("Missing bearer token.")
    return await container.auth.authenticate(creds.credentials)


async def get_optional_staff(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    container=Depends(get_container),
) -> StaffUser | None:
    return await container.auth.authenticate(creds.credentials) if creds else None


def require_role(*roles: str) -> Callable:
    """Dependency factory: declarative RBAC per route, e.g. Depends(require_role("admin"))."""

    async def checker(staff: StaffUser = Depends(get_current_staff)) -> StaffUser:
        if staff.role not in roles:
            raise Forbidden(f"Requires role: {', '.join(roles)}.")
        return staff

    return checker


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"
