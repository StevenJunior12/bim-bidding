"""Pluggable knowledge base search for framework and chapter generation.

Abstract interface: search(query, top_k) -> list[str].
Adapters: ragflow (RAGFlow /api/v1/retrieval); none = return [].
"""
import logging
from collections.abc import Callable

import httpx

from app import config
from app.settings_store import get_kb_config, get_ragflow_effective
from app.url_safety import validate_ragflow_base_url

logger = logging.getLogger(__name__)

# Type for search implementation: (query, top_k) -> list[str]
SearchFn = Callable[[str, int], list[str]]


def _search_none(_query: str, _top_k: int) -> list[str]:
    """No retrieval; return empty list."""
    return []


def _resolve_scope_from_task(task_id: int | None) -> tuple[str | None, str | None]:
    if task_id is None:
        return None, None
    from app.database import SessionLocal
    from app.models import Task

    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            return None, None
        return task.tenant_id, task.user_id
    finally:
        db.close()


def _search_ragflow(query: str, top_k: int = 10, *, task_id: int | None = None) -> list[str]:
    """RAGFlow adapter: POST /api/v1/retrieval, parse response to list of text chunks. Config from DB then env."""
    tenant_id, user_id = _resolve_scope_from_task(task_id)
    effective = get_ragflow_effective(tenant_id=tenant_id, user_id=user_id)
    if not effective:
        logger.info("RAGFlow not configured: missing RAGFLOW_API_URL, RAGFLOW_API_KEY or RAGFLOW_DATASET_IDS")
        return []
    base_url, api_key, dataset_ids = effective
    url = f"{base_url}/api/v1/retrieval"
    payload = {
        "question": query,
        "dataset_ids": dataset_ids,
        "page_size": top_k,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        logger.warning("RAGFlow retrieve HTTP error: %s %s", e.response.status_code, e.response.text[:200])
        return []
    except Exception as e:
        logger.warning("RAGFlow retrieve failed: %s", e)
        return []

    if not isinstance(data, dict):
        logger.warning("RAGFlow retrieve: response is not a dict")
        return []
    if data.get("code") != 0:
        logger.warning("RAGFlow retrieve: code=%s", data.get("code"))
        return []
    raw_list = data.get("data", {}).get("chunks") if isinstance(data.get("data"), dict) else None
    if not isinstance(raw_list, list):
        return []
    chunks: list[str] = []
    for item in raw_list:
        if isinstance(item, dict):
            text = item.get("content")
            if isinstance(text, str) and text.strip():
                chunks.append(text.strip())
    return chunks


def get_search_fn(task_id: int | None = None) -> SearchFn:
    """Return the search implementation based on effective kb_type (DB then env)."""
    tenant_id, user_id = _resolve_scope_from_task(task_id)
    kb_config = get_kb_config(tenant_id=tenant_id, user_id=user_id)
    kb_type = kb_config.get("kb_type") or config.KNOWLEDGE_BASE_TYPE
    if kb_type == "ragflow":
        return lambda q, k: _search_ragflow(q, k, task_id=task_id)
    if kb_type == "internal":
        collection_id = kb_config.get("internal_collection_id")
        if collection_id:
            scoped_tenant_id = tenant_id or config.AUTH_DEFAULT_TENANT_ID
            scoped_user_id = user_id or config.AUTH_DEFAULT_USER_ID
            return lambda q, k: _search_internal(
                q,
                k,
                collection_id=int(collection_id),
                tenant_id=scoped_tenant_id,
                user_id=scoped_user_id,
            )
        logger.warning("Internal KB selected but no collection configured")
        return _search_none
    return _search_none


def _search_internal(
    query: str,
    top_k: int,
    *,
    collection_id: int,
    tenant_id: str,
    user_id: str,
) -> list[str]:
    try:
        from app.kb_search import search_internal

        results = search_internal(
            query,
            top_k,
            collection_id=collection_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        return [result.content for result in results]
    except Exception as e:
        logger.warning("Internal KB search failed: %s", e)
        return []


def search(query: str, top_k: int = 10, *, task_id: int | None = None) -> list[str]:
    """Search knowledge base; returns list of text chunks. Never raises; returns [] on misconfig or error."""
    return get_search_fn(task_id=task_id)(query, top_k)


def test_ragflow_connection(base_url: str, api_key: str) -> tuple[bool, str]:
    """Test RAGFlow connectivity: GET /api/v1/datasets with page_size=1. Returns (success, message)."""
    if not (base_url and (base_url or "").strip()) or not (api_key and (api_key or "").strip()):
        return False, "请填写 Base URL 和 API Key"
    ok, err = validate_ragflow_base_url(base_url.strip())
    if not ok:
        return False, err
    url = f"{base_url.rstrip('/')}/api/v1/datasets"
    params = {"page": 1, "page_size": 1}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except httpx.ConnectError as e:
        return False, f"无法连接：{e!s}"
    except httpx.TimeoutException:
        return False, "连接超时，请检查地址与网络"
    except httpx.HTTPStatusError as e:
        try:
            body = e.response.json()
            msg = body.get("message") or body.get("detail") or e.response.text[:200]
        except Exception:
            msg = e.response.text[:200] or str(e)
        return False, f"请求失败 ({e.response.status_code})：{msg}"
    except Exception as e:
        return False, f"检测失败：{e!s}"
    if not isinstance(data, dict):
        return False, "响应格式异常"
    if data.get("code") != 0:
        return False, data.get("message") or f"RAGFlow 返回 code={data.get('code')}"
    return True, "连接成功"
