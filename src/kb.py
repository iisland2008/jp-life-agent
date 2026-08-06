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
GOMI_SJK = _load("gomi_shinjuku.json")  # 新宿区官方垃圾数据(带来源URL)


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


def search_gomi_shinjuku(query: str = "", k: int = 3) -> dict:
    """对新宿区官方数据做 Top-K 检索,每条附官方来源 URL 供引用。"""
    scored = []
    for doc in GOMI_SJK["docs"]:
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
                    "updated": doc["last_updated"],
                },
            }
        )
    return {
        "区": "新宿区",
        "query": query,
        "source_mode": "新宿区官方数据(带出处)",
        "hits": hits,
        "disclaimer": GOMI_SJK["_meta"]["免责"],
    }


# ---------- 垃圾分类检索 ----------
def search_gomi(item: str = "", ward: str = "") -> dict:
    # 新宿区:走官方结构化数据,返回带来源的检索结果
    if ward and "新宿" in ward:
        return search_gomi_shinjuku(item, k=3)

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
