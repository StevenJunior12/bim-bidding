"""Celery task: extract project_info, key_requirements, risk_points from analyze text."""
import json
import logging
import re

from app.database import SessionLocal
from app.llm import call_llm
from app.models import TaskStep
from app.params_compat import REQUIREMENTS_JSON_KEY, coalesce_requirements_from_llm_raw
from app.prompt_merge import load_merged_semantic_for_task
from app.prompts import build_params_messages
from celery_app import app
from sqlalchemy.orm import Session

from tasks.scope_guard import validate_task_scope

logger = logging.getLogger(__name__)

PARAMS_TEMPERATURE = 0.1
ERROR_MESSAGE_MAX_LEN = 2000


def _get_or_create_params_step(db: Session, task_id: int) -> TaskStep:
    params_step = (
        db.query(TaskStep)
        .filter(TaskStep.task_id == task_id, TaskStep.step_key == "params")
        .first()
    )
    if not params_step:
        params_step = TaskStep(task_id=task_id, step_key="params", status="pending")
        db.add(params_step)
        db.flush()
    return params_step


def _set_params_failed(db: Session, task_id: int, error_message: str) -> None:
    step = _get_or_create_params_step(db, task_id)
    step.status = "failed"
    step.error_message = (error_message[:ERROR_MESSAGE_MAX_LEN] if error_message else None)
    step.output_snapshot = None
    db.commit()


def _extract_json_from_response(text: str) -> str:
    """Strip markdown code block if present and return inner JSON string."""
    text = text.strip()
    # Match ```json ... ``` or ``` ... ```
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text


def _normalize_params(raw: dict) -> dict:
    """Ensure project_info (dict), key_requirements (list[str]), risk_points (list[str]), scoring_items (list[str]);
    optional: construction_goals, standards_refs, deliverables (list[str] each).

    Accepts LLM output with key_requirements or legacy bim_requirements; persists only key_requirements.
    """
    project_info = raw.get("project_info")
    if project_info is None:
        project_info = {}
    elif isinstance(project_info, str):
        try:
            project_info = json.loads(project_info) if project_info.strip() else {}
        except json.JSONDecodeError:
            project_info = {"raw": project_info}
    if not isinstance(project_info, dict):
        project_info = {}

    key_requirements = coalesce_requirements_from_llm_raw(raw)

    risk_points = raw.get("risk_points")
    if not isinstance(risk_points, list):
        risk_points = []
    risk_points = [str(x) for x in risk_points]

    scoring_items = raw.get("scoring_items")
    if not isinstance(scoring_items, list):
        scoring_items = []
    scoring_items = [str(x) for x in scoring_items if x]

    def _str_list(key: str) -> list[str]:
        val = raw.get(key)
        if not isinstance(val, list):
            return []
        return [str(x) for x in val if x]

    construction_goals = _str_list("construction_goals")
    standards_refs = _str_list("standards_refs")
    deliverables = _str_list("deliverables")

    return {
        "project_info": project_info,
        REQUIREMENTS_JSON_KEY: key_requirements,
        "risk_points": risk_points,
        "scoring_items": scoring_items,
        "construction_goals": construction_goals,
        "standards_refs": standards_refs,
        "deliverables": deliverables,
    }


@app.task
def run_params(task_id: int, tenant_id: str | None = None, user_id: str | None = None) -> None:
    """Extract params from analyze step text and write to params step.

    Reads analyze step output_snapshot["text"], calls LLM with params prompt,
    parses JSON, normalizes to project_info / key_requirements / risk_points,
    then creates/updates params step with output_snapshot. On failure sets
    params step status=failed and error_message.
    """
    db: Session = SessionLocal()
    try:
        task = validate_task_scope(
            db,
            task_id,
            tenant_id,
            user_id,
            logger=logger,
            task_name="run_params",
            on_failed=lambda msg: _set_params_failed(db, task_id, msg),
        )
        if not task:
            return

        analyze_step = (
            db.query(TaskStep)
            .filter(
                TaskStep.task_id == task_id,
                TaskStep.step_key == "analyze",
            )
            .first()
        )
        if not analyze_step or analyze_step.status != "completed" or not analyze_step.output_snapshot:
            _set_params_failed(db, task_id, "请先完成分析")
            return

        try:
            output = json.loads(analyze_step.output_snapshot)
        except (json.JSONDecodeError, TypeError):
            _set_params_failed(db, task_id, "分析步骤输出格式异常")
            return

        analyze_text = output.get("text")
        if analyze_text is None:
            _set_params_failed(db, task_id, "分析步骤缺少 text")
            return
        analyze_text = str(analyze_text)

        merged = load_merged_semantic_for_task(db, task_id)
        messages = build_params_messages(analyze_text, semantic_overrides=merged)
        from app.llm_resolver import get_llm_for_step
        provider, model = get_llm_for_step("params")

        content = call_llm(
            provider=provider,
            model=model,
            messages=messages,
            temperature=PARAMS_TEMPERATURE,
            prompt_step="params",
            task_id=task_id,
        )

        json_str = _extract_json_from_response(content)
        try:
            raw = json.loads(json_str)
        except json.JSONDecodeError as e:
            _set_params_failed(db, task_id, f"LLM 返回非合法 JSON: {e!s}")
            return

        if not isinstance(raw, dict):
            _set_params_failed(db, task_id, "LLM 返回的 JSON 不是对象")
            return

        normalized = _normalize_params(raw)

        params_step = _get_or_create_params_step(db, task_id)
        params_step.output_snapshot = json.dumps(normalized, ensure_ascii=False)
        params_step.status = "completed"
        params_step.error_message = None
        db.commit()
        logger.info(
            "run_params: task_id=%s params completed, project_info keys=%s, key_requirements=%s, risk=%s, scoring=%s",
            task_id,
            len(normalized["project_info"]),
            len(normalized[REQUIREMENTS_JSON_KEY]),
            len(normalized["risk_points"]),
            len(normalized["scoring_items"]),
        )
    except Exception as e:
        logger.exception("run_params: task_id=%s failed", task_id)
        try:
            db.rollback()
            err_msg = str(e)[:ERROR_MESSAGE_MAX_LEN]
            _set_params_failed(db, task_id, err_msg)
        except Exception:
            db.rollback()
            raise
    finally:
        db.close()
