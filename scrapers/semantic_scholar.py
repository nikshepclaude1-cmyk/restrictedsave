"""
Semantic Scholar — uses their public API to get recent highly-cited
AI/ML papers with open access PDF links.
No API key needed for basic usage (rate limited to 100 req/5min).
"""
import aiohttp
import asyncio
import logging

logger = logging.getLogger(__name__)

API_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AIResearchBot/1.0)"}

QUERIES = [
    "large language model alignment 2024",
    "multimodal foundation model 2024",
    "chain of thought reasoning LLM",
    "AI safety interpretability",
]

FIELDS = "title,abstract,year,openAccessPdf,publicationDate,externalIds"


async def _search(session: aiohttp.ClientSession, query: str) -> list[dict]:
    params = {
        "query":  query,
        "fields": FIELDS,
        "limit":  10,
    }
    try:
        async with session.get(
            API_URL, params=params, timeout=aiohttp.ClientTimeout(total=20)
        ) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()

        out = []
        for p in data.get("data", []):
            title    = p.get("title", "").strip()
            abstract = p.get("abstract", "") or ""
            date     = p.get("publicationDate", "") or str(p.get("year", ""))

            # Get PDF: prefer openAccessPdf, else build from arXiv ID
            pdf_url = ""
            oap = p.get("openAccessPdf")
            if oap and oap.get("url"):
                pdf_url = oap["url"]
            else:
                ext = p.get("externalIds", {})
                arxiv_id = ext.get("ArXiv")
                if arxiv_id:
                    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

            if not title or not pdf_url:
                continue

            out.append({
                "title":   title,
                "url":     pdf_url,
                "summary": abstract[:400],
                "date":    date,
            })
        return out
    except Exception as e:
        logger.warning(f"SemanticScholar query '{query}': {e}")
        return []


async def scrape_semantic_scholar() -> list[dict]:
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        # Stagger requests to avoid rate limit
        results = []
        for q in QUERIES:
            r = await _search(session, q)
            results.extend(r)
            await asyncio.sleep(1)

    seen, articles = set(), []
    for a in results:
        if a["url"] not in seen:
            seen.add(a["url"])
            articles.append(a)

    logger.info(f"SemanticScholar: {len(articles)} papers")
    return articles
