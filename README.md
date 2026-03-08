# FashionVoid Asia Monitor

> Automated archive fashion sourcing across Japanese, Korean, and Chinese resale platforms.
> Targets rare pieces — instant alerts the moment something underpriced surfaces.

Built for hunting **Dior Homme (Hedi era)**, **Saint Laurent Paris (Hedi era)**, and other archive fashion across Asia's biggest resale markets.

---

## What it does

The bot continuously scrapes five Asian resale platforms, translates listings to English, converts prices to EUR in real-time, detects suspiciously low prices (possible fakes or underpriced gems), and fires instant alerts across multiple channels.

A live **web dashboard** gives you a real-time overview: an interactive 3D globe showing active markets, listing counts per country, and a full searchable listing grid.

---

## Platforms monitored

| Platform | Region | Method |
|---|---|---|
| Mercari JP | 🇯🇵 Japan | JSON API |
| Yahoo Auctions | 🇯🇵 Japan | Playwright (headless browser) |
| Rakuma (Fril) | 🇯🇵 Japan | JSON API |
| Bunjang | 🇰🇷 South Korea | JSON API |
| Xianyu (闲鱼) | 🇨🇳 China | Playwright + XHR intercept |

---

## Alert channels

| Channel | Provider | Notes |
|---|---|---|
| **Email** | SMTP / Gmail | Rich HTML with inline listing image |
| **SMS** | Twilio | Instant text alert with price + link |
| **WhatsApp** | Twilio | Same config as SMS |
| **Push** | ntfy.sh | Free desktop + mobile push, no account required |

---

## Live Dashboard

The dashboard (`localhost:8000`) features:

- **3D interactive globe** — dot-matrix Earth rendered in pure Three.js with a hemisphere-fade shader, GlitchShader post-processing (RGB split, scan-line flicker), and floating pin cards for each monitored country
- **Live city clocks** — real-time local time for Tokyo, Seoul, and Beijing displayed in both the header strip and each pin card
- **Listing grid** — searchable, filterable table of all scraped listings with thumbnail, translated title, EUR price, platform, and suspicious-price flag
- **Auto-refresh** — dashboard updates live as the bot scrapes

---

## Prerequisites

- Python 3.11+
- pip

---

## Installation

```bash
# 1. Clone the repo
git clone https://github.com/Petar164/FV_bot_Asia.git
cd FV_bot_Asia

# 2. Create a virtual environment
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Install Playwright browser (needed for Yahoo Auctions & Xianyu)
playwright install chromium
```

---

## Configuration

Copy `config.yaml.example` to `config.yaml` and fill in your credentials. Every field is documented inline.

### Minimum viable config (push alerts only — no API keys needed)

```yaml
alerts:
  push:
    enabled: true
    ntfy_topic: "fashionvoid-alerts"   # subscribe to this in the ntfy app
```

Install the [ntfy app](https://ntfy.sh) on your phone and subscribe to the topic. That's it.

---

## API Keys & Services

### Google Cloud Translate (optional)

Translates Japanese/Korean/Chinese listing titles to English.

1. [console.cloud.google.com](https://console.cloud.google.com) → New project → Enable **Cloud Translation API**
2. Credentials → Create API Key → restrict to Translation API
3. Paste into `config.yaml → translate.api_key`

> Cost: ~$20/million characters. At 1000 listings/day (~50 chars each) = ~$1/day. Well within Google's $300 free trial credit.

### Twilio — SMS & WhatsApp

1. Sign up at [twilio.com](https://twilio.com) (free trial includes credit)
2. Copy **Account SID** and **Auth Token** from your console
3. For WhatsApp: join the sandbox — send `join <word>` to `+1 415 523 8886`
4. Fill in `config.yaml → alerts.sms.*`

### Gmail App Password — email alerts

1. Enable 2FA on your Google account
2. myaccount.google.com → Security → **App passwords** → Mail
3. Paste the 16-character password into `config.yaml → alerts.email.password`

### Currency conversion

The free tier of [exchangerate-api.com](https://www.exchangerate-api.com) works out of the box (1500 req/month, no key). For unlimited requests, register and paste your key into `config.yaml → currency.api_key`.

### Proxies (optional but recommended for Xianyu)

Recommended providers:
- [Webshare](https://webshare.io) — free tier (10 proxies)
- [Oxylabs](https://oxylabs.io) — residential, best for Xianyu
- [Brightdata](https://brightdata.com) — rotating super-proxy

Set `proxies.enabled: true` and add your rotation URL.

---

## Running

```bash
# Start bot + live dashboard
python main.py

# Run all scrapers once (for testing)
python main.py --once

# Run only one platform
python main.py --platform mercari_jp

# Custom config path
python main.py --config /path/to/config.yaml
```

Dashboard runs at **http://localhost:8000**

### Windows — activate venv first

```powershell
.venv\Scripts\Activate.ps1
python main.py
```

### Linux / macOS — background service

```bash
# Using screen
screen -S fashionvoid
python main.py
# Ctrl+A, D to detach

# Or systemd — create /etc/systemd/system/fashionvoid.service:
[Unit]
Description=FashionVoid Asia Monitor
After=network.target

[Service]
WorkingDirectory=/path/to/FV_bot_Asia
ExecStart=/path/to/.venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

---

## Project structure

```
FV_bot_Asia/
├── config.yaml              — all settings (not committed — contains secrets)
├── requirements.txt
├── main.py                  — entry point, scheduler, live dashboard
│
├── db/
│   └── database.py          — SQLite schema + query helpers
│
├── scrapers/
│   ├── base_scraper.py      — abstract base (translation, FX, dedup, suspicious-price)
│   ├── mercari_jp.py        — Mercari Japan (JSON API)
│   ├── yahoo_auctions.py    — Yahoo Auctions Japan (Playwright)
│   ├── rakuma.py            — Rakuma / Fril (JSON API)
│   ├── bunjang.py           — Bunjang Korea (JSON API)
│   └── xianyu.py            — Xianyu China (Playwright + XHR intercept)
│
├── notifications/
│   ├── email_alert.py       — SMTP HTML email
│   ├── sms_alert.py         — Twilio SMS + WhatsApp
│   └── push_alert.py        — ntfy.sh push notification
│
├── utils/
│   ├── translator.py        — Google Translate v2 wrapper
│   ├── currency.py          — live JPY / KRW / CNY → EUR conversion
│   └── proxy_manager.py     — rotating proxy pool
│
└── dashboard/
    ├── server.py             — FastAPI server + REST endpoints
    └── templates/
        └── index.html        — full SPA dashboard (Three.js globe, listing grid)
```

---

## How dedup & suspicious-price detection works

1. Every scraped listing ID is stored in SQLite — already-seen listings are skipped (no duplicate alerts)
2. For each keyword group the bot maintains an **exponential moving average** of EUR prices (α = 0.1)
3. If a new listing's price is below `suspicious_threshold × rolling average` (default 25%), it's flagged `is_suspicious = True` and the alert prominently warns you
4. The `price_ceiling_eur` hard-cap filters out anything over budget before any alert fires

---

## Keyword configuration

```yaml
keywords:
  - group: "Dior Homme Hedi"
    terms:
      - "dior homme"
      - "ディオールオム"      # Japanese
      - "디올 옴므"            # Korean
      - "迪奥男装"             # Chinese
    size_filter: ["46", "48", "S"]   # empty list = no size filter
    price_ceiling_eur: 500
    suspicious_threshold: 0.25       # flag if < 25% of rolling avg
    platforms: ["mercari_jp", "yahoo_auctions", "rakuma", "bunjang", "xianyu"]
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'uvicorn'` | Activate the venv first: `.venv\Scripts\activate` (Windows) or `source .venv/bin/activate` |
| `playwright install` fails | Run `pip install playwright` then retry |
| Xianyu shows empty results | Site may require login — try injecting cookies via Playwright context |
| Yahoo Auctions timeout | Increase timeout in `yahoo_auctions.py` → `goto(..., timeout=50000)` |
| Email not sending | Use an **App Password**, not your Gmail password |
| Twilio error 21211 | Phone number must include country code: `+44...` |
| Currency shows fallback rates | Check internet connection — rates auto-refresh hourly |

---

## Roadmap

- [ ] Telegram bot integration
- [ ] Discord webhook support
- [ ] Login sessions for Xianyu (significantly expands results)
- [ ] Image similarity detection (flag re-listed or fake items)
- [ ] Seller reputation scoring
- [ ] Price history charts in dashboard
- [ ] Mobile-responsive dashboard layout

---

*Built for FashionVoid. All scraping is rate-limited and respectful of platform terms of service.*
