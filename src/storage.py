"""
SQLite tabanlı yerel kalıcı veri depolama katmanı.
İlan kimlikleri, filtre eşleşmeleri ve tarama geçmişi burada saklanır.
"""

from __future__ import annotations

import datetime
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bionluk_bot.storage")


@dataclass
class StoredListing:
    listing_id: str
    url: str
    title: str
    description: str = ""
    budget: str = ""
    category: str = ""
    first_seen_at: str = ""
    notified: bool = False
    notification_error: str = ""
    matched_keyword: str = ""


class Storage:
    def __init__(self, db_path: Path | str | None = None):
        if db_path is None:
            base_dir = Path(__file__).resolve().parent.parent
            self.data_dir = base_dir / "data"
            self.db_path = self.data_dir / "bot_database.sqlite3"
        else:
            self.db_path = Path(db_path)
            self.data_dir = self.db_path.parent

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # İlanlar tablosu
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS listings (
                    listing_id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    budget TEXT,
                    category TEXT,
                    first_seen_at TEXT NOT NULL,
                    notified INTEGER DEFAULT 0,
                    notification_error TEXT,
                    matched_keyword TEXT,
                    notification_retries INTEGER DEFAULT 0,
                    last_notification_attempt TEXT
                )
            """)

            # Mevcut veritabanı varsa eksik sütunları güvenle ekle
            cursor.execute("PRAGMA table_info(listings)")
            columns = [col[1] for col in cursor.fetchall()]
            if "notification_retries" not in columns:
                cursor.execute("ALTER TABLE listings ADD COLUMN notification_retries INTEGER DEFAULT 0")
            if "last_notification_attempt" not in columns:
                cursor.execute("ALTER TABLE listings ADD COLUMN last_notification_attempt TEXT")

            # Tarama geçmişi tablosu
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS scan_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scanned_at TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    items_found INTEGER NOT NULL,
                    new_items_count INTEGER NOT NULL,
                    error_message TEXT
                )
            """)

            # Uygulama durum tablosu (baseline durumu vb.)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS app_state (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            conn.commit()

    def is_listing_seen(self, listing_id: str) -> bool:
        """İlan ID'sinin daha önce görülüp görülmediğini kontrol eder."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM listings WHERE listing_id = ?", (listing_id,))
            return cursor.fetchone() is not None

    def save_listing(
        self,
        listing_id: str,
        url: str,
        title: str,
        description: str = "",
        budget: str = "",
        category: str = "",
        notified: bool = False,
        matched_keyword: str = "",
        first_seen_at: str | None = None,
    ) -> bool:
        """
        Yeni bir ilanı veritabanına ekler. Zaten varsa eklemez.
        Başarıyla yeni eklendiyse True, zaten kayıtlıysa False döner.
        """
        now_str = first_seen_at or datetime.datetime.now().isoformat()
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO listings (
                        listing_id, url, title, description, budget,
                        category, first_seen_at, notified, matched_keyword
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        listing_id,
                        url,
                        title,
                        description,
                        budget,
                        category,
                        now_str,
                        1 if notified else 0,
                        matched_keyword,
                    ),
                )
                conn.commit()
                return True
        except sqlite3.IntegrityError:
            # Zaten var
            return False
        except Exception as e:
            logger.error(f"İlan kaydedilirken hata: {e}")
            return False

    def mark_listing_notified(self, listing_id: str, success: bool, error_msg: str = ""):
        """Bildirim gönderim sonucunu kaydeder."""
        self.record_notification_result(listing_id, success, error_msg)

    def record_notification_result(self, listing_id: str, success: bool, error_msg: str = ""):
        """Bildirim gönderim durumunu, deneme sayısını ve zaman damgasını kaydeder."""
        now_str = datetime.datetime.now().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if success:
                cursor.execute(
                    """
                    UPDATE listings 
                    SET notified = 1, notification_error = '', last_notification_attempt = ?
                    WHERE listing_id = ?
                    """,
                    (now_str, listing_id),
                )
            else:
                cursor.execute(
                    """
                    UPDATE listings 
                    SET notified = 0, notification_error = ?,
                        notification_retries = notification_retries + 1,
                        last_notification_attempt = ?
                    WHERE listing_id = ?
                    """,
                    (error_msg, now_str, listing_id),
                )
            conn.commit()

    def should_retry_notification(self, listing_id: str, max_retries: int = 3) -> bool:
        """
        Bildirimi başarısız olmuş bir ilan için tekrar deneme yapılıp yapılmayacağını belirler.
        Sadece filtre eşleşmesi olan (matched_keyword != '') ve bildirilmemiş (notified == 0)
        ilanlar deneme sınırına kadar tekrar denenir.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT notified, notification_retries, matched_keyword
                FROM listings
                WHERE listing_id = ?
                """,
                (listing_id,),
            )
            row = cursor.fetchone()
            if not row:
                return False
            is_notified = bool(row["notified"])
            retries = int(row["notification_retries"] or 0)
            matched_kw = row["matched_keyword"] or ""

            # Başlangıç kaydı veya filtrelenmiş ilanlar tekrar denenmez
            if is_notified or not matched_kw or matched_kw == "Başlangıç Kaydı":
                return False

            return retries < max_retries

    def get_matched_keyword(self, listing_id: str) -> str:
        """İlanın eşleştiği anahtar kelimeyi döner."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT matched_keyword FROM listings WHERE listing_id = ?", (listing_id,))
            row = cursor.fetchone()
            return row["matched_keyword"] if row and row["matched_keyword"] else ""


    def is_baseline_established(self) -> bool:
        """İlk başarılı tarama kaydı yapılmış mı kontrol eder."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM app_state WHERE key = 'baseline_established'")
            row = cursor.fetchone()
            return bool(row and row["value"] == "1")

    def set_baseline_established(self):
        """İlk tarama başarıyla yapıldığında başlangıç durumunu işaretler."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO app_state (key, value) VALUES ('baseline_established', '1')
                ON CONFLICT(key) DO UPDATE SET value = '1'
                """
            )
            conn.commit()

    def log_scan(
        self,
        success: bool,
        items_found: int,
        new_items_count: int,
        error_message: str = "",
    ):
        """Tarama sonucunu günlüğe kaydeder."""
        now_str = datetime.datetime.now().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO scan_history (scanned_at, success, items_found, new_items_count, error_message)
                VALUES (?, ?, ?, ?, ?)
                """,
                (now_str, 1 if success else 0, items_found, new_items_count, error_message),
            )
            if success:
                cursor.execute(
                    """
                    INSERT INTO app_state (key, value) VALUES ('last_successful_scan', ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (now_str,),
                )
            conn.commit()

    def get_last_successful_scan(self) -> Optional[str]:
        """Son başarılı taramanın zamanını döner."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM app_state WHERE key = 'last_successful_scan'")
            row = cursor.fetchone()
            return row["value"] if row else None

    def get_recent_listings(self, limit: int = 100) -> List[StoredListing]:
        """Arayüz için son kaydedilen eşleşen ilanları listeler."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT listing_id, url, title, description, budget, category,
                       first_seen_at, notified, notification_error, matched_keyword
                FROM listings
                ORDER BY first_seen_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()
            return [
                StoredListing(
                    listing_id=r["listing_id"],
                    url=r["url"],
                    title=r["title"],
                    description=r["description"] or "",
                    budget=r["budget"] or "",
                    category=r["category"] or "",
                    first_seen_at=r["first_seen_at"],
                    notified=bool(r["notified"]),
                    notification_error=r["notification_error"] or "",
                    matched_keyword=r["matched_keyword"] or "",
                )
                for r in rows
            ]
