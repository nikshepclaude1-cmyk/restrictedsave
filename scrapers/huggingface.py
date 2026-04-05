"""
HuggingFace Daily Papers — https://huggingface.co/papers
This page curates the best AI papers daily. All papers link to arXiv,
so we can extract direct PDF links.
"""
import aiohttp
from bs4 import BeautifulSoup
import logging
import re

logger = logging.getLogger(__name__)

URL = "https://huggingface.co/papers"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AIResearchBot/1.0)"}


def _to_pdf(url: str) -> str:
    m = re.search(r"arxiv\.org/abs/(\d+\.\d+)", url)
    if m:
        return f"https://arxiv.org/pdf/{m.group(1)}.pdf"
    return url


async def scrape_huggingface():
    articles = []
    try:
        async with aiohttp.ClientSession(headers=HEADERS) as session:
            async with session.get(URL, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                resp.raise_for_status()
                html = await resp.text()

        soup = BeautifulSoup(html, "html.parser")

        # HF papers page: each paper is an article tag or a card with h3
        for article in soup.select("article, div.paper-card, [class*='paper']"):
            a_tag = article.find("a", href=re.compile(r"papers/\d+\.\d+|arxiv\.org"))
            if not a_tag:
                continue

            href = a_tag.get("href", "")
            # HF internal links like /papers/2401.12345
            if href.startswith("/papers/"):
                arxiv_id = href.split("/papers/")[-1].strip()
                pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
            else:
                pdf_url = _to_pdf(href)

            title_el = article.find(["h3", "h2", "h1"])
            title = title_el.get_text(strip=True) if title_el else a_tag.get_text(strip=True)
            if not title or len(title) < 5:
                continue

            summary_el = article.find("p")
            summary = summary_el.get_text(strip=True) if summary_el else ""

            articles.append({
                "title":   title,
                "url":     pdf_url,
                "summary": summary,
                "date":    "",
            })

        # Fallback: just grab all /papers/XXXX.XXXX links on the page
        if not articles:
            for a in soup.find_all("a", href=re.compile(r"/papers/\d+\.\d+")):
                arxiv_id = a["href"].split("/papers/")[-1].strip()
                title = a.get_text(strip=True)
                if title and len(title) > 5:
                    articles.append({
                        "title":   title,
                        "url":     f"https://arxiv.org/pdf/{arxiv_id}.pdf",
                        "summary": "",
                        "date":    "",
                    })

        # Deduplicate
        seen, out = set(), []
        for a in articles:
            if a["url"] not in seen:
                seen.add(a["url"])
                out.append(a)

        logger.info(f"HuggingFace: {len(out)} papers")
        return out
    except Exception as e:
        logger.error(f"HuggingFace scraper error: {e}")
        return []
