"""Celery task: parse uploaded document and write text to extract step."""
import json
import logging

from app import config
from app.database import SessionLocal
from app.models import TaskStep
from app.parser import parse_document
from celery_app import app
from sqlalchemy.orm import Session

from tasks.scope_guard import validate_task_scope

logger = logging.getLogger(__name__)


def _get_or_create_extract_step(db: Session, task_id: int) -> TaskStep:
    extract_step = (
        db.query(TaskStep)
        .filter(TaskStep.task_id == task_id, TaskStep.step_key == "extract")
        .first()
    )
    if not extract_step:
        extract_step = TaskStep(task_id=task_id, step_key="extract", status="pending")
        db.add(extract_step)
        db.flush()
    return extract_step


def _set_extract_failed(db: Session, task_id: int, error_message: str) -> None:
    step = _get_or_create_extract_step(db, task_id)
    step.status = "failed"
    step.error_message = error_message
    step.output_snapshot = None
    db.commit()


@app.task
def run_extract(task_id: int, tenant_id: str | None = None, user_id: str | None = None) -> None:
    """Parse uploaded file for task and write text to extract step.

    Reads upload step output_snapshot (stored_path), calls parse_document,
    then creates/updates extract step with output_snapshot={"text": "..."}.
    On failure sets extract step status=failed and error_message.
    """
    db: Session = SessionLocal()
    try:
        task = validate_task_scope(
            db,
            task_id,
            tenant_id,
            user_id,
            logger=logger,
            task_name="run_extract",
            on_failed=lambda msg: _set_extract_failed(db, task_id, msg),
        )
        if not task:
            return

        upload_step = (
            db.query(TaskStep)
            .filter(
                TaskStep.task_id == task_id,
                TaskStep.step_key == "upload",
            )
            .first()
        )
        if not upload_step or upload_step.status != "completed" or not upload_step.output_snapshot:
            _set_extract_failed(db, task_id, "请先完成上传")
            return

        try:
            output = json.loads(upload_step.output_snapshot)
        except (json.JSONDecodeError, TypeError):
            _set_extract_failed(db, task_id, "上传步骤输出格式异常")
            return

        stored_path = output.get("stored_path")
        if not stored_path or not isinstance(stored_path, str):
            _set_extract_failed(db, task_id, "上传步骤缺少 stored_path")
            return

        # SEC-07: 规范化并限制在 UPLOAD_DIR 内，防止路径穿越
        upload_root = config.UPLOAD_DIR.resolve()
        try:
            absolute_path = (upload_root / stored_path).resolve()
        except (OSError, ValueError):
            _set_extract_failed(db, task_id, "存储路径非法")
            return
        try:
            absolute_path.relative_to(upload_root)
        except ValueError:
            _set_extract_failed(db, task_id, "存储路径非法（越界）")
            return

        if not absolute_path.exists():
            _set_extract_failed(db, task_id, f"文件不存在: {stored_path}")
            return

        text = parse_document(absolute_path)

        extract_step = _get_or_create_extract_step(db, task_id)
        extract_step.output_snapshot = json.dumps({"text": text}, ensure_ascii=False)
        extract_step.status = "completed"
        extract_step.error_message = None
        db.commit()
        logger.info("run_extract: task_id=%s extract completed, text length=%s", task_id, len(text))
    except Exception as e:
        logger.exception("run_extract: task_id=%s failed", task_id)
        try:
            db.rollback()
            step = _get_or_create_extract_step(db, task_id)
            step.status = "failed"
            step.error_message = str(e)[:2000]
            step.output_snapshot = None
            db.commit()
        except Exception:
            db.rollback()
            raise
    finally:
        db.close()
