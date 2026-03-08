"""
fashionvoid-bot · utils/keyword_suggester.py
─────────────────────────────────────────────────────────────────────────────
Lightweight real-time keyword suggester.

Fires while the user is typing in the UI (debounced at 600 ms).
Faster than the full KeywordAIExpander — max 6 suggestions, no save.

Flow:
    1. GPT-4o generates up to 6 JP/KR/CN suggestions with metadata
    2. DeepL back-translates each to verify (drops hallucinated chars)
    3. Returns verified suggestions array to the caller (UI / IPC bridge)

Each suggestion shape:
    {
        "term":            str,   # JP/KR/CN text
        "language":        str,   # "jp" | "kr" | "cn"
        "english_meaning": str,   # rough translation (≤5 words)
        "context":         str,   # one of the 6 context labels
    }
─────────────────────────────────────────────────────────────────────────────
"""

import asyncio
import json
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_OPENAI_URL = "https://api.openai.com/v1/chat/completions"

_VALID_CONTEXTS = {
    "direct translation",
    "seller slang",
    "era reference",
    "material descriptor",
    "style descriptor",
    "brand abbreviation",
}


class KeywordSuggester:
    """
    Lightweight real-time suggester for the UI keyword input.
    Returns up to 6 verified suggestions without saving anything.
    """

    def __init__(self, config: dict, translator):
        ai_cfg = config.get("openai", {})
        exp_cfg = config.get("ai_expander", {})

        self._api_key = ai_cfg.get("api_key", "")
        self._enabled = (
            bool(self._api_key)
            and self._api_key != "YOUR_OPENAI_KEY"
        )
        self._model = ai_cfg.get("vision_model", "gpt-4o")
        self._max = exp_cfg.get("max_suggestions", 6)
        self._translator = translator

    # ── Public API ────────────────────────────────────────────────────────────

    async def suggest(self, typed_input: str) -> list[dict]:
        """
        Return up to *max* verified suggestions for *typed_input*.
        Safe to call from asyncio context (Electron IPC → subprocess).
        """
        if not self._enabled or len(typed_input.strip()) < 3:
            return []

        raw = await self._ask_gpt(typed_input)
        if not raw:
            return []

        verified = await self._verify(raw)
        return verified[:self._max]

    # ── GPT call ──────────────────────────────────────────────────────────────

    async def _ask_gpt(self, typed_input: str) -> list[dict]:
        prompt = (
            "You are an expert in Japanese, Korean and Chinese secondhand "
            "fashion marketplace language. The user is searching for: "
            f"'{typed_input}'.\n"
            f"Generate up to {self._max} search terms that sellers would actually "
            "use on Mercari JP, Yahoo Auctions, Rakuma, Bunjang, or Xianyu.\n"
            "For each term return:\n"
            "  term: the JP/KR/CN text\n"
            "  language: jp / kr / cn\n"
            "  english_meaning: rough translation (max 5 words)\n"
            "  context: one of 'direct translation' / 'seller slang' / "
            "'era reference' / 'material descriptor' / "
            "'style descriptor' / 'brand abbreviation'\n"
            'Return JSON only: { "suggestions": [ { "term": "...", "language": "jp", '
            '"english_meaning": "...", "context": "..." }, ... ] }'
        )

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "response_format": {"type": "json_object"},
        }

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(_OPENAI_URL, headers=headers, json=body)
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                data = json.loads(content)
                return data.get("suggestions", [])
        except Exception as exc:
            logger.warning(f"[keyword_suggester] GPT call failed: {exc}")
            return []

    # ── Verification ──────────────────────────────────────────────────────────

    async def _verify(self, suggestions: list[dict]) -> list[dict]:
        """
        Back-translate each suggestion's term via DeepL.
        Drop any that back-translate to empty / clearly wrong text.
        """
        verified = []

        async def _check(s: dict) -> Optional[dict]:
            term = s.get("term", "").strip()
            if not term:
                return None
            try:
                back = await self._translator.back_translate(term, s.get("language", "jp"))
                if back and len(back.strip()) > 1:
                    # Normalise context label
                    ctx = s.get("context", "direct translation").lower().strip()
                    if ctx not in _VALID_CONTEXTS:
                        ctx = "direct translation"
                    return {
                        "term":            term,
                        "language":        s.get("language", "jp"),
                        "english_meaning": (s.get("english_meaning") or back)[:40],
                        "context":         ctx,
                    }
            except Exception:
                pass
            return None

        results = await asyncio.gather(*[_check(s) for s in suggestions])
        return [r for r in results if r is not None]
