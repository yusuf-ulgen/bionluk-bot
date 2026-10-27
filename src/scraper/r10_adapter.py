"""R10 yazılım iş verenler forumu için ayrı Chrome profilli okuyucu."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

from .base import Listing, ScrapeResult
from .playwright_adapter import PlaywrightBionlukAdapter, find_chrome_executable

R10_URL = "https://www.r10.net/yazilim-kodlama-is-verenler/"
logger = logging.getLogger("bionluk_bot.scraper.r10")


def parse_threads(rows: list[dict]) -> list[Listing]:
    """Konu kimliği ve ilk sayfa bağlantısını normalize edip tekrarları atar."""
    result: list[Listing] = []
    seen: set[str] = set()
    for row in rows:
        url = str(row.get("url", ""))
        match = re.search(r"/yazilim-kodlama-is-verenler/(\d+)-[^/?#]+\.html", url)
        title = str(row.get("title", "")).strip()
        if not match or not title or match.group(1) in seen or row.get("sticky"):
            continue
        seen.add(match.group(1))
        result.append(Listing(
            id=f"r10:{match.group(1)}", title=title, url=url.split("?")[0].split("#")[0],
            category="R10", description=str(row.get("description", "")).strip(),
        ))
    return result


class PlaywrightR10Adapter(PlaywrightBionlukAdapter):
    login_url = "https://www.r10.net/login.php"
    verify_url = R10_URL

    def __init__(self, profile_dir: Path | str | None = None, headless: bool = True):
        if profile_dir is None:
            profile_dir = Path(__file__).resolve().parents[2] / "data" / "r10_chrome_profile"
        super().__init__(profile_dir, headless)

    def verify_session(self, url: str = R10_URL) -> tuple[bool, str]:
        if self.is_profile_locked():
            return False, "R10 giriş penceresini kapatın; oturum ardından doğrulanacak."
        if not find_chrome_executable():
            return False, "Google Chrome bulunamadı."
        try:
            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(self.profile_dir.resolve()), channel="chrome", headless=True,
                )
                try:
                    page = context.pages[0] if context.pages else context.new_page()
                    response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    if response and response.status == 403:
                        return False, "R10 erişimi engelledi veya güvenlik doğrulaması istiyor. R10 Girişi ile açılan pencerede kontrol edin."
                    if not response or response.status >= 400:
                        return False, f"R10 sayfası açılamadı (HTTP {response.status if response else 'yanıt yok'})."
                    if self._is_guest(page):
                        return False, "R10 oturumu açık görünmüyor. R10 Girişi ile hesabınıza giriş yapın."
                    return True, "R10 oturumu doğrulandı."
                finally:
                    context.close()
        except Exception as exc:
            logger.exception("R10 oturumu doğrulanamadı")
            return False, f"R10 oturumu doğrulanamadı: {exc}"

    @staticmethod
    def _is_guest(page) -> bool:
        return bool(page.locator("a.login[href*='#girisModal'], a[href*='login.php?do=login']").count()) and not bool(
            page.locator("a[href*='logout.php'], a[href*='do=logout']").count()
        )

    def scrape_listings(self, url: str = R10_URL) -> ScrapeResult:
        if self.is_profile_locked():
            return ScrapeResult(False, error_message="R10 giriş penceresi açık; kapatılınca tarama sürecek.")
        if not find_chrome_executable():
            return ScrapeResult(False, error_message="Google Chrome bulunamadı.")
        with self._lock:
            try:
                with sync_playwright() as p:
                    context = p.chromium.launch_persistent_context(
                        user_data_dir=str(self.profile_dir.resolve()), channel="chrome", headless=self.headless,
                    )
                    try:
                        page = context.pages[0] if context.pages else context.new_page()
                        response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        if response and response.status == 429:
                            return ScrapeResult(False, error_message="R10 erişim sınırı uyguladı.", rate_limited=True, retry_after_seconds=120)
                        if response and response.status == 403:
                            return ScrapeResult(False, error_message="R10 erişimi engelledi veya güvenlik doğrulaması istiyor. R10 Girişi ile kontrol edin.", requires_login=True)
                        if not response or response.status >= 400:
                            return ScrapeResult(False, error_message=f"R10 sayfası açılamadı (HTTP {response.status if response else 'yanıt yok'}).")
                        if "login.php" in page.url or self._is_guest(page):
                            return ScrapeResult(False, error_message="R10 oturumu açık değil veya süresi doldu.", requires_login=True)
                        if page.locator("input[name='cf-turnstile-response'], #challenge-running").count():
                            return ScrapeResult(False, error_message="R10 güvenlik doğrulaması istiyor. R10 Girişi ile açılan pencerede doğrulayın.", requires_login=True)
                        rows = page.evaluate("""() => Array.from(document.querySelectorAll(
                            'a[id^="thread_title_"]'
                        )).map(a => {
                            const row = a.closest('.thread, tr, li, .structItem, .threadbit');
                            const href = a.href;
                            const title = (a.innerText || '').trim();
                            const classes = (row?.className || '').toString().toLowerCase();
                            const heading = (a.parentElement?.innerText || '').toLowerCase();
                            return {url: href, title, sticky: /sticky|sabit/.test(classes) || heading.includes('sabit'),
                                description: ''};
                        })""")
                        listings = parse_threads(rows)
                        if not listings:
                            return ScrapeResult(False, error_message="R10 konu listesi okunamadı; sayfa yapısı veya erişim değişmiş olabilir.")
                        return ScrapeResult(True, listings=listings)
                    finally:
                        context.close()
            except Exception as exc:
                logger.exception("R10 taraması başarısız")
                return ScrapeResult(False, error_message=f"R10 taraması başarısız: {exc}")
