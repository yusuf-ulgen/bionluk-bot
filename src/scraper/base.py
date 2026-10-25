"""
İlan ve tarama adaptörü temel sınıfları ve veri modelleri.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Listing:
    id: str
    title: str
    url: str
    description: str = ""
    budget: str = ""
    category: str = ""
    raw_data: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.id = str(self.id).strip()
        self.title = str(self.title).strip()
        self.url = str(self.url).strip()
        self.description = str(self.description).strip()
        self.budget = str(self.budget).strip()
        self.category = str(self.category).strip()


@dataclass
class ScrapeResult:
    success: bool
    listings: List[Listing] = field(default_factory=list)
    error_message: str = ""
    requires_login: bool = False
    rate_limited: bool = False
    retry_after_seconds: int = 0


class BaseScraperAdapter(ABC):
    """Bionluk veya test kaynaklarını okumak için soyut arayüz."""

    @abstractmethod
    def scrape_listings(self, url: str) -> ScrapeResult:
        """Belirtilen URL adresindeki güncel ilanları çeker."""
        pass

    @abstractmethod
    def open_login_session(self, url: str):
        """Kullanıcının güvenle kendi hesabına giriş yapması için tarayıcı açar."""
        pass

    @abstractmethod
    def close(self):
        """Tarayıcı ve açık kaynakları temizler."""
        pass
