"""
fashionvoid-bot · notifications/telegram_alert.py
─────────────────────────────────────────────────────────────────────────────
Telegram Bot notification channel.

Sends rich listing cards via the Telegram Bot HTTP API (no library required,
uses httpx directly).  A background polling coroutine handles bot commands.

Config (config.yaml):
  alerts:
    telegram:
      enabled: true
      bot_token: "1234567890:AAF..."
      chat_id: "-100..."        # channel / group / user chat ID

Commands:
  /status    — show scraper status and listing counts
  /pause     — pause all scrapers
  /resume    — resume all scrapers
  /bookmarks — list your 5 most recent bookmarks
─────────────────────────────────────────────────────────────────────────────
"""

import asyncio
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_API = "https://api.telegram.org/bot{token}/{method}"

# Shipping costs mirrored from dashboard (EUR, NL destination)
_SHIPPING: dict = {
    "mercari_jp":     20.0,
    "yahoo_auctions": 20.0,
    "rakuma":         20.0,
    "bunjang":        20.0,
    "xianyu":         25.0,
    "vinted":         25.0,
    "vestiaire":      25.0,
}

_CONDITION_SCORES: dict = {
    "new with tags": 25, "new_with_tags": 25, "brandnew": 25,
    "like new": 20,      "like_new": 20,
    "very good": 18,
    "good": 15,
    "fair": 8,
    "poor": 3,
}

_PLATFORM_FLAGS: dict = {
    "mercari_jp":     "🇯🇵",
    "yahoo_auctions": "🇯🇵",
    "rakuma":         "🇯🇵",
    "bunjang":        "🇰🇷",
    "xianyu":         "🇨🇳",
    "vinted":         "🇪🇺",
    "vestiaire":      "🇫🇷",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _landed(listing: dict) -> Optional[float]:
    p = listing.get("price_eur")
    if p is None:
        return None
    shipping = _SHIPPING.get(listing.get("platform", ""), 20.0)
    return round(p + p * 0.21 + shipping, 2)


def _cond_score(listing: dict) -> int:
    cond = (listing.get("condition") or "").lower()
    for k, v in _CONDITION_SCORES.items():
        if k in cond:
            return v
    return 10


def _build_caption(listing: dict, db) -> str:
    title = listing.get("translated_title") or listing.get("title", "—")
    platform = listing.get("platform", "")
    flag = _PLATFORM_FLAGS.get(platform, "🌐")
    price_eur = listing.get("price_eur")
    total = _landed(listing)
    condition = listing.get("condition") or "—"
    group = listing.get("keyword_group", "—")
    is_susp = listing.get("is_suspicious", False)

    # Deal score
    price_pts = 0
    if price_eur and db:
        try:
            with db._conn() as conn:
                row = conn.execute(
                    "SELECT AVG(rolling_avg_eur) AS avg FROM keywords "
                    "WHERE group_name = ? AND platform = ? AND rolling_avg_eur IS NOT NULL",
                    (group, platform),
                ).fetchone()
            avg = row["avg"] if row and row["avg"] else None
            if avg and avg > 0 and price_eur < avg:
                price_pts = min(60, max(0, int((1 - price_eur / avg) * 60)))
        except Exception:
            pass
    cond_pts = _cond_score(listing)
    vision = listing.get("vision_score")
    vision_pts = int((vision / 100) * 15) if vision is not None else 0
    deal = min(100, price_pts + cond_pts + vision_pts + (10 if is_susp else 0))

    lines = [
        f"{flag} *{_esc(title)}*",
        "",
        f"💰 €{price_eur:.0f}" + (f"  →  🛬 €{total:.0f} landed" if total else ""),
        f"📦 {_esc(condition)}   ⭐ Deal score: {deal}/100",
        f"🔍 {_esc(group)}   🏪 {_esc(platform)}",
    ]
    if is_susp:
        lines.append("⚠️ *Suspiciously cheap*")

    return "\n".join(lines)


def _esc(text: str) -> str:
    """Escape MarkdownV2 special characters."""
    for ch in r"\_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text


def _inline_keyboard(listing: dict) -> dict:
    url = listing.get("url", "")
    lid = listing.get("id", "")
    platform = listing.get("platform", "")
    return {
        "inline_keyboard": [[
            {"text": "🔗 Open listing", "url": url},
            {"text": "🔖 Bookmark", "callback_data": f"bookmark:{lid}:{platform}"},
        ]]
    }


# ── Main class ────────────────────────────────────────────────────────────────

class TelegramAlert:
    """Telegram Bot notification sender + command handler."""

    def __init__(self, config: dict, db):
        self.db = db
        cfg = config.get("alerts", {}).get("telegram", {})
        self._token: str = cfg.get("bot_token", "")
        self._chat_id: str = str(cfg.get("chat_id", ""))
        self.enabled: bool = bool(
            cfg.get("enabled", False) and self._token and self._chat_id
        )
        self._last_update_id: int = 0

        if self.enabled:
            logger.info("[telegram] Bot ready — alerts enabled")
        else:
            logger.info("[telegram] Disabled — set alerts.telegram.enabled + bot_token + chat_id")

    # ── Internal API call ─────────────────────────────────────────────────

    async def _call(self, method: str, payload: dict) -> Optional[dict]:
        url = _API.format(token=self._token, method=method)
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(url, json=payload)
                r.raise_for_status()
                return r.json()
        except Exception as exc:
            logger.warning(f"[telegram] API call '{method}' failed: {exc}")
            return None

    # ── Public send ───────────────────────────────────────────────────────

    async def send(self, listing: dict) -> bool:
        """Send a listing card. Called by base_scraper._notify()."""
        if not self.enabled:
            return False
        if self.db.alert_already_sent(listing["id"], listing["platform"], "telegram"):
            return False

        caption = _build_caption(listing, self.db)
        keyboard = _inline_keyboard(listing)
        image_url = listing.get("image_url")

        if image_url:
            result = await self._call("sendPhoto", {
                "chat_id": self._chat_id,
                "photo": image_url,
                "caption": caption,
                "parse_mode": "MarkdownV2",
                "reply_markup": keyboard,
            })
        else:
            result = await self._call("sendMessage", {
                "chat_id": self._chat_id,
                "text": caption,
                "parse_mode": "MarkdownV2",
                "reply_markup": keyboard,
                "disable_web_page_preview": False,
            })

        ok = bool(result and result.get("ok"))
        self.db.log_alert(
            listing["id"], listing["platform"], "telegram",
            success=ok, error_msg=None if ok else str(result),
        )
        return ok

    # ── Command polling ───────────────────────────────────────────────────

    async def start_polling(
        self,
        run_gate: asyncio.Event,
        scheduler=None,
        stats_store: Optional[dict] = None,
    ) -> None:
        """
        Long-poll Telegram for updates and handle bot commands.
        Runs indefinitely as a background asyncio task.
        """
        if not self.enabled:
            return

        logger.info("[telegram] Starting command polling")
        while True:
            try:
                await self._poll_once(run_gate, scheduler, stats_store)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning(f"[telegram] Polling error: {exc}")
            await asyncio.sleep(2)

    async def _poll_once(self, run_gate, scheduler, stats_store) -> None:
        url = _API.format(token=self._token, method="getUpdates")
        payload = {"offset": self._last_update_id + 1, "timeout": 20, "limit": 10}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(url, json=payload)
                r.raise_for_status()
                data = r.json()
        except Exception:
            return

        for update in data.get("result", []):
            self._last_update_id = update["update_id"]

            # Handle inline button callbacks (bookmark toggle)
            if "callback_query" in update:
                await self._handle_callback(update["callback_query"])
                continue

            msg = update.get("message", {})
            text = (msg.get("text") or "").strip()
            chat_id = str(msg.get("chat", {}).get("id", ""))

            # Only respond to the configured chat
            if chat_id != self._chat_id:
                continue

            if text.startswith("/status"):
                await self._cmd_status(stats_store)
            elif text.startswith("/pause"):
                await self._cmd_pause(run_gate, scheduler)
            elif text.startswith("/resume"):
                await self._cmd_resume(run_gate, scheduler)
            elif text.startswith("/bookmarks"):
                await self._cmd_bookmarks()

    async def _handle_callback(self, cb: dict) -> None:
        data = cb.get("data", "")
        cb_id = cb.get("id", "")
        if data.startswith("bookmark:"):
            _, lid, platform = data.split(":", 2)
            new_state = self.db.toggle_bookmark(lid, platform)
            label = "Bookmarked" if new_state else "Bookmark removed"
            await self._call("answerCallbackQuery", {
                "callback_query_id": cb_id,
                "text": label,
                "show_alert": False,
            })

    async def _cmd_status(self, stats_store: Optional[dict]) -> None:
        if not stats_store:
            await self._send_text("No stats available yet\\.")
            return
        db_stats = self.db.stats()
        lines = [
            "*FashionVoid Status*",
            f"Total listings: {db_stats['total_listings']}",
            f"Suspicious: {db_stats['suspicious']}",
            f"Alerts sent: {db_stats['alerts_sent']}",
            "",
            "*Scrapers*",
        ]
        for name, s in stats_store.items():
            status_icon = "✅" if s["status"] == "OK" else ("❌" if s["status"] == "ERR" else "⏳")
            lines.append(
                f"{status_icon} {_esc(name)} — last: {_esc(s['last_run'])}  new: {s['new_found']}"
            )
        await self._send_text("\n".join(lines))

    async def _cmd_pause(self, run_gate: asyncio.Event, scheduler) -> None:
        run_gate.clear()
        await self._send_text("⏸ Scrapers *paused*\\.")

    async def _cmd_resume(self, run_gate: asyncio.Event, scheduler) -> None:
        run_gate.set()
        await self._send_text("▶️ Scrapers *resumed*\\.")

    async def _cmd_bookmarks(self) -> None:
        bookmarks = self.db.get_bookmarks()
        if not bookmarks:
            await self._send_text("No bookmarks yet\\.")
            return
        lines = ["*Your bookmarks*", ""]
        for b in bookmarks[:5]:
            title = b.get("translated_title") or b.get("title", "—")
            price = b.get("price_eur")
            url = b.get("url", "")
            price_str = f"€{price:.0f}" if price else "—"
            lines.append(f"• [{_esc(title)}]({url}) — {price_str}")
        if len(bookmarks) > 5:
            lines.append(f"_\\.\\.\\. and {len(bookmarks) - 5} more_")
        await self._send_text("\n".join(lines))

    async def _send_text(self, text: str) -> None:
        await self._call("sendMessage", {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": True,
        })
