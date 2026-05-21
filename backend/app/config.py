"""Application configuration: pydantic-settings from environment and backend/.env."""
from __future__ import annotations

from pathlib import Path
from typing import Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Single source for env-backed settings; .env lives under backend/."""

    model_config = SettingsConfigDict(
        env_file=str(_BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    admin_api_key: str = ""
    auth_mode: str = Field(default="hybrid", validation_alias="AUTH_MODE")
    auth_default_tenant_id: str = Field(default="default", validation_alias="AUTH_DEFAULT_TENANT_ID")
    auth_default_user_id: str = Field(default="dev-user", validation_alias="AUTH_DEFAULT_USER_ID")
    # Fernet 32-byte URL-safe base64；与 backend/.env 中 SETTINGS_SECRET_KEY 对应（SEC-02）
    settings_secret_key: str = Field(default="", validation_alias="SETTINGS_SECRET_KEY")
    redis_url: str = "redis://localhost:6379/0"
    database_url: str = "postgresql://user:password@localhost:5432/bim_bidding"

    upload_dir_raw: str = Field(default="data/uploads", validation_alias="UPLOAD_DIR")
    max_upload_size_mb: int = Field(default=50, validation_alias="MAX_UPLOAD_SIZE_MB")
    export_dir_raw: str = Field(default="data/exports", validation_alias="EXPORT_DIR")

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"

    llm_timeout_connect: float = Field(default=10.0, validation_alias="LLM_TIMEOUT_CONNECT")
    llm_timeout_read: float = Field(default=180.0, validation_alias="LLM_TIMEOUT_READ")
    llm_max_tokens: int = Field(default=8192, validation_alias="LLM_MAX_TOKENS")

    analyze_llm_provider: str = Field(default="deepseek", validation_alias="ANALYZE_LLM_PROVIDER")
    analyze_llm_model: str = Field(default="deepseek-v4-flash", validation_alias="ANALYZE_LLM_MODEL")
    params_llm_provider: str = Field(default="deepseek", validation_alias="PARAMS_LLM_PROVIDER")
    params_llm_model: str = Field(default="deepseek-v4-flash", validation_alias="PARAMS_LLM_MODEL")
    framework_llm_provider: str = Field(default="deepseek", validation_alias="FRAMEWORK_LLM_PROVIDER")
    framework_llm_model: str = Field(default="deepseek-v4-flash", validation_alias="FRAMEWORK_LLM_MODEL")
    chapter_llm_provider: str = Field(default="deepseek", validation_alias="CHAPTER_LLM_PROVIDER")
    chapter_llm_model: str = Field(default="deepseek-v4-flash", validation_alias="CHAPTER_LLM_MODEL")
    prompt_profile_gen_llm_provider: str = Field(
        default="deepseek", validation_alias="PROMPT_PROFILE_GEN_LLM_PROVIDER"
    )
    prompt_profile_gen_llm_model: str = Field(
        default="deepseek-v4-flash", validation_alias="PROMPT_PROFILE_GEN_LLM_MODEL"
    )

    chapter_outline_analyze_max_len: int = Field(
        default=8000, validation_alias="CHAPTER_OUTLINE_ANALYZE_MAX_LEN"
    )
    chapter_content_analyze_max_len: int = Field(
        default=6000, validation_alias="CHAPTER_CONTENT_ANALYZE_MAX_LEN"
    )

    framework_kb_fallback_query: str = Field(
        default="标书框架", validation_alias="FRAMEWORK_KB_FALLBACK_QUERY"
    )
    framework_kb_query_max_len: int = Field(default=500, validation_alias="FRAMEWORK_KB_QUERY_MAX_LEN")

    ragflow_api_url: str = ""
    ragflow_api_key: str = ""
    ragflow_dataset_ids_raw: str = Field(default="", validation_alias="RAGFLOW_DATASET_IDS")

    siliconflow_base_url: str = Field(default="https://api.siliconflow.cn/v1", validation_alias="SILICONFLOW_BASE_URL")
    siliconflow_embedding_model: str = Field(default="BAAI/bge-m3", validation_alias="SILICONFLOW_EMBEDDING_MODEL")
    siliconflow_embedding_dims: int = Field(default=1024, validation_alias="SILICONFLOW_EMBEDDING_DIMS")
    kb_chunk_batch_size: int = Field(default=32, validation_alias="KB_CHUNK_BATCH_SIZE")

    knowledge_base_type_env: str = Field(default="", validation_alias="KNOWLEDGE_BASE_TYPE")

    # 设为 1/true 时，call_llm 在发送请求前按 prompt_step 记录契约层文案（见 app.contract_prompt_log）
    log_contract_prompts: bool = Field(default=False, validation_alias="LOG_CONTRACT_PROMPTS")
    log_contract_max_chars: int = Field(default=200_000, validation_alias="LOG_CONTRACT_MAX_CHARS")
    # 相对 backend/ 或绝对路径；留空则仅输出到控制台 logger，不写文件
    log_contract_prompts_file: str = Field(
        default="data/logs/contract_prompts.log",
        validation_alias="LOG_CONTRACT_PROMPTS_FILE",
    )

    upload_dir: Path = Field(default=Path("."))
    export_dir: Path = Field(default=Path("."))
    max_upload_size_bytes: int = 0
    knowledge_base_type: str = "none"

    @field_validator("log_contract_prompts", mode="before")
    @classmethod
    def _coerce_log_contract_prompts(cls, v: object) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in ("1", "true", "yes", "on")
        return bool(v)

    @field_validator("log_contract_max_chars", mode="after")
    @classmethod
    def _non_negative_log_contract_max_chars(cls, v: int) -> int:
        return max(0, v)

    @field_validator("log_contract_prompts_file", mode="after")
    @classmethod
    def _strip_log_contract_prompts_file(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else ""

    @field_validator("admin_api_key", "settings_secret_key", mode="after")
    @classmethod
    def _strip_secrets_and_admin(cls, v: str) -> str:
        return v.strip()

    @field_validator("auth_mode", mode="after")
    @classmethod
    def _normalize_auth_mode(cls, v: str) -> str:
        mode = v.strip().lower()
        if mode not in ("mock", "header", "jwt", "hybrid"):
            return "hybrid"
        return mode

    @field_validator("auth_default_tenant_id", "auth_default_user_id", mode="after")
    @classmethod
    def _normalize_auth_defaults(cls, v: str) -> str:
        return v.strip() or "default"

    @field_validator("deepseek_base_url", mode="after")
    @classmethod
    def _normalize_deepseek_base_url(cls, v: str) -> str:
        return v.strip().rstrip("/")

    @field_validator("ragflow_api_url", mode="after")
    @classmethod
    def _normalize_ragflow_api_url(cls, v: str) -> str:
        return v.strip().rstrip("/")

    @field_validator("siliconflow_base_url", mode="after")
    @classmethod
    def _normalize_siliconflow_base_url(cls, v: str) -> str:
        return v.strip().rstrip("/")

    @model_validator(mode="after")
    def _derive_paths_and_kb(self) -> Self:
        u_raw = self.upload_dir_raw
        u_path = Path(u_raw)
        upload_dir = u_path.resolve() if u_path.is_absolute() else (_BACKEND_ROOT / u_raw).resolve()

        e_raw = self.export_dir_raw
        e_path = Path(e_raw)
        export_dir = e_path.resolve() if e_path.is_absolute() else (_BACKEND_ROOT / e_raw).resolve()

        max_bytes = self.max_upload_size_mb * 1024 * 1024

        kb_env = self.knowledge_base_type_env.strip().lower()
        if kb_env in ("ragflow", "none"):
            kb_type = kb_env
        elif self.ragflow_api_key and self.ragflow_dataset_ids_raw.strip():
            kb_type = "ragflow"
        else:
            kb_type = "none"

        object.__setattr__(self, "upload_dir", upload_dir)
        object.__setattr__(self, "export_dir", export_dir)
        object.__setattr__(self, "max_upload_size_bytes", max_bytes)
        object.__setattr__(self, "knowledge_base_type", kb_type)
        return self


settings = Settings()

# Backward compatibility: existing code uses `from app import config` and config.UPPER_NAME
ADMIN_API_KEY: str = settings.admin_api_key
AUTH_MODE: str = settings.auth_mode
AUTH_DEFAULT_TENANT_ID: str = settings.auth_default_tenant_id
AUTH_DEFAULT_USER_ID: str = settings.auth_default_user_id
SETTINGS_SECRET_KEY: str = settings.settings_secret_key
REDIS_URL: str = settings.redis_url
DATABASE_URL: str = settings.database_url
UPLOAD_DIR: Path = settings.upload_dir
MAX_UPLOAD_SIZE_MB: int = settings.max_upload_size_mb
MAX_UPLOAD_SIZE_BYTES: int = settings.max_upload_size_bytes
EXPORT_DIR: Path = settings.export_dir
DEEPSEEK_API_KEY: str = settings.deepseek_api_key
DEEPSEEK_BASE_URL: str = settings.deepseek_base_url
LLM_TIMEOUT_CONNECT: float = settings.llm_timeout_connect
LLM_TIMEOUT_READ: float = settings.llm_timeout_read
LLM_MAX_TOKENS: int = settings.llm_max_tokens
ANALYZE_LLM_PROVIDER: str = settings.analyze_llm_provider
ANALYZE_LLM_MODEL: str = settings.analyze_llm_model
PARAMS_LLM_PROVIDER: str = settings.params_llm_provider
PARAMS_LLM_MODEL: str = settings.params_llm_model
FRAMEWORK_LLM_PROVIDER: str = settings.framework_llm_provider
FRAMEWORK_LLM_MODEL: str = settings.framework_llm_model
CHAPTER_LLM_PROVIDER: str = settings.chapter_llm_provider
CHAPTER_LLM_MODEL: str = settings.chapter_llm_model
PROMPT_PROFILE_GEN_LLM_PROVIDER: str = settings.prompt_profile_gen_llm_provider
PROMPT_PROFILE_GEN_LLM_MODEL: str = settings.prompt_profile_gen_llm_model
CHAPTER_OUTLINE_ANALYZE_MAX_LEN: int = settings.chapter_outline_analyze_max_len
CHAPTER_CONTENT_ANALYZE_MAX_LEN: int = settings.chapter_content_analyze_max_len
FRAMEWORK_KB_FALLBACK_QUERY: str = settings.framework_kb_fallback_query
FRAMEWORK_KB_QUERY_MAX_LEN: int = settings.framework_kb_query_max_len
RAGFLOW_API_URL: str = settings.ragflow_api_url
RAGFLOW_API_KEY: str = settings.ragflow_api_key
RAGFLOW_DATASET_IDS_RAW: str = settings.ragflow_dataset_ids_raw
KNOWLEDGE_BASE_TYPE: str = settings.knowledge_base_type
SILICONFLOW_BASE_URL: str = settings.siliconflow_base_url
SILICONFLOW_EMBEDDING_MODEL: str = settings.siliconflow_embedding_model
SILICONFLOW_EMBEDDING_DIMS: int = settings.siliconflow_embedding_dims
KB_CHUNK_BATCH_SIZE: int = settings.kb_chunk_batch_size
LOG_CONTRACT_PROMPTS: bool = settings.log_contract_prompts
LOG_CONTRACT_MAX_CHARS: int = settings.log_contract_max_chars
LOG_CONTRACT_PROMPTS_FILE: str = settings.log_contract_prompts_file


def get_ragflow_dataset_ids() -> list[str]:
    """Return list of dataset IDs from RAGFLOW_DATASET_IDS (comma-separated)."""
    raw = settings.ragflow_dataset_ids_raw
    if not raw.strip():
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def _get_task_scope(task_id: int | None) -> tuple[str | None, str | None]:
    if task_id is None:
        return None, None
    from app.database import SessionLocal
    from app.models import Task

    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            return None, None
        return task.tenant_id, task.user_id
    finally:
        db.close()


def get_llm_api_key(provider: str, task_id: int | None = None) -> str | None:
    """Return API key for provider (deepseek); from DB first, then env; None if not set."""
    from app.settings_store import get_api_key_from_db

    tenant_id, user_id = _get_task_scope(task_id)
    key = get_api_key_from_db(provider, tenant_id=tenant_id, user_id=user_id)
    if key:
        return key
    if provider == "deepseek":
        return settings.deepseek_api_key or None
    return None


def get_llm_base_url(provider: str, task_id: int | None = None) -> str:
    """Return base URL for provider (no trailing slash); from DB first, then env."""
    from app.settings_store import get_base_url_from_db

    tenant_id, user_id = _get_task_scope(task_id)
    url = get_base_url_from_db(provider, tenant_id=tenant_id, user_id=user_id)
    if url:
        return url.rstrip("/")
    if provider == "deepseek":
        return settings.deepseek_base_url.rstrip("/")
    if provider == "siliconflow":
        return settings.siliconflow_base_url.rstrip("/")
    raise ValueError(f"Unknown provider: {provider}")
