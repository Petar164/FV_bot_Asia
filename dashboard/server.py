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
_config_path: str | None = None
_current_mode: str = "nonstop"
_revert_task: asyncio.Task | None = None
_run_gate = None   # asyncio.Event injected from main.py

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
    "japan":  ["mercari_jp", "yahoo_auctions", "rakuma"],
    "korea":  ["bunjang"],
    "china":  ["xianyu"],
}

_COUNTRY_META = {
    "japan": {"lat": 36.2048, "lng": 138.2529, "name": "Japan",       "flag": "🇯🇵"},
    "korea": {"lat": 37.5665, "lng": 126.9780, "name": "South Korea", "flag": "🇰🇷"},
    "china": {"lat": 31.2304, "lng": 121.4737, "name": "China",       "flag": "🇨🇳"},
}

# NL VAT: 21% on all items, no import duty threshold
def _nl_landed(price_eur: float) -> float:
    if price_eur is None:
        return None
    return round(price_eur * 1.21, 2)


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
    limit: int = Query(default=60, le=200),
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

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        rows = conn.execute(
            f"SELECT * FROM listings {where_sql} ORDER BY first_seen DESC LIMIT ?",
            params + [limit],
        ).fetchall()

    listings = []
    for r in rows:
        d = dict(r)
        d["price_eur_nl"] = _nl_landed(d.get("price_eur"))
        listings.append(d)

    return {"listings": listings}


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

@app.get("/api/config")
async def api_get_config():
    """Return editable keyword groups from the loaded config."""
    return {"keywords": _config.get("keywords", [])}


@app.post("/api/config")
async def api_update_config(request: Request):
    """Update keyword groups in memory and persist to config.yaml."""
    global _config
    body = await request.json()
    if "keywords" in body:
        _config["keywords"] = body["keywords"]
    if _config_path:
        with open(_config_path, "w", encoding="utf-8") as f:
            yaml.dump(_config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    return {"ok": True}


# ── Init ──────────────────────────────────────────────────────────────────────

def init(db, stats_store: dict, config: dict, scheduler=None, config_path: str = None, run_gate=None):
    """Called from main.py to inject shared state."""
    global _db, _stats_store, _config, _scheduler, _config_path, _run_gate
    _db = db
    _stats_store = stats_store
    _config = config
    _scheduler = scheduler
    _config_path = config_path
    _run_gate = run_gate
