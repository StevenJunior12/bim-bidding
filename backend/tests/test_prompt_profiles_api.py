"""Integration tests for /api/prompt-profiles (Phase B)."""
from unittest.mock import patch

from app.auth import verify_api_key
from app.main import app
from fastapi.testclient import TestClient


async def _verify_api_key_override() -> None:
    return None


def test_prompt_profiles_disciplines_list():
    app.dependency_overrides[verify_api_key] = _verify_api_key_override
    try:
        client = TestClient(app)
        r = client.get("/api/prompt-profiles/disciplines")
        assert r.status_code == 200
        items = r.json()["items"]
        assert "建筑" in items
        assert "BIM" in items
        assert "暖通" in items
        assert "智慧运维" in items
    finally:
        app.dependency_overrides.pop(verify_api_key, None)


def test_prompt_profiles_create_invalid_discipline():
    app.dependency_overrides[verify_api_key] = _verify_api_key_override
    try:
        client = TestClient(app)
        r = client.post(
            "/api/prompt-profiles",
            json={"name": "x", "discipline": "星际专业"},
        )
        assert r.status_code == 400
    finally:
        app.dependency_overrides.pop(verify_api_key, None)


@patch("app.prompt_profile_generate.call_llm")
def test_generate_semantic_analyze_user_requires_context_placeholder(mock_llm):
    app.dependency_overrides[verify_api_key] = _verify_api_key_override
    try:
        mock_llm.return_value = "改编后的 user 模板但忘了占位符"
        client = TestClient(app)
        r = client.post(
            "/api/prompt-profiles/generate-semantic",
            json={
                "profile_name": "测试配置",
                "discipline": "建筑",
                "slot_key": "analyze_user",
            },
        )
        assert r.status_code == 400
    finally:
        app.dependency_overrides.pop(verify_api_key, None)


@patch("app.prompt_profile_generate.call_llm")
def test_generate_semantic_review_system_ok_without_json_literal(mock_llm):
    """review_system: JSON format is appended at runtime; semantic need not contain 'JSON'."""
    app.dependency_overrides[verify_api_key] = _verify_api_key_override
    try:
        mock_llm.return_value = (
            "你是暖通技术标校审专家。\n\n"
            "## 审查维度\n"
            "请从以下四类判断：废标项、幻觉、套路、建议。\n"
            "若无问题则输出空数组。\n"
            "（具体数组字段约定由系统拼接的输出格式段说明。）"
        )
        client = TestClient(app)
        r = client.post(
            "/api/prompt-profiles/generate-semantic",
            json={
                "profile_name": "测试配置",
                "discipline": "暖通",
                "slot_key": "review_system",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["slot_key"] == "review_system"
        assert "废标项" in body["text"]
    finally:
        app.dependency_overrides.pop(verify_api_key, None)


@patch("app.prompt_profile_generate.call_llm")
def test_generate_semantic_review_system_fails_if_few_types(mock_llm):
    app.dependency_overrides[verify_api_key] = _verify_api_key_override
    try:
        mock_llm.return_value = "仅泛泛说要注意质量，没有维度分类。"
        client = TestClient(app)
        r = client.post(
            "/api/prompt-profiles/generate-semantic",
            json={
                "profile_name": "测试配置",
                "discipline": "建筑",
                "slot_key": "review_system",
            },
        )
        assert r.status_code == 400
    finally:
        app.dependency_overrides.pop(verify_api_key, None)


@patch("app.prompt_profile_generate.call_llm")
def test_generate_semantic_analyze_system_ok(mock_llm):
    app.dependency_overrides[verify_api_key] = _verify_api_key_override
    try:
        mock_llm.return_value = "改编后的 analyze system 全文，足够长以通过校验。"
        client = TestClient(app)
        r = client.post(
            "/api/prompt-profiles/generate-semantic",
            json={
                "profile_name": "测试配置",
                "discipline": "给排水",
                "slot_key": "analyze_system",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["slot_key"] == "analyze_system"
        assert "analyze" in body["text"] or "改编" in body["text"]
    finally:
        app.dependency_overrides.pop(verify_api_key, None)


def test_prompt_profiles_create_list_invalid_key():
    app.dependency_overrides[verify_api_key] = _verify_api_key_override
    try:
        client = TestClient(app)
        bad = client.post(
            "/api/prompt-profiles",
            json={
                "name": "bad",
                "discipline": "建筑",
                "semantic_overrides": {"not_a_slot": "x"},
            },
        )
        assert bad.status_code == 400

        ok = client.post(
            "/api/prompt-profiles",
            json={
                "name": "ok_profile",
                "discipline": "结构",
                "semantic_overrides": {"analyze_system": "自定义分析 system"},
            },
        )
        assert ok.status_code == 201
        data = ok.json()
        assert data["name"] == "ok_profile"
        assert data["discipline"] == "结构"
        assert data["semantic_overrides"]["analyze_system"] == "自定义分析 system"

        listed = client.get("/api/prompt-profiles")
        assert listed.status_code == 200
        ids = {x["id"] for x in listed.json()}
        assert data["id"] in ids
    finally:
        app.dependency_overrides.pop(verify_api_key, None)
