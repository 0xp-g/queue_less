"""Staff authentication and user management (ADR-0009)."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings
from app.core.errors import AuthError, Conflict, Forbidden
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.db.models import StaffUser

# Verified against when the email is unknown, so response time does not reveal which emails exist.
_DUMMY_HASH = hash_password("timing-equalizer")


class AuthService:
    def __init__(self, session_factory: async_sessionmaker, settings: Settings):
        self._sessions = session_factory
        self._settings = settings

    async def login(self, email: str, password: str) -> str:
        async with self._sessions() as s:
            user = await s.scalar(select(StaffUser).where(StaffUser.email == email.lower()))
        if user is None:
            verify_password(password, _DUMMY_HASH)
            raise AuthError("Invalid email or password.")
        if not verify_password(password, user.password_hash) or not user.is_active:
            raise AuthError("Invalid email or password.")
        return self.issue_token(user)

    def issue_token(self, user: StaffUser) -> str:
        return create_access_token(
            user_id=user.id,
            venue_id=user.venue_id,
            role=user.role,
            secret=self._settings.jwt_secret,
            ttl_minutes=self._settings.jwt_ttl_minutes,
        )

    async def authenticate(self, token: str) -> StaffUser:
        """Decode the JWT, then RELOAD the user: deactivation and role changes apply now,
        not when the token expires."""
        claims = decode_access_token(token, self._settings.jwt_secret)
        async with self._sessions() as s:
            user = await s.get(StaffUser, int(claims["sub"]))
        if user is None or not user.is_active:
            raise AuthError("Account is disabled.")
        return user

    async def create_staff(
        self, admin: StaffUser, email: str, password: str, role: str
    ) -> StaffUser:
        if admin.role != "admin":
            raise Forbidden("Only admins can add staff.")
        user = StaffUser(
            venue_id=admin.venue_id,  # always the admin's venue, never from the request
            email=email.lower(),
            password_hash=hash_password(password),
            role=role,
        )
        async with self._sessions() as s:
            s.add(user)
            try:
                await s.commit()
            except IntegrityError as exc:
                raise Conflict(
                    "A user with this email already exists.", code="EMAIL_TAKEN"
                ) from exc
        return user
