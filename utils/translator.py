"""
fashionvoid-bot · utils/translator.py
─────────────────────────────────────────────────────────────────────────────
Google Cloud Translate (REST v2) wrapper with in-memory caching.

Uses the simple REST API endpoint — no heavy Google SDK required.
API key is read from config.yaml → translate.api_key.

Cache: translations are cached in memory for the lifetime of the process.
For persistent caching across restarts, store them in the DB (future sprint).
─────────────────────────────────────────────────────────────────────────────
"""

import asyncio
import logging
from functools import lru_cache
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_TRANSLATE_ENDPOINT = (
    "https://translation.googleapis.com/language/translate/v2"
)


class Translator:
    """Async Google Cloud Translate v2 wrapper."""

    def __init__(self, config: dict):
        cfg = config.get("translate", {})
        self._api_key = cfg.get("api_key", "")
        self._target = cfg.get("target_language", "en")
        self._cache: dict[str, str] = {}
        self._enabled = bool(self._api_key and self._api_key != "YOUR_GOOGLE_TRANSLATE_API_KEY")

        if not self._enabled:
            logger.warning(
                "[translator] No API key configured — titles will not be translated"
            )
        else:
            logger.info("[translator] Google Translate ready")

    async def translate(self, text: str) -> str:
        """
        Translate *text* to English.
        Returns the original text unchanged if translation is unavailable.
        """
        if not text or not text.strip():
            return text

        # ── Cache hit ─────────────────────────────────────────────────
        if text in self._cache:
            return self._cache[text]

        if not self._enabled:
            return text

        try:
            translated = await self._call_api(text)
            self._cache[text] = translated
            return translated
        except Exception as exc:
            logger.warning(f"[translator] Translation failed for '{text[:40]}': {exc}")
            return text  # fail gracefully — return original

    async def translate_batch(self, texts: list[str]) -> list[str]:
        """
        Translate multiple texts concurrently (up to 10 at a time to respect
        Google's QPS limits).
        """
        if not self._enabled:
            return texts

        sem = asyncio.Semaphore(10)

        async def _one(t: str) -> str:
            async with sem:
                return await self.translate(t)

        return await asyncio.gather(*[_one(t) for t in texts])

    async def _call_api(self, text: str) -> str:
        """Raw Google Translate REST call."""
        payload = {
            "q": text,
            "target": self._target,
            "format": "text",
            "key": self._api_key,
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(_TRANSLATE_ENDPOINT, json=payload)
            response.raise_for_status()
            data = response.json()

        translations = (
            data.get("data", {}).get("translations", [])
        )
        if translations:
            return translations[0].get("translatedText", text)
        return text

    @property
    def cache_size(self) -> int:
        return len(self._cache)
