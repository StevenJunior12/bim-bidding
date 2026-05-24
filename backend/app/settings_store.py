"""Encrypt/decrypt and DB read/write for LLM API keys (stage 5.1)."""
import logging
from datetime import datetime

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import ExportFormatSetting, KbSetting, LlmSetting

logger = logging.getLogger(__name__)

SUPPORTED_PROVIDERS = ("deepseek", "siliconflow")

# Fernet key (URL-safe base64, 32 bytes). SEC-02: no placeholder fallback — missing or invalid key fails at import.
# 值来自 pydantic-settings（.env / 环境变量 SETTINGS_SECRET_KEY），与 os.getenv 双轨已去除。
_SETTINGS_SECRET_KEY = settings.settings_secret_key
if not _SETTINGS_SECRET_KEY:
    raise RuntimeError(
        "SETTINGS_SECRET_KEY 未配置，服务拒绝启动。"
        "请执行: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        " 并将输出写入 backend/.env 中的 SETTINGS_SECRET_KEY=..."
    )
try:
    _fernet = Fernet(_SETTINGS_SECRET_KEY.encode("utf-8"))
except Exception as e:
    raise RuntimeError(
        f"SETTINGS_SECRET_KEY 不是有效的 Fernet 密钥: {e}"
    ) from e


def _get_fernet() -> Fernet:
    return _fernet


def _resolve_scope(tenant_id: str | None = None, user_id: str | None = None) -> tuple[str, str]:
    t = (tenant_id or "").strip() or settings.auth_default_tenant_id
    u = (user_id or "").strip() or settings.auth_default_user_id
    return t, u


def encrypt_api_key(plain: str) -> str:
    """Encrypt plain API key to base64 string for storage."""
    return _get_fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_api_key(cipher: str) -> str | None:
    """Decrypt stored cipher to plain key; None on failure."""
    try:
        return _get_fernet().decrypt(cipher.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None


def mask_api_key(plain: str) -> str:
    """Return masked key e.g. sk-***xyz (first 2 + *** + last 3)."""
    if len(plain) <= 5:
        return "***"
    return plain[:2] + "***" + plain[-3:]


def get_api_key_from_db(provider: str, tenant_id: str | None = None, user_id: str | None = None) -> str | None:
    """Return decrypted API key for provider from DB, or None."""
    if provider not in SUPPORTED_PROVIDERS:
        return None
    tenant, user = _resolve_scope(tenant_id, user_id)
    db: Session = SessionLocal()
    try:
        row = (
            db.query(LlmSetting)
            .filter(
                LlmSetting.provider == provider,
                LlmSetting.tenant_id == tenant,
                LlmSetting.user_id == user,
            )
            .first()
        )
        if not row or not row.encrypted_api_key:
            return None
        return decrypt_api_key(row.encrypted_api_key)
    finally:
        db.close()


def get_base_url_from_db(provider: str, tenant_id: str | None = None, user_id: str | None = None) -> str | None:
    """Return base_url for provider from DB, or None (use env default)."""
    if provider not in SUPPORTED_PROVIDERS:
        return None
    tenant, user = _resolve_scope(tenant_id, user_id)
    db: Session = SessionLocal()
    try:
        row = (
            db.query(LlmSetting)
            .filter(
                LlmSetting.provider == provider,
                LlmSetting.tenant_id == tenant,
                LlmSetting.user_id == user,
            )
            .first()
        )
        if not row or not row.base_url:
            return None
        return row.base_url.rstrip("/") or None
    finally:
        db.close()


def set_api_key_in_db(
    provider: str,
    api_key: str,
    base_url: str | None = None,
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> None:
    """Encrypt and upsert API key for provider; optionally set base_url (empty string = clear)."""
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(f"Unsupported provider: {provider}")
    tenant, user = _resolve_scope(tenant_id, user_id)
    encrypted = encrypt_api_key(api_key)
    db: Session = SessionLocal()
    try:
        row = (
            db.query(LlmSetting)
            .filter(
                LlmSetting.provider == provider,
                LlmSetting.tenant_id == tenant,
                LlmSetting.user_id == user,
            )
            .first()
        )
        if row:
            row.encrypted_api_key = encrypted
            row.updated_at = datetime.utcnow()
            if base_url is not None:
                row.base_url = base_url.strip() or None
        else:
            db.add(LlmSetting(
                tenant_id=tenant,
                user_id=user,
                provider=provider,
                encrypted_api_key=encrypted,
                base_url=base_url.strip() or None if base_url is not None else None,
            ))
        db.commit()
    finally:
        db.close()


def update_base_url_in_db(
    provider: str,
    base_url: str | None,
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> None:
    """Update only base_url for provider (row must exist). Empty string = clear."""
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(f"Unsupported provider: {provider}")
    tenant, user = _resolve_scope(tenant_id, user_id)
    db: Session = SessionLocal()
    try:
        row = (
            db.query(LlmSetting)
            .filter(
                LlmSetting.provider == provider,
                LlmSetting.tenant_id == tenant,
                LlmSetting.user_id == user,
            )
            .first()
        )
        if not row:
            raise ValueError(f"No existing config for provider: {provider}")
        row.base_url = base_url.strip() or None if base_url else None
        row.updated_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()


def clear_llm_config(provider: str, tenant_id: str | None = None, user_id: str | None = None) -> None:
    """Remove stored API key and base_url for provider (delete row)."""
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(f"Unsupported provider: {provider}")
    tenant, user = _resolve_scope(tenant_id, user_id)
    db: Session = SessionLocal()
    try:
        (
            db.query(LlmSetting)
            .filter(
                LlmSetting.provider == provider,
                LlmSetting.tenant_id == tenant,
                LlmSetting.user_id == user,
            )
            .delete()
        )
        db.commit()
    finally:
        db.close()


def get_all_providers_status(tenant_id: str | None = None, user_id: str | None = None) -> list[dict]:
    """Return list of {provider, configured, masked_key, base_url} for all supported providers."""
    tenant, user = _resolve_scope(tenant_id, user_id)
    db: Session = SessionLocal()
    result: list[dict] = []
    try:
        for provider in SUPPORTED_PROVIDERS:
            row = (
                db.query(LlmSetting)
                .filter(
                    LlmSetting.provider == provider,
                    LlmSetting.tenant_id == tenant,
                    LlmSetting.user_id == user,
                )
                .first()
            )
            if row and row.encrypted_api_key:
                plain = decrypt_api_key(row.encrypted_api_key)
                result.append({
                    "provider": provider,
                    "configured": True,
                    "masked_key": mask_api_key(plain) if plain else None,
                    "base_url": row.base_url if row.base_url else None,
                })
            else:
                result.append({"provider": provider, "configured": False, "masked_key": None, "base_url": None})
        return result
    finally:
        db.close()


# --- Export format settings (stage 7.1) ---

EXPORT_FORMAT_KEYS = (
    "heading_1_font", "heading_1_size_pt",
    "heading_2_font", "heading_2_size_pt",
    "heading_3_font", "heading_3_size_pt",
    "body_font", "body_size_pt",
    "table_font", "table_size_pt",
    "first_line_indent_pt", "line_spacing",
)

DEFAULT_EXPORT_FORMAT: dict = {
    "heading_1_font": "宋体",
    "heading_1_size_pt": 22,
    "heading_2_font": "宋体",
    "heading_2_size_pt": 16,
    "heading_3_font": "宋体",
    "heading_3_size_pt": 14,
    "body_font": "宋体",
    "body_size_pt": 12,
    "table_font": "宋体",
    "table_size_pt": 12,
    "first_line_indent_pt": 24,
    "line_spacing": 1.5,
}

FONT_SIZE_MIN, FONT_SIZE_MAX = 8, 72
LINE_SPACING_MIN, LINE_SPACING_MAX = 0.5, 3.0
FIRST_LINE_INDENT_MAX = 100

# Supported font names for export format dropdown (configurable; extend here or later from config/DB).
SUPPORTED_EXPORT_FONTS: list[str] = [
    "宋体",
    "黑体",
    "微软雅黑",
    "楷体",
    "仿宋",
    "Arial",
    "Times New Roman",
]


def get_supported_export_fonts() -> list[str]:
    """Return list of font names supported for export format (heading/body/table)."""
    return list(SUPPORTED_EXPORT_FONTS)


def get_export_format_config(tenant_id: str | None = None, user_id: str | None = None) -> dict:
    """Return export format config dict (merge DB row with defaults); for 7.2 format_options."""
    tenant, user = _resolve_scope(tenant_id, user_id)
    db: Session = SessionLocal()
    try:
        row = (
            db.query(ExportFormatSetting)
            .filter(
                ExportFormatSetting.tenant_id == tenant,
                ExportFormatSetting.user_id == user,
            )
            .first()
        )
        if not row:
            return dict(DEFAULT_EXPORT_FORMAT)
        out = dict(DEFAULT_EXPORT_FORMAT)
        for key in EXPORT_FORMAT_KEYS:
            val = getattr(row, key, None)
            if val is not None:
                out[key] = val
        return out
    finally:
        db.close()


def set_export_format_config(
    heading_1_font: str | None = None,
    heading_1_size_pt: int | None = None,
    heading_2_font: str | None = None,
    heading_2_size_pt: int | None = None,
    heading_3_font: str | None = None,
    heading_3_size_pt: int | None = None,
    body_font: str | None = None,
    body_size_pt: int | None = None,
    table_font: str | None = None,
    table_size_pt: int | None = None,
    first_line_indent_pt: int | None = None,
    line_spacing: float | None = None,
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> None:
    """Upsert single row of export format settings; validate sizes and ranges."""
    for attr, val in (
        ("heading_1_size_pt", heading_1_size_pt),
        ("heading_2_size_pt", heading_2_size_pt),
        ("heading_3_size_pt", heading_3_size_pt),
        ("body_size_pt", body_size_pt),
        ("table_size_pt", table_size_pt),
    ):
        if val is not None and (val < FONT_SIZE_MIN or val > FONT_SIZE_MAX):
            raise ValueError(f"字号 {attr} 应在 {FONT_SIZE_MIN}–{FONT_SIZE_MAX} 之间")
    if first_line_indent_pt is not None and (first_line_indent_pt < 0 or first_line_indent_pt > FIRST_LINE_INDENT_MAX):
        raise ValueError(f"首行缩进应在 0–{FIRST_LINE_INDENT_MAX} 磅之间")
    if line_spacing is not None and (line_spacing < LINE_SPACING_MIN or line_spacing > LINE_SPACING_MAX):
        raise ValueError(f"行距应在 {LINE_SPACING_MIN}–{LINE_SPACING_MAX} 之间")

    tenant, user = _resolve_scope(tenant_id, user_id)
    db: Session = SessionLocal()
    try:
        row = (
            db.query(ExportFormatSetting)
            .filter(
                ExportFormatSetting.tenant_id == tenant,
                ExportFormatSetting.user_id == user,
            )
            .first()
        )
        if not row:
            row = ExportFormatSetting(
                tenant_id=tenant,
                user_id=user,
                heading_1_font=heading_1_font.strip() or None if heading_1_font is not None else None,
                heading_1_size_pt=heading_1_size_pt,
                heading_2_font=heading_2_font.strip() or None if heading_2_font is not None else None,
                heading_2_size_pt=heading_2_size_pt,
                heading_3_font=heading_3_font.strip() or None if heading_3_font is not None else None,
                heading_3_size_pt=heading_3_size_pt,
                body_font=body_font.strip() or None if body_font is not None else None,
                body_size_pt=body_size_pt,
                table_font=table_font.strip() or None if table_font is not None else None,
                table_size_pt=table_size_pt,
                first_line_indent_pt=first_line_indent_pt if first_line_indent_pt != 0 else None,
                line_spacing=line_spacing,
            )
            db.add(row)
        else:
            if heading_1_font is not None:
                row.heading_1_font = heading_1_font.strip() or None
            if heading_1_size_pt is not None:
                row.heading_1_size_pt = heading_1_size_pt
            if heading_2_font is not None:
                row.heading_2_font = heading_2_font.strip() or None
            if heading_2_size_pt is not None:
                row.heading_2_size_pt = heading_2_size_pt
            if heading_3_font is not None:
                row.heading_3_font = heading_3_font.strip() or None
            if heading_3_size_pt is not None:
                row.heading_3_size_pt = heading_3_size_pt
            if body_font is not None:
                row.body_font = body_font.strip() or None
            if body_size_pt is not None:
                row.body_size_pt = body_size_pt
            if table_font is not None:
                row.table_font = table_font.strip() or None
            if table_size_pt is not None:
                row.table_size_pt = table_size_pt
            if first_line_indent_pt is not None:
                row.first_line_indent_pt = first_line_indent_pt if first_line_indent_pt != 0 else None
            if line_spacing is not None:
                row.line_spacing = line_spacing
        db.commit()
    finally:
        db.close()


# --- Knowledge base settings (single row: kb_type + RAGFlow config) ---

VALID_KB_TYPES = ("none", "ragflow", "internal")


def _kb_config_from_env() -> dict:
    """Build kb_config dict from environment (used when no DB row)."""
    from app import config
    ragflow_ids = config.get_ragflow_dataset_ids()
    return {
        "kb_type": config.KNOWLEDGE_BASE_TYPE,
        "ragflow_api_url": config.RAGFLOW_API_URL or None,
        "ragflow_configured": bool(config.RAGFLOW_API_KEY and ragflow_ids),
        "ragflow_masked_key": mask_api_key(config.RAGFLOW_API_KEY) if config.RAGFLOW_API_KEY else None,
        "ragflow_dataset_ids": ",".join(ragflow_ids) if ragflow_ids else "",
    }


def get_kb_config(tenant_id: str | None = None, user_id: str | None = None) -> dict:
    """Return kb_type and RAGFlow config (masked key only). From DB row or env default."""
    tenant, user = _resolve_scope(tenant_id, user_id)
    db: Session = SessionLocal()
    try:
        row = (
            db.query(KbSetting)
            .filter(
                KbSetting.tenant_id == tenant,
                KbSetting.user_id == user,
            )
            .first()
        )
        if not row:
            env_cfg = _kb_config_from_env()
            env_cfg["internal_collection_id"] = None
            env_cfg["siliconflow_configured"] = False
            return env_cfg
        plain_key = decrypt_api_key(row.ragflow_encrypted_api_key) if row.ragflow_encrypted_api_key else None
        has_url = bool(row.ragflow_api_url and (row.ragflow_api_url or "").strip())
        has_ids = bool(row.ragflow_dataset_ids and (row.ragflow_dataset_ids or "").strip())

        # Check SiliconFlow config
        sf_key = get_api_key_from_db("siliconflow", tenant_id=tenant, user_id=user)
        sf_configured = bool(sf_key)

        return {
            "kb_type": row.kb_type or "none",
            "ragflow_api_url": (row.ragflow_api_url or "").strip() or None,
            "ragflow_configured": bool(has_url and plain_key and has_ids),
            "ragflow_masked_key": mask_api_key(plain_key) if plain_key else None,
            "ragflow_dataset_ids": (row.ragflow_dataset_ids or "").strip() or "",
            "internal_collection_id": getattr(row, "internal_collection_id", None),
            "siliconflow_configured": sf_configured,
        }
    except Exception as e:
        logger.debug("get_kb_config fallback to env: %s", e)
        env_cfg = _kb_config_from_env()
        env_cfg["internal_collection_id"] = None
        env_cfg["siliconflow_configured"] = False
        return env_cfg
    finally:
        db.close()


def set_kb_config(
    kb_type: str,
    ragflow_api_url: str | None = None,
    ragflow_api_key: str | None = None,
    ragflow_dataset_ids: str | None = None,
    internal_collection_id: int | None = None,
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> None:
    """Upsert single row of kb settings. Empty api_key = keep current; empty url/ids = clear or keep per existing."""
    if kb_type not in VALID_KB_TYPES:
        raise ValueError(f"kb_type must be one of {VALID_KB_TYPES}, got {kb_type!r}")
    tenant, user = _resolve_scope(tenant_id, user_id)
    db: Session = SessionLocal()
    try:
        if kb_type == "internal" and internal_collection_id is None:
            raise ValueError("internal 知识库必须指定 collection")
        # Validate collection ownership when internal is selected
        if kb_type == "internal" and internal_collection_id is not None:
            from app.models import KbCollection
            col = db.query(KbCollection).filter(
                KbCollection.id == internal_collection_id,
                KbCollection.tenant_id == tenant,
                KbCollection.user_id == user,
            ).first()
            if not col:
                raise ValueError("知识库不存在或不属于当前用户")

        row = (
            db.query(KbSetting)
            .filter(
                KbSetting.tenant_id == tenant,
                KbSetting.user_id == user,
            )
            .first()
        )
        now = datetime.utcnow()
        if not row:
            row = KbSetting(
                tenant_id=tenant,
                user_id=user,
                kb_type=kb_type,
                ragflow_api_url=ragflow_api_url.strip() or None if ragflow_api_url is not None else None,
                ragflow_encrypted_api_key=encrypt_api_key(ragflow_api_key) if (ragflow_api_key and ragflow_api_key.strip()) else None,
                ragflow_dataset_ids=ragflow_dataset_ids.strip() or None if ragflow_dataset_ids is not None else None,
                updated_at=now,
            )
            db.add(row)
            db.flush()
        else:
            row.kb_type = kb_type
            row.updated_at = now
            if ragflow_api_url is not None:
                row.ragflow_api_url = ragflow_api_url.strip() or None
            if ragflow_api_key is not None:
                if ragflow_api_key.strip():
                    row.ragflow_encrypted_api_key = encrypt_api_key(ragflow_api_key)
                else:
                    row.ragflow_encrypted_api_key = None  # explicit empty string = clear key
            if ragflow_dataset_ids is not None:
                row.ragflow_dataset_ids = ragflow_dataset_ids.strip() or None

        # Set internal_collection_id if the column exists
        if hasattr(row, "internal_collection_id") or kb_type == "internal":
            if internal_collection_id is not None:
                row.internal_collection_id = internal_collection_id
            elif kb_type != "internal":
                row.internal_collection_id = None

        db.commit()
    finally:
        db.close()


def get_ragflow_effective(
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> tuple[str, str, list[str]] | None:
    """Return (base_url, api_key, dataset_ids_list) for RAGFlow when kb_type=ragflow; DB first then env. None if not configured."""
    from app import config
    tenant, user = _resolve_scope(tenant_id, user_id)
    cfg = get_kb_config(tenant, user)
    if cfg.get("kb_type") != "ragflow":
        return None
    db: Session = SessionLocal()
    try:
        row = (
            db.query(KbSetting)
            .filter(
                KbSetting.tenant_id == tenant,
                KbSetting.user_id == user,
            )
            .first()
        )
        if row and row.kb_type == "ragflow" and row.ragflow_api_url and row.ragflow_encrypted_api_key and row.ragflow_dataset_ids:
            plain = decrypt_api_key(row.ragflow_encrypted_api_key)
            if plain:
                ids_raw = (row.ragflow_dataset_ids or "").strip()
                ids_list = [x.strip() for x in ids_raw.split(",") if x.strip()]
                if ids_list:
                    return ((row.ragflow_api_url or "").rstrip("/"), plain, ids_list)
    except Exception as e:
        logger.debug("get_ragflow_effective DB read failed: %s", e)
    finally:
        db.close()
    if config.RAGFLOW_API_URL and config.RAGFLOW_API_KEY and config.get_ragflow_dataset_ids():
        return (
            config.RAGFLOW_API_URL.rstrip("/"),
            config.RAGFLOW_API_KEY,
            config.get_ragflow_dataset_ids(),
        )
    return None
