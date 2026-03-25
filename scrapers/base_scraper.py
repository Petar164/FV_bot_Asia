"""
fashionvoid-bot · scrapers/base_scraper.py
─────────────────────────────────────────────────────────────────────────────
Abstract base class that every platform scraper inherits from.

Each concrete scraper must implement:
    search(keyword: str) -> list[dict]

The returned listing dict shape (all fields required unless marked optional):
    {
        "id":               str,   # platform-native listing ID
        "platform":         str,   # e.g. "mercari_jp"
        "title":            str,   # original title
        "translated_title": str,   # English translation  (optional — filled by base)
        "price":            float, # in original currency
        "currency":         str,   # "JPY" | "KRW" | "CNY"
        "price_eur":        float, # converted at scrape time  (filled by base)
        "url":              str,
        "image_url":        str | None,
        "condition":        str | None,
        "keyword_group":    str,   # matched keyword group name
        "is_suspicious":    bool,  # True if price < threshold × rolling_avg
    }
─────────────────────────────────────────────────────────────────────────────
"""

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """
    Platform-agnostic scraper scaffold.

    Subclasses set:
        PLATFORM   — string identifier  (e.g. "mercari_jp")
        CURRENCY   — ISO 4217 code      (e.g. "JPY")
        BASE_URL   — root URL of the platform
    """

    PLATFORM: str = ""
    CURRENCY: str = ""
    BASE_URL: str = ""
    NEEDS_TRANSLATION: bool = True   # EU scrapers override to False

    # Default browser-like headers to reduce bot detection
    _DEFAULT_HEADERS: dict = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1",
    }

    def __init__(
        self,
        config: dict,
        db,
        translator,
        currency_converter,
        proxy_manager=None,
    ):
        """
        Parameters
        ──────────
        config            : full parsed config.yaml dict
        db                : Database instance
        translator        : Translator instance
        currency_converter: CurrencyConverter instance
        proxy_manager     : ProxyManager instance (optional)
        """
        self.config = config
        self.db = db
        self.translator = translator
        self.fx = currency_converter
        self.proxy = proxy_manager

        self._kw_config = config.get("keywords", [])
        self._platform_cfg = config.get("intervals_seconds", {})

        logger.info(f"[{self.PLATFORM}] Scraper initialised")

    # ── Session persistence ───────────────────────────────────────────────

    def _session_path(self) -> Path:
        """Return path to this platform's Playwright browser session file."""
        p = Path("sessions") / self.PLATFORM / "state.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    # ── Abstract interface ────────────────────────────────────────────────

    @abstractmethod
    async def search(self, keyword: str, keyword_group: dict) -> list[dict]:
        """
        Search the platform for *keyword* and return raw listing dicts.
        Implementations should NOT call translate/convert — the base class
        post-processes the list via `process_listings()`.
        """
        ...

    # ── HTTP helpers ──────────────────────────────────────────────────────

    def _build_client(self, extra_headers: Optional[dict] = None) -> httpx.AsyncClient:
        """Create a pre-configured httpx AsyncClient."""
        headers = {**self._DEFAULT_HEADERS, "User-Agent": self._random_ua()}
        if extra_headers:
            headers.update(extra_headers)

        proxy_url = self.proxy.get_proxy() if self.proxy else None
        proxies = {"http://": proxy_url, "https://": proxy_url} if proxy_url else None

        return httpx.AsyncClient(
            headers=headers,
            proxies=proxies,
            timeout=httpx.Timeout(20.0, connect=10.0),
            follow_redirects=True,
            http2=True,
        )

    @staticmethod
    def _random_ua() -> str:
        """Rotate through a small pool of realistic User-Agent strings."""
        import random
        agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
            "Gecko/20100101 Firefox/125.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
        ]
        return random.choice(agents)

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    async def _get(self, client: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response:
        """GET with automatic retry on network / timeout errors."""
        response = await client.get(url, **kwargs)
        response.raise_for_status()
        return response

    # ── Post-processing pipeline ──────────────────────────────────────────

    async def process_listings(
        self, raw_listings: list[dict], keyword_group: dict
    ) -> list[dict]:
        """
        For each raw listing:
          1. Convert price to EUR
          2. Translate title
          3. Check suspicious-price flag
          4. Update rolling average
          5. Skip if already in DB
        Returns only NEW listings.
        """
        new_listings = []
        group_name = keyword_group.get("group", "unknown")
        threshold = keyword_group.get("suspicious_threshold", 0.25)
        ceiling_eur = keyword_group.get("price_ceiling_eur", float("inf"))

        for listing in raw_listings:
            lid = listing.get("id")
            platform = listing.get("platform", self.PLATFORM)

            # ── Skip already-seen listings ────────────────────────────
            if self.db.listing_exists(lid, platform):
                self.db.update_last_seen(lid, platform)
                continue

            # ── Currency conversion ───────────────────────────────────
            try:
                price_eur = await self.fx.convert(
                    listing["price"], listing["currency"], "EUR"
                )
            except Exception as exc:
                logger.warning(f"[{self.PLATFORM}] FX conversion failed: {exc}")
                price_eur = None

            # ── Price ceiling filter ──────────────────────────────────
            if price_eur and price_eur > ceiling_eur:
                logger.debug(
                    f"[{self.PLATFORM}] Skipping {lid} — €{price_eur:.0f} > ceiling €{ceiling_eur}"
                )
                continue

            # ── Translation (Asia platforms only) ─────────────────────
            if self.NEEDS_TRANSLATION:
                try:
                    translated = await self.translator.translate(listing["title"])
                except Exception as exc:
                    logger.warning(f"[{self.PLATFORM}] Translation failed: {exc}")
                    translated = listing["title"]
            else:
                translated = listing.get("translated_title") or listing["title"]

            # ── Suspicious price check ────────────────────────────────
            is_suspicious = False
            en_terms = keyword_group.get("terms_en") or keyword_group.get("terms", [])
            if price_eur:
                for term in en_terms:
                    avg = self.db.get_rolling_average(group_name, term, platform)
                    if avg and price_eur < threshold * avg:
                        is_suspicious = True
                        logger.warning(
                            f"[{self.PLATFORM}] SUSPICIOUS — {lid} "
                            f"€{price_eur:.0f} vs avg €{avg:.0f}"
                        )
                        break

            # ── Assemble final dict ───────────────────────────────────
            enriched = {
                **listing,
                "translated_title": translated,
                "price_eur": price_eur,
                "keyword_group": group_name,
                "is_suspicious": is_suspicious,
            }

            # ── Persist & update rolling average ──────────────────────
            self.db.insert_listing(enriched)
            if price_eur:
                for term in en_terms:
                    self.db.update_rolling_average(group_name, term, platform, price_eur)

            new_listings.append(enriched)
            logger.info(
                f"[{self.PLATFORM}] NEW  {lid[:20]}…  "
                f"{listing['price']:,.0f} {listing['currency']}  "
                f"(≈ €{price_eur:.0f})"
                if price_eur
                else f"[{self.PLATFORM}] NEW  {lid}"
            )

        return new_listings

    # ── Size filter helper ────────────────────────────────────────────────

    @staticmethod
    def matches_size(title: str, sizes: list[str]) -> bool:
        """
        Return True if any size token appears in the title string.
        Case-insensitive, whole-word boundary not enforced (platforms use
        abbreviations like '46', 'S', 'M' which are short enough to match inline).
        """
        if not sizes:
            return True
        title_lower = title.lower()
        return any(s.lower() in title_lower for s in sizes)

    # ── Public run method ─────────────────────────────────────────────────

    async def run(self, notifications: list, vision_filter=None) -> int:
        """
        Called by the scheduler.  Iterates keyword groups, runs search(),
        post-processes results, optionally scores images via GPT-4o vision,
        and fires notifications routed by vision score.
        Returns total count of new listings found.

        Vision routing (when vision_filter is set and listing has image_url):
          score >= min_confidence      → all notification channels
          score >= priority_threshold  → email only
          score <  priority_threshold  → no alert (stored in DB only)
          score is None (no image/API fail) → all channels (no filter)
        """
        total_new = 0

        for kw_group in self._kw_config:
            if not self._platform_selected(kw_group):
                continue

            for term in self._get_search_terms(kw_group):
                # ── Pause gate ────────────────────────────────────────
                gate = getattr(self, "_run_gate", None)
                if gate is not None and not gate.is_set():
                    logger.debug(f"[{self.PLATFORM}] Paused — stopping scan early")
                    return total_new

                try:
                    raw = await self.search(term, kw_group)
                    new_listings = await self.process_listings(raw, kw_group)

                    for listing in new_listings:
                        await self._notify(listing, notifications, vision_filter)

                    total_new += len(new_listings)

                except Exception as exc:
                    logger.error(
                        f"[{self.PLATFORM}] Error scraping '{term}': {exc}",
                        exc_info=True,
                    )

        return total_new

    async def _notify(self, listing: dict, notifications: list, vision_filter=None) -> None:
        """
        Score the listing image via vision filter (if enabled) then route
        notifications based on the score threshold config.
        """
        score = None
        if vision_filter and vision_filter.enabled:
            score = await vision_filter.score(listing)
            if score is not None:
                listing["vision_score"] = score
                self.db.update_vision_score(listing["id"], listing["platform"], score)

        # Determine which channels to fire
        if score is not None:
            if score < vision_filter.priority_threshold:
                # Below priority threshold — store only, no alert
                logger.debug(
                    f"[{self.PLATFORM}] vision score {score} below threshold "
                    f"({vision_filter.priority_threshold}) — suppressing alerts for {listing['id']}"
                )
                return
            elif score < vision_filter.min_confidence:
                # Between thresholds — email only
                for notifier in notifications:
                    if notifier.__class__.__name__ == "EmailAlert":
                        await notifier.send(listing)
                return

        # Full confidence or no vision filter — fire all channels
        for notifier in notifications:
            await notifier.send(listing)

    def _platform_selected(self, kw_group: dict) -> bool:
        """
        Return True if this scraper's platform is selected in the keyword group.
        Handles both the legacy flat list and the new {eu, asia} dict schema.
        """
        platforms_cfg = kw_group.get("platforms", [])
        if isinstance(platforms_cfg, dict):
            all_platforms = (
                platforms_cfg.get("eu", []) + platforms_cfg.get("asia", [])
            )
        else:
            all_platforms = platforms_cfg
        return self.PLATFORM in all_platforms

    def _get_search_terms(self, kw_group: dict) -> list[str]:
        """
        Return the search terms appropriate for this platform.

        Legacy schema  → returns kw_group['terms']
        New schema     → EU platforms use terms_en only;
                         Asia platforms use all language terms combined.
        """
        # Legacy flat list
        if "terms" in kw_group:
            return kw_group["terms"]

        eu_platforms = {"vinted", "vestiaire"}
        terms = list(kw_group.get("terms_en", []))

        if self.PLATFORM not in eu_platforms:
            terms += kw_group.get("terms_jp", [])
            terms += kw_group.get("terms_kr", [])
            terms += kw_group.get("terms_cn", [])

        return terms
