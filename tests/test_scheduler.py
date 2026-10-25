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


def test_scheduler_failed_first_scan_does_not_establish_baseline(tmp_path: Path):
    """Senaryo 8: İlk tarama başarısızsa başlangıç kaydı oluşmaz; sonraki başarılı tarama yağmur yapmaz."""
    cfg_mgr = ConfigManager(tmp_path / "config.json")
    storage = Storage(tmp_path / "test.db")
    filter_engine = FilterEngine()
    notifier = DummyNotifier()

    adapter = MockScraperAdapter([Listing(id="old-1", title="Eski İlan", url="https://bionluk.com/old")])
    adapter.should_fail = True
    adapter.failure_message = "İnternet kesintisi"

    scheduler = JobScheduler(
        config_mgr=cfg_mgr,
        storage=storage,
        filter_engine=filter_engine,
        notifier=notifier,
        scraper_adapter=adapter,
    )

    # 1. Başarısız tarama
    scheduler._execute_scan()
    assert storage.is_baseline_established() is False
    assert len(notifier.sent_notifications) == 0

    # 2. İnternet düzeldi, başarılı tarama
    adapter.should_fail = False
    scheduler._execute_scan()
    # Şimdi baseline kurulmalı ve eski ilan için bildirim GÖNDERİLMEMELİ
    assert storage.is_baseline_established() is True
    assert storage.is_listing_seen("old-1") is True
    assert len(notifier.sent_notifications) == 0

    # 3. Sonradan yeni ilan gelince bildirim gitmeli
    adapter.add_listing(Listing(id="new-1", title="Yeni İlan", url="https://bionluk.com/new"))
    scheduler._execute_scan()
    assert len(notifier.sent_notifications) == 1
    assert "Yeni İlan" in notifier.sent_notifications[0]["message"]


def test_filter_change_does_not_re_notify_old_listings(tmp_path: Path):
    """Senaryo 10: Filtre değişikliği geçmiş ilanların tamamını yeniden bildirmez."""
    cfg_mgr = ConfigManager(tmp_path / "config.json")
    storage = Storage(tmp_path / "test.db")
    filter_engine = FilterEngine(included_keywords=["python"])
    notifier = DummyNotifier()

    adapter = MockScraperAdapter()
    scheduler = JobScheduler(cfg_mgr, storage, filter_engine, notifier, adapter)

    # Baseline oluştur
    adapter.add_listing(Listing(id="1", title="Python ve Django İşi", url="https://bionluk.com/1"))
    scheduler._execute_scan()
    assert len(notifier.sent_notifications) == 0

    # Filtreyi değiştir (django ekle)
    filter_engine.update_rules(["django"], [])
    cfg_mgr.update_keywords(["django"], [])

    # Tekrar tara: İlan 1 zaten görüldüğü için ASLA tekrar bildirilmez
    scheduler._execute_scan()
    assert len(notifier.sent_notifications) == 0


def test_notification_failure_and_controlled_retry(tmp_path: Path):
    """Senaryo 11: Bildirim başarısız olursa kayıt teslim edilmiş sayılmaz; kontrollü tekrar denenir."""
    cfg_mgr = ConfigManager(tmp_path / "config.json")
    storage = Storage(tmp_path / "test.db")
    filter_engine = FilterEngine(included_keywords=["python"])

    class FailingNotifier(DummyNotifier):
        def __init__(self):
            super().__init__()
            self.fail_mode = True

        def send_notification(self, title, message, url=None, sound=None):
            if self.fail_mode:
                return False, "Windows Notification Service Error"
            self.sent_notifications.append({"title": title, "message": message})
            return True, ""

    notifier = FailingNotifier()
    adapter = MockScraperAdapter([Listing(id="base-1", title="Eski Python İşi", url="https://bionluk.com/base")])
    scheduler = JobScheduler(cfg_mgr, storage, filter_engine, notifier, adapter)

    # 1. Baseline
    scheduler._execute_scan()
    assert storage.is_baseline_established() is True

    # 2. Yeni ilan geldi ama bildirim servisi hata verdi
    new_item = Listing(id="retry-1", title="Python Bot", url="https://bionluk.com/r1")
    adapter.add_listing(new_item)

    scheduler._execute_scan()
    # Veritabanında kayıtlı ama notified=False olmalı
    assert storage.is_listing_seen("retry-1") is True
    status = storage.get_recent_listings()[0]
    assert status.notified is False
    assert "Windows Notification Service Error" in status.notification_error
    assert len(notifier.sent_notifications) == 0

    # 3. Sonraki taramada bildirim servisi düzeldi -> tekrar denemeli ve teslim etmeli
    notifier.fail_mode = False
    scheduler._execute_scan()
    assert len(notifier.sent_notifications) == 1
    updated_status = storage.get_recent_listings()[0]
    assert updated_status.notified is True

    # 4. Daha sonraki taramada bildirim zaten ulaştığı için tekrar gönderilmemeli
    scheduler._execute_scan()
    assert len(notifier.sent_notifications) == 1


def test_same_title_different_ids_and_title_change(tmp_path: Path):
    """Senaryo 3: Aynı başlığa sahip 2 farklı ilan karışmaz; başlık değişince yeni ilan sayılmaz."""
    storage = Storage(tmp_path / "test.db")

    # Aynı başlığa sahip iki farklı ilan
    res_a = storage.save_listing("id-A", "https://bionluk.com/A", "Logo Tasarımı")
    res_b = storage.save_listing("id-B", "https://bionluk.com/B", "Logo Tasarımı")
    assert res_a is True
    assert res_b is True

    # İlan A'nın başlığı değişse bile ID'si aynı olduğu için yeni ilan muamelesi görmez
    assert storage.is_listing_seen("id-A") is True
    res_a_dup = storage.save_listing("id-A", "https://bionluk.com/A", "Logo Tasarımı Acil Revize")
    assert res_a_dup is False


def test_fast_stop_during_wait(tmp_path: Path):
    """Senaryo 6: Durdurma uzun beklemelerde anında yanıt verir (< 200ms)."""
    import time
    cfg_mgr = ConfigManager(tmp_path / "config.json")
    cfg_mgr.config.scan_interval_seconds = 100  # 100 saniye bekleme

    storage = Storage(tmp_path / "test.db")
    filter_engine = FilterEngine()
    notifier = DummyNotifier()
    adapter = MockScraperAdapter()

    scheduler = JobScheduler(cfg_mgr, storage, filter_engine, notifier, adapter)
    scheduler.start()

    time.sleep(0.1)  # Başlaması için kısa süre
    assert scheduler.is_running() is True

    t0 = time.time()
    scheduler.stop()
    scheduler._thread.join(timeout=1.0)
    elapsed = time.time() - t0

    assert scheduler.is_running() is False
    assert elapsed < 0.5, f"Durdurma çok uzun sürdü: {elapsed} saniye"


def test_concurrent_scans_prevented(tmp_path: Path):
    """Senaryo 5: Yavaş tarama sırasında 'Şimdi tara' veya zamanlayıcı ikinci bir tarama başlatmaz."""
    import time
    import threading
    cfg_mgr = ConfigManager(tmp_path / "config.json")
    storage = Storage(tmp_path / "test.db")
    filter_engine = FilterEngine()
    notifier = DummyNotifier()

    concurrent_count = 0
    max_concurrent = 0
    lock = threading.Lock()

    class SlowAdapter(MockScraperAdapter):
        def scrape_listings(self, url: str):
            nonlocal concurrent_count, max_concurrent
            with lock:
                concurrent_count += 1
                if concurrent_count > max_concurrent:
                    max_concurrent = concurrent_count
            time.sleep(0.3)
            with lock:
                concurrent_count -= 1
            return super().scrape_listings(url)

    adapter = SlowAdapter([Listing(id="1", title="İlan", url="https://bionluk.com/1")])
    scheduler = JobScheduler(cfg_mgr, storage, filter_engine, notifier, adapter)

    # 3 ayrı thread aynı anda _execute_scan çağırıyor
    threads = [threading.Thread(target=scheduler._execute_scan) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Eşzamanlı çalışan tarama sayısı hiçbir zaman 1'i geçmemeli
    assert max_concurrent == 1


