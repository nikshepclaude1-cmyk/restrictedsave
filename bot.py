import os
import logging
import asyncio
import re
from datetime import datetime

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    InlineQueryResultArticle, InputTextMessageContent,
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, InlineQueryHandler, MessageHandler, filters,
    ChatMemberHandler,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from scrapers.anthropic        import scrape_anthropic
from scrapers.arxiv            import scrape_arxiv, scrape_arxiv_by_month
from scrapers.openai           import scrape_openai
from scrapers.deepmind         import scrape_deepmind
from scrapers.huggingface      import scrape_huggingface
from scrapers.openreview       import scrape_openreview
from scrapers.paperswithcode   import scrape_paperswithcode
from scrapers.semantic_scholar import scrape_semantic_scholar
from scrapers.acl              import scrape_acl
from store         import ArticleStore
from search_engine import search_papers
from summarizer    import analyze_paper
from api_server    import start_api_server

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN    = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHAT_IDS_RAW = os.environ.get("NOTIFY_CHAT_IDS", "")
ADMIN_IDS    = [int(x.strip()) for x in CHAT_IDS_RAW.split(",") if x.strip()]

DEVELOPER = "@nikkk.exe"
DEV_LINK  = "https://instagram.com/nikkk.exe"

store = ArticleStore()

SOURCES = {
    "anthropic":        ("🟠 Anthropic Research",             scrape_anthropic),
    "huggingface":      ("🤗 HuggingFace Daily Papers",       scrape_huggingface),
    "arxiv":            ("📄 arXiv (AI/ML/NLP/CV)",           scrape_arxiv),
    "paperswithcode":   ("💻 Papers With Code",               scrape_paperswithcode),
    "openreview":       ("🏛 OpenReview (NeurIPS/ICLR/ICML)", scrape_openreview),
    "semantic_scholar": ("🔍 Semantic Scholar",               scrape_semantic_scholar),
    "acl":              ("📝 ACL Anthology",                  scrape_acl),
    "openai_blog":      ("🟢 OpenAI Blog",                    scrape_openai),
    "deepmind":         ("🟣 Google DeepMind",                scrape_deepmind),
}

MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
BROWSE_START_YEAR = 2020
BROWSE_END_YEAR   = datetime.now().year

PRESET_TOPICS = [
    ("🧠 LLMs",            "large language model llm gpt claude gemini llama"),
    ("🎯 Alignment",       "alignment rlhf constitutional ai safety harmless"),
    ("🔍 Interpretability","interpretability mechanistic circuit probing explainability"),
    ("🤖 Agents",          "agent tool use planning autonomous multi-agent"),
    ("👁 Multimodal",      "multimodal vision language vlm image text visual"),
    ("📐 Reasoning",       "reasoning chain of thought math logic problem solving"),
    ("⚡ Efficiency",      "efficient quantization distillation pruning inference"),
    ("🎨 Diffusion",       "diffusion generative image generation stable diffusion"),
]

# ─────────────────────────────────────────────────────────────
# Formatters
# ─────────────────────────────────────────────────────────────

def format_article(article: dict, with_button: bool = True) -> tuple[str, InlineKeyboardMarkup | None]:
    """Returns (text, reply_markup). reply_markup has Analyze button if with_button=True and URL is a PDF."""
    title   = article.get("title", "Untitled")
    url     = article.get("url", "")
    summary = article.get("summary", "")
    date    = article.get("date", "")
    source  = article.get("source", "")
    authors = article.get("authors", "")
    cats    = article.get("cats", "")
    is_pdf  = url.endswith(".pdf") or "/pdf/" in url

    icon = "📥 PDF" if is_pdf else "🔗 Link"
    lines = [f"📄 *{title}*"]
    if authors: lines.append(f"✍️ _{authors}_")
    if date:    lines.append(f"🗓 {date}")
    if cats:    lines.append(f"🏷 {cats}")
    if source:  lines.append(f"📡 {source}")
    if summary:
        lines.append(f"\n_{summary[:280]}{'...' if len(summary)>280 else ''}_")
    lines.append(f"\n{icon}: {url}")
    text = "\n".join(lines)

    markup = None
    if with_button and url:
        # Encode url into callback_data — truncate if needed (Telegram limit 64 bytes)
        # Store full URL in store, pass a short key in callback
        url_key = store.cache_url(url, title)
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("🧠 Analyze this paper", callback_data=f"analyze:{url_key}")
        ]])

    return text, markup


def dev_footer() -> str:
    return f"\n\n🛠 Built by [{DEVELOPER}]({DEV_LINK})"


# ─────────────────────────────────────────────────────────────
# Core fetch
# ─────────────────────────────────────────────────────────────

async def fetch_source(key: str) -> list[dict]:
    label, scraper = SOURCES[key]
    try:
        articles = await scraper()
        for a in articles:
            a.setdefault("source", label)
        return articles
    except Exception as e:
        logger.error(f"fetch_source({key}): {e}")
        return []


async def fetch_all_new(
    push_to: list[int] | None = None,
    app: Application | None = None,
    force: bool = False,
) -> list[dict]:
    """
    Fetch all sources and return articles.
    force=False (default): only return articles not seen before (dedup).
    force=True: return everything scraped right now, ignoring seen cache.
    Scheduled auto-push always uses force=False. Manual /latest uses force=True.
    """
    all_results = await asyncio.gather(*[fetch_source(k) for k in SOURCES])
    articles_out = []
    for articles in all_results:
        for a in articles:
            if force:
                articles_out.append(a)
            elif store.is_new(a["url"]):
                store.mark_seen(a["url"])
                articles_out.append(a)

    if app and push_to and articles_out:
        for chat_id in push_to:
            filtered = [a for a in articles_out if store.article_matches(chat_id, a)]
            if not filtered:
                filtered = articles_out
            for article in filtered[:20]:
                try:
                    text, markup = format_article(article)
                    await app.bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        parse_mode="Markdown",
                        disable_web_page_preview=True,
                        reply_markup=markup,
                    )
                    await asyncio.sleep(0.5)
                except Exception as e:
                    logger.error(f"Push {chat_id}: {e}")

    # Cache papers for /api/papers dashboard endpoint
    if articles_out:
        store.add_papers(articles_out)

    return articles_out


async def send_articles(articles: list[dict], reply_fn, max_n: int = 10):
    for article in articles[:max_n]:
        text, markup = format_article(article)
        await reply_fn(text, parse_mode="Markdown", disable_web_page_preview=True, reply_markup=markup)
        await asyncio.sleep(0.35)


# ─────────────────────────────────────────────────────────────
# Commands — Core
# ─────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id    = update.effective_chat.id
    chat_type  = update.effective_chat.type   # private / group / supergroup / channel
    sub_status = "✅ Subscribed" if store.is_subscribed(chat_id) else "❌ Not subscribed"
    topics     = store.get_topics(chat_id)
    topic_str  = ", ".join(topics) if topics else "All topics (no filter)"

    group_note = ""
    if chat_type in ("group", "supergroup"):
        group_note = (
            "\n\n👥 *Running in group mode!* All commands work here. "
            "Members can use /subscribe to get personal DM updates, "
            "or use @inline mode to share papers in any chat."
        )

    text = (
        "🤖 *AI Research Paper Bot*\n\n"
        "Tracks papers from *9 sources* with direct *PDF links* + *AI deep analysis*.\n\n"
        "*Commands:*\n"
        "/latest — fetch new papers from all sources\n"
        "/source — pick a specific source\n"
        "/browse — browse by year → month\n"
        "/search `<query>` — search any topic\n"
        "/topics — set topic filters for your feed\n"
        "/summarize `<pdf_url>` — deep AI analysis of any paper\n"
        "/subscribe — get papers every 2 days automatically\n"
        "/unsubscribe — stop auto updates\n"
        "/status — your subscription + topics\n\n"
        "💡 *Tip:* Tap *🧠 Analyze this paper* on any result for full AI breakdown.\n"
        "💡 *Inline:* Type `@this_bot <query>` in any chat to search & share papers.\n\n"
        f"*Your status:* {sub_status}\n"
        f"*Your topics:* {topic_str}"
        + group_note
        + dev_footer()
    )
    await update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, ctx)


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    topics  = store.get_topics(chat_id)
    topic_str = ", ".join(topics) if topics else "All topics"
    sub = store.is_subscribed(chat_id)
    await update.message.reply_text(
        f"{'✅ Subscribed' if sub else '❌ Not subscribed'}\n"
        f"📌 Topics: {topic_str}\n\n"
        + ("Use /topics to change filters." if sub else "Use /subscribe to start."),
        parse_mode="Markdown",
    )


async def cmd_subscribe(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    added   = store.subscribe(chat_id)
    verb    = "Subscribed" if added else "Already subscribed"
    await update.message.reply_text(
        f"✅ *{verb}!*\n\nYou'll get new papers every *2 days*.\n\n"
        "Use /topics to filter by subject (optional).\n"
        "Use /unsubscribe to stop.",
        parse_mode="Markdown",
    )


async def cmd_unsubscribe(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    removed = store.unsubscribe(chat_id)
    await update.message.reply_text(
        "👋 *Unsubscribed.* No more automatic updates.\n\nYou can still use all commands manually."
        if removed else
        "ℹ️ You weren't subscribed. Use /subscribe to start.",
        parse_mode="Markdown",
    )


async def cmd_latest(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Fetching from all 9 sources...")
    # force=True: always show latest from all sources, not just unseen ones
    articles = await fetch_all_new(force=True)

    if not articles:
        await msg.edit_text(
            "😐 No papers returned from any source. Check Railway logs.",
            parse_mode="Markdown",
        )
        return

    # Group by source so user sees variety, not just one source dominating
    from collections import defaultdict
    by_source = defaultdict(list)
    for a in articles:
        by_source[a.get("source", "Other")].append(a)

    # Pick up to 2 from each source, interleaved
    interleaved = []
    source_iters = {k: iter(v) for k, v in by_source.items()}
    while len(interleaved) < 18 and source_iters:
        done = []
        for src, it in source_iters.items():
            try:
                interleaved.append(next(it))
                if len(interleaved) >= 18:
                    break
            except StopIteration:
                done.append(src)
        for d in done:
            del source_iters[d]
        if not any(True for _ in source_iters):
            break

    sources_found = len(by_source)
    await msg.edit_text(
        f"✅ *{len(articles)}* papers from *{sources_found}* sources — showing latest from each:",
        parse_mode="Markdown",
    )
    await send_articles(interleaved, update.message.reply_text, max_n=18)

    if len(articles) > 18:
        await update.message.reply_text(
            f"_Use /source to browse each source individually._",
            parse_mode="Markdown",
        )


async def cmd_source(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton(label, callback_data=f"src:{key}")]
        for key, (label, _) in SOURCES.items()
    ]
    keyboard.append([InlineKeyboardButton("🔄 All Sources", callback_data="src:all")])
    await update.message.reply_text(
        "📡 *Pick a source:*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


# ─────────────────────────────────────────────────────────────
# /search
# ─────────────────────────────────────────────────────────────

async def cmd_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query_text = " ".join(ctx.args).strip() if ctx.args else ""
    if not query_text:
        await update.message.reply_text(
            "Usage: `/search <topic>`\n\nExamples:\n"
            "`/search chain of thought reasoning`\n"
            "`/search multimodal alignment`\n"
            "`/search efficient transformers`",
            parse_mode="Markdown",
        )
        return

    msg = await update.message.reply_text(f"🔍 Searching: *{query_text}*...", parse_mode="Markdown")
    results = await search_papers(query_text, max_results=15)

    if not results:
        await msg.edit_text(f"😐 No results found for *{query_text}*.", parse_mode="Markdown")
        return

    await msg.edit_text(f"✅ *{len(results)}* papers for *{query_text}*:", parse_mode="Markdown")
    await send_articles(results, update.message.reply_text, max_n=10)


# ─────────────────────────────────────────────────────────────
# /summarize — manual deep analysis
# ─────────────────────────────────────────────────────────────

async def cmd_summarize(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    url = " ".join(ctx.args).strip() if ctx.args else ""
    if not url or not url.startswith("http"):
        await update.message.reply_text(
            "Usage: `/summarize <pdf_url>`\n\nExample:\n"
            "`/summarize https://arxiv.org/pdf/2303.08774.pdf`\n\n"
            "Or tap *🧠 Analyze this paper* on any paper card.",
            parse_mode="Markdown",
        )
        return

    msg = await update.message.reply_text("🧠 Analyzing paper with GPT-4o... this takes ~30s")
    result = await analyze_paper(url)

    await msg.delete()
    # Split if too long for single Telegram message (4096 char limit)
    for chunk in _split_message(result):
        await update.message.reply_text(chunk, parse_mode="Markdown")
        await asyncio.sleep(0.3)


# ─────────────────────────────────────────────────────────────
# /topics
# ─────────────────────────────────────────────────────────────

async def cmd_topics(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    current = store.get_topics(chat_id)

    rows = []
    for i in range(0, len(PRESET_TOPICS), 2):
        row = []
        for label, _ in PRESET_TOPICS[i:i+2]:
            is_on = label in current
            row.append(InlineKeyboardButton(
                f"{'✅' if is_on else '☐'} {label}",
                callback_data=f"tp:{label}",
            ))
        rows.append(row)
    rows.append([
        InlineKeyboardButton("🗑 Clear all filters", callback_data="tp:__clear__"),
        InlineKeyboardButton("✅ Done",              callback_data="tp:__done__"),
    ])

    await update.message.reply_text(
        "📌 *Topic Filters*\n\nToggle topics for your subscription feed.\n"
        "No selection = receive all papers.",
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode="Markdown",
    )


async def callback_topics(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    chat_id = query.from_user.id
    label   = query.data.split(":", 1)[1]

    if label == "__clear__":
        store.set_topics(chat_id, [])
        await query.answer("Filters cleared. You'll receive all papers.")
    elif label == "__done__":
        current = store.get_topics(chat_id)
        topic_str = ", ".join(current) if current else "All topics"
        await query.answer(f"Saved: {topic_str}")
        await query.edit_message_text(
            f"✅ Topic filter saved: *{topic_str}*", parse_mode="Markdown"
        )
        return
    else:
        current = store.get_topics(chat_id)
        if label in current:
            current.remove(label)
        else:
            current.append(label)
        store.set_topics(chat_id, current)
        await query.answer(f"{'Added' if label in current else 'Removed'}: {label}")

    # Refresh keyboard
    current = store.get_topics(chat_id)
    rows = []
    for i in range(0, len(PRESET_TOPICS), 2):
        row = []
        for t_label, _ in PRESET_TOPICS[i:i+2]:
            is_on = t_label in current
            row.append(InlineKeyboardButton(
                f"{'✅' if is_on else '☐'} {t_label}",
                callback_data=f"tp:{t_label}",
            ))
        rows.append(row)
    rows.append([
        InlineKeyboardButton("🗑 Clear all filters", callback_data="tp:__clear__"),
        InlineKeyboardButton("✅ Done",              callback_data="tp:__done__"),
    ])
    try:
        await query.edit_message_reply_markup(InlineKeyboardMarkup(rows))
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────
# Callback: Analyze paper button
# ─────────────────────────────────────────────────────────────

async def callback_analyze(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    url_key  = query.data.split(":", 1)[1]
    url, title = store.get_cached_url(url_key)

    if not url:
        await query.answer("❌ URL expired. Search for the paper again.", show_alert=True)
        return

    await query.answer("🧠 Analyzing... check the chat in ~30s")
    await query.message.reply_text(
        f"🧠 *Analyzing:* _{title or url}_\n\nUsing GPT-4o — this takes ~30 seconds...",
        parse_mode="Markdown",
    )

    result = await analyze_paper(url, title=title)

    for chunk in _split_message(result):
        await query.message.reply_text(chunk, parse_mode="Markdown")
        await asyncio.sleep(0.3)


# ─────────────────────────────────────────────────────────────
# Browse: Year → Month
# ─────────────────────────────────────────────────────────────

async def cmd_browse(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _show_year_picker(update.message.reply_text)


async def _show_year_picker(send_fn):
    years = list(range(BROWSE_END_YEAR, BROWSE_START_YEAR - 1, -1))
    rows  = [years[i:i+3] for i in range(0, len(years), 3)]
    kb    = [[InlineKeyboardButton(str(y), callback_data=f"yr:{y}") for y in row] for row in rows]
    await send_fn(
        "📅 *Browse papers by date*\n\nSelect a year:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown",
    )


async def _show_month_picker(edit_fn, year: int):
    now    = datetime.now()
    rows   = []
    m_rows = [list(range(1, 13))[i:i+4] for i in range(0, 12, 4)]
    for row in m_rows:
        btn_row = []
        for m in row:
            future = (year == now.year and m > now.month)
            btn_row.append(InlineKeyboardButton(
                f"{'🔒' if future else ''}{MONTHS[m-1]}",
                callback_data="noop" if future else f"mo:{year}:{m}",
            ))
        rows.append(btn_row)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="browse:years")])
    await edit_fn(
        f"📅 *{year}* — Select a month:",
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode="Markdown",
    )


async def callback_browse(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data  = query.data

    if data == "noop":
        await query.answer("Future month — not yet available!")
        return

    if data == "browse:years":
        await query.answer()
        await _show_year_picker(query.edit_message_text)
        return

    if data.startswith("yr:"):
        await query.answer()
        await _show_month_picker(query.edit_message_text, int(data.split(":")[1]))
        return

    if data.startswith("mo:"):
        await query.answer()
        _, year_s, month_s = data.split(":")
        year, month = int(year_s), int(month_s)
        mname = MONTHS[month - 1]

        await query.edit_message_text(f"⏳ Fetching *{mname} {year}* papers...", parse_mode="Markdown")
        articles = await scrape_arxiv_by_month(year, month, max_results=30)

        if not articles:
            await query.edit_message_text(f"😐 No results for {mname} {year}.", parse_mode="Markdown")
            return

        await query.edit_message_text(
            f"✅ *{len(articles)}* papers from *{mname} {year}* — top 10:",
            parse_mode="Markdown",
        )
        for a in articles[:10]:
            a.setdefault("source", "📄 arXiv")
            text, markup = format_article(a)
            await query.message.reply_text(text, parse_mode="Markdown",
                                           disable_web_page_preview=True, reply_markup=markup)
            await asyncio.sleep(0.35)

        if len(articles) > 10:
            kb = [[InlineKeyboardButton("📄 Load more", callback_data=f"more:{year}:{month}:10")]]
            await query.message.reply_text(
                f"_{len(articles)-10} more available._",
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode="Markdown",
            )


async def callback_more(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, year_s, month_s, offset_s = query.data.split(":")
    year, month, offset = int(year_s), int(month_s), int(offset_s)
    mname = MONTHS[month - 1]

    await query.edit_message_text(f"⏳ Loading more from *{mname} {year}*...", parse_mode="Markdown")
    articles = await scrape_arxiv_by_month(year, month, max_results=offset + 20)
    batch    = articles[offset:offset + 10]

    if not batch:
        await query.edit_message_text("No more papers.")
        return

    await query.edit_message_text(
        f"📄 Papers {offset+1}–{offset+len(batch)} from *{mname} {year}*:",
        parse_mode="Markdown",
    )
    for a in batch:
        a.setdefault("source", "📄 arXiv")
        text, markup = format_article(a)
        await query.message.reply_text(text, parse_mode="Markdown",
                                       disable_web_page_preview=True, reply_markup=markup)
        await asyncio.sleep(0.35)

    next_offset = offset + 10
    if next_offset < len(articles):
        kb = [[InlineKeyboardButton("📄 Load more", callback_data=f"more:{year}:{month}:{next_offset}")]]
        await query.message.reply_text(
            f"_{len(articles)-next_offset} more._",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown",
        )


# ─────────────────────────────────────────────────────────────
# Source callback
# ─────────────────────────────────────────────────────────────

async def callback_source(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key   = query.data.split(":")[1]

    if key == "all":
        await query.edit_message_text("⏳ Fetching from all sources...")
        articles = await fetch_all_new(force=True)   # force: show latest regardless of dedup
        label    = "all sources"
    else:
        src_label, _ = SOURCES[key]
        await query.edit_message_text(f"⏳ Fetching *{src_label}*...", parse_mode="Markdown")
        articles = await fetch_source(key)
        label    = src_label

    if not articles:
        await query.edit_message_text(f"😐 No papers from {label}.")
        return

    await query.edit_message_text(f"✅ *{len(articles)}* papers from {label}", parse_mode="Markdown")
    for a in articles[:10]:
        text, markup = format_article(a)
        await query.message.reply_text(text, parse_mode="Markdown",
                                       disable_web_page_preview=True, reply_markup=markup)
        await asyncio.sleep(0.35)


# ─────────────────────────────────────────────────────────────
# Inline Mode — @botname <query>
# ─────────────────────────────────────────────────────────────

async def inline_query_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query_text = update.inline_query.query.strip()

    if len(query_text) < 3:
        await update.inline_query.answer([], switch_pm_text="Type a topic to search papers", switch_pm_parameter="inline_help")
        return

    results_data = await search_papers(query_text, max_results=10)

    inline_results = []
    for i, article in enumerate(results_data[:10]):
        title   = article.get("title", "Untitled")[:120]
        url     = article.get("url", "")
        summary = article.get("summary", "")[:300]
        date    = article.get("date", "")
        source  = article.get("source", "")
        authors = article.get("authors", "")
        is_pdf  = url.endswith(".pdf") or "/pdf/" in url
        icon    = "📥 PDF" if is_pdf else "🔗 Link"

        # Build the message that gets shared
        msg_lines = [f"📄 *{title}*"]
        if authors: msg_lines.append(f"✍️ _{authors}_")
        if date:    msg_lines.append(f"🗓 {date}")
        if source:  msg_lines.append(f"📡 {source}")
        if summary: msg_lines.append(f"\n_{summary}_")
        msg_lines.append(f"\n{icon}: {url}")
        msg_lines.append(f"\n\n🧠 _Use /summarize {url} in the bot for deep AI analysis_")
        message_text = "\n".join(msg_lines)

        inline_results.append(
            InlineQueryResultArticle(
                id=str(i),
                title=title,
                description=f"{date} • {source}\n{summary[:100]}",
                input_message_content=InputTextMessageContent(
                    message_text=message_text,
                    parse_mode="Markdown",
                    disable_web_page_preview=True,
                ),
            )
        )

    await update.inline_query.answer(inline_results, cache_time=60)


# ─────────────────────────────────────────────────────────────
# Group welcome when bot is added
# ─────────────────────────────────────────────────────────────

async def on_bot_added_to_group(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Send a welcome message when the bot is added to a group."""
    result = update.chat_member
    new_member = result.new_chat_member
    # Bot was added
    if new_member.user.id == ctx.bot.id and new_member.status == "member":
        text = (
            "👋 *AI Research Paper Bot is here!*\n\n"
            "I track new AI/ML papers from 9 sources with direct PDF links and deep GPT-4o analysis.\n\n"
            "*Commands:*\n"
            "/latest — fetch new papers now\n"
            "/source — pick a source\n"
            "/search `<topic>` — search papers\n"
            "/browse — browse by year/month\n"
            "/subscribe — subscribe to auto-updates\n\n"
            "💡 Tap *🧠 Analyze this paper* on any result for a full AI breakdown.\n"
            "💡 Use `@this_bot <query>` in any chat to search & share papers inline.\n\n"
            + dev_footer()
        )
        await ctx.bot.send_message(
            chat_id=result.chat.id,
            text=text,
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _split_message(text: str, limit: int = 4000) -> list[str]:
    """Split long messages into Telegram-safe chunks at paragraph boundaries."""
    if len(text) <= limit:
        return [text]
    chunks, current = [], ""
    for para in text.split("\n\n"):
        if len(current) + len(para) + 2 > limit:
            if current:
                chunks.append(current.strip())
            current = para
        else:
            current += ("\n\n" if current else "") + para
    if current:
        chunks.append(current.strip())
    return chunks


async def handle_plain_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle raw PDF URLs dropped into chat."""
    text = update.message.text.strip()
    if re.match(r"https?://\S+\.pdf", text) or "arxiv.org/pdf" in text or "openreview.net/pdf" in text:
        msg = await update.message.reply_text("🧠 Detected PDF link — analyzing with GPT-4o...")
        result = await analyze_paper(text)
        await msg.delete()
        for chunk in _split_message(result):
            await update.message.reply_text(chunk, parse_mode="Markdown")
            await asyncio.sleep(0.3)


# ─────────────────────────────────────────────────────────────
# Scheduler
# ─────────────────────────────────────────────────────────────

async def scheduled_fetch(app: Application):
    recipients = list(set(store.subscribers + ADMIN_IDS))
    logger.info(f"Scheduled fetch — {len(recipients)} recipients")
    new = await fetch_all_new(push_to=recipients, app=app)
    logger.info(f"Done: {len(new)} new papers pushed")


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",       cmd_start))
    app.add_handler(CommandHandler("help",        cmd_help))
    app.add_handler(CommandHandler("latest",      cmd_latest))
    app.add_handler(CommandHandler("source",      cmd_source))
    app.add_handler(CommandHandler("browse",      cmd_browse))
    app.add_handler(CommandHandler("search",      cmd_search))
    app.add_handler(CommandHandler("topics",      cmd_topics))
    app.add_handler(CommandHandler("summarize",   cmd_summarize))
    app.add_handler(CommandHandler("subscribe",   cmd_subscribe))
    app.add_handler(CommandHandler("unsubscribe", cmd_unsubscribe))
    app.add_handler(CommandHandler("status",      cmd_status))

    app.add_handler(CallbackQueryHandler(callback_analyze, pattern=r"^analyze:"))
    app.add_handler(CallbackQueryHandler(callback_source,  pattern=r"^src:"))
    app.add_handler(CallbackQueryHandler(callback_browse,  pattern=r"^(yr:|mo:|browse:|noop)"))
    app.add_handler(CallbackQueryHandler(callback_more,    pattern=r"^more:"))
    app.add_handler(CallbackQueryHandler(callback_topics,  pattern=r"^tp:"))

    app.add_handler(InlineQueryHandler(inline_query_handler))
    app.add_handler(ChatMemberHandler(on_bot_added_to_group, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_plain_text))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(scheduled_fetch, trigger="interval", days=2, args=[app], id="auto_fetch")

    async def on_startup(app):
        scheduler.start()
        await start_api_server(store)
        logger.info("Bot live. Auto-fetch every 2 days.")

    async def on_shutdown(app):
        scheduler.shutdown()

    app.post_init     = on_startup
    app.post_shutdown = on_shutdown

    logger.info("Starting bot...")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
