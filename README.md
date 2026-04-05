# 🤖 AI Research Paper Bot

Telegram bot tracking new AI/ML papers from **9 sources** with **direct PDF links**, auto-push every 2 days, browse by month/year, and per-user subscriptions.

---

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Intro + source list + your sub status |
| `/latest` | Fetch new papers from all 9 sources |
| `/source` | Pick a specific source via inline buttons |
| `/browse` | Browse by year → month (arXiv archive) |
| `/subscribe` | Auto-receive new papers every 2 days |
| `/unsubscribe` | Stop auto updates |
| `/status` | Check your subscription status |

---

## Sources (all PDF-first)

| Source | Method | PDF |
|--------|--------|-----|
| 🟠 Anthropic Research | HTML scrape | ✅ Extracted from each paper page |
| 🤗 HuggingFace Daily Papers | HTML scrape | ✅ arXiv PDF |
| 📄 arXiv (AI/ML/NLP/CV) | RSS × 5 feeds | ✅ Direct PDF |
| 💻 Papers With Code | Public API | ✅ Direct PDF |
| 🏛 OpenReview (NeurIPS/ICLR/ICML) | Public API | ✅ openreview.net/pdf |
| 🔍 Semantic Scholar | Public API | ✅ Open access PDF |
| 📝 ACL Anthology | HTML scrape | ✅ aclanthology.org/X.pdf |
| 🟢 OpenAI Blog | RSS | ⚠️ arXiv PDF if available |
| 🟣 Google DeepMind | RSS | ⚠️ arXiv PDF if available |

---

## Deploy on Railway

### 1. Create bot
Message [@BotFather](https://t.me/BotFather) → `/newbot` → copy token.

### 2. Push to GitHub
```bash
git init && git add . && git commit -m "init"
git remote add origin https://github.com/YOUR/ai-research-bot.git
git push -u origin main
```

### 3. Railway setup
1. [railway.app](https://railway.app) → New Project → Deploy from GitHub
2. **Variables** tab:
   ```
   BOT_TOKEN=your_token
   NOTIFY_CHAT_IDS=your_chat_id   # optional legacy admin IDs
   ```
3. **Add Volume** mounted at `/data` — keeps subscriber list + seen URLs across redeploys.

### 4. That's it
Bot runs 24/7, auto-fetches every 2 days, pushes to all subscribers.

---

## Dev

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
BOT_TOKEN=xxx python bot.py
```

---

🛠 Built by [@nikkk.exe](https://instagram.com/nikkk.exe)
