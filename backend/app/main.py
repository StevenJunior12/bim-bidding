"""FastAPI app: health check and optional DB check on startup."""
import logging
import os

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

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
    review as review_router,
)
from app.routers import prompt_profiles as prompt_profiles_router
from app.routers import knowledge_base as kb_router

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

# CORS: allow frontend dev server (localhost) + optional LAN Vite (same port 5173)
_cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").strip().split(",")
_cors_allow_lan_vite = os.getenv("CORS_ALLOW_LAN_VITE", "1").strip().lower() not in ("0", "false", "no", "")
# 内网用 IP 打开 Vite（如 http://192.168.2.14:5173）时与 API 不同源，需放行对应 Origin
_LAN_VITE_ORIGIN_REGEX = (
    r"^http://("
    r"localhost|127\.0\.0\.1|"
    r"192\.168\.\d{1,3}\.\d{1,3}|"
    r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
    r"172\.(1[6-9]|2[0-9]|3[0-1])\.\d{1,3}\.\d{1,3}"
    r"):5173$"
)
# SEC-03: 显式 methods/headers，避免通配符与 credentials 组合过宽
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
    # Create tables (tasks, task_steps) if not exist
    import app.models  # noqa: F401 - register models with Base.metadata

    # pgvector extension must be created BEFORE tables that use VECTOR type
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
        logger.info("pgvector extension ensured")
    except Exception as e:
        logger.warning("Could not create pgvector extension: %s", e)

    Base.metadata.create_all(bind=engine)
    logger.info("Tables created or already exist")
    # Add output_snapshot_before_regenerate to task_steps if missing (6.1 optional)
    try:
        with engine.connect() as conn:
            conn.execute(text(
                "ALTER TABLE task_steps ADD COLUMN output_snapshot_before_regenerate TEXT"
            ))
            conn.commit()
        logger.info("Added column output_snapshot_before_regenerate to task_steps")
    except Exception as e:
        if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
            logger.debug("Column output_snapshot_before_regenerate already exists")
        else:
            logger.warning("Could not add output_snapshot_before_regenerate: %s", e)

    # Add name to tasks if missing (task naming)
    try:
        with engine.connect() as conn:
            conn.execute(text(
                "ALTER TABLE tasks ADD COLUMN name VARCHAR(255)"
            ))
            conn.commit()
        logger.info("Added column name to tasks")
    except Exception as e:
        if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
            logger.debug("Column name already exists")
        else:
            logger.warning("Could not add name to tasks: %s", e)

    # Add celery_task_id to task_steps if missing (for one-click cancel revoke)
    try:
        with engine.connect() as conn:
            conn.execute(text(
                "ALTER TABLE task_steps ADD COLUMN celery_task_id VARCHAR(255)"
            ))
            conn.commit()
        logger.info("Added column celery_task_id to task_steps")
    except Exception as e:
        if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
            logger.debug("Column celery_task_id already exists")
        else:
            logger.warning("Could not add celery_task_id: %s", e)

    # Add composite index on (task_id, step_key) for task_steps — highest-frequency query path
    try:
        with engine.connect() as conn:
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_task_steps_task_id_step_key"
                " ON task_steps (task_id, step_key)"
            ))
            conn.commit()
        logger.info("Index ix_task_steps_task_id_step_key ensured on task_steps")
    except Exception as e:
        logger.warning("Could not create index ix_task_steps_task_id_step_key: %s", e)

    # Add profile_id to tasks (PromptProfile binding, Phase B)
    try:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN profile_id INTEGER"))
            conn.commit()
        logger.info("Added column profile_id to tasks")
    except Exception as e:
        err = str(e).lower()
        if "duplicate" in err or "already exists" in err or "exists" in err:
            logger.debug("Column profile_id already exists on tasks")
        else:
            logger.warning("Could not add profile_id to tasks: %s", e)

    # Add tenant/user scope to tasks
    try:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN tenant_id VARCHAR(64)"))
            conn.commit()
        logger.info("Added column tenant_id to tasks")
    except Exception as e:
        err = str(e).lower()
        if "duplicate" in err or "already exists" in err or "exists" in err:
            logger.debug("Column tenant_id already exists on tasks")
        else:
            logger.warning("Could not add tenant_id to tasks: %s", e)
    try:
        with engine.connect() as conn:
            conn.execute(
                text(
                    "UPDATE tasks SET tenant_id = :tenant_id WHERE tenant_id IS NULL OR TRIM(tenant_id) = ''"
                ),
                {"tenant_id": config.AUTH_DEFAULT_TENANT_ID},
            )
            conn.commit()
        logger.info("Backfilled tasks.tenant_id where null")
    except Exception as e:
        logger.warning("Could not backfill tasks.tenant_id: %s", e)
    try:
        with engine.connect() as conn:
            conn.execute(
                text(
                    "UPDATE tasks SET user_id = :user_id WHERE user_id IS NULL OR TRIM(user_id) = ''"
                ),
                {"user_id": config.AUTH_DEFAULT_USER_ID},
            )
            conn.commit()
        logger.info("Backfilled tasks.user_id where null")
    except Exception as e:
        logger.warning("Could not backfill tasks.user_id: %s", e)
    try:
        with engine.connect() as conn:
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_tasks_tenant_user_created_at "
                    "ON tasks (tenant_id, user_id, created_at)"
                )
            )
            conn.commit()
        logger.info("Index ix_tasks_tenant_user_created_at ensured")
    except Exception as e:
        logger.warning("Could not create ix_tasks_tenant_user_created_at: %s", e)

    # Add discipline to prompt_profiles (semantic profile specialty)
    try:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE prompt_profiles ADD COLUMN discipline VARCHAR(32)"))
            conn.commit()
        logger.info("Added column discipline to prompt_profiles")
    except Exception as e:
        err = str(e).lower()
        if "duplicate" in err or "already exists" in err or "exists" in err:
            logger.debug("Column discipline already exists on prompt_profiles")
        else:
            logger.warning("Could not add discipline to prompt_profiles: %s", e)
    try:
        with engine.connect() as conn:
            conn.execute(
                text(
                    "UPDATE prompt_profiles SET discipline = '建筑' "
                    "WHERE discipline IS NULL OR TRIM(discipline) = ''"
                )
            )
            conn.commit()
        logger.info("Backfilled prompt_profiles.discipline where null")
    except Exception as e:
        logger.warning("Could not backfill prompt_profiles.discipline: %s", e)
    try:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE prompt_profiles ADD COLUMN tenant_id VARCHAR(64)"))
            conn.commit()
        logger.info("Added column tenant_id to prompt_profiles")
    except Exception as e:
        err = str(e).lower()
        if "duplicate" in err or "already exists" in err or "exists" in err:
            logger.debug("Column tenant_id already exists on prompt_profiles")
        else:
            logger.warning("Could not add tenant_id to prompt_profiles: %s", e)
    try:
        with engine.connect() as conn:
            conn.execute(
                text(
                    "UPDATE prompt_profiles SET tenant_id = :tenant_id "
                    "WHERE is_builtin = FALSE AND (tenant_id IS NULL OR TRIM(tenant_id) = '')"
                ),
                {"tenant_id": config.AUTH_DEFAULT_TENANT_ID},
            )
            conn.commit()
        logger.info("Backfilled prompt_profiles.tenant_id where null")
    except Exception as e:
        logger.warning("Could not backfill prompt_profiles.tenant_id: %s", e)
    try:
        with engine.connect() as conn:
            conn.execute(
                text(
                    "UPDATE prompt_profiles SET user_id = :user_id "
                    "WHERE is_builtin = FALSE AND (user_id IS NULL OR TRIM(user_id) = '')"
                ),
                {"user_id": config.AUTH_DEFAULT_USER_ID},
            )
            conn.commit()
        logger.info("Backfilled prompt_profiles.user_id where null")
    except Exception as e:
        logger.warning("Could not backfill prompt_profiles.user_id: %s", e)
    try:
        with engine.connect() as conn:
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_prompt_profiles_tenant_user_updated_at "
                    "ON prompt_profiles (tenant_id, user_id, updated_at)"
                )
            )
            conn.commit()
        logger.info("Index ix_prompt_profiles_tenant_user_updated_at ensured")
    except Exception as e:
        logger.warning("Could not create ix_prompt_profiles_tenant_user_updated_at: %s", e)
    try:
        with engine.connect() as conn:
            conn.execute(
                text(
                    "ALTER TABLE prompt_profiles "
                    "DROP CONSTRAINT IF EXISTS prompt_profiles_slug_key"
                )
            )
            conn.execute(text("DROP INDEX IF EXISTS prompt_profiles_slug_key"))
            conn.commit()
        logger.info("Dropped legacy global unique constraint/index on prompt_profiles.slug")
    except Exception as e:
        logger.debug("Could not drop legacy prompt_profiles.slug unique constraint/index: %s", e)
    try:
        with engine.connect() as conn:
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_prompt_profiles_tenant_user_slug "
                    "ON prompt_profiles (tenant_id, user_id, slug) "
                    "WHERE slug IS NOT NULL"
                )
            )
            conn.commit()
        logger.info("Unique index uq_prompt_profiles_tenant_user_slug ensured")
    except Exception as e:
        logger.warning("Could not ensure uq_prompt_profiles_tenant_user_slug: %s", e)

    # Scope migration: llm_settings
    try:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE llm_settings ADD COLUMN tenant_id VARCHAR(64)"))
            conn.commit()
        logger.info("Added column tenant_id to llm_settings")
    except Exception as e:
        err = str(e).lower()
        if "duplicate" in err or "already exists" in err or "exists" in err:
            logger.debug("Column tenant_id already exists on llm_settings")
        else:
            logger.warning("Could not add tenant_id to llm_settings: %s", e)
    try:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE llm_settings ADD COLUMN user_id VARCHAR(64)"))
            conn.commit()
        logger.info("Added column user_id to llm_settings")
    except Exception as e:
        err = str(e).lower()
        if "duplicate" in err or "already exists" in err or "exists" in err:
            logger.debug("Column user_id already exists on llm_settings")
        else:
            logger.warning("Could not add user_id to llm_settings: %s", e)
    try:
        with engine.connect() as conn:
            conn.execute(
                text(
                    "UPDATE llm_settings SET tenant_id = :tenant_id "
                    "WHERE tenant_id IS NULL OR TRIM(tenant_id) = ''"
                ),
                {"tenant_id": config.AUTH_DEFAULT_TENANT_ID},
            )
            conn.execute(
                text(
                    "UPDATE llm_settings SET user_id = :user_id "
                    "WHERE user_id IS NULL OR TRIM(user_id) = ''"
                ),
                {"user_id": config.AUTH_DEFAULT_USER_ID},
            )
            conn.commit()
        logger.info("Backfilled llm_settings tenant/user where null")
    except Exception as e:
        logger.warning("Could not backfill llm_settings tenant/user: %s", e)
    try:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE llm_settings ADD COLUMN id BIGSERIAL"))
            conn.commit()
        logger.info("Added column id to llm_settings")
    except Exception as e:
        err = str(e).lower()
        if "duplicate" in err or "already exists" in err or "exists" in err:
            logger.debug("Column id already exists on llm_settings")
        else:
            logger.warning("Could not add id to llm_settings: %s", e)
    try:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE llm_settings DROP CONSTRAINT llm_settings_pkey"))
            conn.execute(text("ALTER TABLE llm_settings ADD CONSTRAINT llm_settings_pkey PRIMARY KEY (id)"))
            conn.commit()
        logger.info("Updated llm_settings primary key to id")
    except Exception as e:
        logger.debug("llm_settings primary key migration skipped: %s", e)
    try:
        with engine.connect() as conn:
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_llm_settings_tenant_user_provider "
                    "ON llm_settings (tenant_id, user_id, provider)"
                )
            )
            conn.commit()
        logger.info("Unique index uq_llm_settings_tenant_user_provider ensured")
    except Exception as e:
        logger.warning("Could not ensure uq_llm_settings_tenant_user_provider: %s", e)

    # Scope migration: kb_settings / export_format_settings
    for table_name in ("kb_settings", "export_format_settings"):
        for col in ("tenant_id", "user_id"):
            try:
                with engine.connect() as conn:
                    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col} VARCHAR(64)"))
                    conn.commit()
                logger.info("Added column %s to %s", col, table_name)
            except Exception as e:
                err = str(e).lower()
                if "duplicate" in err or "already exists" in err or "exists" in err:
                    logger.debug("Column %s already exists on %s", col, table_name)
                else:
                    logger.warning("Could not add %s.%s: %s", table_name, col, e)
        try:
            with engine.connect() as conn:
                conn.execute(
                    text(
                        f"UPDATE {table_name} SET tenant_id = :tenant_id "
                        "WHERE tenant_id IS NULL OR TRIM(tenant_id) = ''"
                    ),
                    {"tenant_id": config.AUTH_DEFAULT_TENANT_ID},
                )
                conn.execute(
                    text(
                        f"UPDATE {table_name} SET user_id = :user_id "
                        "WHERE user_id IS NULL OR TRIM(user_id) = ''"
                    ),
                    {"user_id": config.AUTH_DEFAULT_USER_ID},
                )
                conn.commit()
            logger.info("Backfilled %s tenant/user where null", table_name)
        except Exception as e:
            logger.warning("Could not backfill %s tenant/user: %s", table_name, e)

    try:
        with engine.connect() as conn:
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_kb_settings_tenant_user "
                    "ON kb_settings (tenant_id, user_id)"
                )
            )
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_export_format_tenant_user "
                    "ON export_format_settings (tenant_id, user_id)"
                )
            )
            conn.commit()
        logger.info("Unique indexes for scoped kb/export settings ensured")
    except Exception as e:
        logger.warning("Could not ensure scoped settings unique indexes: %s", e)

    # HNSW index for kb_chunks embedding similarity search
    try:
        with engine.connect() as conn:
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_kb_chunks_embedding "
                "ON kb_chunks USING hnsw (embedding vector_cosine_ops)"
            ))
            conn.commit()
        logger.info("HNSW index on kb_chunks.embedding ensured")
    except Exception as e:
        logger.warning("Could not create HNSW index on kb_chunks: %s", e)

    # Add internal_collection_id to kb_settings (internal KB selection)
    try:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE kb_settings ADD COLUMN internal_collection_id INTEGER"))
            conn.commit()
        logger.info("Added column internal_collection_id to kb_settings")
    except Exception as e:
        err = str(e).lower()
        if "duplicate" in err or "already exists" in err or "exists" in err:
            logger.debug("Column internal_collection_id already exists on kb_settings")
        else:
            logger.warning("Could not add internal_collection_id to kb_settings: %s", e)


@app.get("/health")
def health():
    """Health check: returns status ok."""
    return {"status": "ok"}
