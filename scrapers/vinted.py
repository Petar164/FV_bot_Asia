"""
fashionvoid-bot · scrapers/vinted.py
─────────────────────────────────────────────────────────────────────────────
Vinted EU scraper — JSON API, no Playwright needed.

Vinted exposes a public catalog API used by their own web app.
We persist a cookie jar in sessions/vinted/ so the session token survives
process restarts.  No login required for read-only search.

Endpoint:
    GET https://www.vinted.com/api/v2/catalog/items
        ?search_text={keyword}
        &per_page=96
        &order=newest_first

Auth:
    Session cookie obtained by hitting the root page once.
    Cookie jar serialised to sessions/vinted/cookies.json after each request.
─────────────────────────────────────────────────────────────────────────────
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

import httpx

from .base_scraper import BaseScraper

logger = logging.getLogger(__name__)

_SESSION_DIR = Path(__file__).parent.parent / "sessions" / "vinted"
_COOKIE_FILE = _SESSION_DIR / "cookies.json"

_SEARCH_URL = "https://www.vinted.com/api/v2/catalog/items"
_ROOT_URL = "https://www.vinted.com"

# Vinted condition codes → human label
_CONDITION_MAP = {
    "6": "New with tags",
    "1": "Like new",
    "2": "Good",
    "3": "Satisfactory",
}


class VintedScraper(BaseScraper):
    """Vinted EU listing scraper."""

    PLATFORM = "vinted"
    CURRENCY = "EUR"
    BASE_URL = "https://www.vinted.com"
    NEEDS_TRANSLATION = False   # listings already in a Latin-script EU language

    _PAGE_SIZE = 96

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cookies: dict = self._load_cookies()

    # ── Search ────────────────────────────────────────────────────────────

    async def search(self, keyword: str, keyword_group: dict) -> list[dict]:
        await self._ensure_session()

        params = {
            "search_text": keyword,
            "per_page": self._PAGE_SIZE,
            "order": "newest_first",
        }

        headers = self._vinted_headers()
        proxies = None
        if self.proxy:
            proxy_url = self.proxy.get_proxy()
            if proxy_url:
                proxies = {"http://": proxy_url, "https://": proxy_url}

        try:
            async with httpx.AsyncClient(
                headers=headers,
                cookies=self._cookies,
                proxies=proxies,
                timeout=httpx.Timeout(20.0, connect=10.0),
                follow_redirects=True,
                http2=False,   # disable HTTP/2 to avoid compression encoding issues
            ) as client:
                resp = await client.get(_SEARCH_URL, params=params)
                resp.raise_for_status()

                # Persist updated cookies
                self._cookies = dict(resp.cookies)
                self._save_cookies(self._cookies)

                # Use content bytes — json.loads handles encoding detection
                import json as _json
                data = _json.loads(resp.content)

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                # Session expired — clear cookies and retry once
                logger.warning("[vinted] Session expired, refreshing…")
                self._cookies = {}
                _COOKIE_FILE.unlink(missing_ok=True)
                await self._ensure_session()
                return await self.search(keyword, keyword_group)
            logger.error(f"[vinted] HTTP {exc.response.status_code} for '{keyword}'")
            return []
        except Exception as exc:
            logger.error(f"[vinted] Search error for '{keyword}': {exc}")
            return []

        items = data.get("items", [])
        results = []
        sizes = keyword_group.get("size_filter", [])

        for item in items:
            listing = self._parse_item(item, keyword_group, sizes)
            if listing:
                results.append(listing)

        logger.debug(f"[vinted] '{keyword}' → {len(results)} results")
        return results

    # ── Parser ────────────────────────────────────────────────────────────

    def _parse_item(
        self, item: dict, keyword_group: dict, sizes: list[str]
    ) -> Optional[dict]:
        try:
            lid = str(item.get("id", ""))
            if not lid:
                return None

            title = item.get("title", "").strip()
            if not title:
                return None

            # Price — Vinted returns price as a string "25.00"
            price_raw = item.get("price")
            if price_raw is None:
                return None
            try:
                price = float(price_raw)
            except (ValueError, TypeError):
                return None
            if price <= 0:
                return None

            currency = item.get("currency", "EUR").upper()

            # Size filter
            size_title = item.get("size_title", "")
            if sizes and not self.matches_size(f"{title} {size_title}", sizes):
                return None

            # Photo
            photo = item.get("photo") or {}
            image_url = photo.get("url") or photo.get("full_size_url")

            # Condition
            cond_id = str(item.get("status", ""))
            condition = _CONDITION_MAP.get(cond_id, cond_id) or None

            # Brand
            brand = ""
            if isinstance(item.get("brand_title"), str):
                brand = item["brand_title"]

            url = item.get("url") or f"https://www.vinted.com/items/{lid}"
            if not url.startswith("http"):
                url = f"https://www.vinted.com{url}"

            return {
                "id": lid,
                "platform": self.PLATFORM,
                "title": title,
                "translated_title": title,   # no translation for EU
                "price": price,
                "currency": currency,
                "price_eur": price if currency == "EUR" else None,
                "url": url,
                "image_url": image_url,
                "condition": condition,
                "size": size_title,
                "brand": brand,
                "keyword_group": keyword_group.get("group", ""),
                "is_suspicious": False,
            }

        except Exception as exc:
            logger.warning(f"[vinted] Failed to parse item: {exc}")
            return None

    # ── Session management ────────────────────────────────────────────────

    async def _ensure_session(self) -> None:
        """Hit the root page to obtain a valid session cookie if we don't have one."""
        if self._cookies:
            return

        logger.info("[vinted] Obtaining new session cookie…")
        try:
            async with httpx.AsyncClient(
                headers=self._vinted_headers(),
                timeout=15.0,
                follow_redirects=True,
            ) as client:
                resp = await client.get(_ROOT_URL)
                self._cookies = dict(resp.cookies)
                self._save_cookies(self._cookies)
                logger.info(f"[vinted] Session obtained ({len(self._cookies)} cookies)")
        except Exception as exc:
            logger.warning(f"[vinted] Could not obtain session: {exc}")

    def _load_cookies(self) -> dict:
        if _COOKIE_FILE.exists():
            try:
                return json.loads(_COOKIE_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save_cookies(self, cookies: dict) -> None:
        try:
            _SESSION_DIR.mkdir(parents=True, exist_ok=True)
            _COOKIE_FILE.write_text(
                json.dumps(cookies, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            logger.debug(f"[vinted] Could not save cookies: {exc}")

    # ── Headers ───────────────────────────────────────────────────────────

    @staticmethod
    def _vinted_headers() -> dict:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-GB,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://www.vinted.com/",
            "Origin": "https://www.vinted.com",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "DNT": "1",
        }
