"""
fashionvoid-bot · scrapers/rakuma.py
─────────────────────────────────────────────────────────────────────────────
Rakuma (fril.jp) was fully merged into Mercari Japan in 2024.
The fril.jp search API is no longer available — all former Rakuma inventory
migrated to jp.mercari.com.

This scraper is kept as a stub so existing configs referencing "rakuma"
don't crash.  It returns no results and logs a one-time deprecation notice.
Remove "rakuma" from your platforms list — Mercari JP now covers the full
combined inventory.
─────────────────────────────────────────────────────────────────────────────
"""

import logging
from .base_scraper import BaseScraper

logger = logging.getLogger(__name__)
_WARNED = False


class RakumaScraper(BaseScraper):
    """Rakuma stub — platform merged into Mercari JP."""

    PLATFORM = "rakuma"
    CURRENCY = "JPY"
    BASE_URL  = "https://jp.mercari.com"

    async def search(self, keyword: str, keyword_group: dict) -> list[dict]:
        global _WARNED
        if not _WARNED:
            logger.warning(
                "[rakuma] Platform merged into Mercari JP in 2024 — "
                "fril.jp API is gone. Remove 'rakuma' from your platforms "
                "list and use 'mercari_jp' instead."
            )
            _WARNED = True
        return []
