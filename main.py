"""
Bionluk İlan Takipçisi Ana Başlatıcı
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
import sys
import tkinter as tk
from tkinter import messagebox
from pathlib import Path

# Proje kök dizinini sys.path'e ekle
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.config import ConfigManager
from src.filter_engine import FilterEngine
from src.notifier import WindowsNotifier
from src.scraper.playwright_adapter import PlaywrightBionlukAdapter
from src.single_instance import SingleInstanceLock
from src.storage import Storage
from src.ui.app import BionlukBotApp


def setup_logging(data_dir: Path):
    """Sınırlı boyutta dönen (rotating) log yapılandırması."""
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "bot.log"

    # Max 2MB, 3 yedek dosya
    file_handler = RotatingFileHandler(
        str(log_file),
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)


def main():
    data_dir = BASE_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    setup_logging(data_dir)
    logger = logging.getLogger("bionluk_bot.main")
    logger.info("Bionluk İlan Takipçisi başlatılıyor...")

    # 1. Tekil kopya kontrolü
    lock = SingleInstanceLock()
    if not lock.acquire():
        logger.warning("Uygulama zaten açık olduğu için ikinci kopya sonlandırılıyor.")
        root = tk.Tk()
        root.withdraw()
        messagebox.showwarning(
            "Uygulama Zaten Çalışıyor",
            "Bionluk İlan Takipçisi bilgisayarınızda zaten açık durumda.\n\n"
            "Çakışmaları ve çift bildirimleri önlemek için ikinci bir pencere açılamaz. "
            "Lütfen sistem tepsisini (sağ alt) veya görev çubuğunu kontrol edin.",
        )
        root.destroy()
        sys.exit(0)

    try:
        # 2. Modülleri başlat
        config_mgr = ConfigManager()
        storage = Storage()
        filter_engine = FilterEngine(
            included_keywords=config_mgr.config.included_keywords,
            excluded_keywords=config_mgr.config.excluded_keywords,
        )
        notifier = WindowsNotifier(sound_enabled=config_mgr.config.sound_enabled)
        scraper_adapter = PlaywrightBionlukAdapter(headless=config_mgr.config.headless)

        # 3. Masaüstü arayüzünü aç
        app = BionlukBotApp(
            config_mgr=config_mgr,
            storage=storage,
            filter_engine=filter_engine,
            notifier=notifier,
            scraper_adapter=scraper_adapter,
        )

        app.run()
    except Exception as e:
        logger.exception(f"Uygulama çalışırken kritik hata oluştu: {e}")
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "Kritik Hata",
                f"Uygulama başlatılırken veya çalışırken bir hata oluştu:\n\n{e}\n\nDetaylar log dosyasında mevcuttur.",
            )
            root.destroy()
        except Exception:
            pass
    finally:
        lock.release()
        logger.info("Uygulama sonlandı.")


if __name__ == "__main__":
    main()
