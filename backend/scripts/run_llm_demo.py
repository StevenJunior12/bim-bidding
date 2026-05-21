"""LLM 调用联调脚本（stage 2.1）。

在 backend/ 目录下：

  python scripts/run_llm_demo.py

需在 .env 中配置 DEEPSEEK_API_KEY 等。
"""
import os

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(_BACKEND_ROOT)

from app.llm import call_llm


def main():
    print("Calling DeepSeek (deepseek-v4-flash)...")
    content = call_llm(
        "deepseek",
        "deepseek-v4-flash",
        [{"role": "user", "content": "你好，回复一句话"}],
    )
    print("Response:", content)
    print("OK")


if __name__ == "__main__":
    main()
