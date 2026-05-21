"""LLM call layer: OpenAI-compatible chat completions for DeepSeek / Zhipu."""
import httpx

from app import config
from app.contract_prompt_log import log_contract_prompts


def _default_base_url(provider: str) -> str:
    """Return base URL for provider (DB first, then env)."""
    return config.get_llm_base_url(provider)


def call_llm(
    provider: str,
    model: str,
    messages: list[dict],
    temperature: float = 0.7,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    prompt_step: str | None = None,
    task_id: int | None = None,
) -> str:
    """Call LLM via OpenAI-compatible chat completions; return content or raise.

    Args:
        provider: "deepseek" (used for default base_url and key lookup).
        model: Model name (e.g. deepseek-v4-flash, deepseek-chat).
        messages: OpenAI format, e.g. [{"role": "user", "content": "..."}].
        temperature: 0..1.
        api_key: If None, taken from config.get_llm_api_key(provider).
        base_url: If None, taken from config by provider (no trailing slash).
        prompt_step: Optional pipeline step name for LOG_CONTRACT_PROMPTS logging (see contract_prompt_log).
        task_id: Optional task id included in contract prompt logs.

    Returns:
        choices[0].message.content as str.

    Raises:
        ValueError: Missing API key or unknown provider.
        httpx.HTTPStatusError: Non-2xx response.
        KeyError/IndexError: Unexpected response shape (re-raised or wrapped).
    """
    log_contract_prompts(prompt_step=prompt_step, messages=messages, task_id=task_id)

    key = api_key or config.get_llm_api_key(provider, task_id=task_id)
    if not key:
        raise ValueError(f"请在设置中配置 {provider} API Key")
    resolved_base = base_url or config.get_llm_base_url(provider, task_id=task_id)
    url_base = resolved_base.rstrip("/")
    url = f"{url_base}/chat/completions"

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        # 默认允许最多 8K tokens 输出，可通过环境变量 LLM_MAX_TOKENS 调整
        "max_tokens": config.LLM_MAX_TOKENS,
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    timeout = httpx.Timeout(
        connect=config.LLM_TIMEOUT_CONNECT,
        read=config.LLM_TIMEOUT_READ,
        write=config.LLM_TIMEOUT_READ,
        pool=config.LLM_TIMEOUT_CONNECT,
    )
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        # SEC-06: 不在异常中附带完整响应体，避免泄露供应商结构或计费信息
        hint = (
            f"type={type(data).__name__}"
            if not isinstance(data, dict)
            else f"keys={list(data.keys())[:12]}"
        )
        raise ValueError(f"LLM 响应格式异常（{hint}），请检查 API 与模型配置") from e
