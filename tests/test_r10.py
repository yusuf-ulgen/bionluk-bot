from src.scraper.r10_adapter import R10_URL, parse_threads
from src.config import ConfigManager
from src.filter_engine import FilterEngine
from tests.test_scheduler import DummyNotifier
from src.scheduler import JobScheduler
from src.scraper.base import Listing
from src.scraper.mock_adapter import MockScraperAdapter
from src.storage import Storage


def test_parse_threads_excludes_navigation_duplicates_and_sticky():
    rows = [
        {"url": R10_URL + "4913151-android-emulator-yapimi.html", "title": "Android Emulator Yapımı"},
        {"url": R10_URL + "4913151-android-emulator-yapimi.html?page=2", "title": "2"},
        {"url": R10_URL + "4913152-yeni-is.html", "title": "Yeni İş", "sticky": True},
        {"url": R10_URL, "title": "Kategori"},
    ]
    listings = parse_threads(rows)
    assert [(x.id, x.title) for x in listings] == [("r10:4913151", "Android Emulator Yapımı")]


def test_r10_first_scan_is_silent_then_new_topic_notifies(tmp_path):
    config = ConfigManager(tmp_path / "config.json")
    storage = Storage(tmp_path / "r10.db")
    adapter = MockScraperAdapter([Listing("r10:1", "Eski iş", R10_URL + "1-eski.html")])
    notifier = DummyNotifier()
    scheduler = JobScheduler(config, storage, FilterEngine(), notifier, adapter,
                             source_name="R10", notify_on_first_scan=False)
    scheduler._execute_scan()
    assert storage.is_baseline_established()
    assert not notifier.sent_notifications
    adapter.add_listing(Listing("r10:2", "Yeni iş", R10_URL + "2-yeni.html"))
    scheduler._execute_scan()
    assert len(notifier.sent_notifications) == 1
    assert notifier.sent_notifications[0]["title"] == "Yeni R10 İlanı!"
