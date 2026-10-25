"""
Windows masaüstü bildirimleri ve sesli uyarıları yöneten modül.
winotify ile Windows 10/11 yerel bildirim kartları üretir ve ilanı tarayıcıda açma desteği sunar.
"""

from __future__ import annotations

import logging
import sys
import threading
from typing import Optional, Tuple

logger = logging.getLogger("bionluk_bot.notifier")

APP_ID = "Bionluk İlan Takipçisi"


class WindowsNotifier:
    def __init__(self, sound_enabled: bool = True):
        self.sound_enabled = sound_enabled

    def play_sound(self):
        """Windows varsayılan bildirim sesini arka planda çalar."""
        if not self.sound_enabled:
            return
        if not sys.platform.startswith("win"):
            return

        def _sound_thread():
            try:
                import winsound
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception as e:
                logger.debug(f"Ses çalınamadı: {e}")

        threading.Thread(target=_sound_thread, daemon=True).start()

    def send_notification(
        self,
        title: str,
        message: str,
        url: Optional[str] = None,
        sound: Optional[bool] = None,
    ) -> Tuple[bool, str]:
        """
        Masaüstü bildirimi gönderir.
        Başarılıysa (True, ''), hata durumunda (False, 'Hata mesajı') döner.
        """
        # Ses isteğe bağlı tetiklenir
        should_play = self.sound_enabled if sound is None else sound
        if should_play:
            self.play_sound()

        # 1. winotify dene (Windows 10/11 yerel eylem destekli)
        try:
            from winotify import Notification

            toast = Notification(
                app_id=APP_ID,
                title=title[:60],
                msg=message[:150],
                duration="short",
            )

            if url and (url.startswith("http://") or url.startswith("https://")):
                try:
                    toast.add_actions(label="İlana Git", launch=url)
                except Exception as e:
                    logger.debug(f"İlana git butonu eklenemedi: {e}")

            toast.show()
            logger.info(f"Bildirim gönderildi: {title}")
            return True, ""
        except Exception as e:
            logger.warning(f"winotify ile bildirim gönderilemedi: {e}. Basit uyarı deneniyor.")

        # 2. Alternatif: Tkinter messagebox veya standart bildirim (fallback)
        try:
            return False, f"Bildirim altyapısı hatası: {e}"
        except Exception as ex:
            return False, str(ex)

    def send_test_notification(self) -> Tuple[bool, str]:
        """Kullanıcının bildirim ve ses sistemini denemesi için test bildirimi gönderir."""
        return self.send_notification(
            title="Test Bildirimi - Bionluk Botu",
            message="Bildirim ve ses sistemi düzgün çalışıyor!",
            url="https://bionluk.com",
            sound=True,
        )
