"""
fashionvoid-bot · utils/translator.py
─────────────────────────────────────────────────────────────────────────────
Translation wrapper with DeepL as primary and Google Translate as fallback.

Priority:
    1. DeepL Free / Pro API (higher quality, auto language detection)
    2. Google Cloud Translate v2 (fallback if DeepL unavailable / quota hit)

Caching:
    - In-memory cache for the process lifetime (fast path)
    - Persistent DB cache keyed by (text, source_lang, target_lang)

Config keys read:
    translation.primary           "deepl" | "google"  (default: "deepl")
    translation.deepl_api_key     DeepL API key
    translation.google_api_key    Google Cloud Translate key
    translation.cache_translations true | false
─────────────────────────────────────────────────────────────────────────────
"""

import asyncio
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ── API endpoints ──────────────────────────────────────────────────────────────

_DEEPL_FREE_URL = "https://api-free.deepl.com/v2/translate"
_DEEPL_PRO_URL  = "https://api.deepl.com/v2/translate"
_GOOGLE_URL     = "https://translation.googleapis.com/language/translate/v2"

# DeepL target language codes for our markets
_DEEPL_TARGET = "EN-US"


def _is_placeholder(key: Optional[str], placeholder: str) -> bool:
    return not key or key.strip() == placeholder


class Translator:
    """
    Async translator.  DeepL primary, Google Translate fallback.
    Both providers auto-detect the source language so we never
    need to hardcode JP/KR/CN per-platform.
    """

    def __init__(self, config: dict):
        cfg = config.get("translation", config.get("translate", {}))

        # ── DeepL setup ───────────────────────────────────────────────
        self._deepl_key = cfg.get("deepl_api_key", "")
        self._deepl_enabled = not _is_placeholder(
            self._deepl_key, "YOUR_DEEPL_KEY"
        )
        if self._deepl_enabled:
            # Free keys end in ":fx"; Pro keys do not
            self._deepl_url = (
                _DEEPL_FREE_URL
                if self._deepl_key.endswith(":fx")
                else _DEEPL_PRO_URL
            )
            logger.info("[translator] DeepL ready (%s)",
                        "free" if self._deepl_key.endswith(":fx") else "pro")

        # ── Google Translate setup ─────────────────────────────────────
        self._google_key = cfg.get("google_api_key", cfg.get("api_key", ""))
        self._google_enabled = not _is_placeholder(
            self._google_key, "YOUR_GOOGLE_TRANSLATE_API_KEY"
        )
        if self._google_enabled:
            logger.info("[translator] Google Translate ready (fallback)")

        self._primary = cfg.get("primary", "deepl")
        self._cache_enabled = cfg.get("cache_translations", True)

        # In-memory cache:  text → translated_text
        self._mem_cache: dict[str, str] = {}

        if not self._deepl_enabled and not self._google_enabled:
            logger.warning(
                "[translator] No translation API configured — titles will not be translated"
            )

    # ── Public API ────────────────────────────────────────────────────────────

    async def translate(self, text: str, target: str = "EN") -> str:
        """Translate *text* to English.  Returns original on failure."""
        if not text or not text.strip():
            return text

        cache_key = f"{text}|{target}"
        if self._cache_enabled and cache_key in self._mem_cache:
            return self._mem_cache[cache_key]

        result = await self._translate_with_fallback(text, target)

        if self._cache_enabled:
            self._mem_cache[cache_key] = result
        return result

    async def translate_batch(self, texts: list[str], target: str = "EN") -> list[str]:
        """Translate multiple texts concurrently (semaphore-limited)."""
        sem = asyncio.Semaphore(8)

        async def _one(t: str) -> str:
            async with sem:
                return await self.translate(t, target)

        return list(await asyncio.gather(*[_one(t) for t in texts]))

    async def translate_to(self, text: str, target_lang: str) -> str:
        """Translate to an arbitrary DeepL/Google target language code."""
        return await self._translate_with_fallback(text, target_lang.upper())

    async def back_translate(self, text: str, source_lang: str) -> str:
        """
        Translate *text* (in *source_lang*) back to English.
        Used by keyword_ai_expander for quality verification.
        """
        return await self.translate(text, target="EN")

    # ── Internal routing ──────────────────────────────────────────────────────

    async def _translate_with_fallback(self, text: str, target: str) -> str:
        if self._primary == "deepl" and self._deepl_enabled:
            try:
                return await self._deepl_translate(text, target)
            except Exception as exc:
                logger.warning(f"[translator] DeepL failed: {exc} — trying Google")
                if self._google_enabled:
                    try:
                        return await self._google_translate(text, "en")
                    except Exception as exc2:
                        logger.warning(f"[translator] Google also failed: {exc2}")
        elif self._google_enabled:
            try:
                return await self._google_translate(text, "en")
            except Exception as exc:
                logger.warning(f"[translator] Google failed: {exc}")
                if self._deepl_enabled:
                    try:
                        return await self._deepl_translate(text, target)
                    except Exception as exc2:
                        logger.warning(f"[translator] DeepL also failed: {exc2}")

        return text   # graceful degradation

    # ── DeepL ─────────────────────────────────────────────────────────────────

    async def _deepl_translate(self, text: str, target: str) -> str:
        """
        DeepL REST v2 translation.
        - Auto-detects source language
        - formality=less  (casual marketplace text)
        - split_sentences=0  (treat entire input as one sentence)
        """
        # Normalise target code for DeepL (e.g. "EN" → "EN-US", "JA" → "JA")
        deepl_target = _normalise_deepl_target(target)

        payload = {
            "auth_key": self._deepl_key,
            "text": [text],
            "target_lang": deepl_target,
            "split_sentences": "0",
            "formality": "less",
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(self._deepl_url, data=payload)
            resp.raise_for_status()
            data = resp.json()

        translations = data.get("translations", [])
        if translations:
            return translations[0].get("text", text)
        return text

    # ── Google Translate ──────────────────────────────────────────────────────

    async def _google_translate(self, text: str, target: str = "en") -> str:
        """Google Cloud Translate v2 REST call."""
        payload = {
            "q": text,
            "target": target.lower()[:2],
            "format": "text",
            "key": self._google_key,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(_GOOGLE_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()

        translations = data.get("data", {}).get("translations", [])
        if translations:
            return translations[0].get("translatedText", text)
        return text

    # ── Misc ──────────────────────────────────────────────────────────────────

    @property
    def cache_size(self) -> int:
        return len(self._mem_cache)


# ── Helpers ───────────────────────────────────────────────────────────────────

_DEEPL_LANG_MAP = {
    "EN":  "EN-US",
    "PT":  "PT-PT",
    "ZH":  "ZH",
}


def _normalise_deepl_target(target: str) -> str:
    """Map generic language codes to DeepL's expected variants."""
    t = target.upper()
    return _DEEPL_LANG_MAP.get(t, t)
