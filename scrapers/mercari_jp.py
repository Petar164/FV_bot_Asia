"""
fashionvoid-bot · scrapers/mercari_jp.py
─────────────────────────────────────────────────────────────────────────────
Mercari Japan scraper — the fully-implemented reference scraper.

Mercari exposes a public GraphQL / JSON API used by their own SPA.
We hit the search endpoint directly — no Playwright required for basic search.

Endpoint: https://api.mercari.jp/v2/entities:search
Method   : POST (JSON body)
Auth     : None for anonymous search (rate-limited by IP)

Strategy
────────
1. POST keyword to the search API, parse response JSON
2. Filter by size keywords appearing in title / description
3. Filter by price ceiling (EUR converted)
4. Return listing dicts for base class post-processing
─────────────────────────────────────────────────────────────────────────────
"""

import asyncio
import logging
import re
from typing import Optional
from uuid import uuid4

from .base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class MercariJPScraper(BaseScraper):
    """Mercari Japan (mercari.com/jp) listing scraper."""

    PLATFORM = "mercari_jp"
    CURRENCY = "JPY"
    BASE_URL = "https://api.mercari.jp"

    # ── Mercari search API ────────────────────────────────────────────────

    _SEARCH_ENDPOINT = "https://api.mercari.jp/v2/entities:search"

    # Item status: on_sale | trading | sold_out
    _STATUS_ON_SALE = "ITEM_STATUS_ON_SALE"

    # Mercari condition codes (we store these as-is for the alert)
    _CONDITION_MAP = {
        "1": "New / Unworn",
        "2": "Like New",
        "3": "Good",
        "4": "Fair",
        "5": "Poor",
        "6": "For Parts",
    }

    # Max results to request per search call (Mercari allows up to 120)
    _PAGE_SIZE = 60

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Per-session token Mercari injects — generated client-side
        self._dpop_uuid = str(uuid4())

    # ── Search implementation ─────────────────────────────────────────────

    async def search(self, keyword: str, keyword_group: dict) -> list[dict]:
        """
        Search Mercari JP for *keyword* and return raw listing dicts.
        Handles pagination automatically (up to 3 pages to stay polite).
        """
        results = []
        page_token = None
        max_pages = 3

        async with self._build_client(extra_headers=self._mercari_headers()) as client:
            for page in range(max_pages):
                try:
                    payload = self._build_payload(keyword, page_token)
                    response = await client.post(
                        self._SEARCH_ENDPOINT,
                        json=payload,
                    )
                    response.raise_for_status()
                    data = response.json()
                except Exception as exc:
                    logger.error(f"[{self.PLATFORM}] Search error (page {page}): {exc}")
                    break

                items = data.get("items", [])
                if not items:
                    break

                for item in items:
                    listing = self._parse_item(item, keyword_group)
                    if listing:
                        results.append(listing)

                # Pagination
                page_token = data.get("meta", {}).get("nextPageToken")
                if not page_token:
                    break

                # Polite pause between pages
                await asyncio.sleep(1.5)

        logger.debug(f"[{self.PLATFORM}] '{keyword}' → {len(results)} raw results")
        return results

    # ── Payload builder ───────────────────────────────────────────────────

    def _build_payload(self, keyword: str, page_token: Optional[str] = None) -> dict:
        """Construct the JSON payload for the Mercari search API."""
        payload = {
            "userId": "",
            "pageSize": self._PAGE_SIZE,
            "pageToken": page_token or "",
            "searchSessionId": self._dpop_uuid,
            "indexRouting": "INDEX_ROUTING_UNSPECIFIED",
            "thumbnailTypes": [],
            "searchCondition": {
                "keyword": keyword,
                "excludeKeyword": "",
                "sort": "SORT_CREATED_TIME",
                "order": "ORDER_DESC",
                "status": ["ITEM_STATUS_ON_SALE"],
                "sizeId": [],
                "categoryId": [],
                "brandId": [],
                "sellerId": [],
                "priceMin": 0,
                "priceMax": 0,           # 0 = no ceiling (we filter in EUR)
                "itemTypes": [],
                "skuIds": [],
                "colors": [],
            },
            "defaultDatasets": ["DATASET_TYPE_MERCARI", "DATASET_TYPE_BEYOND"],
        }
        return payload

    # ── Item parser ───────────────────────────────────────────────────────

    def _parse_item(self, item: dict, keyword_group: dict) -> Optional[dict]:
        """
        Parse a single Mercari API item dict into our standard listing shape.
        Returns None if the item should be skipped.
        """
        try:
            # Only on-sale items
            if item.get("status") != self._STATUS_ON_SALE:
                return None

            lid = item.get("id", "")
            if not lid:
                return None

            title = item.get("name", "").strip()
            price = float(item.get("price", 0))
            if price <= 0:
                return None

            # ── Size filter ───────────────────────────────────────────
            sizes = keyword_group.get("size_filter", [])
            if sizes and not self.matches_size(title, sizes):
                return None

            # ── Build listing dict ────────────────────────────────────
            seller = item.get("seller") or {}
            thumbnails = item.get("thumbnails") or []
            image_url = thumbnails[0] if thumbnails else item.get("imageUrl")

            condition_id = str(item.get("itemConditionId", ""))
            condition = self._CONDITION_MAP.get(condition_id, condition_id)

            return {
                "id": lid,
                "platform": self.PLATFORM,
                "title": title,
                "translated_title": None,    # filled by base.process_listings()
                "price": price,
                "currency": self.CURRENCY,
                "price_eur": None,           # filled by base.process_listings()
                "url": f"https://jp.mercari.com/item/{lid}",
                "image_url": image_url,
                "condition": condition,
                "keyword_group": keyword_group.get("group", ""),
                "is_suspicious": False,      # filled by base.process_listings()
            }

        except Exception as exc:
            logger.warning(f"[{self.PLATFORM}] Failed to parse item: {exc}")
            return None

    # ── Mercari-specific headers ───────────────────────────────────────────

    @staticmethod
    def _mercari_headers() -> dict:
        """
        Mercari's API requires a few specific headers.
        DPoP (Demonstrating Proof of Possession) is needed for their auth
        layer but anonymous search works with a plausible client hint set.
        """
        return {
            "Authorization": "Bearer anonymous",
            "Origin": "https://jp.mercari.com",
            "Referer": "https://jp.mercari.com/",
            "X-Platform": "web",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json; charset=UTF-8",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
        }
