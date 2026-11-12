"""Password hashing and staff JWTs (ADR-0009).

JWTs are signed, not encrypted: never put secrets in claims.
"""

from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.core.errors import AuthError

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def create_access_token(
    *, user_id: int, venue_id: int, role: str, secret: str, ttl_minutes: int
) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "venue_id": venue_id,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=ttl_minutes),
    }
    return jwt.encode(claims, secret, algorithm=ALGORITHM)


def decode_access_token(token: str, secret: str) -> dict:
    try:
        return jwt.decode(
            token, secret, algorithms=[ALGORITHM], options={"require": ["exp", "sub"]}
        )
    except jwt.PyJWTError as exc:
        raise AuthError("Invalid or expired token.") from exc
