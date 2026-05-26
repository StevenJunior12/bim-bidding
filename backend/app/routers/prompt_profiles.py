"""CRUD API for user-defined prompt profiles (semantic overrides)."""
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import Principal, get_principal
from app.database import get_db
from app.disciplines import list_disciplines, validate_discipline
from app.models import PromptProfile
from app.prompt_profile_generate import generate_all_semantic_slots, generate_one_semantic_slot
from app.prompt_profile_validate import validate_semantic_overrides_for_save
from app.schemas.prompt_profile import (
    GenerateSemanticRequest,
    GenerateSemanticResponse,
    PromptProfileCreate,
    PromptProfileDetail,
    PromptProfileSummary,
    PromptProfileUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/prompt-profiles", tags=["prompt-profiles"])


@router.get("/disciplines")
def get_disciplines():
    return {"items": list_disciplines()}


@router.post("/generate-semantic", response_model=GenerateSemanticResponse)
def post_generate_semantic(body: GenerateSemanticRequest):
    try:
        disc = validate_discipline(body.discipline)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    name = body.profile_name.strip()[:255]
    if not name:
        raise HTTPException(status_code=400, detail="配置名称不能为空")
    sk = body.slot_key
    if sk is not None:
        sk = sk.strip()
        if not sk:
            sk = None
    try:
        if sk is None:
            overrides = generate_all_semantic_slots(profile_name=name, discipline=disc)
            return GenerateSemanticResponse(overrides=overrides)
        text = generate_one_semantic_slot(
            profile_name=name,
            discipline=disc,
            slot_key=sk,
        )
        return GenerateSemanticResponse(slot_key=sk, text=text)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("generate-semantic failed")
        raise HTTPException(
            status_code=502,
            detail=str(e)[:500] if str(e) else "智能生成失败",
        ) from e


def _require_mutable(profile: PromptProfile, principal: Principal) -> None:
    if profile.is_builtin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="内置配置不可修改或删除",
        )
    if profile.tenant_id != principal.tenant_id or profile.user_id != principal.user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="配置不存在")


@router.get("", response_model=list[PromptProfileSummary])
def list_prompt_profiles(
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    rows = (
        db.query(PromptProfile)
        .filter(
            or_(
                PromptProfile.is_builtin.is_(True),
                (
                    (PromptProfile.tenant_id == principal.tenant_id)
                    & (PromptProfile.user_id == principal.user_id)
                ),
            )
        )
        .order_by(PromptProfile.updated_at.desc())
        .all()
    )
    return [PromptProfileSummary.model_validate(r) for r in rows]


@router.get("/{profile_id}", response_model=PromptProfileDetail)
def get_prompt_profile(
    profile_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    row = (
        db.query(PromptProfile)
        .filter(
            PromptProfile.id == profile_id,
            or_(
                PromptProfile.is_builtin.is_(True),
                (
                    (PromptProfile.tenant_id == principal.tenant_id)
                    & (PromptProfile.user_id == principal.user_id)
                ),
            ),
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="配置不存在")
    return PromptProfileDetail.model_validate(row)


@router.post("", response_model=PromptProfileDetail, status_code=201)
def create_prompt_profile(
    body: PromptProfileCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    try:
        overrides = validate_semantic_overrides_for_save(body.semantic_overrides)
        disc = validate_discipline(body.discipline)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    row = PromptProfile(
        name=body.name.strip()[:255],
        slug=(body.slug.strip()[:128] if body.slug and body.slug.strip() else None),
        discipline=disc,
        is_builtin=False,
        semantic_overrides=overrides,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        logger.warning("create_prompt_profile: integrity error: %s", e)
        raise HTTPException(status_code=400, detail="名称或 slug 已存在") from e
    db.refresh(row)
    return PromptProfileDetail.model_validate(row)


@router.patch("/{profile_id}", response_model=PromptProfileDetail)
def update_prompt_profile(
    profile_id: int,
    body: PromptProfileUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    row = (
        db.query(PromptProfile)
        .filter(
            PromptProfile.id == profile_id,
            or_(
                PromptProfile.is_builtin.is_(True),
                (
                    (PromptProfile.tenant_id == principal.tenant_id)
                    & (PromptProfile.user_id == principal.user_id)
                ),
            ),
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="配置不存在")
    _require_mutable(row, principal)
    patch = body.model_dump(exclude_unset=True)
    if "name" in patch:
        row.name = str(patch["name"]).strip()[:255]
    if "slug" in patch:
        s = patch["slug"]
        row.slug = str(s).strip()[:128] if s is not None and str(s).strip() else None
    if "discipline" in patch:
        try:
            row.discipline = validate_discipline(str(patch["discipline"]))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    if "semantic_overrides" in patch:
        try:
            row.semantic_overrides = validate_semantic_overrides_for_save(patch["semantic_overrides"])
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        logger.warning("update_prompt_profile: integrity error: %s", e)
        raise HTTPException(status_code=400, detail="slug 冲突") from e
    db.refresh(row)
    return PromptProfileDetail.model_validate(row)


@router.delete("/{profile_id}", status_code=204)
def delete_prompt_profile(
    profile_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    row = (
        db.query(PromptProfile)
        .filter(
            PromptProfile.id == profile_id,
            or_(
                PromptProfile.is_builtin.is_(True),
                (
                    (PromptProfile.tenant_id == principal.tenant_id)
                    & (PromptProfile.user_id == principal.user_id)
                ),
            ),
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="配置不存在")
    _require_mutable(row, principal)
    db.delete(row)
    db.commit()
    return None
