"""
Zamanlayıcı ve tarama iş döngüsünü yöneten çekirdek modül.
Arka planda çalışır, arayüzü kilitlemez ve ayar değişikliklerine anında tepki verir.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from .config import AppConfig, ConfigManager
from .filter_engine import FilterEngine
from .notifier import WindowsNotifier
from .scraper.base import BaseScraperAdapter, Listing, ScrapeResult
from .storage import Storage

logger = logging.getLogger("bionluk_bot.scheduler")


@dataclass
class SchedulerStatus:
    is_running: bool = False
    is_scanning_now: bool = False
    last_scan_time: Optional[str] = None
    last_successful_scan_time: Optional[str] = None
    seconds_until_next_scan: int = 0
    status_message: str = "Hazır"
    error_message: str = ""
    requires_login: bool = False
    rate_limited: bool = False


class JobScheduler:
    def __init__(
        self,
        config_mgr: ConfigManager,
        storage: Storage,
        filter_engine: FilterEngine,
        notifier: WindowsNotifier,
        scraper_adapter: BaseScraperAdapter,
        status_callback: Optional[Callable[[SchedulerStatus], None]] = None,
        on_new_listing_callback: Optional[Callable[[Listing, str], None]] = None,
    ):
        self.config_mgr = config_mgr
        self.storage = storage
        self.filter_engine = filter_engine
        self.notifier = notifier
        self.scraper_adapter = scraper_adapter
        self.status_callback = status_callback
        self.on_new_listing_callback = on_new_listing_callback

        self._stop_event = threading.Event()
        self._trigger_now_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._scan_lock = threading.Lock()

        # Durum bilgisi
        self.status = SchedulerStatus(
            last_successful_scan_time=self.storage.get_last_successful_scan()
        )

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        """Tarama döngüsünü başlatır."""
        if self.is_running():
            logger.info("Tarayıcı zaten çalışıyor.")
            return

        self._stop_event.clear()
        self._trigger_now_event.clear()
        self.status.is_running = True
        self.status.status_message = "Tarama başlatılıyor..."
        self._notify_status()

        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="BionlukBotWorker")
        self._thread.start()
        logger.info("Tarama arka plan görevi başlatıldı.")

    def stop(self):
        """Tarama döngüsünü durdurur."""
        self._stop_event.set()
        self._trigger_now_event.set()
        self.status.is_running = False
        self.status.status_message = "Durduruldu"
        self.status.seconds_until_next_scan = 0
        self._notify_status()
        logger.info("Tarama durdurma sinyali gönderildi.")

    def trigger_now(self):
        """Hemen bir tarama başlatılması için zamanlayıcıyı tetikler."""
        if not self.is_running():
            # Çalışmıyorsa önce başlat
            self.start()
        self._trigger_now_event.set()
        logger.info("Kullanıcı tarafından anlık tarama tetiklendi.")

    def _notify_status(self):
        if self.status_callback:
            try:
                self.status_callback(self.status)
            except Exception as e:
                logger.error(f"Durum bildirimi çağrılırken hata: {e}")

    def _run_loop(self):
        """Ana zamanlayıcı döngüsü."""
        logger.info("Tarayıcı iş döngüsü başladı.")

        while not self._stop_event.is_set():
            # 1. Taramayı gerçekleştir
            self._execute_scan()

            if self._stop_event.is_set():
                break

            # 2. Bekleme süresini hesapla
            wait_seconds = self.config_mgr.config.scan_interval_seconds

            # Eğer oran sınırlaması veya özel bekleme varsa ona uy
            if self.status.rate_limited and self.status.seconds_until_next_scan > 0:
                wait_seconds = self.status.seconds_until_next_scan

            logger.info(f"Sonraki taramaya kadar bekleniyor: {wait_seconds} saniye.")
            remaining = wait_seconds

            # Bekleme döngüsü (0.5 saniyelik adımlarla kontrol)
            while remaining > 0 and not self._stop_event.is_set():
                if self._trigger_now_event.is_set():
                    self._trigger_now_event.clear()
                    logger.info("Bekleme döngüsü anlık tarama isteği ile kesildi.")
                    break

                self.status.seconds_until_next_scan = remaining
                self.status.status_message = f"Sonraki taramaya: {remaining} sn"
                self._notify_status()

                time.sleep(1.0)
                remaining -= 1

            self.status.seconds_until_next_scan = 0
            self._notify_status()

        self.status.is_running = False
        self.status.is_scanning_now = False
        self.status.status_message = "Durduruldu"
        self._notify_status()
        logger.info("Tarayıcı iş döngüsü sonlandı.")

    def _execute_scan(self):
        """Tek bir tarama işlemi yürütür."""
        if not self._scan_lock.acquire(blocking=False):
            logger.warning("Önceki tarama henüz tamamlanmadı, yeni tarama atlandı.")
            return

        try:
            self.status.is_scanning_now = True
            self.status.status_message = "İlanlar taranıyor..."
            self._notify_status()

            target_url = self.config_mgr.config.target_url
            scrape_result: ScrapeResult = self.scraper_adapter.scrape_listings(target_url)

            # Tarama zamanını güncelle
            now_iso = time.strftime("%Y-%m-%d %H:%M:%S")
            self.status.last_scan_time = now_iso

            if not scrape_result.success:
                logger.warning(f"Tarama başarısız oldu: {scrape_result.error_message}")
                self.status.error_message = scrape_result.error_message
                self.status.requires_login = scrape_result.requires_login
                self.status.rate_limited = scrape_result.rate_limited

                if scrape_result.requires_login:
                    self.status.status_message = "Giriş gerekiyor / Oturum süresi doldu!"
                elif scrape_result.rate_limited:
                    wait_time = max(scrape_result.retry_after_seconds, 30)
                    self.status.status_message = f"Erişim sınırı: {wait_time} sn bekleniyor"
                    self.status.seconds_until_next_scan = wait_time
                else:
                    self.status.status_message = f"Hata: {scrape_result.error_message[:40]}"

                self.storage.log_scan(
                    success=False,
                    items_found=0,
                    new_items_count=0,
                    error_message=scrape_result.error_message,
                )
                self._notify_status()
                return

            # Başarılı tarama
            self.status.requires_login = False
            self.status.rate_limited = False
            self.status.error_message = ""
            self.status.last_successful_scan_time = now_iso

            listings = scrape_result.listings
            logger.info(f"Sayfadan {len(listings)} adet ilan okundu.")

            is_first_baseline = not self.storage.is_baseline_established()
            new_items_count = 0

            if is_first_baseline:
                logger.info("İlk başarılı tarama: Mevcut ilanlar başlangıç kaydı (baseline) olarak kaydediliyor.")
                for item in listings:
                    # Filtreyi değerlendir
                    eval_res = self.filter_engine.evaluate(item.title, item.description)
                    # Baseline ilanlarını bildirilmiş gibi kaydet (bildirim yağmurunu önle)
                    self.storage.save_listing(
                        listing_id=item.id,
                        url=item.url,
                        title=item.title,
                        description=item.description,
                        budget=item.budget,
                        category=item.category,
                        notified=True,
                        matched_keyword=eval_res.matched_include or "Başlangıç Kaydı",
                    )
                self.storage.set_baseline_established()
                self.status.status_message = f"İlk tarama tamamlandı ({len(listings)} ilan kaydedildi)"
            else:
                # Normal tarama döngüsü: Yeni ilanları değerlendir
                for item in listings:
                    if self.storage.is_listing_seen(item.id):
                        continue

                    # İlan daha önce görülmemiş
                    eval_res = self.filter_engine.evaluate(item.title, item.description)
                    if not eval_res.is_match:
                        logger.debug(f"İlan filtreye takıldı: {item.title} ({eval_res.reason})")
                        # Filtreye uymasa da tekrar kontrol edilmemesi için veritabanına ekle (notified=True)
                        self.storage.save_listing(
                            listing_id=item.id,
                            url=item.url,
                            title=item.title,
                            description=item.description,
                            budget=item.budget,
                            category=item.category,
                            notified=True,
                            matched_keyword="",
                        )
                        continue

                    # EŞLEŞEN YENİ İLAN!
                    new_items_count += 1
                    logger.info(f"Yeni eşleşen ilan bulundu: {item.title}")

                    # Bildirim gönder
                    budget_info = f" [Bütçe: {item.budget}]" if item.budget else ""
                    msg = f"{item.title}{budget_info}\nEşleşen: {eval_res.matched_include or 'Tümü'}"
                    
                    sent_ok, send_err = self.notifier.send_notification(
                        title="Yeni Bionluk İlanı!",
                        message=msg,
                        url=item.url,
                    )

                    # Veritabanına kaydet
                    self.storage.save_listing(
                        listing_id=item.id,
                        url=item.url,
                        title=item.title,
                        description=item.description,
                        budget=item.budget,
                        category=item.category,
                        notified=sent_ok,
                        matched_keyword=eval_res.matched_include or "",
                    )
                    if not sent_ok:
                        self.storage.mark_listing_notified(item.id, False, send_err)

                    # Arayüz callback'ini bilgilendir
                    if self.on_new_listing_callback:
                        try:
                            self.on_new_listing_callback(item, eval_res.matched_include or "")
                        except Exception as cb_err:
                            logger.error(f"Yeni ilan bildirim arayüz callback hatası: {cb_err}")

                self.status.status_message = f"Tarama tamamlandı ({new_items_count} yeni eşleşme)"

            self.storage.log_scan(
                success=True,
                items_found=len(listings),
                new_items_count=new_items_count,
            )

        except Exception as e:
            logger.exception(f"Tarama sırasında beklenmeyen hata: {e}")
            self.status.error_message = str(e)
            self.status.status_message = f"Hata: {str(e)[:40]}"
        finally:
            self.status.is_scanning_now = False
            self._notify_status()
            self._scan_lock.release()
