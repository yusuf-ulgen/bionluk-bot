import pytest
from pathlib import Path
from src.config import ConfigManager
from src.filter_engine import FilterEngine
from src.notifier import WindowsNotifier
from src.scheduler import JobScheduler
from src.scraper.base import Listing
from src.scraper.mock_adapter import MockScraperAdapter
from src.storage import Storage


class DummyNotifier(WindowsNotifier):
    """Gerçek bildirim pencereleri açmayan test bildirimcisi."""
    def __init__(self):
        super().__init__(sound_enabled=False)
        self.sent_notifications = []

    def send_notification(self, title: str, message: str, url=None, sound=None):
        self.sent_notifications.append({"title": title, "message": message, "url": url})
        return True, ""


def test_scheduler_baseline_no_notification_storm(tmp_path: Path):
    """İlk başarılı tarama mevcut ilanları başlangıç kaydı yapar, bildirim yağmuru oluşturmaz."""
    cfg_mgr = ConfigManager(tmp_path / "config.json")
    storage = Storage(tmp_path / "test.db")
    filter_engine = FilterEngine(included_keywords=["python"])
    notifier = DummyNotifier()

    # Başlangıçta 2 adet Python ilanı olan sahte adaptör
    item1 = Listing(id="1", title="Python Bot Yazımı", url="https://bionluk.com/1")
    item2 = Listing(id="2", title="Python Otomasyonu", url="https://bionluk.com/2")
    adapter = MockScraperAdapter([item1, item2])

    scheduler = JobScheduler(
        config_mgr=cfg_mgr,
        storage=storage,
        filter_engine=filter_engine,
        notifier=notifier,
        scraper_adapter=adapter,
    )

    # 1. Tarama (Baseline)
    scheduler._execute_scan()

    assert storage.is_baseline_established() is True
    assert storage.is_listing_seen("1") is True
    assert storage.is_listing_seen("2") is True
    # Bildirim listesi BOŞ olmalı çünkü ilk taramada bildirim yağmuru engellendi
    assert len(notifier.sent_notifications) == 0

    # 2. Tarama: Yeni 1 ilan ekleniyor
    item3 = Listing(id="3", title="Yeni Python Projesi", url="https://bionluk.com/3")
    adapter.add_listing(item3)

    scheduler._execute_scan()

    # Şimdi sadece yeni ilan (item3) için 1 adet bildirim gitmiş olmalı
    assert len(notifier.sent_notifications) == 1
    assert "Yeni Python Projesi" in notifier.sent_notifications[0]["message"]
    assert storage.is_listing_seen("3") is True

    # 3. Tarama: Yeni ilan yok, tekrar bildirim gitmemeli (deduplication)
    scheduler._execute_scan()
    assert len(notifier.sent_notifications) == 1


def test_scheduler_handles_adapter_error(tmp_path: Path):
    """Adaptör hata verdiğinde zamanlayıcı çökmemeli ve durumu raporlamalı."""
    cfg_mgr = ConfigManager(tmp_path / "config.json")
    storage = Storage(tmp_path / "test.db")
    filter_engine = FilterEngine()
    notifier = DummyNotifier()

    adapter = MockScraperAdapter()
    adapter.should_fail = True
    adapter.failure_message = "Bionluk 500 İç Sunucu Hatası"

    scheduler = JobScheduler(
        config_mgr=cfg_mgr,
        storage=storage,
        filter_engine=filter_engine,
        notifier=notifier,
        scraper_adapter=adapter,
    )

    scheduler._execute_scan()

    assert scheduler.status.error_message == "Bionluk 500 İç Sunucu Hatası"
    assert "Hata:" in scheduler.status.status_message
    assert len(notifier.sent_notifications) == 0


def test_scheduler_rate_limit_backoff(tmp_path: Path):
    """Oran sınırlaması (429) geldiğinde zamanlayıcı backoff süresini ayarlar."""
    cfg_mgr = ConfigManager(tmp_path / "config.json")
    storage = Storage(tmp_path / "test.db")
    filter_engine = FilterEngine()
    notifier = DummyNotifier()

    adapter = MockScraperAdapter()
    adapter.should_fail = True
    adapter.rate_limited_flag = True
    adapter.retry_after = 45
    adapter.failure_message = "Rate limit"

    scheduler = JobScheduler(
        config_mgr=cfg_mgr,
        storage=storage,
        filter_engine=filter_engine,
        notifier=notifier,
        scraper_adapter=adapter,
    )

    scheduler._execute_scan()

    assert scheduler.status.rate_limited is True
    assert scheduler.status.seconds_until_next_scan == 45
    assert "Erişim sınırı: 45 sn" in scheduler.status.status_message
