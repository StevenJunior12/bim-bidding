"""Celery task: run review (校审) for each chapter after chapters step is completed.

Per chapter: KB search -> build_review_messages -> call_llm -> parse_review_output;
writes result to review step output_snapshot = {"chapters": {"1": [...], "2": [...]}}.
"""
import json
import logging

from app import config
from app.database import SessionLocal

from app.llm import call_llm
from app.models import TaskStep
from app.params_compat import extract_requirements_list
from app.prompt_merge import load_merged_semantic_for_task
from app.prompts import build_review_messages, parse_review_output
from app.review_prompt_assembly import (
    REVIEW_PARAMS_SECTION_KEY_REQUIREMENTS,
    REVIEW_PARAMS_SECTION_PROJECT,
    REVIEW_PARAMS_SECTION_RISK,
    REVIEW_PARAMS_SECTION_SCORING,
)
from celery_app import app
from sqlalchemy.orm import Session
from tasks.scope_guard import validate_task_scope

logger = logging.getLogger(__name__)


REVIEW_TEMPERATURE = 0.2
ERROR_MESSAGE_MAX_LEN = 2000
PARAMS_SUMMARY_MAX_LEN = 6000


def _get_or_create_review_step(db: Session, task_id: int) -> TaskStep:
    step = (
        db.query(TaskStep)
        .filter(TaskStep.task_id == task_id, TaskStep.step_key == "review")
        .first()
    )
    if not step:
        step = TaskStep(task_id=task_id, step_key="review", status="pending")
        db.add(step)
        db.flush()
    return step


def _set_review_failed(db: Session, task_id: int, error_message: str) -> None:
    step = _get_or_create_review_step(db, task_id)
    step.status = "failed"
    step.error_message = (error_message[:ERROR_MESSAGE_MAX_LEN] if error_message else None)
    db.commit()


def _build_params_summary(params_out: dict) -> str:
    """Build a single string from risk_points, key_requirements (legacy bim_requirements), scoring_items."""
    parts = []
    risk_points = params_out.get("risk_points")
    if isinstance(risk_points, list) and risk_points:
        parts.append(REVIEW_PARAMS_SECTION_RISK + "\n" + "\n".join(str(x) for x in risk_points if x))
    key_req = extract_requirements_list(params_out)
    if key_req:
        parts.append(REVIEW_PARAMS_SECTION_KEY_REQUIREMENTS + "\n" + "\n".join(str(x) for x in key_req))
    scoring_items = params_out.get("scoring_items")
    if isinstance(scoring_items, list) and scoring_items:
        parts.append(REVIEW_PARAMS_SECTION_SCORING + "\n" + "\n".join(str(x) for x in scoring_items if x))
    project_info = params_out.get("project_info")
    if isinstance(project_info, dict) and project_info:
        parts.append(REVIEW_PARAMS_SECTION_PROJECT + "\n" + json.dumps(project_info, ensure_ascii=False, indent=2))
    text = "\n\n".join(parts) if parts else "（无）"
    return text.strip()[:PARAMS_SUMMARY_MAX_LEN]


@app.task
def run_review(task_id: int, tenant_id: str | None = None, user_id: str | None = None) -> None:
    """Run review for all chapters. Requires chapters step completed; reads analyze, params, framework.

    For each chapter: KB search -> build_review_messages -> call_llm -> parse_review_output.
    On success sets review step status=completed and output_snapshot={"chapters": {"1": [...], ...}}.
    On failure sets status=failed and error_message.
    """
    db: Session = SessionLocal()
    try:
        task = validate_task_scope(
            db,
            task_id,
            tenant_id,
            user_id,
            logger=logger,
            task_name="run_review",
            on_failed=lambda msg: _set_review_failed(db, task_id, msg),
        )
        if not task:
            return

        chapters_step = (
            db.query(TaskStep)
            .filter(TaskStep.task_id == task_id, TaskStep.step_key == "chapters")
            .first()
        )
        if not chapters_step or chapters_step.status != "completed" or not chapters_step.output_snapshot:
            _set_review_failed(db, task_id, "请先完成按章生成")
            return

        analyze_step = (
            db.query(TaskStep)
            .filter(TaskStep.task_id == task_id, TaskStep.step_key == "analyze")
            .first()
        )
        if not analyze_step or analyze_step.status != "completed" or not analyze_step.output_snapshot:
            _set_review_failed(db, task_id, "请先完成分析")
            return

        params_step = (
            db.query(TaskStep)
            .filter(TaskStep.task_id == task_id, TaskStep.step_key == "params")
            .first()
        )
        if not params_step or params_step.status != "completed" or not params_step.output_snapshot:
            _set_review_failed(db, task_id, "请先完成参数提取")
            return

        framework_step = (
            db.query(TaskStep)
            .filter(TaskStep.task_id == task_id, TaskStep.step_key == "framework")
            .first()
        )
        if not framework_step or framework_step.status != "completed" or not framework_step.output_snapshot:
            _set_review_failed(db, task_id, "请先完成框架并接受框架")
            return

        try:
            fw_out = json.loads(framework_step.output_snapshot)
        except (json.JSONDecodeError, TypeError):
            _set_review_failed(db, task_id, "框架步骤输出格式异常")
            return

        chapters_list = fw_out.get("chapters")
        if not isinstance(chapters_list, list) or not chapters_list:
            _set_review_failed(db, task_id, "框架无章节列表")
            return

        try:
            ch_out = json.loads(chapters_step.output_snapshot)
        except (json.JSONDecodeError, TypeError):
            _set_review_failed(db, task_id, "按章生成步骤输出格式异常")
            return

        chapters_content = ch_out.get("chapters")
        if not isinstance(chapters_content, dict):
            _set_review_failed(db, task_id, "按章生成步骤无章节内容")
            return

        try:
            analyze_out = json.loads(analyze_step.output_snapshot)
            analyze_text = str(analyze_out.get("text", ""))[: config.CHAPTER_OUTLINE_ANALYZE_MAX_LEN]
        except (json.JSONDecodeError, TypeError):
            _set_review_failed(db, task_id, "分析步骤输出格式异常")
            return

        try:
            params_out = json.loads(params_step.output_snapshot)
            params_summary = _build_params_summary(params_out)
        except (json.JSONDecodeError, TypeError):
            _set_review_failed(db, task_id, "参数步骤输出格式异常")
            return

        review_step = _get_or_create_review_step(db, task_id)
        review_step.status = "running"
        review_step.error_message = None
        db.commit()

        from app.llm_resolver import get_llm_for_step

        provider, model = get_llm_for_step("review")
        merged = load_merged_semantic_for_task(db, task_id)
        selected = sorted(chapters_list, key=lambda ch: ch.get("number", 0))
        results_by_chapter: dict[str, list] = {}

        for ch in selected:
            num = ch.get("number")
            full_name = ch.get("full_name") or f"第{num}章 {ch.get('title', '')}"
            chapter_content = chapters_content.get(str(num)) or ""

            try:
                messages = build_review_messages(
                    chapter_full_name=full_name,
                    chapter_content=chapter_content,
                    analyze_text=analyze_text,
                    params_review_context=params_summary,
                    kb_context="",
                    semantic_overrides=merged,
                )
                llm_text = call_llm(
                    provider=provider,
                    model=model,
                    messages=messages,
                    temperature=REVIEW_TEMPERATURE,
                    prompt_step="review",
                    task_id=task_id,
                )
                items = parse_review_output(llm_text)
                results_by_chapter[str(num)] = items
            except Exception as e:
                logger.exception("run_review: task_id=%s chapter %s failed", task_id, num)
                _set_review_failed(db, task_id, f"第{num}章审查失败: {str(e)[:500]}")
                return

            logger.info("run_review: task_id=%s chapter %s done", task_id, num)

        review_step = _get_or_create_review_step(db, task_id)
        review_step.output_snapshot = json.dumps({"chapters": results_by_chapter}, ensure_ascii=False)
        review_step.status = "completed"
        review_step.error_message = None
        db.commit()
        logger.info("run_review: task_id=%s all chapters reviewed", task_id)
    except Exception as e:
        logger.exception("run_review: task_id=%s failed", task_id)
        try:
            db.rollback()
            _set_review_failed(db, task_id, str(e)[:ERROR_MESSAGE_MAX_LEN])
        except Exception:
            db.rollback()
            raise
    finally:
        db.close()


@app.task
def run_review_chapter(
    task_id: int,
    chapter_number: int,
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> None:
    """Run review for a single chapter. Merges result into review step output_snapshot.

    Same pre-checks as run_review; validates chapter_number exists in framework and chapters.
    On success updates only output_snapshot["chapters"][str(chapter_number)], leaves other keys unchanged.
    """
    db: Session = SessionLocal()
    try:
        task = validate_task_scope(
            db,
            task_id,
            tenant_id,
            user_id,
            logger=logger,
            task_name="run_review_chapter",
            on_failed=lambda msg: _set_review_failed(db, task_id, msg),
        )
        if not task:
            return

        chapters_step = (
            db.query(TaskStep)
            .filter(TaskStep.task_id == task_id, TaskStep.step_key == "chapters")
            .first()
        )
        if not chapters_step or chapters_step.status != "completed" or not chapters_step.output_snapshot:
            _set_review_failed(db, task_id, "请先完成按章生成")
            return

        analyze_step = (
            db.query(TaskStep)
            .filter(TaskStep.task_id == task_id, TaskStep.step_key == "analyze")
            .first()
        )
        if not analyze_step or analyze_step.status != "completed" or not analyze_step.output_snapshot:
            _set_review_failed(db, task_id, "请先完成分析")
            return

        params_step = (
            db.query(TaskStep)
            .filter(TaskStep.task_id == task_id, TaskStep.step_key == "params")
            .first()
        )
        if not params_step or params_step.status != "completed" or not params_step.output_snapshot:
            _set_review_failed(db, task_id, "请先完成参数提取")
            return

        framework_step = (
            db.query(TaskStep)
            .filter(TaskStep.task_id == task_id, TaskStep.step_key == "framework")
            .first()
        )
        if not framework_step or framework_step.status != "completed" or not framework_step.output_snapshot:
            _set_review_failed(db, task_id, "请先完成框架并接受框架")
            return

        try:
            fw_out = json.loads(framework_step.output_snapshot)
        except (json.JSONDecodeError, TypeError):
            _set_review_failed(db, task_id, "框架步骤输出格式异常")
            return

        chapters_list = fw_out.get("chapters")
        if not isinstance(chapters_list, list) or not chapters_list:
            _set_review_failed(db, task_id, "框架无章节列表")
            return

        ch_info = next((c for c in chapters_list if c.get("number") == chapter_number), None)
        if not ch_info:
            _set_review_failed(db, task_id, f"框架中无第{chapter_number}章")
            return

        try:
            ch_out = json.loads(chapters_step.output_snapshot)
        except (json.JSONDecodeError, TypeError):
            _set_review_failed(db, task_id, "按章生成步骤输出格式异常")
            return

        chapters_content = ch_out.get("chapters")
        if not isinstance(chapters_content, dict) or str(chapter_number) not in chapters_content:
            _set_review_failed(db, task_id, "按章生成步骤无该章内容")
            return

        try:
            analyze_out = json.loads(analyze_step.output_snapshot)
            analyze_text = str(analyze_out.get("text", ""))[: config.CHAPTER_OUTLINE_ANALYZE_MAX_LEN]
        except (json.JSONDecodeError, TypeError):
            _set_review_failed(db, task_id, "分析步骤输出格式异常")
            return

        try:
            params_out = json.loads(params_step.output_snapshot)
            params_summary = _build_params_summary(params_out)
        except (json.JSONDecodeError, TypeError):
            _set_review_failed(db, task_id, "参数步骤输出格式异常")
            return

        full_name = ch_info.get("full_name") or f"第{chapter_number}章 {ch_info.get('title', '')}"
        chapter_content = chapters_content.get(str(chapter_number)) or ""

        review_step = _get_or_create_review_step(db, task_id)
        review_step.status = "running"
        review_step.error_message = None
        db.commit()

        from app.llm_resolver import get_llm_for_step

        provider, model = get_llm_for_step("review")
        merged = load_merged_semantic_for_task(db, task_id)

        try:
            messages = build_review_messages(
                chapter_full_name=full_name,
                chapter_content=chapter_content,
                analyze_text=analyze_text,
                params_review_context=params_summary,
                kb_context="",
            )
            llm_text = call_llm(
                provider=provider,
                model=model,
                messages=messages,
                temperature=REVIEW_TEMPERATURE,
                prompt_step="review",
                task_id=task_id,
            )
            items = parse_review_output(llm_text)
        except Exception as e:
            logger.exception("run_review_chapter: task_id=%s chapter %s failed", task_id, chapter_number)
            _set_review_failed(db, task_id, f"第{chapter_number}章审查失败: {str(e)[:500]}")
            return

        logger.info("run_review_chapter: task_id=%s chapter %s done", task_id, chapter_number)

        review_step = _get_or_create_review_step(db, task_id)
        if review_step.output_snapshot:
            try:
                existing = json.loads(review_step.output_snapshot)
                results_by_chapter = existing.get("chapters")
                if not isinstance(results_by_chapter, dict):
                    results_by_chapter = {}
            except (json.JSONDecodeError, TypeError):
                results_by_chapter = {}
        else:
            results_by_chapter = {}
        results_by_chapter[str(chapter_number)] = items
        review_step.output_snapshot = json.dumps({"chapters": results_by_chapter}, ensure_ascii=False)
        review_step.status = "completed"
        review_step.error_message = None
        db.commit()
    except Exception as e:
        logger.exception("run_review_chapter: task_id=%s failed", task_id)
        try:
            db.rollback()
            _set_review_failed(db, task_id, str(e)[:ERROR_MESSAGE_MAX_LEN])
        except Exception:
            db.rollback()
            raise
    finally:
        db.close()
