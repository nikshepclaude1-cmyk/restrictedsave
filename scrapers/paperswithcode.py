"""
PapersWithCode — https://paperswithcode.com/latest
Curated ML papers, all linking to arXiv → direct PDF links.
Uses their public API.
"""
import aiohttp
import logging
import re

logger = logging.getLogger(__name__)

API_URL = "https://paperswithcode.com/api/v1/papers/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AIResearchBot/1.0)"}


def _to_pdf(url: str) -> str:
    if not url:
        return ""
    m = re.search(r"arxiv\.org/abs/(\d+\.\d+)", url)
    if m:
        return f"https://arxiv.org/pdf/{m.group(1)}.pdf"
    # already a pdf link
    if url.endswith(".pdf"):
        return url
    return url


async def scrape_paperswithcode() -> list[dict]:
    articles = []
    try:
        params = {"ordering": "-published", "items_per_page": 30}
        async with aiohttp.ClientSession(headers=HEADERS) as session:
            async with session.get(
                API_URL, params=params, timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()

        for paper in data.get("results", []):
            title    = paper.get("title", "").strip()
            abstract = paper.get("abstract", "")
            date     = paper.get("published", "")[:10]
            url_web  = paper.get("url_abs") or paper.get("url_pdf") or ""
            pdf_url  = paper.get("url_pdf") or _to_pdf(url_web)

            if not title or not pdf_url:
                continue

            articles.append({
                "title":   title,
                "url":     pdf_url,
                "summary": (abstract or "")[:400],
                "date":    date,
            })

        logger.info(f"PapersWithCode: {len(articles)} papers")
    except Exception as e:
        logger.error(f"PapersWithCode scraper error: {e}")
    return articles
