"""
fashionvoid-bot · dashboard/server.py
─────────────────────────────────────────────────────────────────────────────
FastAPI web dashboard.  Serves the UI and exposes a REST API the frontend
polls for live data.

Endpoints
─────────
  GET  /                        → dashboard HTML
  GET  /api/listings            → recent listings (JSON), filterable by country/platform
  GET  /api/globe-data          → per-country bubble data for the 3D globe
  GET  /api/stats               → platform + db summary stats
  GET  /api/stream              → Server-Sent Events for real-time push
  GET  /api/scraping/status     → current scraper state (paused, mode)
  POST /api/scraping/pause      → pause all scan jobs
  POST /api/scraping/resume     → resume all scan jobs
  POST /api/scraping/interval   → change scan interval + optional auto-revert duration
  GET  /api/config              → get editable keyword groups
  POST /api/config              → update keyword groups + write config.yaml
─────────────────────────────────────────────────────────────────────────────
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
import yaml
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

try:
    from apscheduler.triggers.interval import IntervalTrigger
except ImportError:
    IntervalTrigger = None

logger = logging.getLogger(__name__)

# ── Injected state ────────────────────────────────────────────────────────────
_db = None
_stats_store: dict = {}
_config: dict = {}
_scheduler = None
_config_path: Optional[str] = None
_current_mode: str = "nonstop"
_revert_task: Optional[asyncio.Task] = None
_run_gate = None          # asyncio.Event injected from main.py
_keyword_expander = None  # KeywordAIExpander injected from main.py
_keyword_suggester = None # KeywordSuggester injected from main.py

# ── Interval presets (seconds) ────────────────────────────────────────────────
INTERVAL_PRESETS = {
    "nonstop": 60,
    "5min":    300,
    "15min":   900,
    "30min":   1800,
    "1hr":     3600,
    "2hr":     7200,
    "6hr":     21600,
}

app = FastAPI(title="FashionVoid Monitor", docs_url=None, redoc_url=None)

# ── Static files ──────────────────────────────────────────────────────────────
_STATIC = Path(__file__).parent / "static"
if _STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


# ── HTML ──────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    tmpl = Path(__file__).parent / "templates" / "index.html"
    return HTMLResponse(tmpl.read_text(encoding="utf-8"))


# ── REST API ──────────────────────────────────────────────────────────────────

@app.get("/api/stats")
async def api_stats():
    """Platform scan stats + db summary."""
    db_stats = _db.stats() if _db else {}
    return {
        "db": db_stats,
        "platforms": _stats_store,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ── Country → platform mapping ────────────────────────────────────────────────

_COUNTRY_PLATFORMS = {
    "japan":    ["mercari_jp", "yahoo_auctions", "rakuma"],
    "korea":    ["bunjang"],
    "china":    ["xianyu"],
    "vinted":   ["vinted"],
    "vestiaire":["vestiaire"],
}

_COUNTRY_META = {
    "japan":     {"lat": 36.2048, "lng": 138.2529, "name": "Japan",       "flag": "🇯🇵"},
    "korea":     {"lat": 37.5665, "lng": 126.9780, "name": "South Korea", "flag": "🇰🇷"},
    "china":     {"lat": 31.2304, "lng": 121.4737, "name": "China",       "flag": "🇨🇳"},
    "vinted":    {"lat": 52.3676, "lng":   4.9041, "name": "Vinted",      "flag": "🛍"},
    "vestiaire": {"lat": 48.8566, "lng":   2.3522, "name": "Vestiaire",   "flag": "✦"},
}

# ── Shipping costs per platform (EUR, NL destination) ─────────────────────────
_SHIPPING_COSTS: dict = {
    "mercari_jp":     20.0,   # Japan → NL tracked parcel
    "yahoo_auctions": 20.0,
    "rakuma":         20.0,
    "bunjang":        20.0,   # Korea → NL (similar distance to Japan)
    "xianyu":         25.0,   # China → NL
    "vinted":         25.0,   # EU → NL buyer protection + platform shipping
    "vestiaire":      25.0,
}


def _cost_breakdown(listing: dict) -> dict:
    """
    Return full landed cost breakdown for a listing.

    Fields:
      shipping_cost  — flat rate per platform region (EUR)
      vat_amount     — 21% NL VAT on list price only
      total_landed   — price_eur + vat_amount + shipping_cost
      price_eur_nl   — legacy field (price + VAT, no shipping) kept for compat
    """
    price_eur = listing.get("price_eur")
    if price_eur is None:
        return {
            "shipping_cost": None,
            "vat_amount":    None,
            "total_landed":  None,
            "price_eur_nl":  None,
        }
    platform  = listing.get("platform", "")
    shipping  = _SHIPPING_COSTS.get(platform, 20.0)
    vat       = round(price_eur * 0.21, 2)
    total     = round(price_eur + vat + shipping, 2)
    return {
        "shipping_cost": shipping,
        "vat_amount":    vat,
        "total_landed":  total,
        "price_eur_nl":  round(price_eur + vat, 2),   # legacy
    }


@app.get("/api/globe-data")
async def api_globe_data():
    """Per-country bubble data for the 3D globe."""
    if not _db:
        return {"countries": []}

    result = []
    with _db._conn() as conn:
        for country, platforms in _COUNTRY_PLATFORMS.items():
            placeholders = ",".join("?" * len(platforms))
            row = conn.execute(
                f"SELECT COUNT(*) as total, SUM(is_suspicious) as susp "
                f"FROM listings WHERE platform IN ({placeholders})",
                platforms,
            ).fetchone()
            total = row["total"] or 0
            suspicious = int(row["susp"] or 0)
            meta = _COUNTRY_META[country]
            result.append({
                "country": country,
                "name": meta["name"],
                "flag": meta["flag"],
                "lat": meta["lat"],
                "lng": meta["lng"],
                "total": total,
                "suspicious": suspicious,
                "platforms": platforms,
            })

    return {"countries": result}


@app.get("/api/listings")
async def api_listings(
    platform: str = Query(default="all"),
    country: str = Query(default="all"),
    suspicious_only: bool = Query(default=False),
    clean_only: bool = Query(default=False),
    sort: str = Query(default="newest"),
    limit: int = Query(default=60, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Return recent listings with optional filters. Supports country=japan|korea|china."""
    if not _db:
        return {"listings": []}

    with _db._conn() as conn:
        where_clauses = []
        params: list = []

        # Country filter expands to its platform list
        if country != "all" and country in _COUNTRY_PLATFORMS:
            platforms = _COUNTRY_PLATFORMS[country]
            placeholders = ",".join("?" * len(platforms))
            where_clauses.append(f"platform IN ({placeholders})")
            params.extend(platforms)
        elif platform != "all":
            where_clauses.append("platform = ?")
            params.append(platform)

        if suspicious_only:
            where_clauses.append("is_suspicious = 1")
        elif clean_only:
            where_clauses.append("is_suspicious = 0")

        _ORDER_MAP = {
            "newest":    "first_seen DESC",
            "oldest":    "first_seen ASC",
            "price_asc": "price_eur ASC",
            "price_desc":"price_eur DESC",
        }
        order_sql = _ORDER_MAP.get(sort, "first_seen DESC")

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        total = conn.execute(
            f"SELECT COUNT(*) FROM listings {where_sql}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM listings {where_sql} ORDER BY {order_sql} LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()

    listings = []
    for r in rows:
        d = dict(r)
        d.update(_cost_breakdown(d))
        listings.append(d)

    return {"listings": listings, "total": total, "offset": offset, "limit": limit}


@app.post("/api/bookmarks/toggle")
async def api_toggle_bookmark(request: Request):
    """Toggle bookmark for a listing. Body: {"id": "...", "platform": "..."}"""
    if not _db:
        return {"ok": False}
    body = await request.json()
    lid = body.get("id", "")
    platform = body.get("platform", "")
    if not lid or not platform:
        return {"ok": False, "error": "id and platform required"}
    new_state = _db.toggle_bookmark(lid, platform)
    return {"ok": True, "bookmarked": new_state}


@app.get("/api/bookmarks")
async def api_get_bookmarks():
    """Return all bookmarked listings grouped by keyword_group."""
    if not _db:
        return {"listings": [], "total": 0}
    listings = _db.get_bookmarks()
    for d in listings:
        d.update(_cost_breakdown(d))
    return {"listings": listings, "total": len(listings)}


@app.get("/api/stream")
async def api_stream():
    """
    Server-Sent Events endpoint.
    Pushes a stats update every 3 seconds so the dashboard stays live
    without the client hammering /api/stats.
    """
    async def event_generator():
        while True:
            db_stats = _db.stats() if _db else {}
            payload = json.dumps({
                "db": db_stats,
                "platforms": _stats_store,
                "timestamp": datetime.utcnow().isoformat(),
            })
            yield f"data: {payload}\n\n"
            await asyncio.sleep(3)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Scraping control ──────────────────────────────────────────────────────────

@app.get("/api/scraping/status")
async def api_scraping_status():
    """Return whether scraper is paused and the current interval mode."""
    paused = False
    if _run_gate is not None:
        paused = not _run_gate.is_set()
    elif _scheduler:
        paused = _scheduler.state == 2  # STATE_PAUSED = 2
    return {"paused": paused, "mode": _current_mode}


@app.post("/api/scraping/pause")
async def api_scrape_pause():
    """Pause immediately: clear run gate (stops in-flight scans between terms)
    and pause the scheduler (prevents new scans from starting)."""
    if _run_gate is not None:
        _run_gate.clear()
    if _scheduler:
        _scheduler.pause()
    return {"ok": True, "paused": True}


@app.post("/api/scraping/resume")
async def api_scrape_resume():
    """Resume: set the run gate and resume the scheduler."""
    if _run_gate is not None:
        _run_gate.set()
    if _scheduler:
        _scheduler.resume()
    return {"ok": True, "paused": False}


@app.post("/api/scraping/interval")
async def api_scrape_interval(request: Request):
    """
    Body: {"mode": "5min", "duration_min": 60}
    duration_min=null means run until manually changed.
    """
    global _current_mode, _revert_task
    body = await request.json()
    mode = body.get("mode", "nonstop")
    duration_min = body.get("duration_min")  # None = until stopped
    interval_s = INTERVAL_PRESETS.get(mode, 60)
    _current_mode = mode

    if _scheduler and IntervalTrigger:
        for job in _scheduler.get_jobs():
            if job.id.startswith("scan_"):
                job.reschedule(trigger=IntervalTrigger(seconds=interval_s))

    # Selecting an interval mode implicitly resumes the bot
    if _run_gate is not None:
        _run_gate.set()
    if _scheduler:
        _scheduler.resume()

    # Cancel any existing revert timer
    if _revert_task and not _revert_task.done():
        _revert_task.cancel()
        _revert_task = None

    if duration_min:
        async def _revert_after():
            global _current_mode, _revert_task
            await asyncio.sleep(int(duration_min) * 60)
            _current_mode = "nonstop"
            if _scheduler and IntervalTrigger:
                for job in _scheduler.get_jobs():
                    if job.id.startswith("scan_"):
                        job.reschedule(trigger=IntervalTrigger(seconds=60))
            _revert_task = None

        _revert_task = asyncio.create_task(_revert_after())

    return {"ok": True, "mode": mode, "interval_s": interval_s}


# ── Config editing ────────────────────────────────────────────────────────────

@app.post("/api/translate")
async def api_translate(request: Request):
    """Translate a list of English terms to JP / KR / CN using the free Google endpoint."""
    body = await request.json()
    terms: list[str] = body.get("terms", [])
    targets: list[str] = body.get("targets", ["ja", "ko", "zh-cn"])
    if not terms:
        return {t: [] for t in targets}

    async def _translate_one(text: str, tl: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(
                    "https://translate.googleapis.com/translate_a/single",
                    params={"client": "gtx", "sl": "en", "tl": tl, "dt": "t", "q": text},
                )
                r.raise_for_status()
                data = r.json()
                return "".join(part[0] for part in data[0] if part and part[0])
        except Exception:
            return text

    result: dict[str, list[str]] = {}
    for tl in targets:
        result[tl] = list(await asyncio.gather(*[_translate_one(t, tl) for t in terms]))

    return result


@app.get("/api/config")
async def api_get_config():
    """Return editable keyword groups from the loaded config."""
    return {"keywords": _config.get("keywords", [])}


@app.post("/api/config")
async def api_update_config(request: Request):
    """Update keyword groups in memory and persist to config.yaml.
    If ai_expander.auto_expand_on_save is true, triggers expansion for
    any group that has empty terms_jp/kr/cn."""
    global _config
    body = await request.json()
    if "keywords" in body:
        _config["keywords"] = body["keywords"]
    if _config_path:
        with open(_config_path, "w", encoding="utf-8") as f:
            yaml.dump(_config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    # Auto-expand groups with missing Asian terms if configured
    if (
        _keyword_expander
        and _config.get("ai_expander", {}).get("auto_expand_on_save", False)
    ):
        for group in _config.get("keywords", []):
            missing = not any([
                group.get("terms_jp"),
                group.get("terms_kr"),
                group.get("terms_cn"),
            ])
            if missing and group.get("user_input"):
                asyncio.ensure_future(
                    _run_expansion(group["group"], group["user_input"])
                )

    return {"ok": True}


async def _run_expansion(group_name: str, user_input: str) -> None:
    """Background task: expand keywords and write results back to config."""
    if not _keyword_expander:
        return
    try:
        result = await _keyword_expander.expand(user_input, group_name)
        if not result:
            return
        for group in _config.get("keywords", []):
            if group.get("group") == group_name:
                group.update(result)
                break
        if _config_path:
            with open(_config_path, "w", encoding="utf-8") as f:
                yaml.dump(_config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        logger.info(f"[config] Auto-expansion complete for '{group_name}'")
    except Exception as exc:
        logger.error(f"[config] Auto-expansion failed for '{group_name}': {exc}")


@app.post("/api/config/expand/{group_name}")
async def api_expand_keywords(group_name: str):
    """Manually trigger full AI keyword expansion for a specific keyword group.
    Runs the 4-step pipeline (EN expand → DeepL translate → per-market GPT-4o → verify)
    and writes the result back to config.yaml."""
    if not _keyword_expander:
        return {"ok": False, "error": "OpenAI not configured — set openai.api_key in config.yaml"}

    group = next(
        (g for g in _config.get("keywords", []) if g.get("group") == group_name),
        None,
    )
    if not group:
        return {"ok": False, "error": f"Group '{group_name}' not found"}

    user_input = group.get("user_input") or group.get("group")
    asyncio.ensure_future(_run_expansion(group_name, user_input))
    return {"ok": True, "message": f"Expansion started for '{group_name}'"}


@app.get("/api/config/suggest")
async def api_suggest_keywords(q: str = ""):
    """Real-time keyword suggestions for the UI keyword editor.
    Returns up to 6 verified JP/KR/CN terms for the given input string."""
    if not _keyword_suggester:
        return {"suggestions": [], "error": "OpenAI not configured"}
    if len(q.strip()) < 3:
        return {"suggestions": []}
    try:
        suggestions = await _keyword_suggester.suggest(q.strip())
        return {"suggestions": suggestions}
    except Exception as exc:
        logger.error(f"[config] Suggest failed: {exc}")
        return {"suggestions": [], "error": str(exc)}


# ── Init ──────────────────────────────────────────────────────────────────────

def init(db, stats_store: dict, config: dict, scheduler=None, config_path: str = None,
         run_gate=None, keyword_expander=None, keyword_suggester=None):
    """Called from main.py to inject shared state."""
    global _db, _stats_store, _config, _scheduler, _config_path, _run_gate
    global _keyword_expander, _keyword_suggester
    _db = db
    _stats_store = stats_store
    _config = config
    _scheduler = scheduler
    _config_path = config_path
    _run_gate = run_gate
    _keyword_expander = keyword_expander
    _keyword_suggester = keyword_suggester
