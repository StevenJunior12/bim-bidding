"""Built-in engineering disciplines for PromptProfile (single source of truth).

Includes **BIM** as a first-class discipline (product origin: BIM 技术标)，与建筑/机电等并列；
**智慧运维** 用于数字孪生 / 智慧运营管理平台 / 多子系统集成类采购技术标，与偏弱电集成的 **智能化** 区分；
智能生成与主/非主专业隔离逻辑均从 DISCIPLINES 推导，勿在其它处硬编码专业表。
"""

from __future__ import annotations

from typing import Final

DEFAULT_DISCIPLINE: Final[str] = "建筑"

DISCIPLINES: Final[tuple[str, ...]] = (
    "建筑",
    "BIM",
    "结构",
    "给排水",
    "暖通",
    "电气",
    "智能化",
    "智慧运维",
    "景观",
    "内装",
    "可研",
    "造价",
    "幕墙",
)

_DISCIPLINE_SET: Final[frozenset[str]] = frozenset(DISCIPLINES)


def validate_discipline(raw: str) -> str:
    """Return stripped discipline or raise ValueError."""
    if raw is None:
        raise ValueError("专业不能为空")
    s = str(raw).strip()
    if not s:
        raise ValueError("专业不能为空")
    if s not in _DISCIPLINE_SET:
        raise ValueError(f"无效的专业: {s!r}，须为内置列表中的一项")
    return s


def list_disciplines() -> list[str]:
    return list(DISCIPLINES)
