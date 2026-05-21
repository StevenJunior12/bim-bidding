"""Settings API: LLM API keys, base URLs, export format, knowledge base (stage 5.1)."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import Principal, get_principal
from app.knowledge_base import test_ragflow_connection
from app.prompt_catalog import PromptCatalogResponse, get_prompt_catalog
from app.settings_store import (
    SUPPORTED_PROVIDERS,
    clear_llm_config,
    get_all_providers_status,
    get_export_format_config,
    get_kb_config,
    get_ragflow_effective,
    get_supported_export_fonts,
    set_api_key_in_db,
    set_export_format_config,
    set_kb_config,
    update_base_url_in_db,
)

router = APIRouter(tags=["settings"])


class PostLlmBody(BaseModel):
    provider: Literal["deepseek", "siliconflow"] = Field(..., description="LLM provider")
    api_key: str | None = Field(None, description="API key (plain); omit or empty to keep current")
    base_url: str | None = Field(None, description="Base URL; omit to keep current, empty string to clear")
    clear: bool = Field(False, description="If true, remove stored API key and base_url for this provider")


@router.get("/llm")
def get_settings_llm(principal: Principal = Depends(get_principal)):
    """Return each provider's configured status, masked key, and base_url (no plain key)."""
    try:
        return {
            "providers": get_all_providers_status(
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
            ),
        }
    except Exception as e:
        # e.g. llm_settings table missing base_url column (old DB): return safe fallback
        from sqlalchemy.exc import OperationalError, ProgrammingError
        if isinstance(e, (OperationalError, ProgrammingError)):
            return {
                "providers": [
                    {"provider": p, "configured": False, "masked_key": None, "base_url": None}
                    for p in SUPPORTED_PROVIDERS
                ],
            }
        raise


@router.post("/llm")
def post_settings_llm(body: PostLlmBody, principal: Principal = Depends(get_principal)):
    """Save API key and/or base_url for provider, or clear config when clear=true. Returns configured + masked_key + base_url."""
    if body.provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {body.provider}")
    if body.clear:
        try:
            clear_llm_config(
                body.provider,
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"取消配置失败: {e!s}") from e
        return {"provider": body.provider, "configured": False, "masked_key": None, "base_url": None}
    api_key = body.api_key.strip() if body.api_key else ""
    try:
        if api_key:
            set_api_key_in_db(
                body.provider,
                api_key,
                base_url=body.base_url if body.base_url is not None else None,
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
            )
        elif body.base_url is not None:
            try:
                update_base_url_in_db(
                    body.provider,
                    body.base_url,
                    tenant_id=principal.tenant_id,
                    user_id=principal.user_id,
                )
            except ValueError as e:
                if "No existing config" in str(e):
                    raise HTTPException(status_code=400, detail="请先保存该 provider 的 API Key 后再设置 Base URL") from e
                raise HTTPException(status_code=400, detail=str(e)) from e
        else:
            raise HTTPException(status_code=400, detail="请提供 api_key 和/或 base_url")
    except HTTPException:
        raise
    except Exception as e:
        from sqlalchemy.exc import OperationalError, ProgrammingError
        if isinstance(e, (OperationalError, ProgrammingError)):
            raise HTTPException(
                status_code=500,
                detail="数据库结构可能过旧，请执行: ALTER TABLE llm_settings ADD COLUMN base_url VARCHAR(512); 或重新创建表后重试。",
            ) from e
        raise HTTPException(status_code=500, detail=f"保存失败: {e!s}") from e
    status_list = get_all_providers_status(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
    )
    for s in status_list:
        if s["provider"] == body.provider:
            return {
                "provider": body.provider,
                "configured": s["configured"],
                "masked_key": s["masked_key"],
                "base_url": s.get("base_url"),
            }
    return {"provider": body.provider, "configured": False, "masked_key": None, "base_url": None}


@router.get("/prompt-catalog", response_model=PromptCatalogResponse)
def get_settings_prompt_catalog():
    """Read-only: contract vs semantic prompt text for SceneTemplatePage review."""
    return get_prompt_catalog()


# --- Export format (stage 7.1) ---


class PostExportFormatBody(BaseModel):
    """All optional; omit or null = keep current / use default."""

    heading_1_font: str | None = Field(None, description="一级标题字体")
    heading_1_size_pt: int | None = Field(None, description="一级标题字号（磅）", ge=8, le=72)
    heading_2_font: str | None = Field(None, description="二级标题字体")
    heading_2_size_pt: int | None = Field(None, description="二级标题字号", ge=8, le=72)
    heading_3_font: str | None = Field(None, description="三级标题字体")
    heading_3_size_pt: int | None = Field(None, description="三级标题字号", ge=8, le=72)
    body_font: str | None = Field(None, description="正文字体")
    body_size_pt: int | None = Field(None, description="正文字号", ge=8, le=72)
    table_font: str | None = Field(None, description="表格内字体")
    table_size_pt: int | None = Field(None, description="表格内字号", ge=8, le=72)
    first_line_indent_pt: int | None = Field(None, description="首行缩进（磅），0 或不传表示不缩进", ge=0, le=100)
    line_spacing: float | None = Field(None, description="行距倍数，如 1.0 / 1.5", ge=0.5, le=3.0)


@router.get("/export-format-fonts")
def get_settings_export_format_fonts():
    """Return list of supported font names for export format dropdown."""
    return {"fonts": get_supported_export_fonts()}


@router.get("/export-format")
def get_settings_export_format(principal: Principal = Depends(get_principal)):
    """Return current export format config (defaults when not configured)."""
    try:
        return get_export_format_config(
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
        )
    except Exception:
        from app.settings_store import DEFAULT_EXPORT_FORMAT
        return dict(DEFAULT_EXPORT_FORMAT)


@router.post("/export-format")
def post_settings_export_format(
    body: PostExportFormatBody,
    principal: Principal = Depends(get_principal),
):
    """Save export format config; returns full current config."""
    try:
        set_export_format_config(
            heading_1_font=body.heading_1_font,
            heading_1_size_pt=body.heading_1_size_pt,
            heading_2_font=body.heading_2_font,
            heading_2_size_pt=body.heading_2_size_pt,
            heading_3_font=body.heading_3_font,
            heading_3_size_pt=body.heading_3_size_pt,
            body_font=body.body_font,
            body_size_pt=body.body_size_pt,
            table_font=body.table_font,
            table_size_pt=body.table_size_pt,
            first_line_indent_pt=body.first_line_indent_pt,
            line_spacing=body.line_spacing,
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return get_export_format_config(tenant_id=principal.tenant_id, user_id=principal.user_id)


# --- Knowledge base (kb_type + RAGFlow config) ---


class PostKnowledgeBaseBody(BaseModel):
    """Knowledge base type and config; empty api_key = keep current."""

    kb_type: Literal["none", "ragflow", "internal"] = Field(..., description="Knowledge base type")
    ragflow_api_url: str | None = Field(None, description="RAGFlow base URL; omit to keep current")
    ragflow_api_key: str | None = Field(None, description="RAGFlow API key; omit or empty to keep current")
    ragflow_dataset_ids: str | None = Field(None, description="RAGFlow dataset IDs, comma-separated")
    internal_collection_id: int | None = Field(None, description="Internal KB collection ID (when kb_type=internal)")


@router.get("/knowledge-base")
def get_settings_knowledge_base(principal: Principal = Depends(get_principal)):
    """Return kb_type and RAGFlow config (masked key only, no plain key)."""
    return get_kb_config(tenant_id=principal.tenant_id, user_id=principal.user_id)


@router.post("/knowledge-base")
def post_settings_knowledge_base(
    body: PostKnowledgeBaseBody,
    principal: Principal = Depends(get_principal),
):
    """Save kb_type and/or RAGFlow config; returns current config (same as GET)."""
    try:
        set_kb_config(
            body.kb_type,
            ragflow_api_url=body.ragflow_api_url,
            ragflow_api_key=body.ragflow_api_key,
            ragflow_dataset_ids=body.ragflow_dataset_ids,
            internal_collection_id=body.internal_collection_id,
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return get_kb_config(tenant_id=principal.tenant_id, user_id=principal.user_id)


class PostKnowledgeBaseTestBody(BaseModel):
    """Optional RAGFlow params for connectivity test; omit = use saved config."""

    ragflow_api_url: str | None = Field(None, description="RAGFlow base URL")
    ragflow_api_key: str | None = Field(None, description="RAGFlow API key")
    ragflow_dataset_ids: str | None = Field(None, description="RAGFlow dataset IDs, comma-separated")


@router.post("/knowledge-base/test")
def post_settings_knowledge_base_test(
    body: PostKnowledgeBaseTestBody,
    principal: Principal = Depends(get_principal),
):
    """Test RAGFlow connectivity. Uses body values if provided, else saved config. Returns { ok, message }."""
    base_url = (body.ragflow_api_url or "").strip() or None
    api_key = (body.ragflow_api_key or "").strip() or None
    if not base_url or not api_key:
        effective = get_ragflow_effective(
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
        )
        if effective:
            base_url = base_url or effective[0]
            api_key = api_key or effective[1]
    if not base_url or not api_key:
        return {"ok": False, "message": "请填写 Base URL 和 API Key，或先保存知识库配置后再检测"}
    ok, message = test_ragflow_connection(base_url, api_key)
    return {"ok": ok, "message": message}
