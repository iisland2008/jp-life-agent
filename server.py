"""
server.py — 轻量 Web 后端 (Flask)

复用现有 Agent(src/agent.py),对外提供:
  GET  /            移动端聊天页面 (web/index.html)
  POST /api/chat    {message, history} -> {answer, tools, history}

前端拿到 tools 数组就能可视化『Agent 调用了哪些知识库工具』——这是 RAG 的核心卖点。

运行:
    export GEMINI_API_KEY=xxxx      # 不配则自动 mock 模式
    pip install -r requirements.txt
    python server.py                # 打开 http://127.0.0.1:5001
"""

import os
import sys

from flask import Flask, jsonify, request, send_from_directory


def _load_dotenv():
    """无需第三方库,自动读取项目根目录的 .env(KEY=VALUE),填入环境变量。"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _load_keyfile():
    """读取可见的 apikey.txt:第一行非注释、非空、且不是占位提示的内容当作 Gemini key。"""
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("LLM_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "apikey.txt")
    if not os.path.exists(p):
        return
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "粘贴" in line or "xxxx" in line.lower():  # 占位提示,跳过
            continue
        os.environ.setdefault("GEMINI_API_KEY", line)
        return


_load_dotenv()   # 先读 .env(给懂命令行的人)
_load_keyfile()  # 再读 apikey.txt(可见文件,更省事)
# 必须在导入 agent 之前(agent 在导入时读取 key)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.agent import chat, has_api_key, MODEL

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
app = Flask(__name__, static_folder=WEB_DIR, static_url_path="")


@app.route("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.route("/api/meta")
def meta():
    return jsonify({"mode": "real" if has_api_key() else "mock", "model": MODEL})


@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json(force=True) or {}
    message = (data.get("message") or "").strip()
    history = data.get("history") or []
    category = (data.get("category") or "").strip()
    image = data.get("image")  # 可选:base64 data URL
    if not message and not image:
        return jsonify({"error": "empty message"}), 400

    # 注入当前功能分类,让 AI 问答聚焦(仅在首轮追加,避免污染多轮上下文)
    sent = message or "请看这张图片,用中文帮我说明。"
    if category and not history:
        sent = f"【当前功能:{category}】{sent}"

    tool_events = []
    try:
        answer, new_history = chat(
            sent, history=history, verbose=False, on_event=tool_events.append, image=image
        )
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500

    return jsonify({"answer": answer, "tools": tool_events, "history": new_history})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    mode = f"真实 API ({MODEL})" if has_api_key() else "MOCK(未配置 GEMINI_API_KEY)"
    print("=" * 56)
    print("🗾 日本生活小助手 · Web  |  模式:", mode)
    print(f"请在浏览器打开:  http://127.0.0.1:{port}")
    print("(手机预览:用同一 WiFi 访问电脑局域网 IP:该端口)")
    print("=" * 56)
    app.run(host="0.0.0.0", port=port, debug=False)
