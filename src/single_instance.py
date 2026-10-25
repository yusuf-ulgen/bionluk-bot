"""
Uygulamanın aynı anda birden fazla kez açılmasını engelleyen tekil çalışma (single instance) mekanizması.
Yerel bir soket dinleyerek aynı profilin veya veritabanının çakışmasını önler.
"""

from __future__ import annotations

import logging
import socket
import sys

logger = logging.getLogger("bionluk_bot.single_instance")

DEFAULT_PORT = 48921


class SingleInstanceLock:
    def __init__(self, port: int = DEFAULT_PORT):
        self.port = port
        self.sock: socket.socket | None = None

    def acquire(self) -> bool:
        """
        Kilit almaya çalışır. Başarılıysa True, başka bir kopya çalışıyorsa False döner.
        """
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # Windows'ta SO_REUSEADDR portu yeniden bağlayabilir, bu yüzden bağlama kontrolü yapılır
            self.sock.bind(("127.0.0.1", self.port))
            self.sock.listen(1)
            logger.info(f"Tekil örnek kilidi başarıyla alındı (Port: {self.port}).")
            return True
        except (socket.error, OSError) as e:
            logger.warning(f"Uygulama zaten çalışıyor olabilir. Port {self.port} meşgul: {e}")
            if self.sock:
                try:
                    self.sock.close()
                except Exception:
                    pass
                self.sock = None
            return False

    def release(self):
        """Kilidi serbest bırakır."""
        if self.sock:
            try:
                self.sock.close()
                logger.info("Tekil örnek kilidi kapatıldı.")
            except Exception as e:
                logger.error(f"Kilit kapatılırken hata: {e}")
            self.sock = None
