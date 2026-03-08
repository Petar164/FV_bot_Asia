"""
fashionvoid-bot · scrapers/rakuma.py
─────────────────────────────────────────────────────────────────────────────
Rakuma (fril.jp) scraper.

Rakuma's search is SPA-rendered but their API can be called directly:
  GET https://fril.jp/api/search/item
  Params: query, page, sort (score | created_at | price_asc | price_desc)

Returns JSON.  No auth required for anonymous search.
─────────────────────────────────────────────────────────────────────────────
"""

import asyncio
import logging
import re
from typing import Optional
from urllib.parse import quote

from .base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class RakumaScraper(BaseScraper):
    """Rakuma (fril.jp) listing scraper."""

    PLATFORM = "rakuma"
    CURRENCY = "JPY"
    BASE_URL = "https://fril.jp"

    _API_ENDPOINT = "https://fril.jp/api/search/item"
    _ITEM_URL = "https://fril.jp/item/{id}"

    async def search(self, keyword: str, keyword_group: dict) -> list[dict]:
        """Call the Rakuma search API and return raw listing dicts."""
        results = []
        max_pages = 3

        async with self._build_client(extra_headers=self._rakuma_headers()) as client:
            for page in range(1, max_pages + 1):
                try:
                    params = {
                        "query": keyword,
                        "page": page,
                        "sort": "created_at",
                        "order": "desc",
                        "status": "selling",
                    }
                    response = await self._get(client, self._API_ENDPOINT, params=params)
                    data = response.json()
                except Exception as exc:
                    logger.error(f"[{self.PLATFORM}] API error (page {page}): {exc}")
                    break

                items = data.get("items", [])
                if not items:
                    break

                for item in items:
                    listing = self._parse_item(item, keyword_group)
                    if listing:
                        results.append(listing)

                # Stop if we got fewer than a full page
                if len(items) < 20:
                    break

                await asyncio.sleep(1.2)

        logger.debug(f"[{self.PLATFORM}] '{keyword}' → {len(results)} raw results")
        return results

    def _parse_item(self, item: dict, keyword_group: dict) -> Optional[dict]:
        """Parse Rakuma API item JSON into our standard listing dict."""
        try:
            lid = str(item.get("id", ""))
            if not lid:
                return None

            title = item.get("name", "").strip()
            if not title:
                return None

            price = float(item.get("price", 0))
            if price <= 0:
                return None

            # ── Size filter ───────────────────────────────────────────
            sizes = keyword_group.get("size_filter", [])
            if sizes and not self.matches_size(title, sizes):
                return None

            # ── Status — only on sale ─────────────────────────────────
            if item.get("status") not in ("selling", None, ""):
                return None

            thumbnails = item.get("thumbnails") or []
            image_url = thumbnails[0].get("image_url") if thumbnails else None

            condition = item.get("condition", {})
            cond_name = condition.get("name") if isinstance(condition, dict) else str(condition)

            return {
                "id": lid,
                "platform": self.PLATFORM,
                "title": title,
                "translated_title": None,
                "price": price,
                "currency": self.CURRENCY,
                "price_eur": None,
                "url": self._ITEM_URL.format(id=lid),
                "image_url": image_url,
                "condition": cond_name,
                "keyword_group": keyword_group.get("group", ""),
                "is_suspicious": False,
            }

        except Exception as exc:
            logger.warning(f"[{self.PLATFORM}] Parse error: {exc}")
            return None

    @staticmethod
    def _rakuma_headers() -> dict:
        return {
            "Origin": "https://fril.jp",
            "Referer": "https://fril.jp/",
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
        }
