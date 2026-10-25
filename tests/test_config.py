import pytest
from pathlib import Path
from src.config import AppConfig, ConfigManager


def test_config_defaults(tmp_path: Path):
    cfg_file = tmp_path / "config.json"
    mgr = ConfigManager(config_path=cfg_file)

    assert mgr.config.scan_interval_seconds == 60
    assert mgr.config.target_url == "https://bionluk.com/panel/alici-istekleri"
    assert mgr.config.sound_enabled is True

    # Eski url otomatik olarak /panel/alici-istekleri adresine düzeltilmeli
    mgr.config.target_url = "https://bionluk.com/alici-istekleri"
    mgr.config.validate()
    assert mgr.config.target_url == "https://bionluk.com/panel/alici-istekleri"


def test_config_interval_validation(tmp_path: Path):
    cfg_file = tmp_path / "config.json"
    mgr = ConfigManager(config_path=cfg_file)

    # Geçerli değerler
    ok, _ = mgr.update_interval("15")
    assert ok is True
    assert mgr.config.scan_interval_seconds == 15

    ok, _ = mgr.update_interval("120")
    assert ok is True
    assert mgr.config.scan_interval_seconds == 120

    # Geçersiz değerler: boş, negatif, sıfır, harf
    ok_empty, msg = mgr.update_interval("")
    assert ok_empty is False

    ok_zero, _ = mgr.update_interval("0")
    assert ok_zero is False

    ok_neg, _ = mgr.update_interval("-10")
    assert ok_neg is False

    ok_str, _ = mgr.update_interval("abc")
    assert ok_str is False


def test_config_save_and_reload(tmp_path: Path):
    cfg_file = tmp_path / "config.json"
    mgr = ConfigManager(config_path=cfg_file)

    mgr.update_keywords(["python", "ai"], ["stajyer"])
    mgr.update_interval("45")

    # Yeniden yükle
    mgr2 = ConfigManager(config_path=cfg_file)
    assert mgr2.config.scan_interval_seconds == 45
    assert mgr2.config.included_keywords == ["python", "ai"]
    assert mgr2.config.excluded_keywords == ["stajyer"]
