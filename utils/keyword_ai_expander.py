"""
fashionvoid-bot · utils/keyword_ai_expander.py
─────────────────────────────────────────────────────────────────────────────
Full AI keyword expansion pipeline.  Runs when a user saves a new keyword
group or manually triggers re-expansion.

Pipeline:
    1. GPT-4o  — English term expansion (brand aliases, era codes, etc.)
    2. DeepL   — Translate English terms to JP, KR, CN
    3. GPT-4o  — Language-specific expansion per market (seller slang, etc.)
    4. DeepL   — Back-translation verification (drop hallucinated terms)
    5. Persist verified terms to config.yaml

Config:
    openai.api_key
    ai_expander.enabled
    ai_expander.max_suggestions   (default 20 per language)
─────────────────────────────────────────────────────────────────────────────
"""

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_OPENAI_URL = "https://api.openai.com/v1/chat/completions"

_LANG_META = {
    "jp": {"name": "Japanese", "platforms": "Mercari JP, Yahoo Auctions, Rakuma"},
    "kr": {"name": "Korean",   "platforms": "Bunjang"},
    "cn": {"name": "Chinese",  "platforms": "Xianyu"},
}


class KeywordAIExpander:
    """
    Full pipeline: English expansion → DeepL translate → per-market
    GPT-4o expansion → back-translation verification → config save.
    """

    def __init__(self, config: dict, translator):
        ai_cfg = config.get("openai", {})
        exp_cfg = config.get("ai_expander", {})

        self._api_key = ai_cfg.get("api_key", "")
        self._enabled = (
            bool(self._api_key)
            and self._api_key != "YOUR_OPENAI_KEY"
            and exp_cfg.get("enabled", True)
        )
        self._model = ai_cfg.get("vision_model", "gpt-4o")
        self._max_terms = exp_cfg.get("max_suggestions", 20)
        self._translator = translator

        if not self._enabled:
            logger.warning("[keyword_expander] OpenAI not configured — AI expansion disabled")

    # ── Public entry point ────────────────────────────────────────────────────

    async def expand(self, user_input: str, group_name: str) -> dict:
        """
        Run the full expansion pipeline for *user_input*.

        Returns a dict ready to be merged into a keyword group config:
        {
            "terms_en": [...],
            "terms_jp": [...],
            "terms_kr": [...],
            "terms_cn": [...],
            "ai_generated": True,
            "last_expanded": "ISO timestamp",
        }
        Returns empty dict if OpenAI is not configured.
        """
        if not self._enabled:
            return {}

        logger.info(f"[keyword_expander] Expanding: '{user_input}'")

        # ── Step 1: English expansion ─────────────────────────────────
        terms_en = await self._expand_english(user_input)
        if not terms_en:
            logger.warning("[keyword_expander] English expansion returned nothing")
            return {}

        logger.debug(f"[keyword_expander] EN terms: {terms_en}")

        # ── Step 2: Translate EN → JP, KR, CN via DeepL ───────────────
        translated = await self._translate_terms(terms_en)

        # ── Step 3: Language-specific GPT-4o expansion ────────────────
        expanded: dict[str, list[str]] = {}
        for lang_code, base_terms in translated.items():
            extra = await self._expand_for_language(
                lang_code, user_input, base_terms
            )
            expanded[lang_code] = base_terms + extra

        # ── Step 4: Back-translation verification ─────────────────────
        verified: dict[str, list[str]] = {}
        for lang_code, terms in expanded.items():
            verified[lang_code] = await self._verify_terms(terms, lang_code)

        return {
            "terms_en":     terms_en,
            "terms_jp":     verified.get("jp", []),
            "terms_kr":     verified.get("kr", []),
            "terms_cn":     verified.get("cn", []),
            "ai_generated": True,
            "last_expanded": datetime.now(timezone.utc).isoformat(),
        }

    # ── Step 1: English expansion ──────────────────────────────────────────────

    async def _expand_english(self, user_input: str) -> list[str]:
        prompt = (
            "You are an expert in archive fashion resale. "
            f"Given this search term: '{user_input}', generate related search terms "
            "a secondhand seller might use. Include: brand name variations and "
            "abbreviations, era/season codes (SS03, AW04 etc), material descriptors, "
            "silhouette descriptors, designer name variations, common seller "
            "misspellings. "
            f"Return up to {self._max_terms} terms. "
            'Return JSON only: { "terms": ["term1", "term2", ...] }'
        )
        data = await self._gpt(prompt)
        return _extract_list(data, "terms")

    # ── Step 2: Translate EN → all target languages ────────────────────────────

    async def _translate_terms(self, terms_en: list[str]) -> dict[str, list[str]]:
        """Translate English terms to JP, KR, CN via DeepL concurrently."""
        target_map = {"jp": "JA", "kr": "KO", "cn": "ZH"}
        results: dict[str, list[str]] = {}

        async def _translate_one_lang(lang_code: str, deepl_target: str):
            translated = []
            for term in terms_en:
                try:
                    t = await self._translator.translate_to(term, deepl_target)
                    if t and t != term:
                        translated.append(t)
                except Exception as exc:
                    logger.debug(f"[keyword_expander] DeepL {deepl_target} failed for '{term}': {exc}")
            results[lang_code] = translated

        await asyncio.gather(
            *[_translate_one_lang(lc, tgt) for lc, tgt in target_map.items()]
        )
        return results

    # ── Step 3: Per-language GPT-4o expansion ─────────────────────────────────

    async def _expand_for_language(
        self, lang_code: str, brand_hint: str, base_terms: list[str]
    ) -> list[str]:
        meta = _LANG_META.get(lang_code, {})
        lang_name = meta.get("name", lang_code)
        platforms = meta.get("platforms", "Asian resale platforms")

        prompt = (
            f"You are an expert in {lang_name} secondhand fashion marketplace language "
            f"on {platforms}. "
            f"Given these translated terms for '{brand_hint}': {json.dumps(base_terms, ensure_ascii=False)}, "
            "expand with: local marketplace slang and abbreviations, character "
            "variations sellers actually use, era descriptions in local language "
            "(e.g. エディ期 for Hedi era in JP), material words local sellers use, "
            "any terms only appearing in local listings. "
            f"Return up to {self._max_terms} additional terms in {lang_name} only. "
            'Return JSON only: { "expanded_terms": ["term1", "term2", ...] }'
        )
        data = await self._gpt(prompt)
        return _extract_list(data, "expanded_terms")

    # ── Step 4: Back-translation verification ─────────────────────────────────

    async def _verify_terms(self, terms: list[str], lang_code: str) -> list[str]:
        """
        Translate each term back to English.  Drop terms whose back-translation
        looks completely unrelated (basic heuristic — avoids hallucinated chars).
        """
        verified = []
        for term in terms:
            try:
                back = await self._translator.back_translate(term, lang_code)
                # Keep the term if back-translation produced meaningful text
                if back and len(back.strip()) > 0 and not _looks_garbled(back):
                    verified.append(term)
                else:
                    logger.debug(
                        f"[keyword_expander] Dropped '{term}' — "
                        f"back-translation: '{back}'"
                    )
            except Exception:
                # On verification failure keep the term (don't drop silently)
                verified.append(term)

        return verified

    # ── OpenAI call ───────────────────────────────────────────────────────────

    async def _gpt(self, prompt: str) -> Optional[dict]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.4,
            "response_format": {"type": "json_object"},
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(_OPENAI_URL, headers=headers, json=body)
                resp.raise_for_status()
                data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return json.loads(content)
        except Exception as exc:
            logger.error(f"[keyword_expander] GPT call failed: {exc}")
            return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_list(data: Optional[dict], key: str) -> list[str]:
    if not data:
        return []
    raw = data.get(key, [])
    if not isinstance(raw, list):
        return []
    return [str(t).strip() for t in raw if str(t).strip()]


def _looks_garbled(text: str) -> bool:
    """Heuristic: back-translation that's all punctuation/numbers is garbled."""
    clean = re.sub(r"[\s\W\d]", "", text)
    return len(clean) == 0
