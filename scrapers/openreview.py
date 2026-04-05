"""
OpenReview — NeurIPS, ICLR, ICML papers with direct PDF links.
Uses OpenReview's public API (no auth needed for public papers).
"""
import aiohttp
import asyncio
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# OpenReview API v2
API_BASE = "https://api2.openreview.net"

# Venues to track (most recent conferences)
VENUES = [
    "NeurIPS.cc/2024/Conference",
    "ICLR.cc/2025/Conference",
    "ICLR.cc/2024/Conference",
    "ICML.cc/2024/Conference",
]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AIResearchBot/1.0)"}


async def _fetch_venue(session: aiohttp.ClientSession, venue: str) -> list[dict]:
    """Fetch accepted papers from a venue via OpenReview API."""
    articles = []
    try:
        # Get submissions for this venue
        params = {
            "invitation": f"{venue}/-/Submission",
            "details":    "replyCount",
            "limit":      25,
            "offset":     0,
        }
        async with session.get(
            f"{API_BASE}/notes",
            params=params,
            timeout=aiohttp.ClientTimeout(total=25),
        ) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()

        for note in data.get("notes", []):
            content = note.get("content", {})

            # content values can be {"value": ...} in API v2
            def val(k):
                v = content.get(k, "")
                return v.get("value", v) if isinstance(v, dict) else v

            title   = val("title")
            abstract = val("abstract")
            pdf_path = val("pdf")

            if not title:
                continue

            # PDF link
            if pdf_path:
                pdf_url = f"https://openreview.net{pdf_path}" if pdf_path.startswith("/") else pdf_path
            else:
                pdf_url = f"https://openreview.net/forum?id={note.get('id', '')}"

            # Date from cdate (creation timestamp in ms)
            cdate = note.get("cdate", 0)
            date = datetime.fromtimestamp(cdate / 1000).strftime("%Y-%m-%d") if cdate else ""

            articles.append({
                "title":   title,
                "url":     pdf_url,
                "summary": (abstract or "")[:400],
                "date":    date,
            })

    except Exception as e:
        logger.warning(f"OpenReview {venue}: {e}")
    return articles


async def scrape_openreview() -> list[dict]:
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        results = await asyncio.gather(
            *[_fetch_venue(session, v) for v in VENUES],
            return_exceptions=True,
        )

    seen, articles = set(), []
    for r in results:
        if isinstance(r, Exception):
            continue
        for a in r:
            if a["url"] not in seen:
                seen.add(a["url"])
                articles.append(a)

    logger.info(f"OpenReview: {len(articles)} papers")
    return articles
