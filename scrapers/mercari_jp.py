"""
fashionvoid-bot · scrapers/mercari_jp.py
─────────────────────────────────────────────────────────────────────────────
Mercari Japan scraper — web page extraction via httpx.

Mercari's JSON API (api.mercari.jp/v2/entities:search) now enforces DPoP
auth tokens that require a real browser session to generate.

Instead we GET their Next.js SSR search page and extract the embedded
__NEXT_DATA__ JSON, which contains the first page of results server-side.

URL:
    GET https://jp.mercari.com/search
        ?keyword={keyword}
        &sort=created_time
        &order=desc
        &status=on_sale

The JSON path to items inside __NEXT_DATA__ varies by Mercari's deploy.
We try several known paths before giving up.
─────────────────────────────────────────────────────────────────────────────
"""

import json as _json
import logging
import re
from typing import Optional
from urllib.parse import quote_plus

import httpx

from .base_scraper import BaseScraper

logger = logging.getLogger(__name__)

_SEARCH_URL = (
    "https://jp.mercari.com/search"
    "?keyword={keyword}&sort=created_time&order=desc&status=on_sale"
)


class MercariJPScraper(BaseScraper):
    """Mercari Japan (jp.mercari.com) listing scraper via SSR page."""

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
        headers = self._mercari_headers()

        try:
            async with httpx.AsyncClient(
                headers=headers,
                timeout=httpx.Timeout(25.0, connect=10.0),
                follow_redirects=True,
                http2=False,
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                html = resp.text
        except Exception as exc:
            logger.error(f"[{self.PLATFORM}] HTTP error for '{keyword}': {exc}")
            return []

        items = self._extract_items(html)
        if items is None:
            logger.warning(
                f"[{self.PLATFORM}] __NEXT_DATA__ not found or empty for '{keyword}'"
            )
            return []

        results = []
        for raw in items:
            listing = self._parse_item(raw, keyword_group)
            if listing:
                results.append(listing)

        logger.debug(f"[{self.PLATFORM}] '{keyword}' → {len(results)} raw results")
        return results

    # ── __NEXT_DATA__ extractor ───────────────────────────────────────────

    @staticmethod
    def _extract_items(html: str) -> Optional[list]:
        """
        Pull the __NEXT_DATA__ JSON block from the HTML and return the list
        of items.  Tries several known paths in Mercari's page structure.
        """
        match = re.search(
            r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>\s*(\{.*?\})\s*</script>',
            html,
            re.DOTALL,
        )
        if not match:
            return None

        try:
            data = _json.loads(match.group(1))
        except _json.JSONDecodeError:
            return None

        pp = data.get("props", {}).get("pageProps", {})

        # Try several known paths in Mercari's SSR payload
        for path in [
            ["searchResult", "items"],
            ["items"],
            ["initialData", "result", "items"],
            ["data", "result", "items"],
        ]:
            node = pp
            for key in path:
                if isinstance(node, dict):
                    node = node.get(key)
                else:
                    node = None
                    break
            if isinstance(node, list) and node:
                return node

        return []

    # ── Item parser ───────────────────────────────────────────────────────

    def _parse_item(self, item: dict, keyword_group: dict) -> Optional[dict]:
        try:
            lid = item.get("id", "")
            if not lid:
                return None

            # Mercari uses different status strings depending on endpoint
            status = item.get("status", "")
            if status and "on_sale" not in status.lower() and "ITEM_STATUS_ON_SALE" not in status:
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

            thumbnails = item.get("thumbnails") or []
            image_url = thumbnails[0] if thumbnails else item.get("imageUrl") or item.get("image_url")

            condition_id = str(item.get("itemConditionId", "") or item.get("item_condition_id", ""))
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

    # ── Headers ───────────────────────────────────────────────────────────

    @staticmethod
    def _mercari_headers() -> dict:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Referer": "https://jp.mercari.com/",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
        }
