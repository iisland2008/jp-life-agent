# 部署指南(给别人使用)

分两步:**① 把代码传到 GitHub → ② 用 Render 从 GitHub 一键部署**,得到一个 `https://xxx.onrender.com` 网址,发给谁都能打开。

---

## 0. 先确认:密钥不会被上传 ⚠️

你的 Gemini key 在 `apikey.txt` 里。项目已带 `.gitignore`,会自动**排除 `apikey.txt` 和 `.env`**,所以 git 不会上传它们。
线上运行时,key 改为在 Render 后台设「环境变量」(见第 2 步),不写进代码。

> 提醒:公开网址意味着任何访问的人都会消耗你这个 key 的免费额度(Gemini 免费层约 1500 次/天,够 demo)。介意的话可随时在 Google AI Studio 换 key。

---

## 1. 传到 GitHub

在项目文件夹里打开终端(路径:`Documents/coding project/jp-life-agent`),依次运行:

```bash
cd "Documents/coding project/jp-life-agent"

git init
git add .
git commit -m "日留生活小助手 初始版本"

# 去 https://github.com/new 建一个空仓库(比如 jp-life-agent),不要勾选 README
# 然后把下面 URL 换成你自己仓库的地址:
git remote add origin https://github.com/你的用户名/jp-life-agent.git
git branch -M main
git push -u origin main
```

推完后刷新 GitHub 仓库页面,应该能看到代码,但**看不到 apikey.txt / .env**(被忽略了,这是对的)。

> 首次 push 可能让你登录 GitHub;按提示用浏览器授权或输入 Personal Access Token 即可。

---

## 2. 用 Render 部署(免费)

1. 打开 https://render.com,用 GitHub 账号登录。
2. 点 **New +** → **Web Service** → 选中你刚才那个仓库。
3. 填写配置:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn server:app --bind 0.0.0.0:$PORT`
   - Instance Type 选 **Free**。
4. 展开 **Environment / Environment Variables**,添加一条:
   - Key: `GEMINI_API_KEY`  Value: 你的 Gemini key
   -(可选)Key: `JP_AGENT_MODEL`  Value: `gemini-flash-latest`
5. 点 **Create Web Service**,等几分钟构建完成,会给你一个网址:
   `https://jp-life-agent-xxxx.onrender.com` —— 这就是发给别人用的链接。

**免费层注意**:15 分钟没人访问会休眠,下一次打开需等约 60 秒唤醒(之后就正常了)。介意冷启动可升级付费,或用下面的备选平台。

---

## 3. 备选托管平台

任选其一,思路都一样(连 GitHub + 设 `GEMINI_API_KEY` 环境变量 + 启动 `gunicorn server:app`):

- **Railway**(railway.app):体验流畅,有少量免费额度。
- **Hugging Face Spaces**:适合展示 AI demo,选 “Docker” 或 “Gradio/Flask” 模板,免费常驻。
- **Fly.io / Google Cloud Run**:更接近生产,配置略多。

---

## 4. 以后更新代码

改完代码后:

```bash
git add .
git commit -m "更新:xxx"
git push
```

Render 检测到 push 会**自动重新部署**,不用手动操作。

---

## 常见问题

- **打开是「演示模式」不是「在线」**:说明 Render 没读到 key。检查第 2 步的环境变量 `GEMINI_API_KEY` 是否填对,改完点 Manual Deploy 重新部署。
- **不小心把 key 传上去了**:立刻去 https://aistudio.google.com/apikey 删掉旧 key 重新生成一个,再把新 key 填到 Render 环境变量。
- **数据会不会互相看到**:不会。日程、课表、打工、收藏等都存在各自浏览器本地(localStorage),每个人的数据互相独立。
