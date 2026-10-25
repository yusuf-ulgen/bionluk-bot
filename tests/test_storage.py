import pytest
from pathlib import Path
from src.storage import Storage


def test_storage_deduplication(tmp_path: Path):
    db_file = tmp_path / "test.db"
    store = Storage(db_path=db_file)

    # İlk ekleme başarılı olmalı
    saved = store.save_listing(
        listing_id="12345",
        url="https://bionluk.com/istek/12345",
        title="Python Scraper Bot",
        budget="1000 TL"
    )
    assert saved is True
    assert store.is_listing_seen("12345") is True

    # Aynı ID tekrar eklenirse False dönmeli
    saved_again = store.save_listing(
        listing_id="12345",
        url="https://bionluk.com/istek/12345",
        title="Farklı Başlık ile Güncellenen İlan",  # Başlık değişse bile aynı ID
        budget="1200 TL"
    )
    assert saved_again is False

    # Veritabanındaki orijinal başlık korunmalı
    recent = store.get_recent_listings(limit=10)
    assert len(recent) == 1
    assert recent[0].title == "Python Scraper Bot"


def test_baseline_and_state(tmp_path: Path):
    db_file = tmp_path / "test.db"
    store = Storage(db_path=db_file)

    assert store.is_baseline_established() is False
    store.set_baseline_established()
    assert store.is_baseline_established() is True


def test_persistence_across_restarts(tmp_path: Path):
    db_file = tmp_path / "test.db"
    
    # 1. Oturum
    store1 = Storage(db_path=db_file)
    store1.save_listing("id-1", "https://bionluk.com/1", "İlan 1")
    store1.log_scan(success=True, items_found=5, new_items_count=1)

    # 2. Oturum (Yeniden başlatma simülasyonu)
    store2 = Storage(db_path=db_file)
    assert store2.is_listing_seen("id-1") is True
    assert store2.get_last_successful_scan() is not None
    recent = store2.get_recent_listings(limit=10)
    assert len(recent) == 1
    assert recent[0].title == "İlan 1"
