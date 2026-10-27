"""
Bionluk için Google Chrome tabanlı kazıma ve oturum yönetimi adaptörü.
Google ile giriş engelini aşmak için:
- Manuel girişte bilgisayarda kurulu standart Google Chrome bağımsız süreç olarak açılır.
- Tarama sırasında Playwright channel="chrome" ile aynı yerel profili kullanır.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from playwright.sync_api import sync_playwright

from .base import BaseScraperAdapter, Listing, ScrapeResult

logger = logging.getLogger("bionluk_bot.scraper.playwright")


def find_chrome_executable() -> Optional[Path]:
    """Bilgisayarda kurulu standart Google Chrome çalıştırılabilir dosyasını bulur."""
    # 1. Özel ortam değişkeni
    env_path = os.environ.get("CHROME_PATH")
    if env_path and os.path.isfile(env_path):
        return Path(env_path)

    # 2. Standart Windows yolları
    candidates = [
        Path(os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe")),
        Path(os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe")),
        Path(os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe")),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate

    # 3. Windows Registry
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe") as key:
            val, _ = winreg.QueryValueEx(key, "")
            if val and os.path.isfile(val):
                return Path(val)
    except Exception:
        pass

    # 4. PATH üzerinde arama
    which_path = shutil.which("chrome") or shutil.which("google-chrome")
    if which_path:
        return Path(which_path)

    return None


class PlaywrightBionlukAdapter(BaseScraperAdapter):
    login_url = "https://bionluk.com/login"
    verify_url = "https://bionluk.com/bugun"
    def __init__(self, profile_dir: Path | str | None = None, headless: bool = True):
        if profile_dir is None:
            base_dir = Path(__file__).resolve().parent.parent.parent
            self.profile_dir = base_dir / "data" / "chrome_profile"
        else:
            self.profile_dir = Path(profile_dir)

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.headless = headless
        self._lock = threading.Lock()
        self._active_login_process: Optional[subprocess.Popen] = None
        self._is_logging_in = False

    def is_login_in_progress(self) -> bool:
        """Kullanıcının manuel giriş penceresinin açık olup olmadığını döner."""
        if self._active_login_process is not None:
            if self._active_login_process.poll() is None:
                return True
            else:
                self._active_login_process = None
        return self._is_logging_in

    def is_profile_locked(self) -> bool:
        """Tarayıcı profil dizininin Chrome tarafından kilitli olup olmadığını kontrol eder."""
        if self.is_login_in_progress():
            return True

        lock_file = self.profile_dir / "lockfile"
        if not lock_file.exists():
            return False

        try:
            with open(lock_file, "r+b"):
                return False
        except (IOError, OSError, PermissionError):
            return True

    def open_login_session(self, url: str, on_complete_callback: Optional[Callable[[bool, str], None]] = None):
        """
        Kullanıcının Google hesabı veya e-posta ile güvenle giriş yapması için
        bilgisayarda kurulu normal Google Chrome'u otomasyonsuz (standalone) süreç olarak açar.
        """
        chrome_path = find_chrome_executable()
        if not chrome_path:
            msg = (
                "Bilgisayarınızda Google Chrome bulunamadı.\n\n"
                "Google ile sorunsuz giriş yapabilmek için lütfen Google Chrome'u kurun:\n"
                "https://www.google.com/chrome/"
            )
            logger.error(msg)
            if on_complete_callback:
                on_complete_callback(False, msg)
            return

        if self.is_profile_locked():
            msg = "Giriş penceresi veya Chrome şu anda zaten açık. Lütfen mevcut pencereyi kullanın veya kapatın."
            logger.warning(msg)
            if on_complete_callback:
                on_complete_callback(False, msg)
            return

        def _login_worker():
            with self._lock:
                self._is_logging_in = True
                login_target = url or self.login_url
                logger.info(f"Normal Google Chrome açılıyor: {chrome_path} (Hedef: {login_target})")

                # Standart Chrome parametreleri (Otomasyon, remote debugging veya stealth YOK!)
                cmd = [
                    str(chrome_path),
                    f"--user-data-dir={self.profile_dir.resolve()}",
                    "--no-first-run",
                    "--no-default-browser-check",
                    login_target,
                ]

                try:
                    self._active_login_process = subprocess.Popen(cmd)
                    logger.info("Chrome başlatıldı. Kullanıcının giriş yapması ve tarayıcıyı kapatması bekleniyor...")

                    # Kullanıcı Chrome'u kapatana kadar bekle
                    self._active_login_process.wait()
                except Exception as e:
                    logger.error(f"Chrome başlatılırken hata: {e}")
                    self._is_logging_in = False
                    self._active_login_process = None
                    if on_complete_callback:
                        on_complete_callback(False, f"Chrome başlatılamadı: {e}")
                    return

                self._active_login_process = None
                self._is_logging_in = False

                # Chrome'un profil kilit dosyasını bırakması için kısa bekleme
                for _ in range(10):
                    if not self.is_profile_locked():
                        break
                    time.sleep(0.5)

                logger.info("Chrome kapatıldı. Gerçek Bionluk oturumu doğrulanıyor...")

                # Oturumu /bugun üzerinden doğrula
                is_valid, verify_msg = self.verify_session(self.verify_url)
                logger.info(f"Oturum doğrulama sonucu: {is_valid} ({verify_msg})")

                if on_complete_callback:
                    on_complete_callback(is_valid, verify_msg)

        threading.Thread(target=_login_worker, daemon=True, name="ChromeLoginWorker").start()

    def verify_session(self, url: str = "https://bionluk.com/bugun") -> Tuple[bool, str]:
        """
        Bionluk oturumunun gerçekten açık olup olmadığını Playwright ile doğrular.
        Sadece tarayıcının kapanmasını yeterli görmez; gerçek sayfa durumunu denetler.
        """
        if self.is_profile_locked():
            return False, "Chrome pencereleri henüz tamamen kapanmadı. Lütfen açık Chrome pencerelerini kapatın."

        chrome_path = find_chrome_executable()
        if not chrome_path:
            return False, "Google Chrome bulunamadı."

        try:
            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(self.profile_dir.resolve()),
                    channel="chrome",
                    headless=True,
                )
                page = context.pages[0] if context.pages else context.new_page()

                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=25000)
                    page.wait_for_timeout(1500)
                except Exception as nav_err:
                    context.close()
                    return False, f"Oturum kontrol edilirken sayfaya erişilemedi: {nav_err}"

                current_url = page.url.lower()

                # 1. Giriş yapılmadığının açık göstergeleri
                # Not: /giris substring araması yapılmaz; blog/girisimcilik ve urun-veri-girisi ile çakışır.
                has_signin_button = page.locator("a[href='/login'], a[href$='/login'], .signin-button, .btn-login").count() > 0

                # 2. Giriş yapıldığının göstergeleri (bugun veya panel sayfası, kullanıcı menü öğeleri)
                is_on_auth_page = "bugun" in current_url or "panel" in current_url
                has_user_element = page.locator(
                    "a[href*='/settings'], a[href*='/panel/'], a[href*='cikis'], a[href*='logout'], a[href='/bugun']"
                ).count() > 0

                # 3. Çerez kontrolü
                cookies = context.cookies()
                cookie_names = {c["name"].lower() for c in cookies if "bionluk" in c.get("domain", "").lower()}
                has_auth_cookie = bool(cookie_names.intersection({"bionluk_authenticated_init", "bionluk_session"}))

                context.close()

                if (is_on_auth_page or has_user_element or has_auth_cookie) and not has_signin_button:
                    return True, "Bionluk oturumu aktif ve başarıyla doğrulandı."
                else:
                    return False, "Bionluk oturumu açık görünmüyor. Lütfen 'Bionluk'a Giriş Yap' ile hesabınıza giriş yapın."

        except Exception as e:
            logger.error(f"Oturum doğrulama sırasında beklenmeyen hata: {e}")
            return False, f"Oturum doğrulanamadı: {e}"

    def scrape_listings(self, url: str) -> ScrapeResult:
        """
        Belirtilen sayfaya giderek alıcı isteklerini/ilanları toplar.
        Playwright channel="chrome" kullanarak girişteki profil ile tarama yapar.
        """
        # Giriş penceresi açıksa veya profil kullanımda ise tarama başlatma
        if self.is_profile_locked():
            return ScrapeResult(
                success=False,
                error_message="Giriş penceresi veya Chrome şu anda açık. Lütfen girişinizi tamamlayıp Chrome'u kapatın.",
                requires_login=True,
            )

        chrome_path = find_chrome_executable()
        if not chrome_path:
            return ScrapeResult(
                success=False,
                error_message="Google Chrome bulunamadı. Lütfen Chrome'u kurun.",
                requires_login=True,
            )

        with self._lock:
            try:
                with sync_playwright() as p:
                    context = p.chromium.launch_persistent_context(
                        user_data_dir=str(self.profile_dir.resolve()),
                        channel="chrome",
                        headless=self.headless,
                    )
                    page = context.pages[0] if context.pages else context.new_page()

                    try:
                        response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    except Exception as e:
                        context.close()
                        return ScrapeResult(
                            success=False,
                            error_message=f"Sayfa yüklenirken zaman aşımı veya bağlantı hatası: {e}",
                        )

                    current_url = page.url.lower()
                    status_code = response.status if response else 200

                    # 1. Hata ve HTTP Durum Kontrolleri
                    if status_code in (429,):
                        retry_after = 60
                        if response:
                            headers = response.headers
                            if "retry-after" in headers:
                                try:
                                    retry_after = int(headers["retry-after"])
                                except ValueError:
                                    pass
                        context.close()
                        return ScrapeResult(
                            success=False,
                            error_message="Bionluk erişim sınırı (Rate limit) uyguladı.",
                            rate_limited=True,
                            retry_after_seconds=retry_after,
                        )

                    # 2. CAPTCHA ve Cloudflare Kontrolü
                    page_content = page.content().lower()
                    if "challenge-running" in page_content or "cf-mitigated" in page_content or "turnstile" in page_content:
                        context.close()
                        return ScrapeResult(
                            success=False,
                            error_message="Güvenlik doğrulaması (Cloudflare/CAPTCHA) tespit edildi. Lütfen 'Giriş Yap' üzerinden doğrulayın.",
                            requires_login=True,
                        )

                    # 3. Oturum / Giriş Kontrolü
                    if "/login" in current_url or status_code in (401, 403):
                        context.close()
                        return ScrapeResult(
                            success=False,
                            error_message="Bionluk oturumu açık değil veya süresi doldu. Lütfen giriş yapın.",
                            requires_login=True,
                        )

                    # SPA için DOM'un oturmasını kısa bir süre bekle (1.5 saniye)
                    page.wait_for_timeout(1500)

                    # 4. Sayfadaki ilanları/alıcı isteklerini ayrıştır
                    listings = self._parse_listings_from_page(page)

                    # Eğer URL 404 döndüyse
                    if status_code == 404 and not listings:
                        context.close()
                        return ScrapeResult(
                            success=False,
                            error_message=f"Belirtilen sayfa bulunamadı (404 Not Found): {url}. Lütfen ayarlarınızdaki URL'yi kontrol edin.",
                        )

                    # 5. Boş liste kontrolü: Gerçekten 0 istek mi var yoksa sayfa açılamadı / oturum mu yok?
                    if not listings:
                        has_login_button = bool(page.locator("a[href='/login'], a[href$='/login'], .signin-button").count() > 0)
                        is_target_different = url.rstrip("/") != current_url.rstrip("/") and ("/login" in current_url or current_url == "https://bionluk.com")

                        if has_login_button or is_target_different:
                            context.close()
                            return ScrapeResult(
                                success=False,
                                error_message="Bionluk oturumu açık değil veya ana sayfaya yönlendirildi. Lütfen 'Bionluk'a Giriş Yap' ile oturum açın.",
                                requires_login=True,
                            )

                        empty_indicators = [
                            "alıcı isteği bulunamadı",
                            "henüz alıcı isteği bulunmuyor",
                            "uygun alıcı isteği yok",
                            "alıcı istekleri",
                            "özel alıcı isteklerim",
                            "bana uygun alıcı istekleri",
                        ]
                        has_valid_indicator = any(ind in page_content for ind in empty_indicators)

                        if not has_valid_indicator:
                            context.close()
                            return ScrapeResult(
                                success=False,
                                error_message="Sayfa yapısı değişmiş veya beklenen alıcı istekleri içeriği bulunamadı. Sayfa içeriği doğrulanamadı.",
                            )

                    context.close()
                    return ScrapeResult(
                        success=True,
                        listings=listings,
                    )

            except Exception as e:
                logger.exception(f"Tarama sırasında beklenmeyen hata: {e}")
                return ScrapeResult(
                    success=False,
                    error_message=f"Tarayıcı çalıştırma hatası: {e}",
                )

    def _parse_listings_from_page(self, page) -> List[Listing]:
        """Sayfadaki alıcı isteklerini DOM öğelerinden çıkarır."""
        results: List[Listing] = []

        items_data = page.evaluate("""() => {
            const items = [];
            
            const cardSelectors = [
                '.request-box',
                '[class*="request-box"]',
                '.custom-order-item',
                '.buyer-request-item',
                '.buyer-request',
                '[data-qa="buyer-request-item"]',
                '.request-card',
                '.alici-istegi-item',
                'div[class*="request-item"]',
                'div[class*="buyer-request"]',
                'div[class*="order-item"]'
            ];

            let elements = [];
            for (const sel of cardSelectors) {
                const found = document.querySelectorAll(sel);
                if (found && found.length > 0) {
                    elements = Array.from(found);
                    break;
                }
            }

            if (elements.length === 0) {
                const actionLinks = Array.from(document.querySelectorAll('a, button')).filter(el => {
                    const txt = (el.innerText || '').toLowerCase();
                    const href = (el.href || '').toLowerCase();
                    return txt.includes('teklif ver') || href.includes('alici-istek') || href.includes('/istek/');
                });

                const parentContainers = new Set();
                actionLinks.forEach(link => {
                    let parent = link.parentElement;
                    let depth = 0;
                    while (parent && depth < 5) {
                        if (parent.tagName === 'LI' || parent.tagName === 'ARTICLE' || (parent.tagName === 'DIV' && parent.children.length > 2)) {
                            parentContainers.add(parent);
                            break;
                        }
                        parent = parent.parentElement;
                        depth++;
                    }
                });
                elements = Array.from(parentContainers);
            }

            elements.forEach((el, index) => {
                const textContent = el.innerText || '';
                const linkEl = el.querySelector('a[href*="istek"], a[href*="alici"], a[href*="siparis"], a') || el.closest('a');
                const url = linkEl ? linkEl.href : window.location.href;

                const headingEl = el.querySelector('h1, h2, h3, h4, h5, .title, strong, [class*="title"]');
                let title = headingEl ? headingEl.innerText.trim() : '';
                if (!title) {
                    const lines = textContent.split('\\n').map(l => l.trim()).filter(l => l.length > 3);
                    title = lines[0] || ('İlan #' + (index + 1));
                }

                let description = '';
                const descEl = el.querySelector('.description, .desc, p, [class*="description"], [class*="detail"]');
                if (descEl && descEl !== headingEl) {
                    description = descEl.innerText.trim();
                } else {
                    description = textContent;
                }

                let budget = '';
                const priceMatch = textContent.match(/(\\d+[\\.,]?\\d*\\s*(?:TL|₺|USD|EUR|\\$|€))/i);
                if (priceMatch) {
                    budget = priceMatch[1].trim();
                }

                let category = '';
                const catEl = el.querySelector('.category, [class*="category"], .badge');
                if (catEl) {
                    category = catEl.innerText.trim();
                }

                let id = '';
                const idMatch = url.match(/\\/(\\d+)(?:[\\/?#]|$)/);
                if (idMatch) {
                    id = idMatch[1];
                } else if (url && url !== window.location.href) {
                    id = url;
                } else {
                    const lines = textContent.split('\\n').map(l => l.trim()).filter(Boolean);
                    const buyer = lines[0] || '';
                    const slug = (buyer + '_' + title).toLowerCase().replace(/[^a-z0-9ğüşıöç]+/gi, '_').slice(0, 50);
                    id = slug || ('item_' + index);
                }

                items.push({
                    id: String(id),
                    title: title,
                    url: url,
                    description: description,
                    budget: budget,
                    category: category
                });
            });

            return items;
        }""")

        for item in items_data:
            results.append(
                Listing(
                    id=item.get("id", ""),
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    description=item.get("description", ""),
                    budget=item.get("budget", ""),
                    category=item.get("category", ""),
                )
            )

        return results

    def close(self):
        """Açık kalan oturum ve süreçleri temizler."""
        if self._active_login_process is not None:
            try:
                self._active_login_process.terminate()
                self._active_login_process.wait(timeout=3)
            except Exception:
                pass
            self._active_login_process = None
        logger.info("Playwright / Chrome adaptörü kapatıldı.")
