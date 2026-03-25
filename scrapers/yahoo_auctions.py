"""
fashionvoid-bot · scrapers/yahoo_auctions.py
─────────────────────────────────────────────────────────────────────────────
Yahoo Auctions Japan scraper.

Yahoo Auctions is heavily JS-rendered — we use Playwright (Chromium) to
load the search results page and then parse the resulting HTML with
BeautifulSoup.

URL pattern:
  https://auctions.yahoo.co.jp/search/search?p=<keyword>&ei=UTF-8&auccat=0
  &va=<keyword>&is_postage_mode=1&dest=1&abatch=1&select=core

Note: BuyNow (即決) and Auction listings are mixed — we capture both.
─────────────────────────────────────────────────────────────────────────────
"""

import asyncio
import logging
import re
from typing import Optional
from urllib.parse import quote_plus

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

from .base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class YahooAuctionsScraper(BaseScraper):
    """Yahoo Auctions Japan (auctions.yahoo.co.jp) scraper via Playwright."""

    PLATFORM = "yahoo_auctions"
    CURRENCY = "JPY"
    BASE_URL = "https://auctions.yahoo.co.jp"

    _SEARCH_URL = (
        "https://auctions.yahoo.co.jp/search/search"
        "?p={keyword}&ei=UTF-8&auccat=0&va={keyword}"
        "&is_postage_mode=1&dest=1&abatch=1&select=core"
        "&sort=bids&order=d"
    )

    async def search(self, keyword: str, keyword_group: dict) -> list[dict]:
        """Playwright-driven search of Yahoo Auctions Japan."""
        results = []
        url = self._SEARCH_URL.format(keyword=quote_plus(keyword))

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ],
            )
            _sp = self._session_path()
            context = await browser.new_context(
                user_agent=self._random_ua(),
                locale="ja-JP",
                viewport={"width": 1280, "height": 900},
                storage_state=str(_sp) if _sp.exists() else None,
            )
            page = await context.new_page()

            # Hide automation markers
            await page.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
            )

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(2000)

                html = await page.content()
                soup = BeautifulSoup(html, "lxml")

                items = soup.select("li.Product")
                if not items:
                    # Fallback selector for alternate layout
                    items = soup.select("div.SearchResult__item")

                for item in items:
                    listing = self._parse_item(item, keyword_group)
                    if listing:
                        results.append(listing)

            except PlaywrightTimeout:
                logger.warning(f"[{self.PLATFORM}] Timeout loading '{keyword}'")
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

    def _parse_item(self, item, keyword_group: dict) -> Optional[dict]:
        """Parse a BeautifulSoup item element into our listing dict."""
        try:
            # ── Listing ID ────────────────────────────────────────────
            link_el = item.select_one("a.Product__titleLink") or item.select_one("a[data-auction-id]")
            if not link_el:
                return None

            href = link_el.get("href", "")
            lid_match = re.search(r"/([a-zA-Z0-9]+)/?$", href)
            lid = lid_match.group(1) if lid_match else href[-16:]
            if not lid:
                return None

            # ── Title ─────────────────────────────────────────────────
            title_el = item.select_one(".Product__title") or link_el
            title = title_el.get_text(strip=True) if title_el else ""
            if not title:
                return None

            # ── Size filter ───────────────────────────────────────────
            sizes = keyword_group.get("size_filter", [])
            if sizes and not self.matches_size(title, sizes):
                return None

            # ── Price ─────────────────────────────────────────────────
            price_el = item.select_one(".Product__priceValue") or item.select_one(".Price")
            price_text = price_el.get_text(strip=True) if price_el else "0"
            price = self._clean_price(price_text)
            if price <= 0:
                return None

            # ── Image ─────────────────────────────────────────────────
            img_el = item.select_one("img.Product__imageData") or item.select_one("img")
            image_url = img_el.get("src") or img_el.get("data-src") if img_el else None

            # ── Condition ─────────────────────────────────────────────
            cond_el = item.select_one(".Product__condition")
            condition = cond_el.get_text(strip=True) if cond_el else None

            # ── Full listing URL ──────────────────────────────────────
            if href.startswith("http"):
                full_url = href
            else:
                full_url = f"{self.BASE_URL}{href}"

            return {
                "id": lid,
                "platform": self.PLATFORM,
                "title": title,
                "translated_title": None,
                "price": price,
                "currency": self.CURRENCY,
                "price_eur": None,
                "url": full_url,
                "image_url": image_url,
                "condition": condition,
                "keyword_group": keyword_group.get("group", ""),
                "is_suspicious": False,
            }

        except Exception as exc:
            logger.warning(f"[{self.PLATFORM}] Parse error: {exc}")
            return None

    @staticmethod
    def _clean_price(text: str) -> float:
        """Strip yen symbols and commas, return float."""
        cleaned = re.sub(r"[^\d.]", "", text)
        try:
            return float(cleaned)
        except ValueError:
            return 0.0
