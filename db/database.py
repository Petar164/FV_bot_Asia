"""
fashionvoid-bot · db/database.py
─────────────────────────────────────────────────────────────────────────────
SQLite persistence layer.  No ORM — pure sqlite3 for zero overhead.

Tables
──────
  listings        — every unique listing discovered across all platforms
  keywords        — keyword groups loaded from config (for rolling averages)
  alerts          — audit trail of every notification sent
  price_history   — one row per (listing_id, scraped_at) for trend tracking
─────────────────────────────────────────────────────────────────────────────
"""

import sqlite3
import logging
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ─── Schema ──────────────────────────────────────────────────────────────────

_DDL = """
-- ── listings ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS listings (
    id               TEXT    NOT NULL,          -- platform-native listing ID
    platform         TEXT    NOT NULL,          -- mercari_jp | yahoo_auctions | …
    title            TEXT    NOT NULL,          -- original title (JP/KR/CN)
    translated_title TEXT,                      -- English translation
    price            REAL    NOT NULL,          -- price in original currency
    currency         TEXT    NOT NULL,          -- JPY | KRW | CNY
    price_eur        REAL,                      -- converted to EUR at scrape time
    url              TEXT    NOT NULL,
    image_url        TEXT,
    condition        TEXT,                      -- as listed on platform
    keyword_group    TEXT,                      -- matched keyword group name
    is_suspicious    INTEGER NOT NULL DEFAULT 0,-- 1 = suspiciously cheap
    first_seen       TEXT    NOT NULL,          -- ISO-8601 timestamp
    last_seen        TEXT    NOT NULL,          -- ISO-8601 timestamp
    PRIMARY KEY (id, platform)
);

-- ── keywords ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS keywords (
    group_name       TEXT    NOT NULL,
    term             TEXT    NOT NULL,
    platform         TEXT    NOT NULL,
    rolling_avg_eur  REAL,                      -- rolling average price in EUR
    sample_count     INTEGER NOT NULL DEFAULT 0,
    updated_at       TEXT    NOT NULL,
    PRIMARY KEY (group_name, term, platform)
);

-- ── alerts ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS alerts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id       TEXT    NOT NULL,
    platform         TEXT    NOT NULL,
    channel          TEXT    NOT NULL,          -- email | sms | whatsapp | push
    sent_at          TEXT    NOT NULL,
    success          INTEGER NOT NULL DEFAULT 1,
    error_msg        TEXT
);

-- ── price_history ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS price_history (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id       TEXT    NOT NULL,
    platform         TEXT    NOT NULL,
    price            REAL    NOT NULL,
    currency         TEXT    NOT NULL,
    price_eur        REAL,
    scraped_at       TEXT    NOT NULL
);

-- ── indices ───────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_listings_platform   ON listings (platform);
CREATE INDEX IF NOT EXISTS idx_listings_group      ON listings (keyword_group);
CREATE INDEX IF NOT EXISTS idx_listings_first_seen ON listings (first_seen);
CREATE INDEX IF NOT EXISTS idx_price_history_lid   ON price_history (listing_id, platform);
CREATE INDEX IF NOT EXISTS idx_alerts_listing      ON alerts (listing_id, platform);
"""


# ─── Database Class ───────────────────────────────────────────────────────────

class Database:
    """Thread-safe SQLite wrapper for the FashionVoid monitor."""

    def __init__(self, db_path: str = "fashionvoid.db"):
        self.db_path = Path(db_path)
        self._init_db()
        logger.info(f"Database ready → {self.db_path.resolve()}")

    # ── Connection management ─────────────────────────────────────────────

    @contextmanager
    def _conn(self):
        """Yield a connection with WAL mode for concurrent reads."""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        """Create all tables and indices if they don't exist."""
        with self._conn() as conn:
            conn.executescript(_DDL)

    # ── Listings ──────────────────────────────────────────────────────────

    def listing_exists(self, listing_id: str, platform: str) -> bool:
        """Return True if we have already stored this listing."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM listings WHERE id = ? AND platform = ?",
                (listing_id, platform),
            ).fetchone()
            return row is not None

    def insert_listing(self, listing: dict) -> None:
        """
        Insert a new listing.  Expects the dict returned by scraper.search().
        Also appends a price_history row.
        """
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO listings
                    (id, platform, title, translated_title, price, currency,
                     price_eur, url, image_url, condition, keyword_group,
                     is_suspicious, first_seen, last_seen)
                VALUES
                    (:id, :platform, :title, :translated_title, :price, :currency,
                     :price_eur, :url, :image_url, :condition, :keyword_group,
                     :is_suspicious, :first_seen, :last_seen)
                """,
                {
                    **listing,
                    "is_suspicious": int(listing.get("is_suspicious", False)),
                    "first_seen": now,
                    "last_seen": now,
                },
            )
            conn.execute(
                """
                INSERT INTO price_history
                    (listing_id, platform, price, currency, price_eur, scraped_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    listing["id"],
                    listing["platform"],
                    listing["price"],
                    listing["currency"],
                    listing.get("price_eur"),
                    now,
                ),
            )

    def update_last_seen(self, listing_id: str, platform: str) -> None:
        """Bump last_seen timestamp for a listing we already know about."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE listings SET last_seen = ? WHERE id = ? AND platform = ?",
                (datetime.utcnow().isoformat(), listing_id, platform),
            )

    def get_recent_listings(self, platform: str, limit: int = 50) -> list[dict]:
        """Return the most recent listings for a platform."""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM listings
                WHERE platform = ?
                ORDER BY first_seen DESC
                LIMIT ?
                """,
                (platform, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    # ── Keyword rolling averages ───────────────────────────────────────────

    def get_rolling_average(
        self, group_name: str, term: str, platform: str
    ) -> Optional[float]:
        """Return the current rolling average EUR price, or None if no data."""
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT rolling_avg_eur, sample_count
                FROM keywords
                WHERE group_name = ? AND term = ? AND platform = ?
                """,
                (group_name, term, platform),
            ).fetchone()
            if row and row["sample_count"] > 0:
                return row["rolling_avg_eur"]
            return None

    def update_rolling_average(
        self,
        group_name: str,
        term: str,
        platform: str,
        new_price_eur: float,
    ) -> None:
        """
        Exponential moving average: α=0.1 so recent prices get 10% weight.
        Inserts the keyword row if it doesn't exist yet.
        """
        alpha = 0.1
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT rolling_avg_eur, sample_count
                FROM keywords
                WHERE group_name = ? AND term = ? AND platform = ?
                """,
                (group_name, term, platform),
            ).fetchone()

            if row is None or row["sample_count"] == 0:
                # First data point — seed the average
                new_avg = new_price_eur
                count = 1
            else:
                prev = row["rolling_avg_eur"]
                count = row["sample_count"] + 1
                new_avg = alpha * new_price_eur + (1 - alpha) * prev

            conn.execute(
                """
                INSERT INTO keywords
                    (group_name, term, platform, rolling_avg_eur, sample_count, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(group_name, term, platform)
                DO UPDATE SET
                    rolling_avg_eur = excluded.rolling_avg_eur,
                    sample_count    = excluded.sample_count,
                    updated_at      = excluded.updated_at
                """,
                (group_name, term, platform, new_avg, count, now),
            )

    # ── Alerts audit ──────────────────────────────────────────────────────

    def log_alert(
        self,
        listing_id: str,
        platform: str,
        channel: str,
        success: bool = True,
        error_msg: Optional[str] = None,
    ) -> None:
        """Record that an alert was (attempted to be) sent."""
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO alerts
                    (listing_id, platform, channel, sent_at, success, error_msg)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    listing_id,
                    platform,
                    channel,
                    datetime.utcnow().isoformat(),
                    int(success),
                    error_msg,
                ),
            )

    def alert_already_sent(
        self, listing_id: str, platform: str, channel: str
    ) -> bool:
        """Prevent duplicate alerts for the same listing on the same channel."""
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM alerts
                WHERE listing_id = ? AND platform = ? AND channel = ? AND success = 1
                """,
                (listing_id, platform, channel),
            ).fetchone()
            return row is not None

    # ── Stats helpers ─────────────────────────────────────────────────────

    def stats(self) -> dict:
        """Return a quick summary dict for the dashboard / startup banner."""
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
            suspicious = conn.execute(
                "SELECT COUNT(*) FROM listings WHERE is_suspicious = 1"
            ).fetchone()[0]
            alerts_sent = conn.execute(
                "SELECT COUNT(*) FROM alerts WHERE success = 1"
            ).fetchone()[0]
            platforms = conn.execute(
                "SELECT platform, COUNT(*) as n FROM listings GROUP BY platform"
            ).fetchall()
            return {
                "total_listings": total,
                "suspicious": suspicious,
                "alerts_sent": alerts_sent,
                "by_platform": {r["platform"]: r["n"] for r in platforms},
            }
