"""
cli.py — 交互式命令行入口

用法:
    export ANTHROPIC_API_KEY=sk-...   # 配置后为真实 LLM 回答;不配置则 mock 演示
    python cli.py

输入 exit / quit 退出。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.agent import chat, has_api_key, MODEL


def main():
    mode = f"真实 API ({MODEL})" if has_api_key() else "MOCK(未检测到 GEMINI_API_KEY)"
    print("=" * 60)
    print("🗾 日本生活小助手 Agent  |  当前模式:", mode)
    print("聚焦:行政手续 · 看病分诊 · 垃圾分类   (输入 exit 退出)")
    print("=" * 60)

    history = []
    while True:
        try:
            user = input("\n你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见!")
            break
        if user.lower() in {"exit", "quit", "q"}:
            print("再见!")
            break
        if not user:
            continue
        answer, history = chat(user, history)
        print("\n助手>", answer)


if __name__ == "__main__":
    main()
