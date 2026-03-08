"""
fashionvoid-bot · utils/proxy_manager.py
─────────────────────────────────────────────────────────────────────────────
Rotating proxy pool manager.

Supports two modes:
  1. Rotation URL  — single endpoint that returns a fresh proxy on each call
     (Webshare, Oxylabs, Brightdata "super-proxy" style)
  2. Static list   — round-robin through a list of proxies defined in config

If proxies are disabled, `get_proxy()` returns None and scrapers connect
directly.
─────────────────────────────────────────────────────────────────────────────
"""

import itertools
import logging
import random
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class ProxyManager:
    """Manages a pool of HTTP proxies with rotation."""

    def __init__(self, config: dict):
        cfg = config.get("proxies", {})
        self.enabled = cfg.get("enabled", False)

        self._rotation_url = cfg.get("rotation_url", "")
        self._username = cfg.get("username", "")
        self._password = cfg.get("password", "")
        self._static_list = cfg.get("static_list", [])

        # Round-robin iterator for static proxies
        self._cycle = itertools.cycle(self._static_list) if self._static_list else None

        # Track failed proxies to temporarily skip them
        self._failed: dict[str, float] = {}     # proxy_url → unix timestamp of failure
        self._cooldown_sec = 120                 # 2-minute cooldown after failure

        if self.enabled:
            mode = "rotation URL" if self._rotation_url else f"{len(self._static_list)} static"
            logger.info(f"[proxy] Enabled — mode: {mode}")
        else:
            logger.info("[proxy] Disabled — direct connections")

    def get_proxy(self) -> Optional[str]:
        """
        Return the next proxy URL to use, or None if proxies are disabled.
        Format returned: http://user:pass@host:port
        """
        if not self.enabled:
            return None

        if self._rotation_url:
            return self._get_rotation_proxy()
        elif self._cycle:
            return self._get_static_proxy()
        return None

    def mark_failed(self, proxy_url: str) -> None:
        """
        Mark a proxy as failed — it will be skipped for `_cooldown_sec`.
        Call this when a request through the proxy fails.
        """
        self._failed[proxy_url] = time.time()
        logger.warning(f"[proxy] Marked failed: {self._redact(proxy_url)}")

    def mark_success(self, proxy_url: str) -> None:
        """Clear a proxy from the failed list on success."""
        self._failed.pop(proxy_url, None)

    # ── Rotation URL mode ─────────────────────────────────────────────────

    def _get_rotation_proxy(self) -> str:
        """
        For rotation URL services (e.g. Webshare):
        The URL itself acts as the proxy — each connection gets a fresh IP.
        Optionally inject credentials if the URL contains placeholders.
        """
        url = self._rotation_url
        if "{username}" in url:
            url = url.replace("{username}", self._username)
        if "{password}" in url:
            url = url.replace("{password}", self._password)
        return url

    # ── Static list mode ──────────────────────────────────────────────────

    def _get_static_proxy(self) -> Optional[str]:
        """Round-robin through static proxies, skipping cooled-down ones."""
        now = time.time()
        tries = len(self._static_list)

        for _ in range(tries):
            proxy = next(self._cycle)
            failed_at = self._failed.get(proxy)
            if failed_at and (now - failed_at) < self._cooldown_sec:
                continue   # still in cooldown — skip
            return proxy

        # All proxies in cooldown — pick least-recently-failed
        if self._failed and self._static_list:
            return min(self._static_list, key=lambda p: self._failed.get(p, 0))

        return None

    # ── Health check ──────────────────────────────────────────────────────

    async def check_health(self) -> dict[str, bool]:
        """
        Ping each static proxy against httpbin.org/ip.
        Returns {proxy_url: is_healthy}.
        """
        results = {}
        for proxy in self._static_list:
            results[proxy] = await self._ping_proxy(proxy)
        return results

    async def _ping_proxy(self, proxy_url: str) -> bool:
        """Test a single proxy against a neutral endpoint."""
        try:
            proxies = {"http://": proxy_url, "https://": proxy_url}
            async with httpx.AsyncClient(proxies=proxies, timeout=8.0) as client:
                resp = await client.get("https://httpbin.org/ip")
                resp.raise_for_status()
            return True
        except Exception:
            return False

    @staticmethod
    def _redact(proxy_url: str) -> str:
        """Redact credentials from proxy URL for safe logging."""
        import re
        return re.sub(r"://[^@]+@", "://***@", proxy_url)
