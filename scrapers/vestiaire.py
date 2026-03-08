"""
fashionvoid-bot · scrapers/vestiaire.py
─────────────────────────────────────────────────────────────────────────────
Vestiaire Collective EU scraper — Playwright headless browser.

The site is heavily JS-rendered; we use Playwright to load the page and
parse the resulting DOM.  Session state (cookies) is persisted in
sessions/vestiaire/ so repeat launches reuse the same browser context.

Search URL:
    https://vestiairecollective.com/search/?q={keyword}&order=new

Extracted fields:
    id, title, price, currency, url, image_url,
    size, brand, condition, authentication_status
─────────────────────────────────────────────────────────────────────────────
"""

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Optional

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    TimeoutError as PlaywrightTimeout,
)

from .base_scraper import BaseScraper

logger = logging.getLogger(__name__)

_SESSION_DIR = Path(__file__).parent.parent / "sessions" / "vestiaire"
_COOKIE_FILE = _SESSION_DIR / "cookies.json"

_SEARCH_URL = "https://vestiairecollective.com/search/?q={keyword}&order=new"


class VestiaireScraper(BaseScraper):
    """Vestiaire Collective EU listing scraper."""

    PLATFORM = "vestiaire"
    CURRENCY = "EUR"
    BASE_URL = "https://vestiairecollective.com"
    NEEDS_TRANSLATION = False   # listings already in EU languages

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None

    # ── Search ────────────────────────────────────────────────────────────

    async def search(self, keyword: str, keyword_group: dict) -> list[dict]:
        url = _SEARCH_URL.format(keyword=keyword)

        try:
            context = await self._get_context()
            page = await context.new_page()

            try:
                await page.goto(url, wait_until="networkidle", timeout=30_000)
            except PlaywrightTimeout:
                logger.warning("[vestiaire] Page load timed out — using partial content")

            # Wait for any product links to appear.
            # Vestiaire product URLs always end in .shtml — use that as the
            # anchor selector since class names change with every deploy.
            try:
                await page.wait_for_selector(
                    "a[href*='.shtml']",
                    timeout=12_000,
                )
            except PlaywrightTimeout:
                logger.warning(f"[vestiaire] No listing cards found for '{keyword}'")
                await page.close()
                return []

            # Save cookies after successful navigation
            cookies = await context.cookies()
            self._save_cookies(cookies)

            # Extract listings via page.evaluate.
            # Strategy: find all <a href="*.shtml"> links, deduplicate by
            # product ID (last digit run before .shtml), then extract
            # surrounding DOM data from the card container.
            raw_items = await page.evaluate("""() => {
                const items = [];
                const seen  = new Set();

                document.querySelectorAll('a[href*=".shtml"]').forEach(link => {
                    const href     = link.getAttribute('href') || '';
                    const idMatch  = href.match(/-(\\d+)\\.shtml/);
                    if (!idMatch || seen.has(idMatch[1])) return;
                    seen.add(idMatch[1]);

                    // Walk up to find the card container (stop at a node
                    // that has at least one <img> inside it)
                    let card = link.parentElement;
                    for (let i = 0; i < 7 && card; i++) {
                        if (card.querySelector('img')) break;
                        card = card.parentElement;
                    }
                    if (!card) card = link;

                    const img = card.querySelector('img');

                    // Price: look for € followed by digits, or digits + €
                    const cardText = card.innerText || '';
                    const priceMatch = cardText.match(/€\\s*([\\d\\s,.]+)|([\\d\\s,.]+)\\s*€/);
                    let price = null;
                    if (priceMatch) {
                        const raw = (priceMatch[1] || priceMatch[2] || '')
                            .replace(/\\s/g, '').replace(',', '.');
                        price = parseFloat(raw) || null;
                    }

                    // Title: prefer a heading or named element; fall back to
                    // URL slug decoded
                    const titleEl = card.querySelector(
                        'h2, h3, h4, p, [class*="name"], [class*="title"], [class*="brand"]'
                    );
                    let title = titleEl ? titleEl.textContent.trim() : '';
                    if (!title) {
                        const slugMatch = href.match(/\\/([^/]+?)-\\d+\\.shtml/);
                        title = slugMatch
                            ? slugMatch[1].replace(/-/g, ' ')
                            : '';
                    }

                    // Authentication badge (any element mentioning authenticity)
                    const authEl = card.querySelector(
                        '[class*="auth"], [class*="verified"], [class*="badge"]'
                    );

                    const fullUrl = href.startsWith('http')
                        ? href
                        : 'https://vestiairecollective.com' + href;

                    items.push({
                        id:                    idMatch[1],
                        title:                 title,
                        price:                 price,
                        url:                   fullUrl,
                        image_url:             img ? (img.src || img.dataset.src) : null,
                        size:                  '',
                        brand:                 '',
                        condition:             null,
                        authentication_status: authEl ? 'verified' : null,
                    });
                });

                return items;
            }""")

            await page.close()

        except Exception as exc:
            logger.error(f"[vestiaire] Search error for '{keyword}': {exc}", exc_info=True)
            return []

        sizes = keyword_group.get("size_filter", [])
        results = []
        for item in raw_items:
            listing = self._parse_item(item, keyword_group, sizes)
            if listing:
                results.append(listing)

        logger.debug(f"[vestiaire] '{keyword}' → {len(results)} results")
        return results

    # ── Parser ────────────────────────────────────────────────────────────

    def _parse_item(
        self, item: dict, keyword_group: dict, sizes: list[str]
    ) -> Optional[dict]:
        try:
            lid = str(item.get("id", "")).strip()
            if not lid:
                return None

            title = item.get("title", "").strip()
            if not title:
                return None

            price = item.get("price")
            if price is None or price <= 0:
                return None

            # Size filter
            size = item.get("size", "")
            if sizes and not self.matches_size(f"{title} {size}", sizes):
                return None

            url = item.get("url", "")
            if not url.startswith("http"):
                url = f"https://vestiairecollective.com{url}"

            return {
                "id": lid,
                "platform": self.PLATFORM,
                "title": title,
                "translated_title": title,   # no translation for EU
                "price": float(price),
                "currency": "EUR",
                "price_eur": float(price),
                "url": url,
                "image_url": item.get("image_url"),
                "condition": item.get("condition"),
                "size": size,
                "brand": item.get("brand", ""),
                "authentication_status": item.get("authentication_status"),
                "keyword_group": keyword_group.get("group", ""),
                "is_suspicious": False,
            }

        except Exception as exc:
            logger.warning(f"[vestiaire] Failed to parse item: {exc}")
            return None

    # ── Browser / context management ──────────────────────────────────────

    async def _get_context(self) -> BrowserContext:
        """Return an existing context or create a new one."""
        if self._context:
            return self._context

        pw = await async_playwright().start()
        self._browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )

        saved_cookies = self._load_cookies()
        self._context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-GB",
            viewport={"width": 1366, "height": 768},
        )

        if saved_cookies:
            try:
                await self._context.add_cookies(saved_cookies)
            except Exception:
                pass   # ignore malformed saved cookies

        return self._context

    def _load_cookies(self) -> list:
        if _COOKIE_FILE.exists():
            try:
                return json.loads(_COOKIE_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return []

    def _save_cookies(self, cookies: list) -> None:
        try:
            _SESSION_DIR.mkdir(parents=True, exist_ok=True)
            _COOKIE_FILE.write_text(
                json.dumps(cookies, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            logger.debug(f"[vestiaire] Could not save cookies: {exc}")
