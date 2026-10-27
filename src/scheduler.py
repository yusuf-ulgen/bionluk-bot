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
        source_name: str = "Bionluk",
        notify_on_first_scan: bool = True,
    ):
        self.config_mgr = config_mgr
        self.storage = storage
        self.filter_engine = filter_engine
        self.notifier = notifier
        self.scraper_adapter = scraper_adapter
        self.status_callback = status_callback
        self.on_new_listing_callback = on_new_listing_callback
        self.source_name = source_name
        self.notify_on_first_scan = notify_on_first_scan

        self._stop_event = threading.Event()
        self._trigger_now_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._scan_lock = threading.Lock()

        # Durum bilgisi
        self.status = SchedulerStatus(
            last_successful_scan_time=self.storage.get_last_successful_scan()
        )
        self._is_first_scan_of_session = True

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

            # Bekleme döngüsü (stop_event kontrollü)
            while remaining > 0 and not self._stop_event.is_set():
                if self._trigger_now_event.is_set():
                    self._trigger_now_event.clear()
                    logger.info("Bekleme döngüsü anlık tarama isteği ile kesildi.")
                    break

                self.status.seconds_until_next_scan = remaining
                if not self.status.status_message or "Sonraki taramaya" in self.status.status_message:
                    self.status.status_message = f"{self.source_name}: Aktif (Oturum Açık)"
                self._notify_status()

                # 1.0 saniyelik adımlarla bekle, stop sinyalinde anında çık
                if self._stop_event.wait(timeout=1.0):
                    break

                # Kullanıcı çalışma anında tarama aralığını düşürdüyse kalan süreyi hemen uyarla
                cfg_interval = self.config_mgr.config.scan_interval_seconds
                if remaining > cfg_interval:
                    remaining = cfg_interval

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
        if hasattr(self.scraper_adapter, "is_login_in_progress") and (
            self.scraper_adapter.is_login_in_progress() or self.scraper_adapter.is_profile_locked()
        ):
            logger.info("Chrome giriş penceresi açık olduğu için bu tarama döngüsü atlandı.")
            self.status.status_message = "Giriş penceresi açık (Chrome'un kapanması bekleniyor)"
            self._notify_status()
            return

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
            previous_r10_max = self.storage.get_max_r10_thread_id() if self.source_name == "R10" else 0

            is_first_baseline = not self.storage.is_baseline_established()
            new_items_count = 0

            if is_first_baseline:
                # Boş liste veya yüklenmemiş sayfa ile başlangıç kaydı oluşturulmamalı
                if len(listings) == 0:
                    logger.warning("İlk taramada sayfada ilan tespit edilemedi; başlangıç kaydı geçerli bir sayfa okumasına kadar ertelendi.")
                    self.status.status_message = "İlk tarama: İlan tespit edilemedi"
                    self.storage.log_scan(success=True, items_found=0, new_items_count=0)
                    return

                logger.info(f"İlk başlangıç kaydı: {len(listings)} ilan bulundu. Yalnızca en güncel 1 tanesi için test bildirimi gönderilecek.")
                first_notif_sent = False

                for item in listings:
                    eval_res = self.filter_engine.evaluate(item.title, item.description)
                    if not eval_res.is_match:
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

                    # Yalnızca en güncel 1 ilanı test amaçlı bildir
                    if not first_notif_sent and self.notify_on_first_scan:
                        first_notif_sent = True
                        new_items_count += 1
                        budget_info = f" [Bütçe: {item.budget}]" if item.budget else ""
                        msg = f"{item.title}{budget_info}\nEşleşen: {eval_res.matched_include or 'Tümü'}"
                        sent_ok, send_err = self.notifier.send_notification(
                            title=f"{self.source_name} Takipçisi Aktif (Son İlan)",
                            message=msg,
                            url=item.url,
                        )
                        self.storage.save_listing(
                            listing_id=item.id,
                            url=item.url,
                            title=item.title,
                            description=item.description,
                            budget=item.budget,
                            category=item.category,
                            notified=sent_ok,
                            matched_keyword=eval_res.matched_include or "Başlangıç İlanı",
                        )
                        self.storage.record_notification_result(item.id, sent_ok, send_err)
                        if self.on_new_listing_callback:
                            try:
                                self.on_new_listing_callback(item, eval_res.matched_include or "")
                            except Exception as cb_err:
                                logger.error(f"Başlangıç ilan arayüz callback hatası: {cb_err}")
                    else:
                        # Kalan diğer eski ilanları sessizce kaydet (bildirim yağmurunu önle)
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
                self._is_first_scan_of_session = False
                self.status.status_message = f"{self.source_name}: Aktif (Oturum Açık)"
            else:
                # Normal tarama döngüsü
                new_matching_items = []
                for item in listings:
                    if not self.storage.is_listing_seen(item.id):
                        if self.source_name == "R10" and item.id.startswith("r10:") and int(item.id[4:]) <= previous_r10_max:
                            self.storage.save_listing(
                                listing_id=item.id, url=item.url, title=item.title,
                                description=item.description, budget=item.budget,
                                category=item.category, notified=True,
                                matched_keyword="Başlangıç Kaydı",
                            )
                            continue
                        eval_res = self.filter_engine.evaluate(item.title, item.description)
                        if eval_res.is_match:
                            new_matching_items.append((item, eval_res))
                        else:
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
                    else:
                        # Daha önce görülmüş, bildirimi başarısız olmuş ilanlar için tekrar deneme (max 3)
                        if self.storage.should_retry_notification(item.id, max_retries=3):
                            logger.info(f"Teslim edilemeyen ilan için bildirim tekrar deneniyor: {item.title}")
                            budget_info = f" [Bütçe: {item.budget}]" if item.budget else ""
                            matched_kw = self.storage.get_matched_keyword(item.id) or "Filtre Eşleşmesi"
                            msg = f"{item.title}{budget_info}\nEşleşen: {matched_kw}"
                            sent_ok, send_err = self.notifier.send_notification(
                                title=f"Yeni {self.source_name} İlanı!",
                                message=msg,
                                url=item.url,
                            )
                            self.storage.record_notification_result(item.id, sent_ok, send_err)

                # Eğer oturum başlangıcında birden fazla yeni ilan varsa (çalıştırmadan önceki ilanlar):
                # Yalnızca en yeni 1 tanesini bildir, diğerlerini sessizce kaydet
                if self._is_first_scan_of_session and not self.notify_on_first_scan:
                    for item, eval_res in new_matching_items:
                        self.storage.save_listing(
                            listing_id=item.id, url=item.url, title=item.title,
                            description=item.description, budget=item.budget,
                            category=item.category, notified=True,
                            matched_keyword=eval_res.matched_include or "Başlangıç Kaydı",
                        )
                elif self._is_first_scan_of_session and len(new_matching_items) > 1:
                    logger.info(f"Oturum başlangıcında {len(new_matching_items)} ilan bulundu. Yalnızca en yeni 1 ilan için bildirim gönderiliyor.")
                    for idx, (item, eval_res) in enumerate(new_matching_items):
                        if idx == 0:
                            new_items_count += 1
                            budget_info = f" [Bütçe: {item.budget}]" if item.budget else ""
                            msg = f"{item.title}{budget_info}\nEşleşen: {eval_res.matched_include or 'Tümü'}"
                            sent_ok, send_err = self.notifier.send_notification(
                                title=f"{self.source_name} Takipçisi Aktif (Son İlan)",
                                message=msg,
                                url=item.url,
                            )
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
                            self.storage.record_notification_result(item.id, sent_ok, send_err)
                            if self.on_new_listing_callback:
                                try:
                                    self.on_new_listing_callback(item, eval_res.matched_include or "")
                                except Exception as cb_err:
                                    logger.error(f"Yeni ilan callback hatası: {cb_err}")
                        else:
                            self.storage.save_listing(
                                listing_id=item.id,
                                url=item.url,
                                title=item.title,
                                description=item.description,
                                budget=item.budget,
                                category=item.category,
                                notified=True,
                                matched_keyword=eval_res.matched_include or "",
                            )
                else:
                    # Normal çalışma (veya tek yeni ilan): HER yeni ilan için sınırsız bildirim gönder!
                    for item, eval_res in new_matching_items:
                        new_items_count += 1
                        logger.info(f"Yeni eşleşen ilan bulundu: {item.title}")
                        budget_info = f" [Bütçe: {item.budget}]" if item.budget else ""
                        msg = f"{item.title}{budget_info}\nEşleşen: {eval_res.matched_include or 'Tümü'}"
                        sent_ok, send_err = self.notifier.send_notification(
                            title=f"Yeni {self.source_name} İlanı!",
                            message=msg,
                            url=item.url,
                        )
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
                        self.storage.record_notification_result(item.id, sent_ok, send_err)

                        if self.on_new_listing_callback:
                            try:
                                self.on_new_listing_callback(item, eval_res.matched_include or "")
                            except Exception as cb_err:
                                logger.error(f"Yeni ilan bildirim callback hatası: {cb_err}")

                self._is_first_scan_of_session = False
                self.status.status_message = f"{self.source_name}: Aktif (Oturum Açık)"

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
