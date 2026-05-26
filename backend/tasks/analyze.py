"""Celery task: run LLM analysis on extracted text and write to analyze step."""
import json
import logging

from app.database import SessionLocal
from app.llm import call_llm
from app.models import TaskStep
from app.prompt_merge import load_merged_semantic_for_task
from app.prompts import build_analyze_messages
from celery_app import app
from sqlalchemy.orm import Session

from tasks.scope_guard import validate_task_scope

logger = logging.getLogger(__name__)

ANALYZE_TEMPERATURE = 0.2
ERROR_MESSAGE_MAX_LEN = 2000


def _get_or_create_analyze_step(db: Session, task_id: int) -> TaskStep:
    analyze_step = (
        db.query(TaskStep)
        .filter(TaskStep.task_id == task_id, TaskStep.step_key == "analyze")
        .first()
    )
    if not analyze_step:
        analyze_step = TaskStep(task_id=task_id, step_key="analyze", status="pending")
        db.add(analyze_step)
        db.flush()
    return analyze_step


def _set_analyze_failed(db: Session, task_id: int, error_message: str) -> None:
    step = _get_or_create_analyze_step(db, task_id)
    step.status = "failed"
    step.error_message = (error_message[:ERROR_MESSAGE_MAX_LEN] if error_message else None)
    step.output_snapshot = None
    db.commit()


@app.task
def run_analyze(task_id: int, tenant_id: str | None = None, user_id: str | None = None) -> None:
    """Run LLM analysis on extract step text and write result to analyze step.

    Reads extract step output_snapshot["text"], calls LLM with analyze prompts,
    then creates/updates analyze step with output_snapshot={"text": "..."}.
    On failure sets analyze step status=failed and error_message.
    """
    db: Session = SessionLocal()
    try:
        task = validate_task_scope(
            db,
            task_id,
            tenant_id,
            user_id,
            logger=logger,
            task_name="run_analyze",
            on_failed=lambda msg: _set_analyze_failed(db, task_id, msg),
        )
        if not task:
            return

        extract_step = (
            db.query(TaskStep)
            .filter(
                TaskStep.task_id == task_id,
                TaskStep.step_key == "extract",
            )
            .first()
        )
        if not extract_step or extract_step.status != "completed" or not extract_step.output_snapshot:
            _set_analyze_failed(db, task_id, "请先完成文档解析")
            return

        try:
            output = json.loads(extract_step.output_snapshot)
        except (json.JSONDecodeError, TypeError):
            _set_analyze_failed(db, task_id, "解析步骤输出格式异常")
            return

        extracted_text = output.get("text")
        if extracted_text is None:
            _set_analyze_failed(db, task_id, "解析步骤缺少 text")
            return
        extracted_text = str(extracted_text)

        merged = load_merged_semantic_for_task(db, task_id)
        messages = build_analyze_messages(extracted_text, semantic_overrides=merged)
        from app.llm_resolver import get_llm_for_step
        provider, model = get_llm_for_step("analyze")

        content = call_llm(
            provider=provider,
            model=model,
            messages=messages,
            temperature=ANALYZE_TEMPERATURE,
            prompt_step="analyze",
            task_id=task_id,
        )

        analyze_step = _get_or_create_analyze_step(db, task_id)
        analyze_step.output_snapshot = json.dumps({"text": content}, ensure_ascii=False)
        analyze_step.status = "completed"
        analyze_step.error_message = None
        db.commit()
        logger.info(
            "run_analyze: task_id=%s analyze completed, output length=%s",
            task_id,
            len(content),
        )
    except Exception as e:
        logger.exception("run_analyze: task_id=%s failed", task_id)
        try:
            db.rollback()
            err_msg = str(e)[:ERROR_MESSAGE_MAX_LEN]
            _set_analyze_failed(db, task_id, err_msg)
        except Exception:
            db.rollback()
            raise
    finally:
        db.close()
