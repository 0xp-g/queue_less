"""FastAPI application factory."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routers import auth, queues, tickets
from app.container import build_container
from app.core.config import Settings, get_settings
from app.core.errors import DomainError

log = logging.getLogger("queueless")


def error_body(code: str, message: str, details=None) -> dict:
    body = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return body


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        container = build_container(settings)
        app.state.container = container
        try:
            yield
        finally:
            await container.close()

    app = FastAPI(title="QueueLess", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError):
        return JSONResponse(error_body(exc.code, exc.message), status_code=exc.http_status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        details = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
        return JSONResponse(
            error_body("VALIDATION_ERROR", "Request body is invalid.", details), status_code=400
        )

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    for module in (auth, queues, tickets):
        app.include_router(module.router)
    return app
