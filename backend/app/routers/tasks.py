"""Task CRUD, list and cancel API.

All step-specific endpoints have been extracted to dedicated router modules:
  upload.py    — file upload
  steps.py     — extract / analyze / params triggers
  framework.py — framework run / regenerate / save-points / accept / diff
  chapters.py  — chapters run / save-points / regenerate / regenerate-all / diff
  review.py    — review run / accept
  export.py    — DOCX download
"""
import logging
import shutil
from datetime import datetime

from celery_app import app as celery_app
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import config
from app.auth import Principal, get_principal
from app.database import get_db
from app.models import PromptProfile, Task, TaskStep
from app.schemas.compare import ChapterCompareMetaItem, CompareMetaResponse, FrameworkCompareMeta
from app.schemas.task import (
    DEFAULT_INITIAL_STEPS,
    CreateTaskRequest,
    CreateTaskResponse,
    TaskCompareSummary,
    TaskDetailResponse,
    TaskStepSchema,
    TaskSummary,
)
from app.services.step_service import (
    compute_compare_meta_for_task,
    compute_compare_meta_from_steps,
    require_task,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.post("", response_model=CreateTaskResponse, status_code=201)
def create_task(
    body: CreateTaskRequest | None = Body(None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """Create a task and optionally initial steps (all pending)."""
    steps_to_create = (
        body.initial_steps if body and body.initial_steps
        else DEFAULT_INITIAL_STEPS
    )
    task = Task(status="pending", tenant_id=principal.tenant_id, user_id=principal.user_id)
    db.add(task)
    db.flush()
    if body and body.name and body.name.strip():
        task.name = body.name.strip()[:255]
    else:
        task.name = f"未命名任务-{task.id}-{datetime.now().strftime('%m%d%H%M')}"
    if body and body.profile_id is not None:
        prof = (
            db.query(PromptProfile)
            .filter(
                PromptProfile.id == body.profile_id,
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
        if not prof:
            raise HTTPException(status_code=404, detail="Prompt 配置不存在")
        task.profile_id = body.profile_id
    for step_key in steps_to_create:
        step = TaskStep(task_id=task.id, step_key=step_key, status="pending")
        db.add(step)
    db.commit()
    db.refresh(task)
    profile_name: str | None = None
    if task.profile_id is not None:
        p = (
            db.query(PromptProfile)
            .filter(
                PromptProfile.id == task.profile_id,
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
        profile_name = p.name if p else None
    return CreateTaskResponse(
        id=task.id,
        name=task.name,
        status=task.status,
        created_at=task.created_at,
        profile_id=task.profile_id,
        profile_name=profile_name,
    )


@router.get("/{task_id}", response_model=TaskDetailResponse)
def get_task(
    task_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """Get task by id with steps (ordered by step id)."""
    task = require_task(task_id, db, principal)
    steps = db.query(TaskStep).filter(TaskStep.task_id == task_id).order_by(TaskStep.id).all()
    profile_name: str | None = None
    if task.profile_id is not None:
        p = (
            db.query(PromptProfile)
            .filter(
                PromptProfile.id == task.profile_id,
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
        profile_name = p.name if p else None
    return TaskDetailResponse(
        id=task.id,
        user_id=task.user_id,
        name=task.name,
        status=task.status,
        created_at=task.created_at,
        updated_at=task.updated_at,
        profile_id=task.profile_id,
        profile_name=profile_name,
        steps=[TaskStepSchema.model_validate(s) for s in steps],
    )


@router.get("/{task_id}/compare-meta", response_model=CompareMetaResponse)
def get_task_compare_meta(
    task_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """Return compare metadata for a task: which items have before/after versions."""
    require_task(task_id, db, principal)
    meta = compute_compare_meta_for_task(task_id, db)
    framework = FrameworkCompareMeta(has_diff=meta["framework_has_diff"])
    chapters_items: list[ChapterCompareMetaItem] = []
    for num in meta["chapter_numbers"]:
        chapters_items.append(
            ChapterCompareMetaItem(number=num, has_diff=True, label=f"第 {num} 章")
        )
    return CompareMetaResponse(
        has_any=meta["has_any"],
        framework=framework,
        chapters=chapters_items,
    )


@router.delete("/{task_id}", status_code=204)
def delete_task(
    task_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """Delete a task and its steps. Returns 204 No Content.

    DB records are removed first; uploaded files are cleaned up after a
    successful commit so that a failed commit never leaves orphaned DB rows.
    """
    task = require_task(task_id, db, principal)
    db.query(TaskStep).filter(TaskStep.task_id == task_id).delete()
    db.delete(task)
    db.commit()
    legacy_task_dir = config.UPLOAD_DIR / f"task_{task_id}"
    scoped_task_dir = config.UPLOAD_DIR / f"tenant_{principal.tenant_id}" / f"user_{principal.user_id}" / f"task_{task_id}"
    shutil.rmtree(legacy_task_dir, ignore_errors=True)
    shutil.rmtree(scoped_task_dir, ignore_errors=True)
    return None


@router.post("/{task_id}/cancel", status_code=200)
def cancel_task(
    task_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """Revoke the currently running Celery step for this task (e.g. one-click cancel)."""
    require_task(task_id, db, principal)
    running = (
        db.query(TaskStep)
        .filter(TaskStep.task_id == task_id, TaskStep.status == "running")
        .first()
    )
    if not running:
        return {"message": "当前无正在执行的步骤", "revoked": False}
    celery_task_id = running.celery_task_id
    revoke_error: str | None = None
    if celery_task_id:
        try:
            celery_app.control.revoke(celery_task_id, terminate=True)
        except Exception as e:
            logger.warning(
                "cancel_task: revoke failed task_id=%s celery_task_id=%s: %s",
                task_id,
                celery_task_id,
                e,
                exc_info=True,
            )
            revoke_error = str(e)[:500]
    running.status = "pending"
    running.celery_task_id = None
    db.commit()
    out: dict = {"message": "已取消当前步骤", "revoked": True, "step_key": running.step_key}
    if revoke_error:
        out["revoke_warning"] = "已向 Broker 发送撤销，但 revoke 调用报错，请查看服务端日志"
    return out


@router.get("", response_model=list[TaskSummary])
def list_tasks(
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
    profile_id: str | None = Query(
        None,
        description="Filter: PromptProfile id (integer string), or 'default' for tasks with no profile. Omit for all tasks.",
    ),
):
    """List tasks (newest first).

    Optional ``profile_id`` query: when set to a numeric id, only tasks bound to that
    PromptProfile are returned; when ``default``, only tasks with ``profile_id IS NULL``.

    Uses 3 queries total regardless of task count (avoids 1+2N pattern):
      1. SELECT tasks (optionally filtered)
      2. SELECT framework steps WHERE task_id IN (...)
      3. SELECT chapters steps WHERE task_id IN (...)
    """
    q = db.query(Task).filter(
        Task.tenant_id == principal.tenant_id,
        Task.user_id == principal.user_id,
    )
    if profile_id is not None and profile_id.strip() != "":
        key = profile_id.strip().lower()
        if key in ("default", "null", "none"):
            q = q.filter(Task.profile_id.is_(None))
        else:
            try:
                pid = int(profile_id.strip(), 10)
            except ValueError as e:
                raise HTTPException(status_code=400, detail="profile_id 须为整数或 default") from e
            p = (
                db.query(PromptProfile)
                .filter(
                    PromptProfile.id == pid,
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
            if not p:
                raise HTTPException(status_code=404, detail="Prompt 配置不存在")
            q = q.filter(Task.profile_id == pid)
    tasks = q.order_by(Task.created_at.desc()).all()
    if not tasks:
        return []

    task_ids = [t.id for t in tasks]

    profile_ids = [t.profile_id for t in tasks if t.profile_id is not None]
    profile_names: dict[int, str] = {}
    if profile_ids:
        for p in (
            db.query(PromptProfile)
            .filter(
                PromptProfile.id.in_(profile_ids),
                or_(
                    PromptProfile.is_builtin.is_(True),
                    (
                        (PromptProfile.tenant_id == principal.tenant_id)
                        & (PromptProfile.user_id == principal.user_id)
                    ),
                ),
            )
            .all()
        ):
            profile_names[p.id] = p.name

    framework_steps = (
        db.query(TaskStep)
        .filter(TaskStep.task_id.in_(task_ids), TaskStep.step_key == "framework")
        .all()
    )
    chapters_steps = (
        db.query(TaskStep)
        .filter(TaskStep.task_id.in_(task_ids), TaskStep.step_key == "chapters")
        .all()
    )

    framework_by_task: dict[int, TaskStep] = {s.task_id: s for s in framework_steps}
    chapters_by_task: dict[int, TaskStep] = {s.task_id: s for s in chapters_steps}

    summaries: list[TaskSummary] = []
    for t in tasks:
        meta = compute_compare_meta_from_steps(
            framework_by_task.get(t.id),
            chapters_by_task.get(t.id),
        )
        compare_summary: TaskCompareSummary | None = None
        if meta["has_any"]:
            compare_summary = TaskCompareSummary(
                has_framework=meta["framework_has_diff"],
                chapter_count=len(meta["chapter_numbers"]),
            )
        summaries.append(
            TaskSummary(
                id=t.id,
                name=t.name,
                status=t.status,
                created_at=t.created_at,
                profile_id=t.profile_id,
                profile_name=profile_names.get(t.profile_id) if t.profile_id else None,
                compare_summary=compare_summary,
            )
        )
    return summaries
