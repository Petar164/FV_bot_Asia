"""
fashionvoid-bot · utils/currency.py
─────────────────────────────────────────────────────────────────────────────
Live currency conversion via exchangerate-api.com (free tier).

Rates are cached in memory and refreshed every `cache_ttl_seconds` seconds
(default 1 hour).  If the API is unavailable, falls back to the last known
rates so the bot keeps running.

Supports: JPY, KRW, CNY → EUR (and any other pair the API provides).
─────────────────────────────────────────────────────────────────────────────
"""

import asyncio
import logging
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Free tier endpoint — no auth, limited to 1500 req/month
_API_ENDPOINT = "https://api.exchangerate-api.com/v4/latest/{base}"

# Paid tier endpoint (requires api_key, unlimited)
_API_ENDPOINT_V6 = "https://v6.exchangerate-api.com/v6/{key}/latest/{base}"

# Hard-coded fallback rates (updated 2025-01 — rough approximations)
_FALLBACK_RATES: dict[str, float] = {
    "JPY": 162.0,   # 1 EUR ≈ 162 JPY
    "KRW": 1420.0,  # 1 EUR ≈ 1420 KRW
    "CNY": 7.8,     # 1 EUR ≈ 7.8 CNY
    "USD": 1.08,
    "GBP": 0.86,
    "EUR": 1.0,
}


class CurrencyConverter:
    """Async currency converter with caching and graceful fallback."""

    def __init__(self, config: dict):
        cfg = config.get("currency", {})
        self._api_key = cfg.get("api_key", "")
        self._base = cfg.get("base", "EUR")
        self._ttl = cfg.get("cache_ttl_seconds", 3600)

        self._rates: dict[str, float] = {}   # {currency_code: rate_vs_base}
        self._last_fetch: float = 0.0
        self._lock = asyncio.Lock()

        logger.info(f"[currency] Converter ready (base={self._base}, TTL={self._ttl}s)")

    async def convert(
        self, amount: float, from_currency: str, to_currency: str = "EUR"
    ) -> Optional[float]:
        """
        Convert *amount* from *from_currency* to *to_currency*.
        Returns None if conversion is impossible.
        """
        if from_currency == to_currency:
            return amount

        rates = await self._get_rates()

        try:
            # Convert through the base currency (EUR)
            # rates[X] = how many X per 1 EUR
            if to_currency == self._base:
                return amount / rates[from_currency]
            elif from_currency == self._base:
                return amount * rates[to_currency]
            else:
                # Triangulate through base
                amount_in_base = amount / rates[from_currency]
                return amount_in_base * rates[to_currency]
        except (KeyError, ZeroDivisionError) as exc:
            logger.warning(f"[currency] Cannot convert {from_currency}→{to_currency}: {exc}")
            return None

    async def get_rate(self, currency: str) -> Optional[float]:
        """Return how many *currency* per 1 EUR."""
        rates = await self._get_rates()
        return rates.get(currency)

    # ── Internal rate fetching ────────────────────────────────────────────

    async def _get_rates(self) -> dict[str, float]:
        """Return cached rates, refreshing if TTL has expired."""
        now = time.monotonic()

        # Fast path: cache is fresh
        if self._rates and (now - self._last_fetch) < self._ttl:
            return self._rates

        # Slow path: refresh under lock to prevent thundering herd
        async with self._lock:
            # Double-check inside lock
            if self._rates and (now - self._last_fetch) < self._ttl:
                return self._rates

            fresh = await self._fetch_rates()
            if fresh:
                self._rates = fresh
                self._last_fetch = time.monotonic()
                logger.info(
                    f"[currency] Rates refreshed — "
                    f"JPY={fresh.get('JPY', '?'):.1f}  "
                    f"KRW={fresh.get('KRW', '?'):.0f}  "
                    f"CNY={fresh.get('CNY', '?'):.2f}"
                )
            elif not self._rates:
                # First run and API is down — use fallback
                logger.warning("[currency] Using fallback rates")
                self._rates = _FALLBACK_RATES.copy()

        return self._rates

    async def _fetch_rates(self) -> Optional[dict[str, float]]:
        """Fetch fresh rates from exchangerate-api.com."""
        # Use v6 paid endpoint if API key is provided
        if self._api_key and self._api_key != "YOUR_EXCHANGERATE_API_KEY":
            url = _API_ENDPOINT_V6.format(key=self._api_key, base=self._base)
            rates_key = "conversion_rates"
        else:
            url = _API_ENDPOINT.format(base=self._base)
            rates_key = "rates"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()

            rates = data.get(rates_key, {})
            if rates:
                return {k: float(v) for k, v in rates.items()}
            return None

        except Exception as exc:
            logger.error(f"[currency] Rate fetch failed: {exc}")
            return None

    def format_price(self, amount: float, currency: str) -> str:
        """Format a price string with appropriate currency symbol."""
        symbols = {"EUR": "€", "JPY": "¥", "KRW": "₩", "CNY": "¥", "USD": "$", "GBP": "£"}
        symbol = symbols.get(currency, currency + " ")
        if currency in ("JPY", "KRW"):
            return f"{symbol}{amount:,.0f}"
        return f"{symbol}{amount:,.2f}"
