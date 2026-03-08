"""
fashionvoid-bot · scrapers/bunjang.py
─────────────────────────────────────────────────────────────────────────────
Bunjang (bunjang.co.kr) scraper — South Korean C2C fashion marketplace.

Bunjang exposes a public REST search API used by their mobile app:
  GET https://api.bunjang.co.kr/api/1/find_it/search.json
  Params: q, n (page size), page, stat (1=on sale), order (pop|recent|price)

Returns JSON.  No auth required for search.
─────────────────────────────────────────────────────────────────────────────
"""

import asyncio
import logging
from typing import Optional

from .base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class BunjangScraper(BaseScraper):
    """Bunjang (bunjang.co.kr) listing scraper."""

    PLATFORM = "bunjang"
    CURRENCY = "KRW"
    BASE_URL = "https://m.bunjang.co.kr"

    _API_ENDPOINT = "https://api.bunjang.co.kr/api/2/find_it/v2/products"
    _ITEM_URL = "https://m.bunjang.co.kr/products/{id}"
    _IMAGE_BASE = "https://media.bunjang.co.kr/images/{path}"

    async def search(self, keyword: str, keyword_group: dict) -> list[dict]:
        """Call the Bunjang search API and return raw listing dicts."""
        results = []
        max_pages = 3
        page_size = 40

        async with self._build_client(extra_headers=self._bunjang_headers()) as client:
            for page in range(max_pages):
                try:
                    params = {
                        "q": keyword,
                        "n": page_size,
                        "page": page,
                        "order": "date",   # newest first
                    }
                    response = await self._get(client, self._API_ENDPOINT, params=params)
                    data = response.json()
                except Exception as exc:
                    logger.error(f"[{self.PLATFORM}] API error (page {page}): {exc}")
                    break

                items = data.get("list", data.get("products", []))
                if not items:
                    break

                for item in items:
                    listing = self._parse_item(item, keyword_group)
                    if listing:
                        results.append(listing)

                if len(items) < page_size:
                    break

                await asyncio.sleep(1.5)

        logger.debug(f"[{self.PLATFORM}] '{keyword}' → {len(results)} raw results")
        return results

    def _parse_item(self, item: dict, keyword_group: dict) -> Optional[dict]:
        """Parse Bunjang API item JSON."""
        try:
            lid = str(item.get("pid", ""))
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

            # ── Only available items (status=1) ───────────────────────
            if str(item.get("status", "1")) != "1":
                return None

            # ── Image URL ─────────────────────────────────────────────
            img_path = item.get("image", "")
            image_url = self._IMAGE_BASE.format(path=img_path) if img_path else None

            # ── Condition ─────────────────────────────────────────────
            condition_map = {
                "0": "New",
                "1": "Like New",
                "2": "Good",
                "3": "Fair",
            }
            condition = condition_map.get(str(item.get("condition", "")))

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
                "condition": condition,
                "keyword_group": keyword_group.get("group", ""),
                "is_suspicious": False,
            }

        except Exception as exc:
            logger.warning(f"[{self.PLATFORM}] Parse error: {exc}")
            return None

    @staticmethod
    def _bunjang_headers() -> dict:
        return {
            "Origin": "https://m.bunjang.co.kr",
            "Referer": "https://m.bunjang.co.kr/",
            "Accept": "application/json",
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
            "App-Version": "240101",
        }
