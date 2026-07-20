"""
agent.py — Agent 循环 (RAG 的 AG:Augmented Generation)

架构:用户输入 -> LLM 决定调用哪个知识库工具 -> 执行检索 -> 把结果喂回 LLM
-> LLM 基于『我们自己的知识库』组织中文回答。多轮 tool-use 循环直到给出最终答案。

默认接入 Google Gemini(免费层),通过其 OpenAI 兼容接口调用。
好处:同一份代码只改 base_url + model 就能切到 Groq / OpenRouter / DeepSeek 等
任何 OpenAI 兼容的供应商,不锁死单一厂商。
未配置 key 时自动降级为 mock 模式,用于离线演示检索链路。
"""

import json
import os

from .tools import TOOL_SCHEMAS, run_tool

# ---- 供应商配置(默认 Gemini 免费层,可用环境变量覆盖切换供应商)----
# Gemini 免费 key 申请:https://aistudio.google.com/apikey (邮箱登录即可,不要信用卡)
DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
BASE_URL = os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL)
MODEL = os.environ.get("JP_AGENT_MODEL", "gemini-flash-latest")
MAX_TURNS = 6


def get_api_key():
    """按优先级读取 key:通用 LLM_API_KEY > GEMINI_API_KEY > GOOGLE_API_KEY。"""
    return (
        os.environ.get("LLM_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
    )


def has_api_key():
    return bool(get_api_key())


SYSTEM_PROMPT = """你是『日本生活小助手』,专门帮助在日本的中国留学生解决生活难题,聚焦三大场景:
1) 行政手续陪办(市役所业务、材料清单、窗口、能否网上预约)
2) 看病分诊(中文症状 -> 该挂哪个科 -> 生成日语症状卡)
3) 垃圾分类(某物品属于哪类、所在区收集日与规则)

铁律:
- 涉及事实(材料、科室、垃圾类别、收集日、金额、规则)必须先调用工具从知识库获取,不要凭记忆编造。
- 回答任何生活问题时,可额外调用 search_tips 补充本地化避坑提醒。
- 用简洁、口语化的中文回答;关键的日语词汇附上假名/汉字方便用户到现场对照。
- 医疗类回答必须带免责声明,提示急症拨打 119 / #7119。
- 若知识库信息不足,坦诚说明并建议官方渠道核实,不要编造。
- 输出用纯文本口语化中文,不要使用 Markdown 记号(如 #、##、**加粗**、* 列表、` 等)。需要分点时用「1. 2. 3.」或直接换行;要强调就用「」括起来,不要用星号。"""


def _to_openai_tools(schemas):
    """把知识库工具定义转成 OpenAI/Gemini 兼容的 tools 格式。"""
    return [
        {
            "type": "function",
            "function": {
                "name": s["name"],
                "description": s["description"],
                "parameters": s["input_schema"],
            },
        }
        for s in schemas
    ]


# ---------------- 真实 API 模式(OpenAI 兼容,默认 Gemini)----------------
def _emit(on_event, name, args):
    if on_event:
        try:
            on_event({"name": name, "args": args})
        except Exception:
            pass


def _run_llm(user_input, history, verbose=True, on_event=None):
    import datetime

    from openai import OpenAI

    client = OpenAI(api_key=get_api_key(), base_url=BASE_URL)
    tools = _to_openai_tools(TOOL_SCHEMAS)

    today = datetime.date.today()
    wd = "一二三四五六日"[today.weekday()]
    date_note = (
        f"\n\n【当前日期】今天是 {today.isoformat()}(周{wd})。用户说“明天/后天/下周x”等相对时间时,"
        "先换算成具体的 YYYY-MM-DD 再调用工具。\n"
        "【动作能力】你可以调用 add_schedule(写入日程)、add_work(记打工)、add_class(加课程)真正帮用户记录。"
        "用户要求安排/记录/提醒时,应调用对应工具,然后用一句话确认。\n"
        "【重要】区役所等官方预约需要本人到官网认证办理,你不能代为预约;遇到这类请求,"
        "改为用 add_schedule 加一条提醒(如“区役所预约·在留卡更新”),并提示用户到官方渠道完成预约、附上所需材料。"
    )
    messages = [{"role": "system", "content": SYSTEM_PROMPT + date_note}] + history + [
        {"role": "user", "content": user_input}
    ]

    for _ in range(MAX_TURNS):
        resp = client.chat.completions.create(
            model=MODEL, messages=messages, tools=tools, temperature=0.3
        )
        msg = resp.choices[0].message

        if msg.tool_calls:
            # 原样回传完整 assistant 消息:保留 Gemini 思考模型要求的
            # thought_signature 等扩展字段(手动重建会丢掉,导致 400)。
            messages.append(msg.model_dump(exclude_none=True))
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                if verbose:
                    print(f"  🔧 调用知识库工具: {tc.function.name}({json.dumps(args, ensure_ascii=False)})")
                _emit(on_event, tc.function.name, args)
                result = run_tool(tc.function.name, args)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
            continue

        # 最终回答:去掉 system,返回可复用的对话历史
        answer = msg.content or ""
        messages.append({"role": "assistant", "content": answer})
        return answer, messages[1:]

    return "(达到最大轮数,未能给出最终回答)", messages[1:]


# ---------------- Mock 模式(离线演示检索链路,无需 API) ----------------
def _run_mock(user_input, history, verbose=True, on_event=None):
    """
    简易意图路由 + 工具调用,用来在没有 API key 时演示『Agent 挑工具 -> 查知识库』的链路。
    真实效果请配置 GEMINI_API_KEY 后运行。
    """
    text = user_input
    calls = []
    if any(k in text for k in ["扔", "垃圾", "分类", "ゴミ", "怎么丢", "哪天收"]):
        ward = next((w for w in ["新宿区", "涩谷区", "丰岛区"] if w in text), "")
        calls.append(("search_gomi", {"item": text, "ward": ward}))
    if any(k in text for k in ["保险", "在留", "年金", "编号", "住民", "市役所", "手续", "签证"]):
        calls.append(("search_admin", {"query": text}))
    if any(k in text for k in ["发烧", "咳嗽", "疼", "痛", "科", "看病", "医院", "症状", "扭"]):
        calls.append(("triage_medical", {"symptoms": text}))
    if not calls:
        calls.append(("search_tips", {"query": text}))

    out = ["【MOCK 模式:仅演示检索链路,配置 GEMINI_API_KEY 后为真实自然语言回答】\n"]
    for name, args in calls:
        if verbose:
            print(f"  🔧 调用知识库工具: {name}({json.dumps(args, ensure_ascii=False)})")
        _emit(on_event, name, args)
        result = run_tool(name, args)
        out.append(f"[{name}] 检索结果:\n{json.dumps(result, ensure_ascii=False, indent=2)}\n")
    return "\n".join(out), history


def chat(user_input, history=None, verbose=True, on_event=None):
    history = history or []
    runner = _run_llm if has_api_key() else _run_mock
    return runner(user_input, history, verbose=verbose, on_event=on_event)
