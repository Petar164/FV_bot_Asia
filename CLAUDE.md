# FashionVoid Market Monitor — Agent Guide

## What This Project Is
A Python bot that scrapes secondhand fashion marketplaces for specific keyword groups, translates listings from JP/KR/CN to English, converts prices to EUR, scores deals, and fires alerts via Telegram. The owner monitors rare/vintage fashion (e.g. Dior Homme Hedi Slimane era) across Asian and EU resale platforms.

## How to Start the Bot
```bash
cd /Users/fashionvoid/Documents/GitHub/FV_bot_Asia
.venv/bin/python main.py
```
Dashboard runs at `http://127.0.0.1:8888`. Kill with `Ctrl+C` or `lsof -ti :8888 | xargs kill -9`.

**One-shot test (no scheduler):**
```bash
.venv/bin/python main.py --once
```

**Single platform:**
```bash
.venv/bin/python main.py --platform mercari_jp
```

## Python Environment
- Python 3.9.6 (macOS system) — venv at `.venv/`
- **Never use `str | None` or `X | Y` union syntax** — Python 3.9 requires `Optional[X]` from `typing`
- Install deps: `.venv/bin/pip install -r requirements.txt`
- Playwright browsers: `.venv/bin/playwright install chromium`

## Project Structure
```
main.py                  — entry point, scheduler, wires everything together
config.yaml              — user config (gitignored — contains secrets)
config.yaml.example      — template for new setups
scrapers/
  base_scraper.py        — abstract base: process_listings, run, _notify, session persistence
  mercari_jp.py          — Playwright/Chromium
  yahoo_auctions.py      — Playwright/Chromium + auction end-time parsing
  vinted.py              — camoufox (stealth Firefox) + Playwright fallback
  vestiaire.py           — camoufox + Playwright fallback
  bunjang.py             — Playwright/Chromium
  xianyu.py              — Playwright/Chromium (frequently times out, needs login)
  rakuma.py              — DEAD (merged into Mercari JP 2024), remove from config
notifications/
  telegram_alert.py      — Telegram Bot API via httpx, cards + command polling
  email_alert.py         — SMTP
  sms_alert.py           — Twilio
  push_alert.py          — ntfy.sh
dashboard/
  server.py              — FastAPI app, REST API, SSE stream
  templates/index.html   — single-page dashboard UI
db/
  database.py            — SQLite wrapper (WAL mode, no ORM)
utils/
  translator.py          — DeepL primary, Google fallback
  currency.py            — exchangerate-api, 1hr TTL cache
  vision_filter.py       — GPT-4o image scoring (disabled if no API key)
  keyword_ai_expander.py — OpenAI keyword expansion
  proxy_manager.py       — proxy rotation (disabled by default)
```

## Key Concepts

### Listing Flow
1. `scraper.search(term, kw_group)` → raw listings (original titles, no FX)
2. `base_scraper.process_listings()` → FX convert, must_contain filter, price ceiling, translate, suspicious check, insert DB
3. `base_scraper._notify()` → vision score → route to Telegram/email/push

### Keyword Groups (config.yaml)
Each group has:
- `terms_en/jp/kr/cn` — search terms per language
- `must_contain` — **required**: at least one must appear in the raw title or listing is dropped. Prevents false positives from short/generic terms like `SS03`, `AW04`
- `price_ceiling_eur` — hard cap, listings above this are skipped
- `suspicious_threshold` — if price < threshold × rolling_avg, mark suspicious (default 0.25)
- `platforms.eu` / `platforms.asia` — which platforms to search this group on

**Always add `must_contain` to every keyword group** with the brand name in all searched languages. Without it, generic season codes will match tablecloths and unrelated items.

### Deal Score (0–100)
Computed in `dashboard/server.py._deal_score()` and attached to every listing in API responses:
- Price vs rolling avg: up to 60 pts — `(1 - price/avg) × 60`
- Condition: New w/tags=25, Like new=20, Very good=18, Good=15, Fair=8, Poor=3, unknown=10
- Vision score: up to 15 pts — `vision_score/100 × 15`
- Suspicious bonus: +10, capped at 100

### Cost Breakdown
`dashboard/server.py._cost_breakdown()` adds to every listing:
- `shipping_cost` — Japan/Korea €20, China/EU €25
- `vat_amount` — 21% NL VAT on list price
- `total_landed` — price_eur + vat + shipping (the real cost to door)

### Session Persistence
All scrapers save/load Playwright `storage_state` at `sessions/{platform}/state.json`. Reduces bot detection and login friction across restarts.

### Telegram Bot
- Token + chat_id in `config.yaml` under `alerts.telegram`
- Bot username: `@FVARCHIVEMARKET_bot`
- Commands: `/status`, `/pause`, `/resume`, `/bookmarks`
- Snipe alerts: Yahoo auctions ending within 15 min fire a countdown alert automatically

## Database (SQLite)
File: `fashionvoid.db` — WAL mode, migrations run on startup.

Key tables:
- `listings` — every unique listing, primary key `(id, platform)`
- `keywords` — rolling average EUR prices per `(group_name, term, platform)`
- `alerts` — dedup log: `alert_already_sent(id, platform, channel)` prevents duplicate alerts
- `price_history` — one row per scrape for trend tracking

Useful queries:
```sql
-- See what's been found
SELECT platform, COUNT(*) FROM listings GROUP BY platform;
-- Check rolling averages
SELECT * FROM keywords ORDER BY updated_at DESC LIMIT 20;
-- Recent alerts
SELECT * FROM alerts ORDER BY sent_at DESC LIMIT 20;
```

**Clear DB for fresh start** (e.g. testing):
```python
conn.execute('DELETE FROM alerts')
conn.execute('DELETE FROM listings')
```

## Active Platforms
| Platform | Language | Status |
|---|---|---|
| mercari_jp | JP | Active |
| yahoo_auctions | JP | Active + snipe alerts |
| vinted | EU | Active |
| vestiaire | EU | Active |
| bunjang | KR | Active |
| xianyu | CN | Disabled — timeouts, needs login |
| rakuma | JP | Dead — remove from config |

## Config Secrets (never commit config.yaml)
- `alerts.telegram.bot_token` + `chat_id`
- `translation.deepl_api_key`
- `openai.api_key` (vision filter, optional)
- `currency.api_key`
- `alerts.email.*`, `alerts.sms.*`

## Common Issues
| Symptom | Cause | Fix |
|---|---|---|
| Port 8888 in use | Previous run still alive | `lsof -ti :8888 \| xargs kill -9` |
| Xianyu timeouts blocking all scrapers | Needs login/proxy | Remove from config platforms list |
| Unrelated listings (tablecloths etc.) | Missing `must_contain` | Add brand anchors to keyword group |
| No Telegram alerts on restart | All listings already in DB | `DELETE FROM alerts; DELETE FROM listings` |
| `str \| None` TypeError | Python 3.9 incompatibility | Use `Optional[str]` from `typing` |
| `maximum instances reached` warnings | One scraper blocking others | Check which scraper is stuck/timing out |

## Adding a New Scraper
1. Create `scrapers/{platform}.py` inheriting `BaseScraper`
2. Set `PLATFORM`, `CURRENCY`, `BASE_URL`, `NEEDS_TRANSLATION`
3. Implement `async def search(self, keyword, keyword_group) -> list[dict]`
4. Use `self._session_path()` for session persistence
5. Register in `scrapers/__init__.py` `SCRAPER_REGISTRY`
6. Add interval to `config.yaml` under `intervals_seconds`
7. Add to keyword group `platforms.asia` or `platforms.eu`

## Adding a New Keyword Group
```yaml
- group: Brand Name Era
  terms_en: [brand name, specific model]
  terms_jp: [Japanese terms]
  terms_kr: [Korean terms]
  terms_cn: [Chinese terms]
  must_contain: [brand, ブランド, 브랜드, 品牌]  # REQUIRED
  price_ceiling_eur: 1500
  suspicious_threshold: 0.4
  platforms:
    eu: [vinted, vestiaire]
    asia: [mercari_jp, yahoo_auctions, bunjang]
```

## Planned / Pending
- Kream (kream.co.kr) scraper — Korean sneaker/streetwear
- Fruitsfamily (fruitsfamily.com) scraper — Japanese vintage
- Xianyu fix — requires authenticated session or proxy
