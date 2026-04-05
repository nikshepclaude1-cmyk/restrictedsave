"""
ACL Anthology — NLP papers from ACL, EMNLP, NAACL, EACL, COLING, etc.
Uses the ACL Anthology RSS feed. All papers have direct PDF links.
"""
import feedparser
import asyncio
import logging
from datetime import datetime
import re

logger = logging.getLogger(__name__)

# ACL Anthology doesn't have a great single RSS, but semantic scholar
# has an ACL anthology feed. We use the ACL site's recent papers.
FEEDS = [
    "https://aclanthology.org/anthology+abstracts.bib.gz",  # not RSS, skip
]

# Better: use Semantic Scholar's ACL feed or just scrape anthology
ACL_RECENT_URL = "https://aclanthology.org/events/"

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AIResearchBot/1.0)"}

# ACL Anthology direct paper URL pattern: aclanthology.org/XXXX.XXXX
# PDFs are at: aclanthology.org/XXXX.XXXX.pdf
import aiohttp
from bs4 import BeautifulSoup


async def scrape_acl() -> list[dict]:
    articles = []
    # Scrape the anthology index for recent proceedings
    recent_venues = [
        "https://aclanthology.org/events/acl-2024/",
        "https://aclanthology.org/events/emnlp-2024/",
        "https://aclanthology.org/events/naacl-2024/",
    ]

    try:
        async with aiohttp.ClientSession(headers=HEADERS) as session:
            for venue_url in recent_venues:
                try:
                    async with session.get(venue_url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                        if resp.status != 200:
                            continue
                        html = await resp.text()

                    soup = BeautifulSoup(html, "html.parser")
                    # Paper links follow pattern /YEAR.venue-volume.N
                    paper_links = soup.select("a[href*='.pdf']")[:20]

                    for a in paper_links:
                        href = a.get("href", "")
                        if not href.endswith(".pdf"):
                            continue
                        pdf_url = f"https://aclanthology.org{href}" if href.startswith("/") else href
                        title = a.get_text(strip=True) or a.get("title", "")
                        if not title or len(title) < 5:
                            # Try parent element
                            parent = a.find_parent(["li", "div", "p"])
                            if parent:
                                strong = parent.find(["strong", "b", "span"])
                                title = strong.get_text(strip=True) if strong else ""
                        if not title:
                            continue

                        articles.append({
                            "title":   title,
                            "url":     pdf_url,
                            "summary": "",
                            "date":    "",
                        })
                except Exception as e:
                    logger.warning(f"ACL venue {venue_url}: {e}")

    except Exception as e:
        logger.error(f"ACL scraper error: {e}")

    # Deduplicate
    seen, out = set(), []
    for a in articles:
        if a["url"] not in seen:
            seen.add(a["url"])
            out.append(a)

    logger.info(f"ACL Anthology: {len(out)} papers")
    return out
