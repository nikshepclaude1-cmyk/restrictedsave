"""
Scrapes https://www.anthropic.com/research for papers.
For each paper card, follows the link to extract the direct PDF URL.
Falls back to the paper page URL if no PDF found.
"""
import aiohttp
import asyncio
from bs4 import BeautifulSoup
import logging
import re

logger = logging.getLogger(__name__)

BASE_URL = "https://www.anthropic.com"
RESEARCH_URL = f"{BASE_URL}/research"

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AIResearchBot/1.0)"}


async def _fetch(session, url):
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
        resp.raise_for_status()
        return await resp.text()


async def _extract_pdf_from_page(session, page_url):
    try:
        html = await _fetch(session, page_url)
        soup = BeautifulSoup(html, "html.parser")

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.endswith(".pdf"):
                return href if href.startswith("http") else BASE_URL + href
            if "arxiv.org/pdf" in href:
                return href
            if re.search(r"/pdf/|/paper\.pdf|download.*pdf", href, re.I):
                return href if href.startswith("http") else BASE_URL + href

        for a in soup.find_all("a", href=True):
            m = re.search(r"arxiv\.org/abs/(\d+\.\d+)", a["href"])
            if m:
                return f"https://arxiv.org/pdf/{m.group(1)}.pdf"
    except Exception as e:
        logger.warning(f"Could not extract PDF from {page_url}: {e}")
    return None


async def scrape_anthropic():
    articles = []
    try:
        async with aiohttp.ClientSession(headers=HEADERS) as session:
            html = await _fetch(session, RESEARCH_URL)
            soup = BeautifulSoup(html, "html.parser")

            cards = soup.select("a[href^='/research/']")
            seen = set()
            candidates = []

            for card in cards:
                href = card.get("href", "")
                if not href or href in seen or href == "/research":
                    continue
                seen.add(href)

                title_el = card.find(["h2", "h3", "h4"])
                title = title_el.get_text(strip=True) if title_el else card.get_text(strip=True)
                if not title or len(title) < 4:
                    continue

                summary_el = card.find("p")
                summary = summary_el.get_text(strip=True) if summary_el else ""

                date_el = card.find("time")
                date = date_el.get("datetime", date_el.get_text(strip=True)) if date_el else ""

                candidates.append({
                    "title": title, "page_url": BASE_URL + href,
                    "summary": summary, "date": date,
                })

            async def resolve(c):
                pdf = await _extract_pdf_from_page(session, c["page_url"])
                return {
                    "title": c["title"], "url": pdf or c["page_url"],
                    "summary": c["summary"], "date": c["date"], "has_pdf": pdf is not None,
                }

            results = await asyncio.gather(*[resolve(c) for c in candidates[:15]], return_exceptions=True)
            for r in results:
                if not isinstance(r, Exception):
                    articles.append(r)

        logger.info(f"Anthropic: {len(articles)} articles, {sum(1 for a in articles if a.get('has_pdf'))} with PDF")
    except Exception as e:
        logger.error(f"Anthropic scraper error: {e}")
    return articles
