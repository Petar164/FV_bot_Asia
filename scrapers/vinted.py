"""
fashionvoid-bot · scrapers/vinted.py
─────────────────────────────────────────────────────────────────────────────
Vinted EU scraper — camoufox browser + multi-strategy extraction.

Cloudflare Bot Management blocks plain Playwright/httpx on vinted.com.
Strategy stack (tried in order):

  1. camoufox on vinted.fr (Firefox stealth, passes CF BM)
       a. Intercept /api/v2/catalog/items network response
       b. Extract __NEXT_DATA__ SSR JSON embedded in page HTML
       c. DOM scrape rendered item cards

  2. Plain Playwright Chromium fallback (works occasionally from clean IPs)
─────────────────────────────────────────────────────────────────────────────
"""

import json
import logging
import sys
from typing import Optional
from urllib.parse import quote_plus

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

from .base_scraper import BaseScraper

logger = logging.getLogger(__name__)

# vinted.fr search URL — French locale passes CF more reliably than .com
_SEARCH_URL = (
    "https://www.vinted.fr/catalog"
    "?search_text={keyword}&order=newest_first&per_page=96"
)
_API_PATTERN = "/api/v2/catalog/items"

# Selectors for cookie/GDPR consent modal — multiple providers used on Vinted
_CONSENT_SELECTORS = [
    "button[id*='accept']",
    "button[class*='accept']",
    "button[data-testid*='accept']",
    "[id*='onetrust-accept']",
    "[class*='onetrust-accept']",
    "#didomi-notice-agree-button",
    "button[title*='Accept']",
    "button[aria-label*='Accept']",
    "button[aria-label*='Accepter']",
    "button:has-text('Accept all')",
    "button:has-text('Accepter tout')",
    "button:has-text('Tout accepter')",
    "button:has-text('I agree')",
    "button:has-text('OK')",
]

# Vinted condition codes → human label
_CONDITION_MAP = {
    "6": "New with tags",
    "1": "Like new",
    "2": "Good",
    "3": "Satisfactory",
}


def _try_load_camoufox():
    """Import camoufox, applying PyYAML CLoader polyfill if needed."""
    try:
        import yaml as _yaml
        if not hasattr(_yaml, "CLoader") or _yaml.CLoader is None:
            _yaml.CLoader = _yaml.Loader
            sys.modules["yaml"] = _yaml
        from camoufox.async_api import AsyncCamoufox  # noqa: F401
        return AsyncCamoufox
    except Exception as exc:
        logger.debug(f"[vinted] camoufox not available: {exc}")
        return None


class VintedScraper(BaseScraper):
    """Vinted EU listing scraper — camoufox + multi-strategy extraction."""

    PLATFORM = "vinted"
    CURRENCY = "EUR"
    BASE_URL = "https://www.vinted.fr"
    NEEDS_TRANSLATION = False

    # ── Search ────────────────────────────────────────────────────────────

    async def search(self, keyword: str, keyword_group: dict) -> list[dict]:
        AsyncCamoufox = _try_load_camoufox()

        if AsyncCamoufox:
            items = await self._search_camoufox(keyword, AsyncCamoufox)
        else:
            items = await self._search_playwright(keyword)

        sizes = keyword_group.get("size_filter", [])
        results = []
        for raw in items:
            listing = self._parse_item(raw, keyword_group, sizes)
            if listing:
                results.append(listing)

        logger.debug(f"[{self.PLATFORM}] '{keyword}' → {len(results)} results")
        return results

    # ── camoufox path (primary) ───────────────────────────────────────────

    async def _search_camoufox(self, keyword: str, AsyncCamoufox) -> list[dict]:
        url = _SEARCH_URL.format(keyword=quote_plus(keyword))
        captured: list[dict] = []

        _sp = self._session_path()
        try:
            async with AsyncCamoufox(headless=True) as browser:
                page = await browser.new_page()

                # ── Intercept API responses ────────────────────────────
                async def on_response(response):
                    url = response.url
                    # Log all vinted API calls at debug level to aid diagnosis
                    if "vinted" in url and "/api/" in url:
                        logger.debug(
                            f"[{self.PLATFORM}] API call: {response.status} {url[:120]}"
                        )
                    if _API_PATTERN not in url:
                        return
                    if response.status != 200:
                        return
                    try:
                        data = await response.json()
                        items = data.get("items", [])
                        if items:
                            captured.extend(items)
                            logger.debug(
                                f"[{self.PLATFORM}] API captured {len(items)} items"
                            )
                    except Exception:
                        pass

                page.on("response", on_response)

                # Navigate — use domcontentloaded to avoid infinite waits
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=35_000)
                except PlaywrightTimeout:
                    logger.warning(
                        f"[{self.PLATFORM}] Navigation timeout for '{keyword}' — continuing"
                    )

                # ── Dismiss cookie/GDPR consent modal ─────────────────
                await self._dismiss_consent(page)

                # Wait up to 12s for API call to fire after consent
                try:
                    await page.wait_for_timeout(12_000)
                except Exception:
                    pass

                # ── If API captured items, we're done ─────────────────
                if captured:
                    return captured

                # ── Fallback 1: __NEXT_DATA__ SSR JSON ────────────────
                next_items = await self._extract_next_data(page)
                if next_items:
                    logger.debug(
                        f"[{self.PLATFORM}] __NEXT_DATA__ yielded {len(next_items)} items"
                    )
                    return next_items

                # ── Fallback 2: DOM scraping ───────────────────────────
                dom_items = await self._extract_dom(page, keyword)
                if dom_items:
                    logger.debug(
                        f"[{self.PLATFORM}] DOM scraping yielded {len(dom_items)} items"
                    )
                    return dom_items

                logger.warning(f"[{self.PLATFORM}] All extraction strategies failed for '{keyword}'")

                try:
                    await page.context.storage_state(path=str(_sp))
                except Exception:
                    pass

        except Exception as exc:
            logger.error(f"[{self.PLATFORM}] camoufox error: {exc}", exc_info=True)

        return []

    # ── Cookie consent dismissal ──────────────────────────────────────────

    async def _dismiss_consent(self, page) -> None:
        """Try every known consent-accept selector; also check shadow DOM / iframes."""
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

        # Also try inside any iframes
        try:
            for frame in page.frames:
                if frame is page.main_frame:
                    continue
                for sel in _CONSENT_SELECTORS:
                    try:
                        btn = frame.locator(sel).first
                        if await btn.is_visible(timeout=300):
                            await btn.click(timeout=1_000)
                            logger.debug(
                                f"[{self.PLATFORM}] Clicked consent in iframe: {sel}"
                            )
                            await page.wait_for_timeout(800)
                            return
                    except Exception:
                        continue
        except Exception:
            pass

    # ── __NEXT_DATA__ extraction ──────────────────────────────────────────

    async def _extract_next_data(self, page) -> list[dict]:
        """Extract catalog items from Next.js SSR hydration JSON."""
        try:
            raw = await page.evaluate("""() => {
                const el = document.getElementById('__NEXT_DATA__');
                return el ? el.textContent : null;
            }""")
            if not raw:
                return []

            data = json.loads(raw)
            return list(_walk_for_items(data))

        except Exception as exc:
            logger.debug(f"[{self.PLATFORM}] __NEXT_DATA__ extraction failed: {exc}")
            return []

    # ── DOM scraping fallback ─────────────────────────────────────────────

    async def _extract_dom(self, page, keyword: str) -> list[dict]:
        """
        Parse Vinted item cards from the rendered DOM.
        Vinted renders into .feed-grid__item cards with data-testid attributes.
        Pattern: product-item-id-{itemId}--{field}
        """
        try:
            items_json = await page.evaluate(r"""() => {
                const results = [];
                const cards = [...document.querySelectorAll('.feed-grid__item')];

                for (const card of cards) {
                    // Item ID + title from URL
                    const link = card.querySelector('a[href*="/items/"]');
                    if (!link) continue;
                    const href = link.href || '';
                    const idMatch = href.match(/\/items\/(\d+)-([^?#]+)/);
                    if (!idMatch) continue;
                    const id       = idMatch[1];
                    const slugTitle = idMatch[2].replace(/-/g, ' ');

                    // Price (seller price, not total)
                    const priceEl = card.querySelector('[data-testid$="--price-text"]');
                    const priceRaw = priceEl ? priceEl.textContent.trim() : '';
                    // Strip everything except digits and comma/dot
                    const priceStr = priceRaw.replace(/[^\d,]/g, '').replace(',', '.');
                    const price = parseFloat(priceStr) || 0;
                    if (price <= 0) continue;

                    // Image
                    const imgEl = card.querySelector('img');
                    const imageUrl = imgEl ? (imgEl.src || imgEl.getAttribute('data-src') || '') : '';

                    // Brand from description-title
                    const brandEl = card.querySelector('[data-testid$="--description-title"]');
                    const brand = brandEl ? brandEl.textContent.trim() : '';

                    // Size/condition from subtitle
                    const subtitleEl = card.querySelector('[data-testid$="--description-subtitle"]');
                    const subtitle = subtitleEl ? subtitleEl.textContent.trim() : '';

                    // Clean URL (remove referrer param)
                    const cleanUrl = href.split('?')[0];

                    results.push({ id, title: slugTitle, brand, price, imageUrl, url: cleanUrl, subtitle });
                }
                return results;
            }""")

            # Convert to the raw item shape _parse_item expects
            out = []
            for item in (items_json or []):
                if not item.get("id") or not item.get("title") or item.get("price", 0) <= 0:
                    continue
                out.append({
                    "id":          item["id"],
                    "title":       item["title"],
                    "price":       item["price"],
                    "currency":    "EUR",
                    "url":         item.get("url", ""),
                    "photo":       {"url": item.get("imageUrl") or ""},
                    "status":      None,
                    "brand_title": item.get("brand", ""),
                    "size_title":  item.get("subtitle", ""),
                })
            return out

        except Exception as exc:
            logger.debug(f"[{self.PLATFORM}] DOM extraction failed: {exc}")
            return []

    # ── Plain Playwright fallback (no camoufox) ───────────────────────────

    async def _search_playwright(self, keyword: str) -> list[dict]:
        url = _SEARCH_URL.format(keyword=quote_plus(keyword))
        captured: list[dict] = []
        _sp = self._session_path()

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage",
                      "--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                user_agent=self._random_ua(),
                locale="fr-FR",
                viewport={"width": 1280, "height": 900},
                storage_state=str(_sp) if _sp.exists() else None,
            )
            page = await context.new_page()
            await page.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
            )

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
                logger.warning(
                    f"[{self.PLATFORM}] Page load timed out for '{keyword}' — using partial results"
                )
            except Exception as exc:
                logger.error(f"[{self.PLATFORM}] Error for '{keyword}': {exc}", exc_info=True)
            finally:
                try:
                    await context.storage_state(path=str(_sp))
                except Exception:
                    pass
                await browser.close()

        return captured

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

            size_title = item.get("size_title", "") or ""
            if sizes and not self.matches_size(f"{title} {size_title}", sizes):
                return None

            photo = item.get("photo") or {}
            image_url = photo.get("url") or photo.get("full_size_url")

            cond_id = str(item.get("status", ""))
            condition = _CONDITION_MAP.get(cond_id, cond_id) or None

            brand = ""
            if isinstance(item.get("brand_title"), str):
                brand = item["brand_title"]

            url = item.get("url") or f"https://www.vinted.fr/items/{lid}"
            if not url.startswith("http"):
                url = f"https://www.vinted.fr{url}"

            return {
                "id": lid,
                "platform": self.PLATFORM,
                "title": title,
                "translated_title": title,
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
            logger.warning(f"[{self.PLATFORM}] Failed to parse item: {exc}")
            return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _walk_for_items(obj, depth: int = 0) -> list:
    """
    Recursively walk the __NEXT_DATA__ JSON tree looking for arrays that
    look like Vinted catalog item lists (contain dicts with 'id' and 'price').
    Returns the first matching array found.
    """
    if depth > 10:
        return []

    if isinstance(obj, list) and len(obj) > 0:
        first = obj[0]
        if isinstance(first, dict) and "id" in first and "price" in first:
            return obj

    if isinstance(obj, dict):
        for val in obj.values():
            result = _walk_for_items(val, depth + 1)
            if result:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = _walk_for_items(item, depth + 1)
            if result:
                return result

    return []
