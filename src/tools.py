"""
tools.py — 把知识库检索封装成 Agent 可调用的工具 (Function Calling)

这是『AI 产品能力』的核心体现:
LLM 不直接编造答案,而是被约束成先调用工具从我们自己的知识库取数,再组织语言。
每个工具 = 一个产品功能。
"""

from . import kb

# 工具的 JSON Schema 定义 (Anthropic / OpenAI 通用的 function-calling 格式)
TOOL_SCHEMAS = [
    {
        "name": "search_gomi",
        "description": "查询日本垃圾分类:某个物品属于哪类垃圾、所在区的收集日和规则。当用户问『这个垃圾怎么扔/属于什么类/哪天收』时调用。",
        "input_schema": {
            "type": "object",
            "properties": {
                "item": {"type": "string", "description": "垃圾物品名称,如『塑料瓶』『喷雾罐』『旧衣服』"},
                "ward": {"type": "string", "description": "所在区,如『新宿区』『涩谷区』。不知道就留空。"},
            },
            "required": ["item"],
        },
    },
    {
        "name": "search_admin",
        "description": "查询日本行政手续办理信息:在留卡更新、国民健康保险、年金、个人编号卡、住民登录等。返回该业务需要的材料、办理窗口、能否网上预约、注意事项。",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "用户的行政需求描述,如『我要加入健康保险』『在留卡快到期了』"}
            },
            "required": ["query"],
        },
    },
    {
        "name": "triage_medical",
        "description": "根据中文症状描述判断在日本该挂哪个科(日本分科很细),并返回给医生看的日语症状卡模板。当用户描述身体不适、问看什么科时调用。",
        "input_schema": {
            "type": "object",
            "properties": {
                "symptoms": {"type": "string", "description": "中文症状描述,如『发烧咳嗽喉咙痛』『扭到脚踝』"}
            },
            "required": ["symptoms"],
        },
    },
    {
        "name": "search_tips",
        "description": "检索日本生活的独特小知识/避坑提醒(大医院初诊要转诊信、大件垃圾要预约、103万之壁等)。在回答任何生活类问题时都可调用,以补充本地化的准确提醒。",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "话题关键词,如『看病注意』『打工收入』『搬家手续』"}
            },
            "required": ["query"],
        },
    },
    # ===== 动作工具(由前端真正执行:写入用户本地数据)=====
    {
        "name": "add_schedule",
        "description": "把一个事项加入用户的日程/日历。当用户说『加入日程/帮我记一下/提醒我/安排一下』某件事时调用。官方预约(如区役所)不能代订,应改为用本工具加一条提醒。",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "事项标题,如『去新宿区役所办在留卡更新』"},
                "date": {"type": "string", "description": "日期,格式 YYYY-MM-DD;相对日期(明天等)先换算成具体日期"},
                "time": {"type": "string", "description": "时间,可选,格式 HH:MM,如 17:00"},
            },
            "required": ["title", "date"],
        },
    },
    {
        "name": "add_work",
        "description": "给用户的打工记录添加一条。当用户说『记一下我某天打工了几小时』时调用。",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "place": {"type": "string", "description": "店名/打工地点"},
                "hours": {"type": "number", "description": "工时(小时)"},
                "wage": {"type": "number", "description": "时薪(日元)"},
            },
            "required": ["date", "hours", "wage"],
        },
    },
    {
        "name": "add_class",
        "description": "给用户的周间课表添加一节课。当用户说『把xx课加到课表/我周几第几限有xx课』时调用。",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "课程名"},
                "day": {"type": "string", "description": "星期:周一/周二/周三/周四/周五"},
                "period": {"type": "integer", "description": "节次 1-5(对应 1限~5限)"},
            },
            "required": ["name", "day", "period"],
        },
    },
]

# 工具名 -> 实际执行函数
TOOL_IMPL = {
    "search_gomi": lambda a: kb.search_gomi(a.get("item", ""), a.get("ward", "")),
    "search_admin": lambda a: kb.search_admin(a.get("query", "")),
    "triage_medical": lambda a: kb.triage_medical(a.get("symptoms", "")),
    "search_tips": lambda a: kb.search_tips(a.get("query", "")),
    # 动作工具:真正的写入在前端完成,这里只回执让模型确认
    "add_schedule": lambda a: {"status": "ok", "action": "add_schedule", "added": a},
    "add_work": lambda a: {"status": "ok", "action": "add_work", "added": a},
    "add_class": lambda a: {"status": "ok", "action": "add_class", "added": a},
}


def run_tool(name: str, args: dict):
    if name not in TOOL_IMPL:
        return {"error": f"unknown tool: {name}"}
    return TOOL_IMPL[name](args)
