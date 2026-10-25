"""
Testler ve sahte veri denemeleri için Mock (Sahte) Adaptör.
"""

from __future__ import annotations

from typing import List, Optional

from .base import BaseScraperAdapter, Listing, ScrapeResult


class MockScraperAdapter(BaseScraperAdapter):
    def __init__(self, initial_listings: Optional[List[Listing]] = None):
        self.listings: List[Listing] = initial_listings or []
        self.should_fail: bool = False
        self.failure_message: str = "Bağlantı hatası"
        self.requires_login_flag: bool = False
        self.rate_limited_flag: bool = False
        self.retry_after: int = 0
        self.login_opened: bool = False
        self.closed: bool = False

    def add_listing(self, listing: Listing):
        self.listings.append(listing)

    def scrape_listings(self, url: str) -> ScrapeResult:
        if self.should_fail:
            return ScrapeResult(
                success=False,
                error_message=self.failure_message,
                requires_login=self.requires_login_flag,
                rate_limited=self.rate_limited_flag,
                retry_after_seconds=self.retry_after,
            )
        return ScrapeResult(
            success=True,
            listings=list(self.listings),
        )

    def open_login_session(self, url: str, on_complete_callback=None):
        self.login_opened = True
        if on_complete_callback:
            on_complete_callback(True, "Oturum doğrulandı (Mock)")

    def verify_session(self, url: str = "https://bionluk.com/bugun"):
        if self.requires_login_flag:
            return False, "Oturum açık değil"
        return True, "Oturum aktif"

    def is_login_in_progress(self) -> bool:
        return False

    def is_profile_locked(self) -> bool:
        return False

    def close(self):
        self.closed = True

