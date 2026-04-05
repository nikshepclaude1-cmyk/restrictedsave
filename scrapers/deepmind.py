"""
Google DeepMind blog + research papers with PDF extraction.
"""
import feedparser
import aiohttp
from bs4 import BeautifulSoup
import asyncio
import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)

FEEDS = [
    "https://deepmind.google/blog/rss.xml",
    "https://www.deepmind.com/blog/rss.xml",
]
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AIResearchBot/1.0)"}


def _to_pdf(url: str) -> str:
    m = re.search(r"arxiv\.org/abs/(\d+\.\d+)", url)
    if m:
        return f"https://arxiv.org/pdf/{m.group(1)}.pdf"
    return url


async def scrape_deepmind():
    loop = asyncio.get_event_loop()
    articles = []

    for feed_url in FEEDS:
        feed = await loop.run_in_executor(None, feedparser.parse, feed_url)
        if not feed.entries:
            continue
        for entry in feed.entries:
            published = ""
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                published = datetime(*entry.published_parsed[:3]).strftime("%Y-%m-%d")

            content = " ".join(
                c.get("value", "") for c in entry.get("content", [])
            ) + entry.get("summary", "")
            pdf_match = re.search(r"arxiv\.org/abs/(\d+\.\d+)", content)
            pdf_url = f"https://arxiv.org/pdf/{pdf_match.group(1)}.pdf" if pdf_match else entry.get("link", "")

            articles.append({
                "title":   entry.get("title", "").strip(),
                "url":     pdf_url,
                "summary": (entry.get("summary") or "")[:400].strip(),
                "date":    published,
            })
        break

    logger.info(f"DeepMind: {len(articles)} articles")
    return articles
