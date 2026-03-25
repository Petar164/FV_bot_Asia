"""
fashionvoid-bot · scrapers/xianyu.py
─────────────────────────────────────────────────────────────────────────────
Xianyu (2.taobao.com / goofish.com) scraper — Alibaba's secondhand platform.

Xianyu is heavily protected (anti-bot, encrypted tokens).
Strategy: Playwright with stealth mode, intercept the internal XHR/Fetch
calls that the SPA fires, capture the JSON before it's rendered.

URL: https://2.taobao.com/list/item.htm?q=<keyword>

We intercept the AJAX response from the search API endpoint
(/recommend.json or /search_item.json) which returns structured JSON.

If interception fails we fall back to HTML parsing of visible cards.
─────────────────────────────────────────────────────────────────────────────
"""

import asyncio
import json
import logging
import re
from typing import Optional
from urllib.parse import quote_plus

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

from .base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class XianyuScraper(BaseScraper):
    """Xianyu / Idle Fish (2.taobao.com) scraper via Playwright + XHR intercept."""

    PLATFORM = "xianyu"
    CURRENCY = "CNY"
    BASE_URL = "https://2.taobao.com"

    _SEARCH_URL = "https://2.taobao.com/list/item.htm?q={keyword}&sort=s"

    async def search(self, keyword: str, keyword_group: dict) -> list[dict]:
        """
        Navigate to Xianyu search page, intercept JSON API responses,
        and return raw listing dicts.
        """
        results = []
        intercepted_data: list[dict] = []

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-web-security",
                    "--disable-dev-shm-usage",
                ],
            )
            _sp = self._session_path()
            context = await browser.new_context(
                user_agent=self._random_ua(),
                locale="zh-CN",
                viewport={"width": 1366, "height": 768},
                extra_http_headers={"Accept-Language": "zh-CN,zh;q=0.9"},
                storage_state=str(_sp) if _sp.exists() else None,
            )

            # ── Intercept API calls ───────────────────────────────────
            async def handle_response(response):
                """Capture JSON from Xianyu's internal search API calls."""
                url = response.url
                if any(k in url for k in ["search_item", "recommend", "mtop.taobao"]):
                    try:
                        body = await response.body()
                        data = json.loads(body)
                        intercepted_data.append(data)
                    except Exception:
                        pass

            page = await context.new_page()
            page.on("response", handle_response)

            # Stealth patches
            await page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.chrome = {runtime: {}};
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});
            """)

            try:
                url = self._SEARCH_URL.format(keyword=quote_plus(keyword))
                await page.goto(url, wait_until="networkidle", timeout=35000)
                await page.wait_for_timeout(3000)

                # ── Parse intercepted JSON first ──────────────────────
                for data in intercepted_data:
                    items = self._extract_from_json(data)
                    for item in items:
                        listing = self._parse_item(item, keyword_group)
                        if listing:
                            results.append(listing)

                # ── HTML fallback if interception yielded nothing ──────
                if not results:
                    html = await page.content()
                    soup = BeautifulSoup(html, "lxml")
                    cards = (
                        soup.select(".card--UOVpA")
                        or soup.select("[class*='card']")
                        or soup.select(".list-item")
                    )
                    for card in cards:
                        listing = self._parse_html_card(card, keyword_group)
                        if listing:
                            results.append(listing)

            except PlaywrightTimeout:
                logger.warning(f"[{self.PLATFORM}] Timeout for '{keyword}'")
            except Exception as exc:
                logger.error(f"[{self.PLATFORM}] Error: {exc}", exc_info=True)
            finally:
                try:
                    await context.storage_state(path=str(_sp))
                except Exception:
                    pass
                await browser.close()

        logger.debug(f"[{self.PLATFORM}] '{keyword}' → {len(results)} raw results")
        return results

    # ── JSON extraction ───────────────────────────────────────────────────

    def _extract_from_json(self, data: dict) -> list[dict]:
        """Try several known Xianyu JSON shapes to extract item arrays."""
        # Shape 1: data.data.items
        items = (
            data.get("data", {}).get("items")
            or data.get("data", {}).get("resultList")
            or data.get("result", {}).get("items")
            or []
        )
        if isinstance(items, list):
            return items
        return []

    def _parse_item(self, item: dict, keyword_group: dict) -> Optional[dict]:
        """Parse Xianyu JSON item dict."""
        try:
            # Xianyu wraps items in a 'data' key sometimes
            if "data" in item and isinstance(item["data"], dict):
                item = item["data"]

            lid = str(item.get("itemId") or item.get("id") or "")
            if not lid:
                return None

            title = (
                item.get("title")
                or item.get("name")
                or item.get("subject", "")
            ).strip()
            if not title:
                return None

            # Price: may be in fen (1/100 yuan) or yuan depending on endpoint
            price_raw = float(item.get("price") or item.get("salePrice", 0))
            # Heuristic: if > 100,000 assume fen → convert to yuan
            price = price_raw / 100 if price_raw > 100000 else price_raw
            if price <= 0:
                return None

            sizes = keyword_group.get("size_filter", [])
            if sizes and not self.matches_size(title, sizes):
                return None

            image_url = (
                item.get("picUrl")
                or item.get("imgUrl")
                or item.get("img")
            )
            if image_url and not image_url.startswith("http"):
                image_url = "https:" + image_url

            return {
                "id": lid,
                "platform": self.PLATFORM,
                "title": title,
                "translated_title": None,
                "price": price,
                "currency": self.CURRENCY,
                "price_eur": None,
                "url": f"https://2.taobao.com/item.htm?id={lid}",
                "image_url": image_url,
                "condition": item.get("itemStatus") or item.get("quality"),
                "keyword_group": keyword_group.get("group", ""),
                "is_suspicious": False,
            }

        except Exception as exc:
            logger.warning(f"[{self.PLATFORM}] JSON parse error: {exc}")
            return None

    def _parse_html_card(self, card, keyword_group: dict) -> Optional[dict]:
        """HTML fallback parser for a single Xianyu card element."""
        try:
            link_el = card.select_one("a[href*='item.htm']")
            if not link_el:
                return None

            href = link_el.get("href", "")
            lid_match = re.search(r"id=(\d+)", href)
            lid = lid_match.group(1) if lid_match else ""
            if not lid:
                return None

            title_el = card.select_one("[class*='title']") or card.select_one("h3")
            title = title_el.get_text(strip=True) if title_el else ""
            if not title:
                return None

            price_el = card.select_one("[class*='price']")
            price_text = price_el.get_text(strip=True) if price_el else "0"
            price = float(re.sub(r"[^\d.]", "", price_text) or 0)

            img_el = card.select_one("img")
            image_url = img_el.get("src") or img_el.get("data-src") if img_el else None

            sizes = keyword_group.get("size_filter", [])
            if sizes and not self.matches_size(title, sizes):
                return None

            return {
                "id": lid,
                "platform": self.PLATFORM,
                "title": title,
                "translated_title": None,
                "price": price,
                "currency": self.CURRENCY,
                "price_eur": None,
                "url": f"https://2.taobao.com/item.htm?id={lid}",
                "image_url": image_url,
                "condition": None,
                "keyword_group": keyword_group.get("group", ""),
                "is_suspicious": False,
            }

        except Exception as exc:
            logger.warning(f"[{self.PLATFORM}] HTML parse error: {exc}")
            return None
