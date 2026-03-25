"""
fashionvoid-bot · utils/vision_filter.py
─────────────────────────────────────────────────────────────────────────────
GPT-4o vision filter for listing images.

Scores each new listing image 0–100 for how likely it is to match the
keyword group description. Used in base_scraper.run() to route alerts:

  score >= min_confidence (default 70)   → all channels (push + email + sms)
  score >= priority_threshold (default 50) → email only
  score <  priority_threshold             → no alert (listing still stored in DB)
  no image_url or vision disabled         → all channels (no filter applied)

Config keys read:
  openai.api_key
  openai.vision_model        (default: gpt-4o)
  openai.vision_enabled      (default: true)
  openai.min_confidence      (default: 70)
  openai.priority_threshold  (default: 50)
─────────────────────────────────────────────────────────────────────────────
"""

import json
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_OPENAI_URL = "https://api.openai.com/v1/chat/completions"

_PROMPT = """\
You are a fashion expert assisting with secondhand marketplace authentication.
Looking at this product listing image, rate from 0 to 100 how likely it is that \
this item matches the following search: "{description}".

Consider:
- Is this the correct item type and category?
- Does the brand era and silhouette match the description?
- Does the item appear genuine rather than a replica or counterfeit?
- Is the image clear enough to judge? (placeholder or unrelated image = low score)

Score guide: 0-30 = wrong item or unrelated, 31-60 = possible match, 61-100 = clear match.

Return JSON only: {{"score": <0-100>, "reason": "<one sentence>"}}"""


class VisionFilter:
    """GPT-4o vision-based listing image scorer."""

    def __init__(self, config: dict):
        cfg = config.get("openai", {})
        self._api_key = cfg.get("api_key", "")
        self._enabled = (
            bool(self._api_key)
            and self._api_key != "YOUR_OPENAI_KEY"
            and cfg.get("vision_enabled", True)
        )
        self._model = cfg.get("vision_model", "gpt-4o")
        self.min_confidence = int(cfg.get("min_confidence", 70))
        self.priority_threshold = int(cfg.get("priority_threshold", 50))

        if self._enabled:
            logger.info(
                f"[vision] GPT-4o vision filter ready — model={self._model}  "
                f"min_confidence={self.min_confidence}  "
                f"priority_threshold={self.priority_threshold}"
            )
        else:
            logger.info("[vision] Vision filter disabled — no API key or vision_enabled=false")

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def score(self, listing: dict) -> Optional[int]:
        """
        Score a listing image 0-100 against its keyword group description.
        Returns None if vision is disabled, no image_url, or the API call fails.
        None means the caller should treat the listing as passing (no filter applied).
        """
        if not self._enabled:
            return None

        image_url = listing.get("image_url")
        if not image_url:
            return None

        description = listing.get("keyword_group", "fashion item")
        prompt = _PROMPT.format(description=description)

        try:
            result = await self._call_vision(prompt, image_url)
            logger.debug(
                f"[vision] {listing.get('platform')} {str(listing.get('id', ''))[:16]} "
                f"— score={result}  group='{description}'"
            )
            return result
        except Exception as exc:
            logger.warning(f"[vision] Score failed for {listing.get('id')}: {exc}")
            return None

    async def _call_vision(self, prompt: str, image_url: str) -> Optional[int]:
        """Call GPT-4o vision API with the image URL directly."""
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": image_url, "detail": "low"},
                        },
                    ],
                }
            ],
            "max_tokens": 100,
            "response_format": {"type": "json_object"},
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(_OPENAI_URL, headers=headers, json=body)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            data = json.loads(content)

        score = data.get("score")
        if score is None:
            return None
        return max(0, min(100, int(score)))
