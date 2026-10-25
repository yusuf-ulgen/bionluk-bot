import os
import sys
import tkinter as tk
import pytest
from pathlib import Path

# Tkinter Tcl kitaplık yollarını garantile
if "TCL_LIBRARY" not in os.environ:
    os.environ["TCL_LIBRARY"] = os.path.join(sys.base_prefix, "tcl", "tcl8.6")
if "TK_LIBRARY" not in os.environ:
    os.environ["TK_LIBRARY"] = os.path.join(sys.base_prefix, "tcl", "tk8.6")

from src.config import ConfigManager
from src.filter_engine import FilterEngine
from src.notifier import WindowsNotifier
from src.scraper.mock_adapter import MockScraperAdapter
from src.storage import Storage, StoredListing
from src.scheduler import SchedulerStatus
from src.ui.app import BionlukBotApp


@pytest.fixture(scope="module")
def shared_root():
    root = tk.Tk()
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


@pytest.fixture
def test_app(shared_root, tmp_path: Path):
    # Önceki testin widget'larını temizle
    for child in shared_root.winfo_children():
        child.destroy()

    cfg_mgr = ConfigManager(tmp_path / "config.json")
    storage = Storage(tmp_path / "test.db")
    filter_engine = FilterEngine()
    notifier = WindowsNotifier(sound_enabled=False)
    adapter = MockScraperAdapter()

    app = BionlukBotApp(
        config_mgr=cfg_mgr,
        storage=storage,
        filter_engine=filter_engine,
        notifier=notifier,
        scraper_adapter=adapter,
        root=shared_root,
    )

    yield app


def test_ui_table_starts_empty_without_old_listings(test_app: BionlukBotApp):
    """Eski oturumdan kalan veritabanı kayıtları yeni oturum arayüzünde görünmemeli."""
    assert len(test_app.tree.get_children()) == 0


def test_ui_new_listings_inserted_at_top(test_app: BionlukBotApp):
    """Yeni gelen ilanlar her zaman tablonun en tepesine (index 0) eklenmeli."""
    item1 = StoredListing(
        listing_id="item-1",
        url="https://bionluk.com/1",
        title="İlk Eklenen İlan",
        budget="1000 TL",
        category="Yazılım",
        first_seen_at="2026-10-25 10:00:00",
        notified=True,
    )
    item2 = StoredListing(
        listing_id="item-2",
        url="https://bionluk.com/2",
        title="İkinci Eklenen Yeni İlan",
        budget="5000 TL",
        category="Yazılım",
        first_seen_at="2026-10-25 10:05:00",
        notified=True,
    )

    test_app._insert_tree_item(item1)
    test_app._insert_tree_item(item2)

    children = test_app.tree.get_children()
    assert len(children) == 2
    # item-2 en tepede (index 0) olmalı
    assert children[0] == "item-2"
    assert children[1] == "item-1"


def test_ui_column_sorting_time_and_budget(test_app: BionlukBotApp):
    """Zaman ve Bütçe sütunları dikey ok göstergeleriyle artan ve azalan şekilde sıralanabilmeli."""
    items = [
        StoredListing("1", "https://bionluk.com/1", "A", budget="500 TL", category="-", first_seen_at="2026-10-25 10:00:00", notified=True),
        StoredListing("2", "https://bionluk.com/2", "B", budget="15000 TL", category="-", first_seen_at="2026-10-25 12:00:00", notified=True),
        StoredListing("3", "https://bionluk.com/3", "C", budget="3000 TL", category="-", first_seen_at="2026-10-25 11:00:00", notified=True),
    ]
    for it in items:
        test_app._insert_tree_item(it)

    # 1. Bütçeye göre azalan sıralama (En yüksek bütçe başta)
    test_app._sort_by_column("budget")
    children = test_app.tree.get_children()
    # 15000 TL -> 3000 TL -> 500 TL
    assert children[0] == "2"
    assert children[1] == "3"
    assert children[2] == "1"
    assert "▼" in test_app.tree.heading("budget")["text"]

    # 2. Bütçeye göre artan sıralama (En düşük bütçe başta)
    test_app._sort_by_column("budget")
    children = test_app.tree.get_children()
    # 500 TL -> 3000 TL -> 15000 TL
    assert children[0] == "1"
    assert children[1] == "3"
    assert children[2] == "2"
    assert "▲" in test_app.tree.heading("budget")["text"]

    # 3. Zamana göre azalan sıralama (En yeni başta)
    test_app._sort_by_column("time")
    children = test_app.tree.get_children()
    # 12:00:00 -> 11:00:00 -> 10:00:00
    assert children[0] == "2"
    assert children[1] == "3"
    assert children[2] == "1"
    assert "▼" in test_app.tree.heading("time")["text"]


def test_ui_tabs_equal_size_and_colored(test_app: BionlukBotApp):
    """Tüm sekme butonları eşit boyutta kalmalı ve seçili olan yeşil ile renklenmeli."""
    assert len(test_app._tab_buttons) == 3

    # Sekme 0 seçili
    test_app._switch_tab(0)
    assert test_app._tab_buttons[0].cget("bg") == "#00a885"
    assert test_app._tab_buttons[0].cget("fg") == "#ffffff"
    assert test_app._tab_buttons[1].cget("bg") == "#e2e8f0"

    # Sekme 1 seç
    test_app._switch_tab(1)
    assert test_app._tab_buttons[1].cget("bg") == "#00a885"
    assert test_app._tab_buttons[0].cget("bg") == "#e2e8f0"


def test_ui_account_connected_button_style(test_app: BionlukBotApp):
    """Hesap bağlı olduğunda buton hafif soluk renge geçip 'Hesap Bağlı' demeli."""
    # 1. Oturum gerekli durumu
    status_login_needed = SchedulerStatus(requires_login=True)
    test_app._update_status_ui(status_login_needed)
    assert "Gerekli" in test_app.btn_login.cget("text")
    assert test_app.btn_login.cget("bg") == "#0284c7"

    # 2. Hesap bağlı durumu
    status_connected = SchedulerStatus(
        requires_login=False,
        last_successful_scan_time="2026-10-25 16:00:00",
        status_message="Bionluk Bağlantısı: Aktif (Oturum Açık)",
    )
    test_app._update_status_ui(status_connected)
    assert "Hesap Bağlı" in test_app.btn_login.cget("text")
    assert test_app.btn_login.cget("bg") == "#f1f5f9"
