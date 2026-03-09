"""
fashionvoid-bot · scrapers/vestiaire.py
─────────────────────────────────────────────────────────────────────────────
Vestiaire Collective EU scraper — camoufox stealth browser.

Vestiaire is protected by Cloudflare Bot Management; plain Playwright gets
403.  camoufox (Firefox stealth) passes CF and renders the search page with
full item cards.

Search URL:
    https://www.vestiairecollective.com/search/?q={keyword}&order=new

Items are identified by their .shtml URL pattern and scraped from the DOM.
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import re
import sys
from typing import Optional

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

from .base_scraper import BaseScraper

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://www.vestiairecollective.com/search/?q={keyword}&order=new"

# GDPR/cookie consent selectors
_CONSENT_SELECTORS = [
    "#didomi-notice-agree-button",
    "button[id*='accept']",
    "button[class*='accept']",
    "[id*='onetrust-accept']",
    "[class*='onetrust-accept']",
    "button:has-text('Accept all')",
    "button:has-text('Tout accepter')",
    "button:has-text('I agree')",
]


def _try_load_camoufox():
    try:
        import yaml as _yaml
        if not hasattr(_yaml, "CLoader") or _yaml.CLoader is None:
            _yaml.CLoader = _yaml.Loader
            sys.modules["yaml"] = _yaml
        from camoufox.async_api import AsyncCamoufox  # noqa: F401
        return AsyncCamoufox
    except Exception as exc:
        logger.debug(f"[vestiaire] camoufox not available: {exc}")
        return None


class VestiaireScraper(BaseScraper):
    """Vestiaire Collective EU listing scraper via camoufox."""

    PLATFORM = "vestiaire"
    CURRENCY = "EUR"
    BASE_URL = "https://www.vestiairecollective.com"
    NEEDS_TRANSLATION = False

    # ── Search ────────────────────────────────────────────────────────────

    async def search(self, keyword: str, keyword_group: dict) -> list[dict]:
        AsyncCamoufox = _try_load_camoufox()
        url = _SEARCH_URL.format(keyword=keyword)
        raw_items = []

        if AsyncCamoufox:
            raw_items = await self._search_camoufox(url, keyword, AsyncCamoufox)
        else:
            raw_items = await self._search_playwright(url, keyword)

        sizes = keyword_group.get("size_filter", [])
        results = []
        for item in raw_items:
            listing = self._parse_item(item, keyword_group, sizes)
            if listing:
                results.append(listing)

        logger.debug(f"[{self.PLATFORM}] '{keyword}' → {len(results)} results")
        return results

    # ── camoufox path ─────────────────────────────────────────────────────

    async def _search_camoufox(self, url: str, keyword: str, AsyncCamoufox) -> list[dict]:
        try:
            async with AsyncCamoufox(headless=True) as browser:
                page = await browser.new_page()

                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                except PlaywrightTimeout:
                    logger.warning(f"[{self.PLATFORM}] Navigation timeout for '{keyword}' — continuing")

                # Dismiss GDPR consent
                await self._dismiss_consent(page)

                # Wait for item cards
                try:
                    await page.wait_for_selector("a[href*='.shtml']", timeout=12_000)
                except PlaywrightTimeout:
                    logger.warning(f"[{self.PLATFORM}] No .shtml cards appeared for '{keyword}'")

                return await self._extract_items(page)

        except Exception as exc:
            logger.error(f"[{self.PLATFORM}] camoufox error: {exc}", exc_info=True)
            return []

    # ── Plain Playwright fallback ─────────────────────────────────────────

    async def _search_playwright(self, url: str, keyword: str) -> list[dict]:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = await browser.new_context(
                user_agent=self._random_ua(),
                locale="en-GB",
                viewport={"width": 1366, "height": 768},
            )
            page = await context.new_page()

            try:
                await page.goto(url, wait_until="networkidle", timeout=30_000)
            except PlaywrightTimeout:
                logger.warning(f"[{self.PLATFORM}] Timeout for '{keyword}'")

            try:
                await page.wait_for_selector("a[href*='.shtml']", timeout=10_000)
            except PlaywrightTimeout:
                pass

            items = await self._extract_items(page)
            await browser.close()
            return items

    # ── Consent dismissal ─────────────────────────────────────────────────

    async def _dismiss_consent(self, page) -> None:
        for sel in _CONSENT_SELECTORS:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=300):
                    await btn.click(timeout=1_000)
                    logger.debug(f"[{self.PLATFORM}] Clicked consent: {sel}")
                    await page.wait_for_timeout(800)
                    return
            except Exception:
                continue

    # ── DOM extraction ────────────────────────────────────────────────────

    async def _extract_items(self, page) -> list[dict]:
        try:
            return await page.evaluate(r"""() => {
                const items = [];
                const seen  = new Set();

                document.querySelectorAll('a[href*=".shtml"]').forEach(link => {
                    const href     = link.getAttribute('href') || '';
                    const idMatch  = href.match(/-(\d+)\.shtml/);
                    if (!idMatch || seen.has(idMatch[1])) return;
                    seen.add(idMatch[1]);

                    // Walk up to find the card container (has an <img> inside)
                    let card = link.parentElement;
                    for (let i = 0; i < 7 && card; i++) {
                        if (card.querySelector('img')) break;
                        card = card.parentElement;
                    }
                    if (!card) card = link;

                    const img = card.querySelector('img');

                    // Price: look for € followed by digits
                    const cardText = card.innerText || '';
                    const priceMatch = cardText.match(/€\s*([\d\s,.]+)|([\d\s,.]+)\s*€/);
                    let price = null;
                    if (priceMatch) {
                        const raw = (priceMatch[1] || priceMatch[2] || '')
                            .replace(/\s/g, '').replace(',', '.');
                        price = parseFloat(raw) || null;
                    }

                    // Title: prefer heading elements, fall back to URL slug
                    const titleEl = card.querySelector(
                        'h2, h3, h4, p[class*="name"], p[class*="title"], [class*="name"], [class*="title"]'
                    );
                    let title = titleEl ? titleEl.textContent.trim() : '';
                    if (!title) {
                        const slugMatch = href.match(/\/([^/]+?)-\d+\.shtml/);
                        title = slugMatch ? slugMatch[1].replace(/-/g, ' ') : '';
                    }

                    const fullUrl = href.startsWith('http')
                        ? href
                        : 'https://www.vestiairecollective.com' + href;

                    const authEl = card.querySelector('[class*="auth"], [class*="verified"], [class*="badge"]');

                    items.push({
                        id:                    idMatch[1],
                        title:                 title,
                        price:                 price,
                        url:                   fullUrl,
                        image_url:             img ? (img.src || img.dataset.src || null) : null,
                        size:                  '',
                        brand:                 '',
                        condition:             null,
                        authentication_status: authEl ? 'verified' : null,
                    });
                });

                return items;
            }""")
        except Exception as exc:
            logger.error(f"[{self.PLATFORM}] DOM extraction error: {exc}")
            return []

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

            size = item.get("size", "")
            if sizes and not self.matches_size(f"{title} {size}", sizes):
                return None

            url = item.get("url", "")
            if not url.startswith("http"):
                url = f"https://www.vestiairecollective.com{url}"

            return {
                "id": lid,
                "platform": self.PLATFORM,
                "title": title,
                "translated_title": title,
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
            logger.warning(f"[{self.PLATFORM}] Failed to parse item: {exc}")
            return None
