"""FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .database import database, metadata
from .routers import admin, ai, auth, orders, public, scheduling, user

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("putzfee")


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: D401
    settings = get_settings()
    await database.connect()
    log.info(
        "PUTZFEE server started in %s mode (timezone=%s)",
        settings.APP_ENV,
        settings.SERVER_TIMEZONE,
    )

    if settings.ENABLE_SCHEMA_CREATE and not settings.is_production:
        # Development convenience only — production must use Alembic.
        from sqlalchemy import create_engine

        from .database import SYNC_DATABASE_URL

        engine = create_engine(SYNC_DATABASE_URL)
        metadata.create_all(engine)
        engine.dispose()
        log.warning("Schema created from metadata (ENABLE_SCHEMA_CREATE=1)")
    try:
        yield
    finally:
        await database.disconnect()
        log.info("PUTZFEE server stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="PUTZFEE API",
        version="1.0.0",
        description="Cleaning & car-wash booking API.",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount media under the configured prefix.
    media_dir = Path(settings.MEDIA_DIR)
    media_dir.mkdir(parents=True, exist_ok=True)
    app.mount(
        settings.MEDIA_URL_PREFIX,
        StaticFiles(directory=str(media_dir)),
        name="media",
    )

    app.include_router(auth.router)
    app.include_router(user.router)
    app.include_router(orders.router)
    app.include_router(scheduling.router)
    app.include_router(public.router)
    app.include_router(ai.router)
    app.include_router(admin.router)

    @app.get("/health", tags=["meta"])
    async def health() -> dict:
        return {"status": "ok", "env": settings.APP_ENV}

    return app


app = create_app()
 
