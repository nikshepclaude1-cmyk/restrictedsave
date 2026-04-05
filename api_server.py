"""
Lightweight aiohttp HTTP server that runs alongside the Telegram bot.
Exposes a JSON API so papers.nikshep.vercel.app can fetch papers
without any Firebase/database dependency.

Endpoints:
  GET /api/papers          — paginated paper list
  GET /api/papers/stats    — counts per source + total
  GET /health              — health check

Query params for /api/papers:
  source    — filter by sourceKey (e.g. "anthropic", "arxiv")
  search    — full-text search across title/summary/authors
  limit     — default 50, max 100
  offset    — for pagination

Railway exposes PORT env var. Bot runs on polling (no webhook port conflict).
"""
import os
import json
import logging
from aiohttp import web

logger = logging.getLogger(__name__)

PORT = int(os.environ.get("PORT", 8080))

# CORS origins allowed — your Vercel dashboard
ALLOWED_ORIGINS = [
    "https://papers.nikshep.vercel.app",
    "https://nikshep.vercel.app",
    "http://localhost:5173",   # local dev
    "http://localhost:4173",
]


def cors_headers(request: web.Request) -> dict:
    origin = request.headers.get("Origin", "")
    allowed = origin if origin in ALLOWED_ORIGINS else ALLOWED_ORIGINS[0]
    return {
        "Access-Control-Allow-Origin":  allowed,
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Cache-Control":                "public, max-age=120",   # 2 min cache
    }


def json_response(data, status=200, request=None) -> web.Response:
    return web.Response(
        text=json.dumps(data, ensure_ascii=False, default=str),
        status=status,
        content_type="application/json",
        headers=cors_headers(request) if request else {},
    )


def make_app(store) -> web.Application:
    app = web.Application()

    async def handle_options(request: web.Request) -> web.Response:
        return web.Response(status=204, headers=cors_headers(request))

    async def handle_papers(request: web.Request) -> web.Response:
        try:
            source = request.rel_url.query.get("source") or None
            search = request.rel_url.query.get("search") or None
            limit  = min(int(request.rel_url.query.get("limit",  50)), 100)
            offset = max(int(request.rel_url.query.get("offset",  0)),   0)
        except ValueError:
            return json_response({"error": "Invalid query params"}, 400, request)

        papers = store.get_papers(source_key=source, search=search, limit=limit, offset=offset)
        total  = store.paper_count

        return json_response({
            "papers": papers,
            "total":  total,
            "limit":  limit,
            "offset": offset,
            "hasMore": (offset + limit) < total,
        }, request=request)

    async def handle_stats(request: web.Request) -> web.Response:
        all_papers = store.get_papers(limit=500)
        counts = {}
        for p in all_papers:
            sk = p.get("sourceKey", "unknown")
            counts[sk] = counts.get(sk, 0) + 1
        return json_response({
            "total":   store.paper_count,
            "sources": counts,
        }, request=request)

    async def handle_health(request: web.Request) -> web.Response:
        return json_response({"status": "ok", "papers": store.paper_count}, request=request)

    app.router.add_route("OPTIONS", "/api/papers",       handle_options)
    app.router.add_route("OPTIONS", "/api/papers/stats", handle_options)
    app.router.add_get(  "/api/papers",                  handle_papers)
    app.router.add_get(  "/api/papers/stats",            handle_stats)
    app.router.add_get(  "/health",                      handle_health)

    return app


async def start_api_server(store) -> web.AppRunner:
    """Start the API server as a background task. Call from bot startup."""
    app    = make_app(store)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"API server live on port {PORT} → /api/papers")
    return runner
