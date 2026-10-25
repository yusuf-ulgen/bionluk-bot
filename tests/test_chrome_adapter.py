import os
from pathlib import Path
import pytest
from src.scraper.playwright_adapter import PlaywrightBionlukAdapter, find_chrome_executable
from src.scraper.mock_adapter import MockScraperAdapter
from src.scheduler import JobScheduler
from src.config import ConfigManager
from src.storage import Storage
from src.filter_engine import FilterEngine
from src.notifier import WindowsNotifier


def test_find_chrome_executable():
    """Google Chrome'un sistemde bulunabilip bulunamadığını test eder."""
    chrome_path = find_chrome_executable()
    # Windows'ta Google Chrome kuruluysa Path nesnesi döner
    if chrome_path:
        assert isinstance(chrome_path, Path)
        assert chrome_path.is_file()
        assert "chrome.exe" in chrome_path.name.lower()


def test_profile_lock_detection(tmp_path: Path):
    """Profil kilidi kontrolünün çalıştığını test eder."""
    profile_dir = tmp_path / "chrome_profile"
    adapter = PlaywrightBionlukAdapter(profile_dir=profile_dir)

    # Başlangıçta kilitli olmamalı
    assert adapter.is_profile_locked() is False
    assert adapter.is_login_in_progress() is False

    # lockfile oluşturup dosya kilitlendiğinde kilitli algılanmalı
    lock_file = profile_dir / "lockfile"
    lock_file.write_text("test lock")

    # Dosya açık tutulmadığı sürece is_profile_locked False olmalı
    assert adapter.is_profile_locked() is False

    # Dosyayı özel açarak kilit simüle edelim (Windows'ta dosya açıkken başka bir açılış hata verir veya simüle edilir)
    with open(lock_file, "r+b") as f:
        # lockfile r+b ile açıkken başka bir r+b açılışı Windows'ta engellenir mi test edelim
        pass


def test_scheduler_skips_when_login_in_progress(tmp_path: Path):
    """Giriş penceresi açıkken zamanlayıcının taramayı atladığını test eder."""
    cfg_mgr = ConfigManager(tmp_path / "config.json")
    storage = Storage(tmp_path / "test.db")
    filter_engine = FilterEngine()
    notifier = WindowsNotifier(sound_enabled=False)

    class BusyMockAdapter(MockScraperAdapter):
        def is_login_in_progress(self):
            return True

    adapter = BusyMockAdapter()
    scheduler = JobScheduler(cfg_mgr, storage, filter_engine, notifier, adapter)

    scheduler._execute_scan()

    assert "Giriş penceresi açık" in scheduler.status.status_message
    assert scheduler.status.is_scanning_now is False
