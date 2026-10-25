"""
Windows başlangıcında (Startup) uygulamanın otomatik açılmasını yöneten modül.
Yalnızca mevcut kullanıcı (HKEY_CURRENT_USER) kaydını kullanır; yönetici yetkisi gerektirmez.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger("bionluk_bot.autostart")

APP_NAME = "BionlukIsTakipcisi"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def is_windows() -> bool:
    return sys.platform.startswith("win")


def is_autostart_enabled() -> bool:
    """Windows başlangıcında otomatik başlatmanın etkin olup olmadığını kontrol eder."""
    if not is_windows():
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            try:
                winreg.QueryValueEx(key, APP_NAME)
                return True
            except FileNotFoundError:
                return False
    except Exception as e:
        logger.error(f"Başlangıç ayarı okunurken hata: {e}")
        return False


def set_autostart(enabled: bool, target_command: str | None = None) -> bool:
    """
    Windows başlangıcında otomatik başlatmayı açar veya kapatır.
    """
    if not is_windows():
        return False

    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                if not target_command:
                    # Varsayılan olarak proje kökündeki baslat.bat veya main.py dosyasını hedefler
                    base_dir = Path(__file__).resolve().parent.parent
                    bat_path = base_dir / "baslat.bat"
                    if bat_path.exists():
                        target_command = f'"{bat_path}"'
                    else:
                        python_exe = sys.executable
                        main_py = base_dir / "main.py"
                        target_command = f'"{python_exe}" "{main_py}"'

                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, target_command)
                logger.info(f"Windows başlangıç kaydı eklendi: {target_command}")
                return True
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                    logger.info("Windows başlangıç kaydı kaldırıldı.")
                except FileNotFoundError:
                    pass
                return True
    except Exception as e:
        logger.error(f"Windows başlangıç kaydı güncellenirken hata: {e}")
        return False
