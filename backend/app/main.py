"""FastAPI app: health check and DB initialization."""
from __future__ import annotations

import logging
import os

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import config
from app.auth import verify_api_key
from app.database import check_db, engine
from app.models import Base
from app.routers import (
    chapters as chapters_router,
)
from app.routers import (
    compare,
    settings,
    steps,
    tasks,
    upload,
)
from app.routers import (
    export as export_router,
)
from app.routers import (
    framework as framework_router,
)
from app.routers import (
    knowledge_base as kb_router,
)
from app.routers import (
    prompt_profiles as prompt_profiles_router,
)
from app.routers import (
    review as review_router,
)

logger = logging.getLogger(__name__)
app = FastAPI(
    title="BIM 标书生成 API",
    version="0.1.0",
    dependencies=[Depends(verify_api_key)],
)
app.include_router(tasks.router)
app.include_router(upload.router)
app.include_router(steps.router)
app.include_router(framework_router.router)
app.include_router(chapters_router.router)
app.include_router(review_router.router)
app.include_router(export_router.router)
app.include_router(compare.router, prefix="/api")
app.include_router(settings.router, prefix="/api/settings")
app.include_router(prompt_profiles_router.router)
app.include_router(kb_router.router)

_cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").strip().split(",")
_cors_allow_lan_vite = os.getenv("CORS_ALLOW_LAN_VITE", "1").strip().lower() not in ("0", "false", "no", "")
_LAN_VITE_ORIGIN_REGEX = (
    r"^http://("
    r"localhost|127\.0\.0\.1|"
    r"192\.168\.\d{1,3}\.\d{1,3}|"
    r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
    r"172\.(1[6-9]|2[0-9]|3[0-1])\.\d{1,3}\.\d{1,3}"
    r"):5173$"
)
_CORS_ALLOW_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
_CORS_ALLOW_HEADERS = [
    "Content-Type",
    "Authorization",
    "X-API-Key",
    "X-Debug-User-Id",
    "X-Debug-Tenant-Id",
    "Accept",
    "Accept-Language",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _cors_origins if o.strip()],
    allow_origin_regex=_LAN_VITE_ORIGIN_REGEX if _cors_allow_lan_vite else None,
    allow_credentials=True,
    allow_methods=_CORS_ALLOW_METHODS,
    allow_headers=_CORS_ALLOW_HEADERS,
)


@app.on_event("startup")
async def startup():
    """Test DB connection and create tables if not exist."""
    logger.info("Auth mode: %s", config.AUTH_MODE)
    if not (config.ADMIN_API_KEY or "").strip():
        logger.warning(
            "ADMIN_API_KEY is not set: HTTP API authentication is disabled. "
            "Set ADMIN_API_KEY in .env for production."
        )
    try:
        check_db()
        logger.info("Database connection OK")
    except Exception as e:
        logger.warning("Database connection check failed: %s", e)

    import app.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    logger.info("Tables created or already exist")


@app.get("/health")
def health():
    """Health check: returns status ok."""
    return {"status": "ok"}
