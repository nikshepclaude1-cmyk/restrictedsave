"""
Multi-source paper search:
- arXiv (via arxiv.py — proper relevance ranking, pdf_url, authors)
- Semantic Scholar (open access PDFs across all venues)

Used by /search command and @bot inline mode.
"""
import asyncio
import aiohttp
import logging
from scrapers.arxiv import search_arxiv   # uses arxiv.py Client properly

logger  = logging.getLogger(__name__)
SS_API  = "https://api.semanticscholar.org/graph/v1/paper/search"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AIResearchBot/1.0)"}


async def _search_semantic_scholar(query: str, n: int = 10) -> list[dict]:
    params = {
        "query":  query,
        "fields": "title,abstract,year,openAccessPdf,publicationDate,externalIds,authors",
        "limit":  n,
    }
    try:
        async with aiohttp.ClientSession(headers=HEADERS) as session:
            async with session.get(
                SS_API, params=params, timeout=aiohttp.ClientTimeout(total=25)
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()

        out = []
        for p in data.get("data", []):
            title    = p.get("title", "").strip()
            abstract = p.get("abstract") or ""
            date     = p.get("publicationDate") or str(p.get("year", ""))
            authors_raw = p.get("authors") or []
            authors  = ", ".join(a.get("name","") for a in authors_raw[:4])
            if len(authors_raw) > 4:
                authors += " et al."

            pdf_url = ""
            oap = p.get("openAccessPdf")
            if oap and oap.get("url"):
                pdf_url = oap["url"]
            else:
                arxiv_id = (p.get("externalIds") or {}).get("ArXiv")
                if arxiv_id:
                    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

            if not title or not pdf_url:
                continue
            out.append({
                "title":   title,
                "url":     pdf_url,
                "summary": abstract[:400],
                "date":    date,
                "authors": authors,
                "source":  "🔍 Semantic Scholar",
            })
        return out
    except Exception as e:
        logger.error(f"Semantic Scholar search error: {e}")
        return []


async def search_papers(query: str, max_results: int = 15) -> list[dict]:
    """
    Search arXiv (via arxiv.py) + Semantic Scholar simultaneously.
    arXiv uses proper relevance ranking and returns result.pdf_url directly.
    Merges and deduplicates by PDF URL.
    """
    arxiv_task = search_arxiv(query, max_results=max_results)
    ss_task    = _search_semantic_scholar(query, n=max_results)

    arxiv_res, ss_res = await asyncio.gather(arxiv_task, ss_task, return_exceptions=True)

    combined = []
    if not isinstance(arxiv_res, Exception):
        combined.extend(arxiv_res)
    if not isinstance(ss_res, Exception):
        combined.extend(ss_res)

    seen, out = set(), []
    for a in combined:
        if a.get("url") and a["url"] not in seen:
            seen.add(a["url"])
            out.append(a)

    logger.info(f"search_papers('{query}'): {len(out)} results")
    return out[:max_results]
