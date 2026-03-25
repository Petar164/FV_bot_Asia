"""
fashionvoid-bot · scrapers/mercari_jp.py
─────────────────────────────────────────────────────────────────────────────
Mercari Japan scraper — Playwright + network response interception.

Mercari's search page (jp.mercari.com/search) is fully client-side rendered;
httpx sees no items in the HTML.  Their JSON API (api.mercari.jp/v2/entities:search)
now requires DPoP proof-of-possession tokens that only the browser JS can
generate.

Strategy: launch Playwright, navigate to the search page, and intercept
the browser's own request to the search API.  The browser handles DPoP
auth automatically, so we receive the full JSON payload without needing
to replicate the token flow ourselves.
─────────────────────────────────────────────────────────────────────────────
"""

import asyncio
import logging
from typing import Optional
from urllib.parse import quote_plus

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

from .base_scraper import BaseScraper

logger = logging.getLogger(__name__)

_SEARCH_URL = (
    "https://jp.mercari.com/search"
    "?keyword={keyword}&sort=created_time&order=desc&status=on_sale"
)
_API_PATTERN = "entities:search"   # substring present in Mercari's search API URL


class MercariJPScraper(BaseScraper):
    """Mercari Japan (jp.mercari.com) listing scraper via Playwright + API intercept."""

    PLATFORM = "mercari_jp"
    CURRENCY = "JPY"
    BASE_URL = "https://jp.mercari.com"

    _CONDITION_MAP = {
        "1": "New / Unworn",
        "2": "Like New",
        "3": "Good",
        "4": "Fair",
        "5": "Poor",
        "6": "For Parts",
    }

    # ── Search ────────────────────────────────────────────────────────────

    async def search(self, keyword: str, keyword_group: dict) -> list[dict]:
        url = _SEARCH_URL.format(keyword=quote_plus(keyword))
        captured: list[dict] = []

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage",
                      "--disable-blink-features=AutomationControlled"],
            )
            _sp = self._session_path()
            context = await browser.new_context(
                user_agent=self._random_ua(),
                locale="ja-JP",
                viewport={"width": 1280, "height": 900},
                storage_state=str(_sp) if _sp.exists() else None,
            )
            page = await context.new_page()
            await page.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
            )

            # Intercept the search API response the browser makes
            async def on_response(response):
                if _API_PATTERN not in response.url:
                    return
                if response.status != 200:
                    return
                try:
                    data = await response.json()
                    items = data.get("items", [])
                    if items:
                        captured.extend(items)
                except Exception:
                    pass

            page.on("response", on_response)

            try:
                await page.goto(url, wait_until="networkidle", timeout=35_000)
            except PlaywrightTimeout:
                logger.warning(f"[{self.PLATFORM}] Page load timed out for '{keyword}' — using partial results")
            except Exception as exc:
                logger.error(f"[{self.PLATFORM}] Error for '{keyword}': {exc}", exc_info=True)
            finally:
                try:
                    await context.storage_state(path=str(_sp))
                except Exception:
                    pass
                await browser.close()

        if not captured:
            logger.debug(f"[{self.PLATFORM}] No API response captured for '{keyword}'")

        results = []
        for raw in captured:
            listing = self._parse_item(raw, keyword_group)
            if listing:
                results.append(listing)

        logger.debug(f"[{self.PLATFORM}] '{keyword}' → {len(results)} raw results")
        return results

    # ── Item parser ───────────────────────────────────────────────────────

    def _parse_item(self, item: dict, keyword_group: dict) -> Optional[dict]:
        try:
            lid = item.get("id", "")
            if not lid:
                return None

            status = item.get("status", "")
            if status and "on_sale" not in status.lower() and "ITEM_STATUS_ON_SALE" not in status:
                return None

            title = item.get("name", "").strip()
            if not title:
                return None

            price = float(item.get("price", 0))
            if price <= 0:
                return None

            sizes = keyword_group.get("size_filter", [])
            if sizes and not self.matches_size(title, sizes):
                return None

            thumbnails = item.get("thumbnails") or []
            image_url = thumbnails[0] if thumbnails else item.get("imageUrl")

            condition_id = str(item.get("itemConditionId", "") or "")
            condition = self._CONDITION_MAP.get(condition_id, condition_id or None)

            return {
                "id": lid,
                "platform": self.PLATFORM,
                "title": title,
                "translated_title": None,
                "price": price,
                "currency": self.CURRENCY,
                "price_eur": None,
                "url": f"https://jp.mercari.com/item/{lid}",
                "image_url": image_url,
                "condition": condition,
                "keyword_group": keyword_group.get("group", ""),
                "is_suspicious": False,
            }

        except Exception as exc:
            logger.warning(f"[{self.PLATFORM}] Parse error: {exc}")
            return None
