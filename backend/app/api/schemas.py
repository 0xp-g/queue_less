"""Pydantic request models: validation at the boundary (malformed input -> 400)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class StaffCreateIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    role: Literal["staff", "admin"] = "staff"


class QueueCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    counters: int = Field(default=1, ge=1, le=50)
    default_service_sec: float = Field(default=80, gt=0, le=3600)
    no_show_grace_sec: int = Field(default=120, ge=10, le=3600)
    max_requeues: int = Field(default=1, ge=0, le=5)


class QueueUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    status: Literal["open", "paused", "closed"] | None = None
    default_service_sec: float | None = Field(default=None, gt=0, le=3600)
    no_show_grace_sec: int | None = Field(default=None, ge=10, le=3600)
    max_requeues: int | None = Field(default=None, ge=0, le=5)


class CounterUpdateIn(BaseModel):
    active: bool


class JoinIn(BaseModel):
    join_token: str = Field(min_length=1, max_length=100)
    # Browser-generated UUID: the idempotency key for retried joins.
    client_request_id: str = Field(min_length=8, max_length=64)
    device_id: str | None = Field(default=None, min_length=8, max_length=64)


class CallNextIn(BaseModel):
    counter_id: int | None = None


class CheckInIn(BaseModel):
    """Visitor check-in: ticket token + counter id + nonce from the counter screen.
    Staff check-in sends an empty body with a bearer token instead."""

    token: str | None = None
    counter_id: int | None = None
    nonce: str | None = None
