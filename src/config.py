"""
Uygulama ayarlarını yöneten modül.
Ayarları 'data/config.json' dosyasında tutar ve doğrulamalar yapar.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger("bionluk_bot.config")

DEFAULT_URL = "https://bionluk.com/alici-istekleri"
DEFAULT_INTERVAL_SECONDS = 60
MIN_INTERVAL_SECONDS = 5


@dataclass
class AppConfig:
    target_url: str = DEFAULT_URL
    scan_interval_seconds: int = DEFAULT_INTERVAL_SECONDS
    included_keywords: List[str] = field(default_factory=list)
    excluded_keywords: List[str] = field(default_factory=list)
    sound_enabled: bool = True
    autostart_enabled: bool = False
    headless: bool = True

    def validate(self) -> Tuple[bool, str]:
        """Ayarları doğrular. Geçerliyse (True, ''), değilse (False, 'Hata mesajı') döner."""
        if not self.target_url or not self.target_url.strip():
            return False, "Takip edilecek URL adresi boş olamaz."
        
        target = self.target_url.strip().lower()
        if not (target.startswith("http://") or target.startswith("https://")):
            return False, "Takip URL'si 'http://' veya 'https://' ile başlamalıdır."

        try:
            val = int(self.scan_interval_seconds)
            if val < MIN_INTERVAL_SECONDS:
                return False, f"Tarama aralığı en az {MIN_INTERVAL_SECONDS} saniye olmalıdır."
        except (ValueError, TypeError):
            return False, "Tarama aralığı geçerli bir pozitif tam sayı olmalıdır."

        return True, ""


class ConfigManager:
    """Ayar dosyasını yükleyen, saklayan ve yöneten sınıf."""

    def __init__(self, config_path: Path | str | None = None):
        if config_path is None:
            base_dir = Path(__file__).resolve().parent.parent
            self.config_dir = base_dir / "data"
            self.config_path = self.config_dir / "config.json"
        else:
            self.config_path = Path(config_path)
            self.config_dir = self.config_path.parent

        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config = self.load()

    def load(self) -> AppConfig:
        """Ayarları diskten okur. Dosya yoksa veya bozuksa varsayılanı döner."""
        if not self.config_path.exists():
            default_cfg = AppConfig()
            self.save(default_cfg)
            return default_cfg

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # Anahtar sözcükleri temizle
            inc = [str(k).strip() for k in data.get("included_keywords", []) if str(k).strip()]
            exc = [str(k).strip() for k in data.get("excluded_keywords", []) if str(k).strip()]

            cfg = AppConfig(
                target_url=data.get("target_url", DEFAULT_URL).strip() or DEFAULT_URL,
                scan_interval_seconds=int(data.get("scan_interval_seconds", DEFAULT_INTERVAL_SECONDS)),
                included_keywords=inc,
                excluded_keywords=exc,
                sound_enabled=bool(data.get("sound_enabled", True)),
                autostart_enabled=bool(data.get("autostart_enabled", False)),
                headless=bool(data.get("headless", True)),
            )
            is_valid, err = cfg.validate()
            if not is_valid:
                logger.warning(f"Ayar dosyasında geçersiz değerler tespit edildi: {err}. Varsayılan değerler kullanılıyor.")
                return AppConfig()
            return cfg
        except Exception as e:
            logger.error(f"Ayar dosyası yüklenirken hata oluştu: {e}. Varsayılan değerler kullanılacak.")
            return AppConfig()

    def save(self, cfg: AppConfig | None = None) -> Tuple[bool, str]:
        """Ayarları kaydeder."""
        if cfg is not None:
            is_valid, msg = cfg.validate()
            if not is_valid:
                return False, msg
            self.config = cfg

        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(asdict(self.config), f, ensure_ascii=False, indent=2)
            return True, "Ayarlar başarıyla kaydedildi."
        except Exception as e:
            logger.error(f"Ayarlar kaydedilirken hata: {e}")
            return False, f"Ayarlar kaydedilemedi: {e}"

    def update_interval(self, interval_str: str) -> Tuple[bool, str]:
        """Arayüzden gelen tarama aralığını doğrular ve günceller."""
        raw = str(interval_str).strip()
        if not raw:
            return False, "Tarama aralığı boş bırakılamaz."
        if not raw.isdigit():
            return False, "Lütfen sadece pozitif tam sayı (örn. 15, 30, 60) giriniz."
        val = int(raw)
        if val < MIN_INTERVAL_SECONDS:
            return False, f"Tarama aralığı en az {MIN_INTERVAL_SECONDS} saniye olabilir."
        
        self.config.scan_interval_seconds = val
        return self.save()

    def update_keywords(self, included: List[str], excluded: List[str]) -> Tuple[bool, str]:
        """Anahtar kelimeleri günceller."""
        self.config.included_keywords = [k.strip() for k in included if k.strip()]
        self.config.excluded_keywords = [k.strip() for k in excluded if k.strip()]
        return self.save()
