"""
fashionvoid-bot · notifications/push_alert.py
─────────────────────────────────────────────────────────────────────────────
ntfy.sh desktop / mobile push notification sender.

ntfy.sh is a free, open-source push service — no account required for
the public server (rate-limited).  Self-host for unlimited use.

API: HTTP POST to https://ntfy.sh/<topic>
Headers control the title, priority, tags, and click action (URL).
─────────────────────────────────────────────────────────────────────────────
"""

import logging

import httpx

logger = logging.getLogger(__name__)

# ntfy priority levels
_PRIORITY_MAP = {
    "min": "1",
    "low": "2",
    "default": "3",
    "high": "4",
    "urgent": "5",
    "max": "5",
}


class PushAlert:
    """ntfy.sh push notification sender."""

    def __init__(self, config: dict, db):
        self.cfg = config.get("alerts", {}).get("push", {})
        self.db = db
        self.enabled = self.cfg.get("enabled", False)

        self._server = self.cfg.get("ntfy_server", "https://ntfy.sh").rstrip("/")
        self._topic = self.cfg.get("ntfy_topic", "fashionvoid-alerts")
        self._priority = _PRIORITY_MAP.get(
            self.cfg.get("priority", "high"), "4"
        )
        self._endpoint = f"{self._server}/{self._topic}"

    async def send(self, listing: dict) -> bool:
        """POST a push notification for *listing* to ntfy.sh."""
        if not self.enabled:
            return False

        if self.db.alert_already_sent(listing["id"], listing["platform"], "push"):
            return False

        title = self._build_title(listing)
        body = self._build_body(listing)
        tags = self._build_tags(listing)

        headers = {
            "Title": title.encode("utf-8"),
            "Priority": self._priority,
            "Tags": ",".join(tags),
            "Click": listing.get("url", ""),
            "Content-Type": "text/plain; charset=utf-8",
        }

        # Attach image if available (ntfy shows inline attachment previews)
        image_url = listing.get("image_url")
        if image_url:
            headers["Attach"] = image_url

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    self._endpoint,
                    content=body.encode("utf-8"),
                    headers={
                        k: v if isinstance(v, str) else v.decode()
                        for k, v in headers.items()
                    },
                )
                response.raise_for_status()

            self.db.log_alert(listing["id"], listing["platform"], "push", success=True)
            logger.info(
                f"[push] Sent '{title[:50]}' → {self._endpoint}"
            )
            return True

        except Exception as exc:
            logger.error(f"[push] Failed: {exc}")
            self.db.log_alert(
                listing["id"], listing["platform"], "push",
                success=False, error_msg=str(exc)
            )
            return False

    @staticmethod
    def _build_title(listing: dict) -> str:
        """Short title for the push notification."""
        platform = listing.get("platform", "").replace("_", " ").upper()
        price_eur = listing.get("price_eur")
        price_str = f"€{price_eur:,.0f}" if price_eur else ""
        suspicious = "⚠ " if listing.get("is_suspicious") else ""
        return f"{suspicious}[{platform}] {price_str}"

    @staticmethod
    def _build_body(listing: dict) -> str:
        """Multi-line body text for the push notification."""
        price_eur = listing.get("price_eur")
        price_eur_str = f"€{price_eur:,.0f}" if price_eur else "N/A"
        price_orig = f"{listing.get('price', 0):,.0f} {listing.get('currency', '')}"
        title = (listing.get("translated_title") or listing.get("title", ""))[:100]
        condition = listing.get("condition") or "—"

        lines = [title, f"{price_eur_str} · {price_orig}", f"Condition: {condition}"]
        if listing.get("is_suspicious"):
            lines.insert(0, "⚠ SUSPICIOUS PRICE — verify authenticity!")
        return "\n".join(lines)

    @staticmethod
    def _build_tags(listing: dict) -> list[str]:
        """ntfy emoji tags that appear as icons in the notification."""
        tags = ["shopping_bags"]
        platform = listing.get("platform", "")
        if "jp" in platform:
            tags.append("jp")
        elif "bunjang" in platform:
            tags.append("kr")
        elif "xianyu" in platform:
            tags.append("cn")
        if listing.get("is_suspicious"):
            tags.append("warning")
        return tags
