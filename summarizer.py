"""
Deep paper analysis using OpenAI gpt-4o-mini.
gpt-4o-mini is 100x cheaper than gpt-4o and still excellent for structured analysis.
Requires OPENAI_API_KEY with billing enabled on platform.openai.com
"""
import os
import io
import asyncio
import aiohttp
import logging
import re

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL   = "gpt-4o-mini"
OPENAI_URL     = "https://api.openai.com/v1/chat/completions"

ANALYSIS_SYSTEM = """You are an expert AI/ML research analyst with deep knowledge of machine learning, NLP, computer vision, and AI safety.
You produce thorough, technically accurate paper analyses useful for both researchers and practitioners.
Always be specific — cite actual numbers, method names, and findings from the paper. Never be vague."""

ANALYSIS_PROMPT = """Analyze this research paper and produce a structured deep analysis. Use Markdown bold headers exactly as shown:

**🔑 TL;DR**
2-3 sentences. What is this paper about and why does it matter?

**🚀 Key Contributions**
3-6 bullet points. What is genuinely new here? Be specific.

**⚙️ Methodology**
2-3 paragraphs. How did they approach the problem? What architecture, training procedure, dataset, or technique? Be technical.

**📊 Results & Benchmarks**
Specific numbers. Which benchmarks? What scores? How do they compare to prior work?

**⚠️ Limitations & Weaknesses**
2-4 honest points. What does this paper not address? Where might it fail in practice?

**💡 Key Takeaways to Apply**
3-5 actionable insights. If a practitioner wanted to use or build on this today, what should they take away?

**👥 Who Should Read This**
1-2 sentences. Specific audience (e.g. "ML engineers working on RAG pipelines").

**📚 Related Work to Explore Next**
3-5 paper titles or research directions that connect to this work.

Be technically precise. Use exact terminology from the paper."""


async def _fetch_pdf_text(pdf_url: str, max_chars: int = 15000) -> str:
    """Download PDF and extract raw text using pdfminer."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; AIResearchBot/1.0)"}
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(pdf_url, timeout=aiohttp.ClientTimeout(total=40)) as resp:
                resp.raise_for_status()
                pdf_bytes = await resp.read()

        from pdfminer.high_level import extract_text
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(
            None,
            lambda: extract_text(io.BytesIO(pdf_bytes), maxpages=10)
        )
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        logger.info(f"PDF extracted: {len(text)} chars from {pdf_url}")
        return text[:max_chars]
    except Exception as e:
        logger.error(f"PDF fetch/extract error for {pdf_url}: {e}")
        return ""


async def analyze_paper(pdf_url: str, title: str = "") -> str:
    """
    Fetch a PDF and return a gpt-4o-mini deep structured analysis.
    Returns formatted string ready to send as Telegram message.
    """
    if not OPENAI_API_KEY:
        return (
            "❌ *OPENAI_API_KEY not set.*\n\n"
            "Add it to Railway → Variables tab.\n"
            "Get your key at platform.openai.com/api-keys"
        )

    label = f'"{title}"' if title else pdf_url
    text  = await _fetch_pdf_text(pdf_url)

    if not text or len(text) < 300:
        return (
            f"❌ Could not extract readable text from this PDF.\n\n"
            "It may be scanned/image-only or access-restricted.\n"
            f"Open directly: {pdf_url}"
        )

    user_content = f"Paper: {label}\n\nExtracted text:\n\n{text}"
    payload = {
        "model":       OPENAI_MODEL,
        "max_tokens":  2000,
        "temperature": 0.3,
        "messages": [
            {"role": "system", "content": ANALYSIS_SYSTEM},
            {"role": "user",   "content": f"{ANALYSIS_PROMPT}\n\n---\n\n{user_content}"},
        ],
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                OPENAI_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type":  "application/json",
                },
                timeout=aiohttp.ClientTimeout(total=90),
            ) as resp:
                data = await resp.json()

        if "error" in data:
            err      = data["error"].get("message", "Unknown error")
            err_code = data["error"].get("code", "")
            logger.error(f"OpenAI error [{err_code}]: {err}")

            if err_code == "insufficient_quota" or "quota" in err.lower():
                return (
                    "❌ *OpenAI quota exceeded.*\n\n"
                    "Your API key has no credit balance.\n\n"
                    "Fix:\n"
                    "1. Go to platform.openai.com/billing\n"
                    "2. Add payment method + credits ($5 min)\n"
                    "3. This bot uses `gpt-4o-mini` — costs ~$0.002 per analysis\n\n"
                    "_Analysis will work as soon as balance is added._"
                )
            if err_code in ("invalid_api_key", "unauthorized"):
                return "❌ Invalid OpenAI API key. Check `OPENAI_API_KEY` in Railway Variables."

            return f"❌ OpenAI error: {err}"

        choices = data.get("choices", [])
        if not choices:
            return "❌ No response from OpenAI. Try again."

        result = choices[0]["message"]["content"].strip()
        tokens = data.get("usage", {}).get("total_tokens", 0)
        logger.info(f"Analysis done for '{title}': {tokens} tokens")
        return result

    except Exception as e:
        logger.error(f"OpenAI request failed: {e}")
        return f"❌ Request failed: {e}"


# Backward compat alias
async def summarize_paper(pdf_url: str) -> str:
    return await analyze_paper(pdf_url)
