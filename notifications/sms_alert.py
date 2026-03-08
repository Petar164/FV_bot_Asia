"""
fashionvoid-bot · notifications/sms_alert.py
─────────────────────────────────────────────────────────────────────────────
Twilio SMS + WhatsApp notifier.

Twilio's Python library is synchronous, so we wrap it in an executor.
Both channels (SMS and WhatsApp) are controlled independently in config.yaml.
─────────────────────────────────────────────────────────────────────────────
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

# SMS message template — kept concise for character limits
_SMS_TEMPLATE = """\
{suspicious}FashionVoid ·  {platform}
{title}
{price_eur} ({price_original})
{condition}
{url}"""


class SMSAlert:
    """Twilio SMS and WhatsApp alert sender."""

    def __init__(self, config: dict, db):
        self.cfg = config.get("alerts", {}).get("sms", {})
        self.db = db
        self.sms_enabled = self.cfg.get("enabled", False)
        self.wa_enabled = self.cfg.get("whatsapp_enabled", False)

        self._client = None
        if self.sms_enabled or self.wa_enabled:
            self._init_client()

    def _init_client(self):
        """Lazily initialise the Twilio REST client."""
        try:
            from twilio.rest import Client as TwilioClient
            self._client = TwilioClient(
                self.cfg["twilio_sid"],
                self.cfg["twilio_token"],
            )
            logger.info("[sms] Twilio client initialised")
        except ImportError:
            logger.error("[sms] twilio package not installed — pip install twilio")
        except Exception as exc:
            logger.error(f"[sms] Failed to init Twilio: {exc}")

    async def send(self, listing: dict) -> bool:
        """Send SMS and/or WhatsApp alert.  Returns True if at least one succeeded."""
        if not (self.sms_enabled or self.wa_enabled) or not self._client:
            return False

        body = self._format_body(listing)
        success = False

        if self.sms_enabled:
            if not self.db.alert_already_sent(listing["id"], listing["platform"], "sms"):
                ok = await asyncio.get_event_loop().run_in_executor(
                    None, self._send_sms, body
                )
                self.db.log_alert(
                    listing["id"], listing["platform"], "sms",
                    success=ok,
                    error_msg=None if ok else "Send failed",
                )
                success = success or ok

        if self.wa_enabled:
            if not self.db.alert_already_sent(listing["id"], listing["platform"], "whatsapp"):
                ok = await asyncio.get_event_loop().run_in_executor(
                    None, self._send_whatsapp, body
                )
                self.db.log_alert(
                    listing["id"], listing["platform"], "whatsapp",
                    success=ok,
                    error_msg=None if ok else "Send failed",
                )
                success = success or ok

        return success

    def _send_sms(self, body: str) -> bool:
        """Blocking Twilio SMS send."""
        try:
            msg = self._client.messages.create(
                body=body,
                from_=self.cfg["from_number"],
                to=self.cfg["to_number"],
            )
            logger.info(f"[sms] Sent — SID: {msg.sid}")
            return True
        except Exception as exc:
            logger.error(f"[sms] Send failed: {exc}")
            return False

    def _send_whatsapp(self, body: str) -> bool:
        """Blocking Twilio WhatsApp send."""
        try:
            msg = self._client.messages.create(
                body=body,
                from_=self.cfg["whatsapp_from"],
                to=self.cfg["whatsapp_to"],
            )
            logger.info(f"[whatsapp] Sent — SID: {msg.sid}")
            return True
        except Exception as exc:
            logger.error(f"[whatsapp] Send failed: {exc}")
            return False

    @staticmethod
    def _format_body(listing: dict) -> str:
        """Compose the SMS body string."""
        price_eur = listing.get("price_eur")
        price_eur_str = f"€{price_eur:,.0f}" if price_eur else "N/A"
        price_orig = f"{listing.get('price', 0):,.0f} {listing.get('currency', '')}"
        platform = listing.get("platform", "").replace("_", " ").upper()
        title = (
            listing.get("translated_title") or listing.get("title", "")
        )[:80]

        return _SMS_TEMPLATE.format(
            suspicious="⚠ SUSPICIOUS PRICE\n" if listing.get("is_suspicious") else "",
            platform=platform,
            title=title,
            price_eur=price_eur_str,
            price_original=price_orig,
            condition=listing.get("condition") or "Condition unknown",
            url=listing.get("url", ""),
        ).strip()
