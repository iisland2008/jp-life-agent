"""
demo.py — 预设演示脚本,一键跑 3 大场景

面试演示话术:先跑这个展示『Agent 自主挑工具 -> 查我的知识库 -> 组织回答』,
再切到 cli.py 现场问答。配了 ANTHROPIC_API_KEY 就是真实回答,没配就演示检索链路。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.agent import chat, has_api_key, MODEL

DEMOS = [
    ("垃圾分类", "我住新宿区,喝完的塑料瓶要怎么扔?哪天收?"),
    ("看病分诊", "这两天有点发烧还咳嗽、喉咙痛,在日本应该挂什么科?"),
    ("行政手续", "我刚来日本,想加入国民健康保险,要准备哪些材料、去哪办?"),
]


def main():
    mode = f"真实 API ({MODEL})" if has_api_key() else "MOCK(演示检索链路)"
    print(f"\n### 日本生活小助手 · 演示 (模式: {mode}) ###\n")
    for title, q in DEMOS:
        print("─" * 60)
        print(f"◆ 场景:{title}")
        print(f"用户提问:{q}\n")
        answer, _ = chat(q, verbose=True)
        print(f"\n助手回答:\n{answer}\n")


if __name__ == "__main__":
    main()
