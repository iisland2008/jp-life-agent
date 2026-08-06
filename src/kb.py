"""
kb.py — 知识库加载与检索层 (RAG 的 R:Retrieval)

产品设计要点:
- 结构化知识(垃圾/行政/医疗)用『字段匹配』做精确查询,保证准确性;
- 独特小知识(tips)是自由文本,用轻量语义打分做 Top-K 检索;
- 检索层与 LLM 解耦,LLM 只负责理解意图和组织语言,事实来自知识库。
"""

import json
import re
from pathlib import Path

KB_DIR = Path(__file__).resolve().parent.parent / "knowledge_base"


def _load(name: str) -> dict:
    with open(KB_DIR / name, encoding="utf-8") as f:
        return json.load(f)


GOMI = _load("gomi.json")
ADMIN = _load("admin.json")
MEDICAL = _load("medical.json")
TIPS = _load("tips.json")
EXPERIENCE = _load("experience.json")
# 各区官方垃圾数据(带来源URL);合并成一个带『区』标签的文档列表,便于按区检索
_GOMI_FILES = ["gomi_shinjuku.json", "gomi_shibuya.json", "gomi_toshima.json"]
GOMI_LOCAL_DOCS = []
for _f in _GOMI_FILES:
    try:
        GOMI_LOCAL_DOCS += _load(_f)["docs"]
    except Exception:
        pass
# 有本地官方数据的区(用于判断是否走本地检索)
WARDS_WITH_DATA = sorted({d.get("区") for d in GOMI_LOCAL_DOCS if d.get("区")})


# ---------- 通用文本打分 (轻量语义检索,无需外部 embedding) ----------
def _char_ngrams(text: str, n: int = 2) -> set:
    text = re.sub(r"\s+", "", text)
    return {text[i : i + n] for i in range(len(text) - n + 1)} if len(text) >= n else {text}


def _score(query: str, doc_text: str, tags=None) -> float:
    q = _char_ngrams(query)
    d = _char_ngrams(doc_text)
    if not q or not d:
        return 0.0
    overlap = len(q & d) / len(q)
    tag_bonus = 0.0
    if tags:
        for t in tags:
            if t and t in query:
                tag_bonus += 0.5
    return overlap + tag_bonus


# ---------- 新宿区官方垃圾数据:跨语言检索 + 出处引用 ----------
def _score_doc(query: str, doc: dict) -> float:
    """中文/日文关键词命中 + 字符 n-gram 语义重叠,支持中文提问检索日文来源的数据。"""
    score = 0.0
    for kw in doc.get("keywords_cn", []) + doc.get("keywords_jp", []):
        if kw and kw in query:
            score += 2.0
    for part in re.split(r"[ /・]", doc.get("category", "")):
        if part and part in query:
            score += 0.5
    blob = doc.get("text_cn", "") + "".join(doc.get("keywords_cn", []))
    q, d = _char_ngrams(query), _char_ngrams(blob)
    if q and d:
        score += len(q & d) / len(q)
    return score


def _ward_of(ward: str):
    """把传入地区归一化到有本地数据的区名(支持中/日写法的模糊匹配)。"""
    if not ward:
        return None
    alias = {"新宿": "新宿区", "渋谷": "涩谷区", "涩谷": "涩谷区", "豊島": "丰岛区", "丰岛": "丰岛区"}
    for key, canon in alias.items():
        if key in ward and canon in WARDS_WITH_DATA:
            return canon
    for w in WARDS_WITH_DATA:
        if w in ward or ward in w:
            return w
    return None


def search_gomi_local(query: str = "", ward: str = "", k: int = 3) -> dict:
    """对『指定区』的官方数据做 Top-K 检索,每条附官方来源 URL 供引用。"""
    canon = _ward_of(ward)
    docs = [d for d in GOMI_LOCAL_DOCS if d.get("区") == canon]
    scored = []
    for doc in docs:
        s = _score_doc(query, doc)
        if doc.get("type") == "item":
            s += 0.3  # 物品级条目对『XX怎么扔』更精确,轻微加权
        if s > 0.5:
            scored.append((s, doc))
    scored.sort(key=lambda x: -x[0])
    hits = []
    for s, doc in scored[:k]:
        hits.append(
            {
                "category": doc["category"],
                "content": doc.get("text_cn", ""),
                "confusing": doc.get("confusing_cn"),
                "source": {
                    "title": doc["source_title"],
                    "url": doc["source_url"],
                    "updated": doc.get("last_updated", ""),
                },
            }
        )
    return {
        "区": canon,
        "query": query,
        "source_mode": f"{canon}官方数据(带出处)",
        "hits": hits,
        "disclaimer": "规则可能调整,请以官方页面最新信息为准。",
    }


# ---------- 垃圾分类检索 ----------
def search_gomi(item: str = "", ward: str = "") -> dict:
    # 有本地官方数据的区(新宿/涩谷/丰岛):走官方结构化数据,返回带来源的检索结果
    if _ward_of(ward):
        return search_gomi_local(item, ward, k=3)

    result = {"ward": ward or "default", "matched_items": [], "ward_info": None, "notes": []}

    ward_key = None
    for w in GOMI["wards"]:
        if ward and ward in w:
            ward_key = w
            break
    ward_data = GOMI["wards"].get(ward_key or "default")
    result["ward"] = ward_key or "default(未指定区,返回通用规则)"
    result["ward_info"] = ward_data

    if item:
        scored = []
        for entry in GOMI["item_classification"]:
            s = _score(item, entry["item"] + entry["tips"])
            if entry["item"].split()[0] in item or item in entry["item"]:
                s += 1.0
            if s > 0.2:
                scored.append((s, entry))
        scored.sort(key=lambda x: -x[0])
        for s, entry in scored[:3]:
            cat_name = GOMI["_meta"]["categories"].get(entry["category"], entry["category"])
            result["matched_items"].append(
                {"item": entry["item"], "category": cat_name, "tips": entry["tips"]}
            )
    result["notes"].append(GOMI["_meta"]["note"])
    return result


# ---------- 行政手续检索 ----------
def search_admin(query: str) -> dict:
    scored = []
    for svc in ADMIN["services"]:
        blob = svc["name"] + " ".join(svc["materials"]) + svc.get("notes", "")
        s = _score(query, blob)
        for kw in [svc["name"], svc["id"]]:
            if any(part in query for part in re.split(r"[ /()（）]", kw) if len(part) > 1):
                s += 1.0
        scored.append((s, svc))
    scored.sort(key=lambda x: -x[0])
    top = [svc for s, svc in scored[:2] if s > 0.2]
    return {"query": query, "services": top or [scored[0][1]], "note": ADMIN["_meta"]["note"]}


# ---------- 看病分诊检索 ----------
def triage_medical(symptoms: str) -> dict:
    scored = []
    for entry in MEDICAL["triage"]:
        blob = " ".join(entry["symptoms"])
        s = _score(symptoms, blob, tags=entry["symptoms"])
        scored.append((s, entry))
    scored.sort(key=lambda x: -x[0])
    best = [e for sc, e in scored[:2] if sc > 0.2]
    return {
        "symptoms_input": symptoms,
        "candidates": best or [scored[0][1]],
        "card_template": MEDICAL["symptom_card_template"],
        "disclaimer": MEDICAL["_meta"]["disclaimer"],
        "emergency": MEDICAL["_meta"]["note"],
    }


# ---------- 独特小知识语义检索 ----------
def search_tips(query: str, top_k: int = 3) -> list:
    scored = []
    for tip in TIPS["tips"]:
        s = _score(query, tip["text"], tags=tip["tags"])
        scored.append((s, tip))
    scored.sort(key=lambda x: -x[0])
    return [{"text": t["text"], "tags": t["tags"], "score": round(s, 3)} for s, t in scored[:top_k] if s > 0.2]


# ---------- 留学生亲身经验库检索(优先参考) ----------
def search_experience(query: str, top_k: int = 3) -> list:
    scored = []
    for e in EXPERIENCE["experiences"]:
        s = _score(query, e["topic"] + e["text"], tags=e["tags"])
        scored.append((s, e))
    scored.sort(key=lambda x: -x[0])
    return [
        {"topic": e["topic"], "text": e["text"], "tags": e["tags"], "score": round(s, 3)}
        for s, e in scored[:top_k]
        if s > 0.15
    ]


if __name__ == "__main__":
    # 快速自测(离线,无需 API)
    print("== 垃圾:塑料瓶 @新宿区 ==")
    print(json.dumps(search_gomi("塑料瓶", "新宿区"), ensure_ascii=False, indent=2))
    print("\n== 行政:想加入健康保险 ==")
    print(json.dumps(search_admin("我想加入健康保险要带什么"), ensure_ascii=False, indent=2))
    print("\n== 分诊:发烧咳嗽 ==")
    print(json.dumps(triage_medical("这两天发烧还咳嗽喉咙痛"), ensure_ascii=False, indent=2))
    print("\n== 小知识:大医院初诊 ==")
    print(json.dumps(search_tips("去大医院看病要注意什么"), ensure_ascii=False, indent=2))
