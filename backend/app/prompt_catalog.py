"""Read-only aggregation of contract vs semantic prompt text for human review (SceneTemplatePage)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app import config
from app.params_compat import LEGACY_REQUIREMENTS_JSON_KEY, REQUIREMENTS_JSON_KEY
from app.prompts import (
    ANALYZE_CONTEXT_PLACEHOLDER,
    ANALYZE_SYSTEM,
    ANALYZE_USER_TEMPLATE,
    CHAPTER_CONTENT_SYSTEM,
    CHAPTER_CONTENT_USER_TEMPLATE,
    CHAPTER_OUTLINE_SYSTEM,
    CHAPTER_OUTLINE_USER_TEMPLATE,
    CHAPTER_REGENERATE_SYSTEM,
    CHAPTER_REGENERATE_USER_TEMPLATE,
    FRAMEWORK_ANALYZE_PLACEHOLDER,
    FRAMEWORK_CONTEXT_PLACEHOLDER,
    FRAMEWORK_REQUIREMENTS_PLACEHOLDER,
    FRAMEWORK_SCORING_PLACEHOLDER,
    FRAMEWORK_SYSTEM,
    FRAMEWORK_SYSTEM_WITH_USER_POINTS,
    FRAMEWORK_USER_EXTRA_POINTS_TEMPLATE,
    FRAMEWORK_USER_TEMPLATE,
    PARAMS_CONTEXT_PLACEHOLDER,
    PARAMS_SYSTEM,
    PARAMS_USER_TEMPLATE,
    REVIEW_ANALYZE_EXCERPT,
    REVIEW_CHAPTER_CONTENT,
    REVIEW_CHAPTER_FULL_NAME,
    REVIEW_KB_CONTEXT,
    REVIEW_OUTPUT_FORMAT_SPEC,
    REVIEW_PARAMS_CONTEXT_PLACEHOLDER,
    REVIEW_TYPE_VALUES,
    REVIEW_USER_TEMPLATE,
)
from app.review_prompt_assembly import (
    REVIEW_PARAMS_SECTION_KEY_REQUIREMENTS,
    REVIEW_PARAMS_SECTION_PROJECT,
    REVIEW_PARAMS_SECTION_RISK,
    REVIEW_PARAMS_SECTION_SCORING,
)

# 仅用于 prompt-catalog / 场景与模板页与 Profile 弹窗预填：不展开四类判定说明，避免与契约层重复；运行时仍用 prompts.REVIEW_SYSTEM_SEMANTIC。
REVIEW_SYSTEM_SEMANTIC_CATALOG_DISPLAY = """你是BIM技术标校审专家，对单章正文进行质量与合规校审。

本条为只读目录与配置弹窗中的简要示例，不展开各审查维度的具体定义。线上默认校审仍使用代码中的完整 system（含维度说明），并与契约层「校审 · 输出 JSON 结构」拼接后调用模型。"""


class PromptCatalogItem(BaseModel):
    id: str
    step: str
    title: str
    content: str = Field(..., description="Plain text for read-only display")


class PromptCatalogResponse(BaseModel):
    contract_items: list[PromptCatalogItem]
    semantic_items: list[PromptCatalogItem]


def _params_snapshot_contract_doc() -> str:
    return f"""持久化与 LLM 原始 JSON（params 步骤）

## JSON 键（canonical）
- {REQUIREMENTS_JSON_KEY}：须响应要点列表（写入快照）。
- {LEGACY_REQUIREMENTS_JSON_KEY}：历史键，仅读取兼容。

## 函数行为（与代码一致）
- coalesce_requirements_from_llm_raw(raw)：若 raw 中出现键 {REQUIREMENTS_JSON_KEY!r}（含空列表），以其为准；否则使用 {LEGACY_REQUIREMENTS_JSON_KEY!r}。
- extract_requirements_list(params_out)：快照读取时优先 {REQUIREMENTS_JSON_KEY} 列表，否则 legacy 列表。
- params_snapshot_has_requirements_list(params_out)：{REQUIREMENTS_JSON_KEY} 或 {LEGACY_REQUIREMENTS_JSON_KEY} 任一为 list 即 True（含空列表）。"""


def _runtime_contract_doc() -> str:
    return f"""框架步骤运行时（非 LLM 文案）

- KB 检索 query：取分析正文前 {config.FRAMEWORK_KB_QUERY_MAX_LEN} 字符；若分析正文为空则使用固定串「{config.FRAMEWORK_KB_FALLBACK_QUERY}」。
- 框架步骤 HTTP 门禁（/steps/framework/run）：params 步骤 output_snapshot 解析为对象后，须满足 params_snapshot_has_requirements_list（见「持久化与 LLM 原始 JSON」）。"""


def _placeholder_table() -> str:
    lines = [
        "占位符常量（字面量）",
        "",
        f"ANALYZE_CONTEXT_PLACEHOLDER = {ANALYZE_CONTEXT_PLACEHOLDER!r}",
        f"PARAMS_CONTEXT_PLACEHOLDER = {PARAMS_CONTEXT_PLACEHOLDER!r}",
        f"FRAMEWORK_ANALYZE_PLACEHOLDER = {FRAMEWORK_ANALYZE_PLACEHOLDER!r}",
        f"FRAMEWORK_REQUIREMENTS_PLACEHOLDER = {FRAMEWORK_REQUIREMENTS_PLACEHOLDER!r}",
        f"FRAMEWORK_SCORING_PLACEHOLDER = {FRAMEWORK_SCORING_PLACEHOLDER!r}",
        f"FRAMEWORK_CONTEXT_PLACEHOLDER = {FRAMEWORK_CONTEXT_PLACEHOLDER!r}",
        f"REVIEW_CHAPTER_FULL_NAME = {REVIEW_CHAPTER_FULL_NAME!r}",
        f"REVIEW_CHAPTER_CONTENT = {REVIEW_CHAPTER_CONTENT!r}",
        f"REVIEW_ANALYZE_EXCERPT = {REVIEW_ANALYZE_EXCERPT!r}",
        f"REVIEW_PARAMS_CONTEXT_PLACEHOLDER = {REVIEW_PARAMS_CONTEXT_PLACEHOLDER!r}",
        f"REVIEW_KB_CONTEXT = {REVIEW_KB_CONTEXT!r}",
    ]
    return "\n".join(lines)


def _review_assembly_labels() -> str:
    return f"""校审参数摘要拼装用段落标题（review 任务 _build_params_summary）

- {REVIEW_PARAMS_SECTION_RISK!r}
- {REVIEW_PARAMS_SECTION_KEY_REQUIREMENTS!r}
- {REVIEW_PARAMS_SECTION_SCORING!r}
- {REVIEW_PARAMS_SECTION_PROJECT!r}
"""


def get_prompt_catalog() -> PromptCatalogResponse:
    contract: list[PromptCatalogItem] = [
        PromptCatalogItem(
            id="contract.params_snapshot",
            step="runtime",
            title="持久化与 LLM 原始 JSON（params）",
            content=_params_snapshot_contract_doc(),
        ),
        PromptCatalogItem(
            id="contract.runtime_framework",
            step="runtime",
            title="框架步骤运行时默认值与门禁",
            content=_runtime_contract_doc(),
        ),
        PromptCatalogItem(
            id="contract.placeholders",
            step="runtime",
            title="占位符总表",
            content=_placeholder_table(),
        ),
        PromptCatalogItem(
            id="contract.review_type_values",
            step="review",
            title="校审输出 type 枚举（REVIEW_TYPE_VALUES）",
            content=repr(REVIEW_TYPE_VALUES),
        ),
        PromptCatalogItem(
            id="contract.review_assembly_labels",
            step="review",
            title="校审参数摘要拼装标签",
            content=_review_assembly_labels(),
        ),
        PromptCatalogItem(
            id="contract.framework_user",
            step="framework",
            title="框架生成 · user 模板（完整生成）",
            content=FRAMEWORK_USER_TEMPLATE,
        ),
        PromptCatalogItem(
            id="contract.framework_user_points",
            step="framework",
            title="框架生成 · user 模板（仅用户要点）",
            content=FRAMEWORK_USER_EXTRA_POINTS_TEMPLATE
            + "\n\n（{current_framework_str}、{points_str} 由运行时注入）",
        ),
        PromptCatalogItem(
            id="contract.chapter_outline_user",
            step="chapter_outline",
            title="章节小节大纲 · user 模板",
            content=CHAPTER_OUTLINE_USER_TEMPLATE
            + "\n\n（{chapter_full_name}、{analyze_excerpt}、{requirements_str}、{risk_str}、{scoring_str} 由运行时注入；analyze_excerpt 经 CHAPTER_OUTLINE_ANALYZE_MAX_LEN 截断）",
        ),
        PromptCatalogItem(
            id="contract.chapter_content_user",
            step="chapter_content",
            title="章节正文 · user 模板",
            content=CHAPTER_CONTENT_USER_TEMPLATE
            + "\n\n（{chapter_full_name}、{outline_text}、{requirements_str}、{project_str}、{risk_str}、{scoring_str}、{context_text} 由运行时注入）",
        ),
        PromptCatalogItem(
            id="contract.chapter_regenerate_user",
            step="chapter_regenerate",
            title="章节重生成 · user 模板",
            content=CHAPTER_REGENERATE_USER_TEMPLATE
            + "\n\n（{chapter_full_name}、{current_content}、{points_str} 由运行时注入）",
        ),
        PromptCatalogItem(
            id="contract.review_user",
            step="review",
            title="校审 · user 模板",
            content=REVIEW_USER_TEMPLATE,
        ),
        PromptCatalogItem(
            id="contract.review_output_spec",
            step="review",
            title="校审 · 输出 JSON 结构（REVIEW_OUTPUT_FORMAT_SPEC）",
            content=REVIEW_OUTPUT_FORMAT_SPEC,
        ),
    ]

    semantic: list[PromptCatalogItem] = [
        PromptCatalogItem(
            id="semantic.analyze_system",
            step="analyze",
            title="分析 · system",
            content=ANALYZE_SYSTEM,
        ),
        PromptCatalogItem(
            id="semantic.analyze_user",
            step="analyze",
            title="分析 · user 模板",
            content=ANALYZE_USER_TEMPLATE,
        ),
        PromptCatalogItem(
            id="semantic.params_system",
            step="params",
            title="参数提取 · system",
            content=PARAMS_SYSTEM,
        ),
        PromptCatalogItem(
            id="semantic.params_user",
            step="params",
            title="参数提取 · user 模板",
            content=PARAMS_USER_TEMPLATE,
        ),
        PromptCatalogItem(
            id="semantic.framework_system",
            step="framework",
            title="框架生成 · system（完整生成）",
            content=FRAMEWORK_SYSTEM,
        ),
        PromptCatalogItem(
            id="semantic.framework_system_points",
            step="framework",
            title="框架生成 · system（仅用户要点）",
            content=FRAMEWORK_SYSTEM_WITH_USER_POINTS,
        ),
        PromptCatalogItem(
            id="semantic.chapter_outline_system",
            step="chapter_outline",
            title="章节小节大纲 · system",
            content=CHAPTER_OUTLINE_SYSTEM,
        ),
        PromptCatalogItem(
            id="semantic.chapter_content_system",
            step="chapter_content",
            title="章节正文 · system",
            content=CHAPTER_CONTENT_SYSTEM,
        ),
        PromptCatalogItem(
            id="semantic.chapter_regenerate_system",
            step="chapter_regenerate",
            title="章节重生成 · system",
            content=CHAPTER_REGENERATE_SYSTEM,
        ),
        PromptCatalogItem(
            id="semantic.review_system",
            step="review",
            title="校审 · system（人设示例；维度与输出格式见契约层）",
            content=REVIEW_SYSTEM_SEMANTIC_CATALOG_DISPLAY,
        ),
    ]

    return PromptCatalogResponse(contract_items=contract, semantic_items=semantic)
