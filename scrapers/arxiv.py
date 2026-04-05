"""
arXiv scraper using the official arxiv.py library.
- result.pdf_url is resolved directly by the library (no regex hacking)
- Supports latest feed mode AND month-range browse mode
- Covers cs.AI, cs.LG, cs.CL, cs.CV, stat.ML
"""
import arxiv
import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Categories to watch
CATEGORIES = ["cs.AI", "cs.LG", "cs.CL", "cs.CV", "stat.ML"]

# Keywords to keep results focused on LLM/foundation model research
KEYWORDS = [
    "large language model", "llm", "transformer", "foundation model",
    "alignment", "rlhf", "chain of thought", "reasoning", "agent",
    "anthropic", "claude", "gpt", "gemini", "llama", "mistral",
    "multimodal", "vision language", "diffusion", "generative",
    "in-context learning", "emergent", "scaling", "mechanistic",
    "interpretability", "fine-tuning", "instruction tuning",
    "retrieval augmented", "rag", "tool use", "code generation",
    "reinforcement learning", "safety", "hallucination", "jailbreak",
    "prompt", "tokenizer", "attention", "moe", "mixture of experts",
]


def _is_relevant(result: arxiv.Result) -> bool:
    text = (result.title + " " + result.summary).lower()
    return any(kw in text for kw in KEYWORDS)


def _result_to_dict(result: arxiv.Result, source_label: str = "") -> dict:
    authors = ", ".join(str(a) for a in result.authors[:4])
    if len(result.authors) > 4:
        authors += " et al."

    return {
        "title":    result.title.replace("\n", " ").strip(),
        "url":      result.pdf_url or result.entry_id,
        "summary":  result.summary.strip()[:450],
        "date":     result.published.strftime("%Y-%m-%d") if result.published else "",
        "authors":  authors,
        "cats":     ", ".join(result.categories[:3]),
        "source":   source_label,
    }


def _make_client() -> arxiv.Client:
    return arxiv.Client(
        page_size=50,
        delay_seconds=3.0,
        num_retries=3,
    )


async def scrape_arxiv() -> list[dict]:
    """
    Fetch the latest papers across all AI/ML categories.
    Runs the blocking arxiv.Client in a thread so it doesn't block the event loop.
    """
    label = "📄 arXiv (AI/ML/NLP/CV)"

    def _fetch() -> list[dict]:
        client = _make_client()
        # One broad category query — arXiv API supports OR via space
        cat_query = " OR ".join(f"cat:{c}" for c in CATEGORIES)
        search = arxiv.Search(
            query=cat_query,
            max_results=100,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending,
        )
        out = []
        for result in client.results(search):
            if _is_relevant(result):
                out.append(_result_to_dict(result, label))
        return out

    loop = asyncio.get_event_loop()
    try:
        articles = await loop.run_in_executor(None, _fetch)
        logger.info(f"arXiv latest: {len(articles)} relevant papers (all with pdf_url)")
        return articles
    except Exception as e:
        logger.error(f"arXiv scraper error: {e}")
        return []


async def scrape_arxiv_by_month(year: int, month: int, max_results: int = 50) -> list[dict]:
    """
    Fetch papers submitted in a specific year+month using the arXiv API
    submittedDate range filter. Uses arxiv.py's Search + Client properly.
    Returns papers with direct pdf_url from result.pdf_url.
    """
    label = f"📄 arXiv ({datetime(year, month, 1).strftime('%b %Y')})"

    # arXiv date range format: YYYYMMDDHHMMSS
    start_date = f"{year}{month:02d}01000000"
    if month == 12:
        end_date = f"{year + 1}0101000000"
    else:
        end_date = f"{year}{month + 1:02d}01000000"

    cat_query = " OR ".join(f"cat:{c}" for c in CATEGORIES)
    date_query = f"submittedDate:[{start_date} TO {end_date}]"
    full_query = f"({cat_query}) AND {date_query}"

    def _fetch() -> list[dict]:
        client = _make_client()
        search = arxiv.Search(
            query=full_query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending,
        )
        out = []
        for result in client.results(search):
            out.append(_result_to_dict(result, label))
        return out

    loop = asyncio.get_event_loop()
    try:
        articles = await loop.run_in_executor(None, _fetch)
        logger.info(f"arXiv {year}-{month:02d}: {len(articles)} papers")
        return articles
    except Exception as e:
        logger.error(f"arXiv monthly scrape error ({year}-{month:02d}): {e}")
        return []


async def search_arxiv(query: str, max_results: int = 15) -> list[dict]:
    """
    Free-text search on arXiv. Used by the /search command in bot.py.
    Returns papers sorted by relevance with direct pdf_url.
    """
    label = f"📄 arXiv search: {query}"

    def _fetch() -> list[dict]:
        client = _make_client()
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.Relevance,
            sort_order=arxiv.SortOrder.Descending,
        )
        return [_result_to_dict(r, label) for r in client.results(search)]

    loop = asyncio.get_event_loop()
    try:
        articles = await loop.run_in_executor(None, _fetch)
        logger.info(f"arXiv search '{query}': {len(articles)} results")
        return articles
    except Exception as e:
        logger.error(f"arXiv search error: {e}")
        return []
