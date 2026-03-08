"""
fashionvoid-bot · scrapers/bunjang.py
─────────────────────────────────────────────────────────────────────────────
Bunjang (bunjang.co.kr) scraper — South Korean C2C fashion marketplace.

Bunjang's REST API endpoints (/api/1/... and /api/2/...) are no longer
publicly accessible (HTTP 404).  We scrape the web search page instead via
Playwright, using JavaScript evaluation to extract product data from the
React-rendered DOM.

Search URL:
    https://bunjang.co.kr/search/products?q={keyword}&order=date
─────────────────────────────────────────────────────────────────────────────
"""

import logging
from typing import Optional
from urllib.parse import quote_plus

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

from .base_scraper import BaseScraper

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://bunjang.co.kr/search/products?q={keyword}&order=date"
_ITEM_URL = "https://bunjang.co.kr/products/{id}"


class BunjangScraper(BaseScraper):
    """Bunjang (bunjang.co.kr) listing scraper via Playwright."""

    PLATFORM = "bunjang"
    CURRENCY = "KRW"
    BASE_URL = "https://bunjang.co.kr"

    # ── Search ────────────────────────────────────────────────────────────

    async def search(self, keyword: str, keyword_group: dict) -> list[dict]:
        url = _SEARCH_URL.format(keyword=quote_plus(keyword))
        raw_items = []

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage",
                      "--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                user_agent=self._random_ua(),
                locale="ko-KR",
                viewport={"width": 1366, "height": 768},
            )
            page = await context.new_page()
            await page.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
            )

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                await page.wait_for_timeout(3_000)   # let React render

                raw_items = await page.evaluate("""() => {
                    const items = [];
                    const seen = new Set();

                    // Product links: /products/{numeric-id}
                    const links = Array.from(
                        document.querySelectorAll('a[href*="/products/"]')
                    );

                    links.forEach(link => {
                        const href = link.getAttribute('href') || '';
                        const idMatch = href.match(/\\/products\\/(\\d+)/);
                        if (!idMatch || seen.has(idMatch[1])) return;
                        seen.add(idMatch[1]);

                        // Walk up to find the card container
                        let card = link;
                        for (let i = 0; i < 6; i++) {
                            if (!card.parentElement) break;
                            card = card.parentElement;
                            if (card.querySelectorAll('img').length > 0) break;
                        }

                        const img  = card.querySelector('img');
                        const text = card.innerText || '';

                        // Extract first number that looks like a KRW price (3+ digits)
                        const priceMatch = text.match(/([\\d,]{3,})\\s*원?/);
                        const price = priceMatch
                            ? parseInt(priceMatch[1].replace(/,/g, ''), 10)
                            : null;

                        // Title: prefer explicit text node, fall back to alt text
                        const nameEl = card.querySelector(
                            'p, span, h2, h3, [class*="name"], [class*="title"]'
                        );
                        const title = (nameEl && nameEl.textContent.trim())
                            || (img && img.getAttribute('alt'))
                            || '';

                        items.push({
                            id:        idMatch[1],
                            title:     title,
                            price:     price,
                            image_url: img ? (img.src || img.dataset.src) : null,
                        });
                    });

                    return items;
                }""")

            except PlaywrightTimeout:
                logger.warning(f"[{self.PLATFORM}] Timeout loading '{keyword}'")
            except Exception as exc:
                logger.error(f"[{self.PLATFORM}] Error scraping '{keyword}': {exc}", exc_info=True)
            finally:
                await browser.close()

        results = []
        for raw in raw_items:
            listing = self._parse_item(raw, keyword_group)
            if listing:
                results.append(listing)

        logger.debug(f"[{self.PLATFORM}] '{keyword}' → {len(results)} raw results")
        return results

    # ── Parser ────────────────────────────────────────────────────────────

    def _parse_item(self, item: dict, keyword_group: dict) -> Optional[dict]:
        try:
            lid = str(item.get("id", "")).strip()
            if not lid:
                return None

            title = (item.get("title") or "").strip()
            if not title:
                return None

            price = item.get("price")
            if not price or price <= 0:
                return None

            sizes = keyword_group.get("size_filter", [])
            if sizes and not self.matches_size(title, sizes):
                return None

            return {
                "id": lid,
                "platform": self.PLATFORM,
                "title": title,
                "translated_title": None,
                "price": float(price),
                "currency": self.CURRENCY,
                "price_eur": None,
                "url": _ITEM_URL.format(id=lid),
                "image_url": item.get("image_url"),
                "condition": None,
                "keyword_group": keyword_group.get("group", ""),
                "is_suspicious": False,
            }

        except Exception as exc:
            logger.warning(f"[{self.PLATFORM}] Parse error: {exc}")
            return None
