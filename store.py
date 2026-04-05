"""
Persistent JSON store for:
- seen article URLs (dedup)
- subscriber chat IDs
- per-user topic filters
- URL cache (for Telegram analyze button)
- paper cache (for /api/papers HTTP endpoint → dashboard)
"""
import json
import os
import hashlib
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
STORE_PATH = os.environ.get("STORE_PATH", "/data/store.json")

SOURCE_LABEL_TO_KEY = {
    "🟠 Anthropic Research":             "anthropic",
    "🤗 HuggingFace Daily Papers":       "huggingface",
    "📄 arXiv (AI/ML/NLP/CV)":           "arxiv",
    "💻 Papers With Code":               "paperswithcode",
    "🏛 OpenReview (NeurIPS/ICLR/ICML)": "openreview",
    "🔍 Semantic Scholar":               "semantic_scholar",
    "📝 ACL Anthology":                  "acl",
    "🟢 OpenAI Blog":                    "openai_blog",
    "🟣 Google DeepMind":                "deepmind",
}


class ArticleStore:
    def __init__(self):
        self._seen:        set[str]        = set()
        self._subscribers: set[int]        = set()
        self._topics:      dict[int, list] = {}
        self._url_cache:   dict[str, dict] = {}
        self._papers:      list[dict]      = []   # newest first, max 500
        self._load()

    # ── Persistence ──────────────────────────────────────────

    def _load(self):
        try:
            if os.path.exists(STORE_PATH):
                with open(STORE_PATH) as f:
                    data = json.load(f)
                self._seen        = set(data.get("seen", []))
                self._subscribers = set(int(x) for x in data.get("subscribers", []))
                self._topics      = {int(k): v for k, v in data.get("topics", {}).items()}
                self._url_cache   = data.get("url_cache", {})
                self._papers      = data.get("papers", [])
                logger.info(
                    f"Loaded: {len(self._seen)} seen, "
                    f"{len(self._subscribers)} subscribers, "
                    f"{len(self._papers)} papers cached"
                )
        except Exception as e:
            logger.warning(f"Could not load store: {e}. Starting fresh.")

    def _save(self):
        try:
            os.makedirs(os.path.dirname(STORE_PATH), exist_ok=True)
            with open(STORE_PATH, "w") as f:
                json.dump({
                    "seen":        list(self._seen),
                    "subscribers": list(self._subscribers),
                    "topics":      {str(k): v for k, v in self._topics.items()},
                    "url_cache":   self._url_cache,
                    "papers":      self._papers,
                }, f)
        except Exception as e:
            logger.warning(f"Could not save store: {e}")

    # ── URL dedup ─────────────────────────────────────────────

    def is_new(self, url: str) -> bool:
        return url not in self._seen

    def mark_seen(self, url: str):
        self._seen.add(url)
        self._save()

    def reset_seen(self):
        self._seen.clear()
        self._save()

    # ── URL cache (Telegram analyze button) ──────────────────

    def cache_url(self, url: str, title: str = "") -> str:
        key = hashlib.md5(url.encode()).hexdigest()[:16]
        if key not in self._url_cache:
            self._url_cache[key] = {"url": url, "title": title}
            if len(self._url_cache) > 2000:
                oldest = list(self._url_cache.keys())[0]
                del self._url_cache[oldest]
            self._save()
        return key

    def get_cached_url(self, key: str) -> tuple[str, str]:
        entry = self._url_cache.get(key, {})
        return entry.get("url", ""), entry.get("title", "")

    # ── Paper cache (API endpoint for dashboard) ──────────────

    def add_papers(self, articles: list[dict]):
        """
        Cache scraped papers for the /api/papers endpoint.
        Keeps newest 500, deduplicates by URL.
        """
        existing_urls = {p["url"] for p in self._papers}
        now_iso = datetime.now(timezone.utc).isoformat()
        new_ones = []
        for a in articles:
            url = a.get("url", "")
            if not url or url in existing_urls:
                continue
            source_label = a.get("source", "")
            source_key   = SOURCE_LABEL_TO_KEY.get(source_label, "")
            new_ones.append({
                "id":        hashlib.md5(url.encode()).hexdigest(),
                "title":     a.get("title",   "")[:500],
                "url":       url,
                "summary":   a.get("summary", "")[:800],
                "date":      a.get("date",    ""),
                "authors":   a.get("authors", "")[:300],
                "cats":      a.get("cats",    ""),
                "source":    source_label,
                "sourceKey": source_key,
                "scrapedAt": now_iso,
            })
        self._papers = (new_ones + self._papers)[:500]
        self._save()
        if new_ones:
            logger.info(f"Paper cache: added {len(new_ones)}, total {len(self._papers)}")

    def get_papers(
        self,
        source_key: str | None = None,
        search:     str | None = None,
        limit:      int = 50,
        offset:     int = 0,
    ) -> list[dict]:
        papers = self._papers
        if source_key:
            papers = [p for p in papers if p.get("sourceKey") == source_key]
        if search:
            q = search.lower()
            papers = [
                p for p in papers
                if q in (p.get("title","") + p.get("summary","") + p.get("authors","")).lower()
            ]
        return papers[offset : offset + limit]

    @property
    def paper_count(self) -> int:
        return len(self._papers)

    # ── Subscribers ───────────────────────────────────────────

    def subscribe(self, chat_id: int) -> bool:
        if chat_id in self._subscribers:
            return False
        self._subscribers.add(chat_id)
        self._save()
        return True

    def unsubscribe(self, chat_id: int) -> bool:
        if chat_id not in self._subscribers:
            return False
        self._subscribers.discard(chat_id)
        self._save()
        return True

    def is_subscribed(self, chat_id: int) -> bool:
        return chat_id in self._subscribers

    @property
    def subscribers(self) -> list[int]:
        return list(self._subscribers)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    # ── Topic filters ─────────────────────────────────────────

    def get_topics(self, chat_id: int) -> list[str]:
        return self._topics.get(chat_id, [])

    def set_topics(self, chat_id: int, topics: list[str]):
        self._topics[chat_id] = topics
        self._save()

    def article_matches(self, chat_id: int, article: dict) -> bool:
        topics = self._topics.get(chat_id, [])
        if not topics:
            return True
        text = (
            article.get("title", "") + " " +
            article.get("summary", "") + " " +
            article.get("cats", "")
        ).lower()
        from bot import PRESET_TOPICS
        topic_map = {label: kw for label, kw in PRESET_TOPICS}
        for label in topics:
            kw_str = topic_map.get(label, label.lower())
            if any(kw.strip() in text for kw in kw_str.split()):
                return True
        return False
