"""Model name -> provider mapping; used to infer provider from model name."""

# model_id -> provider (used for API key / base_url lookup)
MODEL_TO_PROVIDER: dict[str, str] = {
    "deepseek-v4-flash": "deepseek",
    "deepseek-chat": "deepseek",
    "deepseek-reasoner": "deepseek",
    "deepseek-v3": "deepseek",
}

# Display order and label for settings UI (id, label, provider)
SUPPORTED_MODELS: list[tuple[str, str, str]] = [
    ("deepseek-v4-flash", "DeepSeek V4 Flash", "deepseek"),
    ("deepseek-chat", "DeepSeek Chat", "deepseek"),
    ("deepseek-reasoner", "DeepSeek Reasoner", "deepseek"),
    ("deepseek-v3", "DeepSeek V3", "deepseek"),
]


def get_provider_for_model(model_id: str) -> str | None:
    """Return provider for model id; None if unknown."""
    return MODEL_TO_PROVIDER.get(model_id.strip().lower() if model_id else "")


def list_supported_models() -> list[dict]:
    """Return list of {id, name, provider} for settings UI."""
    return [
        {"id": mid, "name": name, "provider": prov}
        for mid, name, prov in SUPPORTED_MODELS
    ]
