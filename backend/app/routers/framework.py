"""Framework step endpoints: run, regenerate, save-points, accept, diff."""
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from tasks.framework import run_framework

from app.auth import Principal, get_principal
from app.database import get_db
from app.diff_compare import compute_diff
from app.models import TaskStep
from app.params_compat import params_snapshot_has_requirements_list
from app.schemas.compare import DiffResponse
from app.schemas.task import AcceptFrameworkRequest
from app.services.step_service import (
    dispatch_celery_step,
    framework_snapshot_to_text,
    get_or_create_step,
    require_step_completed,
    require_task,
)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.post("/{task_id}/steps/framework/run", status_code=202)
def run_framework_step(
    task_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """Enqueue framework generation. Requires params step completed."""
    require_task(task_id, db, principal)

    params_step = require_step_completed(task_id, "params", db, "请先完成参数提取")
    try:
        output = json.loads(params_step.output_snapshot)  # type: ignore[arg-type]
        if not params_snapshot_has_requirements_list(output):
            raise HTTPException(status_code=400, detail="请先完成参数提取")
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(status_code=400, detail="请先完成参数提取")

    step = get_or_create_step(task_id, "framework", db)
    if step.status == "running":
        return {"message": "框架生成已在进行中", "step_key": "framework"}
    dispatch_celery_step(step, run_framework, db, principal, task_id)
    return {"message": "框架已入队", "step_key": "framework"}


@router.post("/{task_id}/steps/framework/regenerate", status_code=202)
def regenerate_framework_step(
    task_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """Re-enqueue framework generation when status is waiting_user."""
    require_task(task_id, db, principal)

    framework_step = (
        db.query(TaskStep)
        .filter(TaskStep.task_id == task_id, TaskStep.step_key == "framework")
        .first()
    )
    if not framework_step:
        raise HTTPException(status_code=400, detail="未找到框架步骤")
    if framework_step.status == "running":
        return {"message": "框架生成已在进行中", "step_key": "framework"}
    if framework_step.status != "waiting_user":
        raise HTTPException(status_code=400, detail="仅当框架等待审核时可重新生成")

    dispatch_celery_step(framework_step, run_framework, db, principal, task_id)
    return {"message": "框架已重新入队", "step_key": "framework"}


@router.post("/{task_id}/steps/framework/save-points", status_code=200)
def save_framework_points(
    task_id: int,
    body: AcceptFrameworkRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """Save user points for the framework (status remains waiting_user)."""
    require_task(task_id, db, principal)

    framework_step = (
        db.query(TaskStep)
        .filter(TaskStep.task_id == task_id, TaskStep.step_key == "framework")
        .first()
    )
    if not framework_step:
        raise HTTPException(status_code=400, detail="未找到框架步骤")
    if framework_step.status != "waiting_user":
        raise HTTPException(status_code=400, detail="仅当框架等待审核时可保存要点")

    output: dict = {}
    if framework_step.output_snapshot:
        try:
            output = json.loads(framework_step.output_snapshot)
            if not isinstance(output, dict):
                output = {}
        except (json.JSONDecodeError, TypeError):
            output = {}
    output["extra_points"] = body.added_points
    framework_step.output_snapshot = json.dumps(output, ensure_ascii=False)
    db.commit()
    return {"message": "已保存要点", "step_key": "framework"}


@router.post("/{task_id}/steps/framework/accept", status_code=200)
def accept_framework_step(
    task_id: int,
    body: AcceptFrameworkRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """Accept framework and transition step to completed. Only valid when status is waiting_user."""
    require_task(task_id, db, principal)

    framework_step = (
        db.query(TaskStep)
        .filter(TaskStep.task_id == task_id, TaskStep.step_key == "framework")
        .first()
    )
    if not framework_step:
        raise HTTPException(status_code=400, detail="未找到框架步骤")
    if framework_step.status != "waiting_user":
        raise HTTPException(status_code=400, detail="仅当框架等待审核时可接受")

    output: dict = {}
    if framework_step.output_snapshot:
        try:
            output = json.loads(framework_step.output_snapshot)
            if not isinstance(output, dict):
                output = {}
        except (json.JSONDecodeError, TypeError):
            output = {}
    if body.added_points:
        output["extra_points"] = body.added_points
    framework_step.output_snapshot = json.dumps(output, ensure_ascii=False)
    framework_step.status = "completed"
    framework_step.error_message = None
    db.commit()
    return {"message": "已接受并继续", "step_key": "framework"}


@router.get("/{task_id}/steps/framework/diff", response_model=DiffResponse)
def get_framework_diff(
    task_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """Return last framework regenerate: original vs modified text and structured diff."""
    require_task(task_id, db, principal)
    framework_step = (
        db.query(TaskStep)
        .filter(TaskStep.task_id == task_id, TaskStep.step_key == "framework")
        .first()
    )
    if not framework_step:
        raise HTTPException(status_code=404, detail="未找到框架步骤")
    original_text = framework_snapshot_to_text(framework_step.output_snapshot_before_regenerate)
    modified_text = framework_snapshot_to_text(framework_step.output_snapshot)
    if not original_text and not modified_text:
        raise HTTPException(
            status_code=404,
            detail="无框架重生成前后数据，请先执行一次「重新生成框架」后再查看对比",
        )
    diff = compute_diff(original_text, modified_text)
    return DiffResponse(original=original_text, modified=modified_text, diff=diff)
