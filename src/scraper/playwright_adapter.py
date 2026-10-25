"""
Bionluk için Playwright tabanlı kazıma ve oturum yönetimi adaptörü.
Ayrı bir yerel tarayıcı profili (user_data_dir) kullanarak kullanıcının kendi oturumunu korur.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
from pathlib import Path
from typing import List, Optional

from playwright.sync_api import sync_playwright

from .base import BaseScraperAdapter, Listing, ScrapeResult

logger = logging.getLogger("bionluk_bot.scraper.playwright")


class PlaywrightBionlukAdapter(BaseScraperAdapter):
    def __init__(self, profile_dir: Path | str | None = None, headless: bool = True):
        if profile_dir is None:
            base_dir = Path(__file__).resolve().parent.parent.parent
            self.profile_dir = base_dir / "data" / "browser_profile"
        else:
            self.profile_dir = Path(profile_dir)

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.headless = headless
        self._lock = threading.Lock()
        self._active_login_process = None

    def open_login_session(self, url: str):
        """
        Kullanıcının hesaba manuel giriş yapması için görünür (headed) bir tarayıcı penceresi açar.
        Oturum 'data/browser_profile' dizininde saklanır.
        """
        def _login_thread():
            with self._lock:
                logger.info("Kullanıcı giriş oturumu için tarayıcı açılıyor...")
                with sync_playwright() as p:
                    # Kullanıcının görebileceği şekilde headless=False aç
                    context = p.chromium.launch_persistent_context(
                        user_data_dir=str(self.profile_dir),
                        headless=False,
                        viewport={"width": 1280, "height": 800},
                        args=["--start-maximized"],
                    )
                    page = context.pages[0] if context.pages else context.new_page()
                    try:
                        login_target = url if ("giris" in url or "login" in url) else "https://bionluk.com"
                        page.goto(login_target, wait_until="domcontentloaded", timeout=45000)
                        logger.info("Giriş sayfası açıldı. Kullanıcının giriş yapması ve pencereyi kapatması bekleniyor.")
                        
                        # Kullanıcı tarayıcıyı kapatana kadar bekle
                        page.wait_for_event("close", timeout=0)
                    except Exception as e:
                        logger.debug(f"Giriş penceresi kapandı veya sonlandı: {e}")
                    finally:
                        try:
                            context.close()
                        except Exception:
                            pass
                        logger.info("Giriş oturumu tamamlandı ve profil kaydedildi.")

        threading.Thread(target=_login_thread, daemon=True, name="BionlukLoginWorker").start()

    def scrape_listings(self, url: str) -> ScrapeResult:
        """
        Belirtilen sayfaya giderek alıcı isteklerini/ilanları toplar.
        Thread güvenliği için kilit kullanır.
        """
        with self._lock:
            try:
                with sync_playwright() as p:
                    context = p.chromium.launch_persistent_context(
                        user_data_dir=str(self.profile_dir),
                        headless=self.headless,
                        args=["--disable-blink-features=AutomationControlled"],
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
                    if "giris" in current_url or "login" in current_url or status_code in (401, 403):
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

                    # Eğer URL 404 döndüyse ve ilan bulunamadıysa
                    if status_code == 404 and not listings:
                        context.close()
                        return ScrapeResult(
                            success=False,
                            error_message=f"Belirtilen sayfa bulunamadı (404 Not Found): {url}. Lütfen ayarlarınızdaki URL'yi kontrol edin.",
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
        """
        Sayfadaki alıcı isteklerini DOM öğelerinden çıkarır.
        Gerçek Bionluk sayfasındaki olası HTML kart yapılarını destekler.
        """
        results: List[Listing] = []

        # Bionluk Alıcı İstekleri kartları veya satırları için tarama
        # JavaScript yardımıyla DOM üzerinde arama yapıyoruz:
        items_data = page.evaluate("""() => {
            const items = [];
            
            // 1. Olası kart ve liste seçicileri
            const cardSelectors = [
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

            // 2. Eğer özel sınıf bulunamazsa, 'teklif ver' veya istek bağlantısı içeren kapsayıcıları bul
            if (elements.length === 0) {
                const actionLinks = Array.from(document.querySelectorAll('a, button')).filter(el => {
                    const txt = (el.innerText || '').toLowerCase();
                    const href = (el.href || '').toLowerCase();
                    return txt.includes('teklif ver') || href.includes('alici-istek') || href.includes('/istek/');
                });

                const parentContainers = new Set();
                actionLinks.forEach(link => {
                    // En mantıklı kart kapsayıcısını bul
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

            // 3. Her bir elemandan verileri çek
            elements.forEach((el, index) => {
                const textContent = el.innerText || '';
                const linkEl = el.querySelector('a[href*="istek"], a[href*="alici"], a[href*="siparis"], a') || el.closest('a');
                const url = linkEl ? linkEl.href : window.location.href;

                // Başlık bulma
                const headingEl = el.querySelector('h1, h2, h3, h4, h5, .title, strong, [class*="title"]');
                let title = headingEl ? headingEl.innerText.trim() : '';
                if (!title) {
                    const lines = textContent.split('\\n').map(l => l.trim()).filter(l => l.length > 3);
                    title = lines[0] || ('İlan #' + (index + 1));
                }

                // Açıklama bulma
                let description = '';
                const descEl = el.querySelector('.description, .desc, p, [class*="description"], [class*="detail"]');
                if (descEl && descEl !== headingEl) {
                    description = descEl.innerText.trim();
                } else {
                    description = textContent;
                }

                // Bütçe bulma (TL, ₺, $, € içeren metin)
                let budget = '';
                const priceMatch = textContent.match(/(\\d+[\\.,]?\\d*\\s*(?:TL|₺|USD|EUR|\\$|€))/i);
                if (priceMatch) {
                    budget = priceMatch[1].trim();
                }

                // Kategori bulma
                let category = '';
                const catEl = el.querySelector('.category, [class*="category"], .badge');
                if (catEl) {
                    category = catEl.innerText.trim();
                }

                // ID tespiti: URL'deki sayı veya link veya sıra
                let id = '';
                const idMatch = url.match(/\\/(\\d+)(?:[\\/?#]|$)/);
                if (idMatch) {
                    id = idMatch[1];
                } else if (url && url !== window.location.href) {
                    id = url;
                } else {
                    // İçerik karması (hash)
                    id = 'item_' + index + '_' + title.slice(0, 20);
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
        """Açık kalan oturumları temizler."""
        logger.info("Playwright adaptörü kapatıldı.")
