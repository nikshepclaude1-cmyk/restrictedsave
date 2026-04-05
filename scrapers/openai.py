"""
OpenAI blog + research. RSS for blog, HTML scrape for research papers with PDF links.
"""
import feedparser
import aiohttp
import asyncio
from bs4 import BeautifulSoup
import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)

BLOG_FEED   = "https://openai.com/news/rss/"
RESEARCH_URL = "https://openai.com/research"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AIResearchBot/1.0)"}


def _to_pdf(url: str) -> str:
    m = re.search(r"arxiv\.org/abs/(\d+\.\d+)", url)
    if m:
        return f"https://arxiv.org/pdf/{m.group(1)}.pdf"
    return url


async def _blog_articles():
    loop = asyncio.get_event_loop()
    feed = await loop.run_in_executor(None, feedparser.parse, BLOG_FEED)
    out = []
    for entry in feed.entries:
        published = ""
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            published = datetime(*entry.published_parsed[:3]).strftime("%Y-%m-%d")
        link = entry.get("link", "")
        # Check for PDF link inside content
        content = " ".join(
            c.get("value", "") for c in entry.get("content", [])
        ) + entry.get("summary", "")
        pdf_match = re.search(r"arxiv\.org/abs/(\d+\.\d+)", content)
        pdf_url = f"https://arxiv.org/pdf/{pdf_match.group(1)}.pdf" if pdf_match else link

        out.append({
            "title":   entry.get("title", "").strip(),
            "url":     pdf_url,
            "summary": (entry.get("summary") or "")[:400].strip(),
            "date":    published,
        })
    return out


async def scrape_openai():
    articles = await _blog_articles()
    logger.info(f"OpenAI: {len(articles)} articles")
    return articles
