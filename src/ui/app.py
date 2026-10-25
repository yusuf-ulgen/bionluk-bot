"""
Bionluk İlan Takipçisi Tkinter Masaüstü Kullanıcı Arayüzü (GUI).
"""

from __future__ import annotations

import ctypes
import logging
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import List, Optional
import webbrowser

import pystray
from PIL import Image, ImageDraw

from ..autostart import is_autostart_enabled, set_autostart
from ..config import ConfigManager
from ..filter_engine import FilterEngine
from ..notifier import WindowsNotifier
from ..scheduler import JobScheduler, SchedulerStatus
from ..scraper.base import BaseScraperAdapter, Listing
from ..storage import Storage, StoredListing

logger = logging.getLogger("bionluk_bot.ui")


def hide_console():
    """Windows CMD / PowerShell konsol penceresini gizler."""
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if not hwnd:
            hwnd = ctypes.windll.user32.FindWindowW(None, "Bionluk Ilan Takipcisi")
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception as e:
        logger.debug(f"Konsol gizleme hatası: {e}")


def show_console():
    """Windows CMD / PowerShell konsol penceresini geri gösterir."""
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if not hwnd:
            hwnd = ctypes.windll.user32.FindWindowW(None, "Bionluk Ilan Takipcisi")
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 5)
    except Exception as e:
        logger.debug(f"Konsol gösterme hatası: {e}")


class BionlukBotApp:
    def __init__(
        self,
        config_mgr: ConfigManager,
        storage: Storage,
        filter_engine: FilterEngine,
        notifier: WindowsNotifier,
        scraper_adapter: BaseScraperAdapter,
    ):
        self.config_mgr = config_mgr
        self.storage = storage
        self.filter_engine = filter_engine
        self.notifier = notifier
        self.scraper_adapter = scraper_adapter

        self.root = tk.Tk()
        self.root.title("Bionluk İlan Takipçisi")
        self.root.geometry("1020x760")
        self.root.minsize(880, 640)

        # UI güncelleme kuyruğu (Thread safety)
        self.msg_queue: queue.Queue = queue.Queue()

        # Sistem tepsisi simgesi
        self.tray_icon: Optional[pystray.Icon] = None
        self.is_tray_running = False

        # Scheduler başlat
        self.scheduler = JobScheduler(
            config_mgr=self.config_mgr,
            storage=self.storage,
            filter_engine=self.filter_engine,
            notifier=self.notifier,
            scraper_adapter=self.scraper_adapter,
            status_callback=self._on_scheduler_status,
            on_new_listing_callback=self._on_new_listing,
        )

        self._apply_styles()
        self._build_ui()
        self._load_initial_data()

        # Düzenli kuyruk kontrolü
        self.root.after(100, self._process_queue)

        # Pencere kapatma olayı
        self.root.protocol("WM_DELETE_WINDOW", self._on_close_requested)

    def _set_btn_state(self, btn: tk.Button, enabled: bool, normal_bg: str, normal_fg: str = "#ffffff"):
        if enabled:
            btn.configure(state=tk.NORMAL, bg=normal_bg, fg=normal_fg, cursor="hand2")
        else:
            btn.configure(state=tk.DISABLED, bg="#f1f5f9", fg="#94a3b8", cursor="arrow")

    def _apply_styles(self):
        self.style = ttk.Style()
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

        # Modern renk paleti
        self.color_bg = "#f8fafc"           # Yumuşak Slate-50 arka plan
        self.color_card = "#ffffff"         # Beyaz kartlar
        self.color_primary = "#00a885"      # Bionluk Zümrüt Yeşili
        self.color_primary_hover = "#008f71"
        self.color_danger = "#ef4444"       # Modern Mercan Kırmızısı
        self.color_indigo = "#6366f1"       # İndigo Vurgu
        self.color_blue = "#0284c7"         # Mavi Vurgu
        self.color_text = "#0f172a"         # Slate-900
        self.color_text_muted = "#64748b"   # Slate-500
        self.color_border = "#e2e8f0"       # İnce kenarlık rengi

        self.root.configure(bg=self.color_bg)

        self.style.configure(".", font=("Segoe UI", 9), background=self.color_bg, foreground=self.color_text)
        self.style.configure("Card.TFrame", background=self.color_card, relief="flat")
        self.style.configure("TLabel", background=self.color_bg, foreground=self.color_text)
        self.style.configure("Card.TLabel", background=self.color_card, foreground=self.color_text)
        self.style.configure("Header.TLabel", font=("Segoe UI", 13, "bold"), background=self.color_card, foreground="#0f172a")
        self.style.configure("SubHeader.TLabel", font=("Segoe UI", 10, "bold"), background=self.color_card, foreground="#1e293b")

        # Sekme (Notebook) Stili
        self.style.configure("TNotebook", background=self.color_bg, borderwidth=0)
        self.style.configure("TNotebook.Tab", font=("Segoe UI", 9, "bold"), padding=(16, 7), background="#f1f5f9", foreground="#475569")
        self.style.map("TNotebook.Tab", background=[("selected", "#ffffff")], foreground=[("selected", "#00a885")])

        # Treeview Stili
        self.style.configure(
            "Treeview",
            background="#ffffff",
            fieldbackground="#ffffff",
            foreground="#1e293b",
            rowheight=32,
            font=("Segoe UI", 9),
            borderwidth=0,
        )
        self.style.configure(
            "Treeview.Heading",
            font=("Segoe UI", 9, "bold"),
            background="#f1f5f9",
            foreground="#1e293b",
            relief="flat",
            padding=(8, 8),
        )
        self.style.map("Treeview", background=[("selected", "#e0f2fe")], foreground=[("selected", "#0369a1")])

    def _build_ui(self):
        # Ana Konteyner
        main_frame = tk.Frame(self.root, bg=self.color_bg, padx=14, pady=12)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 1. ÜST BİLGİ VE DURUM KARTI
        status_card = tk.Frame(
            main_frame,
            bg=self.color_card,
            highlightbackground=self.color_border,
            highlightthickness=1,
            padx=16,
            pady=12,
        )
        status_card.pack(fill=tk.X, pady=(0, 10))

        # Başlık ve Rozet
        top_row = tk.Frame(status_card, bg=self.color_card)
        top_row.pack(fill=tk.X)

        tk.Label(
            top_row,
            text="⚡  Bionluk İlan & Alıcı İstekleri Takipçisi",
            font=("Segoe UI", 13, "bold"),
            bg=self.color_card,
            fg="#0f172a",
        ).pack(side=tk.LEFT)

        self.badge_lbl = tk.Label(
            top_row,
            text="DURDURULDU",
            font=("Segoe UI", 9, "bold"),
            bg="#f1f5f9",
            fg="#64748b",
            padx=12,
            pady=4,
            relief="flat",
        )
        self.badge_lbl.pack(side=tk.RIGHT)

        # Durum Sayaçları ve Bilgileri (Ayrıştırılmış, mükerrer süre bilgisi içermez)
        info_row = tk.Frame(status_card, bg=self.color_card)
        info_row.pack(fill=tk.X, pady=(10, 0))

        self.lbl_status_msg = tk.Label(
            info_row,
            text="Durum: Beklemede",
            font=("Segoe UI", 9, "bold"),
            bg=self.color_card,
            fg=self.color_primary,
        )
        self.lbl_status_msg.pack(side=tk.LEFT, padx=(0, 24))

        self.lbl_next_countdown = tk.Label(
            info_row,
            text="Kalan Süre: --",
            font=("Segoe UI", 9, "bold"),
            bg=self.color_card,
            fg="#0f172a",
        )
        self.lbl_next_countdown.pack(side=tk.LEFT, padx=(0, 24))

        self.lbl_last_scan = tk.Label(
            info_row,
            text="Son Tarama: Henüz yapılmadı",
            font=("Segoe UI", 9),
            bg=self.color_card,
            fg=self.color_text_muted,
        )
        self.lbl_last_scan.pack(side=tk.LEFT, padx=(0, 24))

        self.lbl_last_success = tk.Label(
            info_row,
            text="Son Başarılı: Henüz yok",
            font=("Segoe UI", 9),
            bg=self.color_card,
            fg=self.color_text_muted,
        )
        self.lbl_last_success.pack(side=tk.LEFT)

        # 2. SEKMELER (KONTROLLER VE AYARLAR)
        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=tk.X, pady=(0, 10))

        tab_controls = tk.Frame(notebook, bg=self.color_card, padx=12, pady=12)
        tab_filters = tk.Frame(notebook, bg=self.color_card, padx=14, pady=12)
        tab_settings = tk.Frame(notebook, bg=self.color_card, padx=14, pady=12)

        notebook.add(tab_controls, text="  Ana Kontroller  ")
        notebook.add(tab_filters, text="  Filtreler (Dahil / Hariç)  ")
        notebook.add(tab_settings, text="  Tarama & Sistem Ayarları  ")

        # --- SEKME 1: ANA KONTROLLER (RENKLİ & MODERN BUTONLAR) ---
        ctrl_row = tk.Frame(tab_controls, bg=self.color_card)
        ctrl_row.pack(fill=tk.X, pady=2)

        self.btn_start = tk.Button(
            ctrl_row,
            text="▶  Taramayı Başlat",
            font=("Segoe UI", 9, "bold"),
            bg="#00a885",
            fg="#ffffff",
            activebackground="#008f71",
            activeforeground="#ffffff",
            relief="flat",
            padx=14,
            pady=7,
            cursor="hand2",
            command=self._start_scanning,
        )
        self.btn_start.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_stop = tk.Button(
            ctrl_row,
            text="⏹  Durdur",
            font=("Segoe UI", 9, "bold"),
            bg="#f1f5f9",
            fg="#94a3b8",
            activebackground="#fee2e2",
            activeforeground="#dc2626",
            relief="flat",
            padx=14,
            pady=7,
            cursor="arrow",
            state=tk.DISABLED,
            command=self._stop_scanning,
        )
        self.btn_stop.pack(side=tk.LEFT, padx=(0, 12))

        self.btn_scan_now = tk.Button(
            ctrl_row,
            text="⚡  Şimdi Tara",
            font=("Segoe UI", 9, "bold"),
            bg="#6366f1",
            fg="#ffffff",
            activebackground="#4f46e5",
            activeforeground="#ffffff",
            relief="flat",
            padx=12,
            pady=7,
            cursor="hand2",
            command=self._scan_now,
        )
        self.btn_scan_now.pack(side=tk.LEFT, padx=(0, 12))

        # Giriş yap ve Test Butonları
        self.btn_login = tk.Button(
            ctrl_row,
            text="🔑  Bionluk Girişi (Chrome)",
            font=("Segoe UI", 9, "bold"),
            bg="#0284c7",
            fg="#ffffff",
            activebackground="#0369a1",
            activeforeground="#ffffff",
            relief="flat",
            padx=12,
            pady=7,
            cursor="hand2",
            command=self._open_login_browser,
        )
        self.btn_login.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_test_notif = tk.Button(
            ctrl_row,
            text="🔔  Test Bildirimi Gönder",
            font=("Segoe UI", 9),
            bg="#f1f5f9",
            fg="#334155",
            activebackground="#e2e8f0",
            activeforeground="#1e293b",
            relief="flat",
            padx=12,
            pady=7,
            cursor="hand2",
            command=self._send_test_notification,
        )
        self.btn_test_notif.pack(side=tk.LEFT)

        # --- SEKME 2: FİLTRELER ---
        filters_grid = tk.Frame(tab_filters, bg=self.color_card)
        filters_grid.pack(fill=tk.X)

        # Dahil Kelimeler
        tk.Label(
            filters_grid,
            text="Dahil Edilecek Kelimeler (En az biri eşleşmeli, boşsa hepsi kabul edilir):",
            font=("Segoe UI", 9, "bold"),
            bg=self.color_card,
            fg="#0f172a",
        ).grid(row=0, column=0, sticky="w", pady=(0, 2))

        self.ent_include = ttk.Entry(filters_grid, width=70)
        self.ent_include.grid(row=1, column=0, sticky="ew", padx=(0, 10), pady=(0, 6))

        tk.Label(
            filters_grid,
            text="Örn: python, flutter, web tasarım, logo, çeviri (Virgülle ayırın)",
            font=("Segoe UI", 8),
            bg=self.color_card,
            fg=self.color_text_muted,
        ).grid(row=2, column=0, sticky="w", pady=(0, 8))

        # Hariç Kelimeler
        tk.Label(
            filters_grid,
            text="Hariç Tutulacak Kelimeler (Önceliklidir, eşleşen elenir):",
            font=("Segoe UI", 9, "bold"),
            bg=self.color_card,
            fg="#0f172a",
        ).grid(row=3, column=0, sticky="w", pady=(0, 2))

        self.ent_exclude = ttk.Entry(filters_grid, width=70)
        self.ent_exclude.grid(row=4, column=0, sticky="ew", padx=(0, 10), pady=(0, 6))

        tk.Label(
            filters_grid,
            text="Örn: stajyer, ücretsiz, ödev (Virgülle ayırın)",
            font=("Segoe UI", 8),
            bg=self.color_card,
            fg=self.color_text_muted,
        ).grid(row=5, column=0, sticky="w", pady=(0, 8))

        filter_btn_row = tk.Frame(filters_grid, bg=self.color_card)
        filter_btn_row.grid(row=6, column=0, sticky="w")

        tk.Button(
            filter_btn_row,
            text="💾  Filtreleri Kaydet",
            font=("Segoe UI", 9, "bold"),
            bg="#00a885",
            fg="#ffffff",
            activebackground="#008f71",
            activeforeground="#ffffff",
            relief="flat",
            padx=12,
            pady=6,
            cursor="hand2",
            command=self._save_filters,
        ).pack(side=tk.LEFT, padx=(0, 10))

        tk.Button(
            filter_btn_row,
            text="🔍  Eski İlanlarla Filtre Testi (Önizleme)",
            font=("Segoe UI", 9),
            bg="#f1f5f9",
            fg="#334155",
            activebackground="#e2e8f0",
            relief="flat",
            padx=12,
            pady=6,
            cursor="hand2",
            command=self._test_filters_preview,
        ).pack(side=tk.LEFT)

        filters_grid.columnconfigure(0, weight=1)

        # --- SEKME 3: TARAMA VE SİSTEM AYARLARI ---
        set_grid = tk.Frame(tab_settings, bg=self.color_card)
        set_grid.pack(fill=tk.X)

        # URL
        tk.Label(
            set_grid,
            text="Takip Edilen Bionluk URL Adresi:",
            font=("Segoe UI", 9, "bold"),
            bg=self.color_card,
            fg="#0f172a",
        ).grid(row=0, column=0, sticky="w", pady=(0, 2))

        url_row = tk.Frame(set_grid, bg=self.color_card)
        url_row.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        self.ent_url = ttk.Entry(url_row)
        self.ent_url.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        tk.Button(
            url_row,
            text="URL'yi Kaydet",
            font=("Segoe UI", 9),
            bg="#f1f5f9",
            fg="#1e293b",
            relief="flat",
            padx=10,
            pady=4,
            cursor="hand2",
            command=self._save_url,
        ).pack(side=tk.LEFT)

        # Tarama Aralığı
        tk.Label(
            set_grid,
            text="Tarama Aralığı (Saniye):",
            font=("Segoe UI", 9, "bold"),
            bg=self.color_card,
            fg="#0f172a",
        ).grid(row=2, column=0, sticky="w", pady=(0, 2))

        interval_row = tk.Frame(set_grid, bg=self.color_card)
        interval_row.grid(row=3, column=0, sticky="w", pady=(0, 8))

        self.ent_interval = ttk.Entry(interval_row, width=8)
        self.ent_interval.pack(side=tk.LEFT, padx=(0, 8))

        tk.Button(
            interval_row,
            text="Aralığı Kaydet",
            font=("Segoe UI", 9),
            bg="#f1f5f9",
            fg="#1e293b",
            relief="flat",
            padx=10,
            pady=4,
            cursor="hand2",
            command=self._save_interval,
        ).pack(side=tk.LEFT, padx=(0, 15))

        # Hızlı Seçim Butonları
        tk.Label(interval_row, text="Hızlı Seçim:", font=("Segoe UI", 9), bg=self.color_card, fg=self.color_text_muted).pack(side=tk.LEFT, padx=(0, 5))
        for sec in [15, 30, 60, 90, 120]:
            tk.Button(
                interval_row,
                text=f"{sec}s",
                font=("Segoe UI", 8),
                bg="#f1f5f9",
                fg="#334155",
                relief="flat",
                padx=6,
                pady=2,
                cursor="hand2",
                command=lambda s=sec: self._quick_set_interval(s),
            ).pack(side=tk.LEFT, padx=2)

        # Seçenekler (Ses ve Başlangıç)
        options_row = tk.Frame(set_grid, bg=self.color_card)
        options_row.grid(row=4, column=0, sticky="w", pady=(8, 0))

        self.var_sound = tk.BooleanVar(value=self.config_mgr.config.sound_enabled)
        ttk.Checkbutton(options_row, text="Bildirimde Ses Çal", variable=self.var_sound, command=self._toggle_sound).pack(side=tk.LEFT, padx=(0, 25))

        self.var_autostart = tk.BooleanVar(value=is_autostart_enabled())
        ttk.Checkbutton(options_row, text="Windows Başlangıcında Otomatik Başlat", variable=self.var_autostart, command=self._toggle_autostart).pack(side=tk.LEFT)

        set_grid.columnconfigure(0, weight=1)

        # 3. İLANLAR LİSTESİ (TREEVIEW)
        list_card = tk.Frame(
            main_frame,
            bg=self.color_card,
            highlightbackground=self.color_border,
            highlightthickness=1,
            padx=14,
            pady=12,
        )
        list_card.pack(fill=tk.BOTH, expand=True)

        list_header = tk.Frame(list_card, bg=self.color_card)
        list_header.pack(fill=tk.X, pady=(0, 8))

        tk.Label(
            list_header,
            text="📋  Yakalanan İlanlar / Alıcı İstekleri",
            font=("Segoe UI", 10, "bold"),
            bg=self.color_card,
            fg="#0f172a",
        ).pack(side=tk.LEFT)

        tk.Button(
            list_header,
            text="🌐  Seçili İlanı Tarayıcıda Aç",
            font=("Segoe UI", 9, "bold"),
            bg="#00a885",
            fg="#ffffff",
            activebackground="#008f71",
            activeforeground="#ffffff",
            relief="flat",
            padx=12,
            pady=5,
            cursor="hand2",
            command=self._open_selected_listing,
        ).pack(side=tk.RIGHT)

        # Tablo
        columns = ("time", "title", "budget", "category", "match", "status")
        self.tree = ttk.Treeview(list_card, columns=columns, show="headings", selectmode="browse")

        self.tree.heading("time", text="Zaman")
        self.tree.heading("title", text="İlan Başlığı")
        self.tree.heading("budget", text="Bütçe")
        self.tree.heading("category", text="Kategori")
        self.tree.heading("match", text="Eşleşen Kelime")
        self.tree.heading("status", text="Bildirim Durumu")

        self.tree.column("time", width=140, anchor="center")
        self.tree.column("title", width=380, anchor="w")
        self.tree.column("budget", width=100, anchor="center")
        self.tree.column("category", width=120, anchor="center")
        self.tree.column("match", width=110, anchor="center")
        self.tree.column("status", width=110, anchor="center")

        # Alternating row tag colors
        self.tree.tag_configure("evenrow", background="#ffffff")
        self.tree.tag_configure("oddrow", background="#f8fafc")

        scrollbar = ttk.Scrollbar(list_card, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<Double-1>", lambda event: self._open_selected_listing())

        # Bilgi Notu
        tk.Label(
            main_frame,
            text="* İlana çift tıklayarak veya butona basarak doğrudan Bionluk üzerinde açabilirsiniz.",
            font=("Segoe UI", 8),
            bg=self.color_bg,
            fg=self.color_text_muted,
        ).pack(anchor="w", pady=(6, 0))

    def _load_initial_data(self):
        """Ayarları ve mevcut veritabanı kayıtlarını arayüze doldurur."""
        cfg = self.config_mgr.config
        self.ent_url.delete(0, tk.END)
        self.ent_url.insert(0, cfg.target_url)

        self.ent_interval.delete(0, tk.END)
        self.ent_interval.insert(0, str(cfg.scan_interval_seconds))

        self.ent_include.delete(0, tk.END)
        self.ent_include.insert(0, ", ".join(cfg.included_keywords))

        self.ent_exclude.delete(0, tk.END)
        self.ent_exclude.insert(0, ", ".join(cfg.excluded_keywords))

        # Son tarama zamanları
        last_success = self.storage.get_last_successful_scan()
        if last_success:
            self.lbl_last_success.configure(text=f"Son Başarılı: {last_success}")

        # Mevcut ilanları listele
        recent_listings = self.storage.get_recent_listings(limit=100)
        for item in recent_listings:
            self._insert_tree_item(item)

    def _insert_tree_item(self, item: StoredListing):
        status_txt = "Bildirildi" if item.notified else ("Hata" if item.notification_error else "Bekliyor")
        time_display = item.first_seen_at[:19].replace("T", " ") if item.first_seen_at else "--"

        row_count = len(self.tree.get_children())
        tag = "evenrow" if row_count % 2 == 0 else "oddrow"

        self.tree.insert(
            "",
            0,
            iid=item.listing_id,
            values=(
                time_display,
                item.title,
                item.budget or "-",
                item.category or "-",
                item.matched_keyword or "Tümü",
                status_txt,
            ),
            tags=(tag,),
        )

    # --- BUTON VE AKSİYON İŞLEYİCİLERİ ---

    def _start_scanning(self):
        if self.scraper_adapter.is_login_in_progress() or self.scraper_adapter.is_profile_locked():
            messagebox.showwarning(
                "Giriş Penceresi Açık",
                "Chrome giriş penceresi şu anda açık veya profil kullanımda.\n\n"
                "Lütfen Bionluk hesabınıza giriş yaptıktan sonra açılan Chrome penceresini kapatın.",
            )
            return

        self._set_btn_state(self.btn_start, False, "#00a885")
        self._set_btn_state(self.btn_stop, True, "#ef4444")
        self.scheduler.start()

    def _stop_scanning(self):
        self.scheduler.stop()
        self._set_btn_state(self.btn_start, True, "#00a885")
        self._set_btn_state(self.btn_stop, False, "#ef4444")

    def _scan_now(self):
        if self.scraper_adapter.is_login_in_progress() or self.scraper_adapter.is_profile_locked():
            messagebox.showwarning(
                "Giriş Penceresi Açık",
                "Chrome giriş penceresi şu anda açık veya profil kullanımda.\n\n"
                "Lütfen giriş işlemini tamamlayıp Chrome penceresini kapatın.",
            )
            return

        self.scheduler.trigger_now()
        self._set_btn_state(self.btn_start, False, "#00a885")
        self._set_btn_state(self.btn_stop, True, "#ef4444")

    def _open_login_browser(self):
        """Kullanıcının güvenle oturum açması için bağımsız Google Chrome açar."""
        if self.scraper_adapter.is_login_in_progress() or self.scraper_adapter.is_profile_locked():
            messagebox.showinfo(
                "Giriş Zaten Açık",
                "Chrome giriş penceresi zaten açık durumda.\n\n"
                "Lütfen açık olan Chrome penceresini kullanarak giriş yapın ve ardından pencereyi kapatın.",
            )
            return

        messagebox.showinfo(
            "Bionluk Google / Manuel Giriş",
            "Bilgisayarınızda kurulu standart Google Chrome açılacaktır.\n\n"
            "1. Açılan Chrome penceresinde (https://bionluk.com/login) 'Google ile Giriş Yap' butonuna veya e-posta/şifre alanına tıklayarak hesabınıza giriş yapın.\n"
            "2. Giriş yapıp sayfa açıldıktan sonra Chrome penceresini kapatın.\n\n"
            "Pencere kapatıldığında uygulamanız oturum durumunu otomatik olarak doğrulayacaktır.",
        )
        login_url = "https://bionluk.com/login"
        self.lbl_status_msg.configure(text="Durum: Chrome giriş penceresi açık, giriş yapılması bekleniyor...")
        self.badge_lbl.configure(text="GİRİŞ AÇIK", bg="#feebc8", fg="#7b341e")

        self.scraper_adapter.open_login_session(login_url, on_complete_callback=self._on_login_completed)

    def _on_login_completed(self, success: bool, msg: str):
        """Chrome kapandıktan sonra oturum doğrulama sonucunu arayüzde gösterir."""
        def _ui_update():
            if success:
                self.badge_lbl.configure(text="OTURUM AKTİF", bg="#c6f6d5", fg="#22543d")
                self.lbl_status_msg.configure(text="Durum: Oturum başarıyla doğrulandı. Taramaya hazır.")
                messagebox.showinfo(
                    "Oturum Doğrulandı",
                    "Tebrikler! Bionluk hesabınız başarıyla doğrulandı.\n\n"
                    "Artık 'Taramayı Başlat' düğmesine basarak ilan takibini başlatabilirsiniz.",
                )
            else:
                self.badge_lbl.configure(text="GİRİŞ GEREKİYOR", bg="#fed7d7", fg="#9b2c2c")
                self.lbl_status_msg.configure(text=f"Durum: {msg[:50]}")
                messagebox.showwarning(
                    "Oturum Doğrulanamadı",
                    f"Giriş penceresi kapatıldı ancak geçerli bir Bionluk oturumu tespit edilemedi:\n\n"
                    f"{msg}\n\n"
                    f"Lütfen 'Bionluk'a Giriş Yap' düğmesine basarak hesabınıza başarıyla giriş yaptığınızdan emin olun.",
                )

        self.root.after(0, _ui_update)

    def _send_test_notification(self):
        ok, err = self.notifier.send_test_notification()
        if not ok:
            messagebox.showerror("Bildirim Hatası", f"Test bildirimi gönderilemedi:\n{err}")
        else:
            messagebox.showinfo("Başarılı", "Test bildirimi gönderildi. Masaüstünüzün sağ alt köşesini kontrol edin.")

    def _quick_set_interval(self, seconds: int):
        self.ent_interval.delete(0, tk.END)
        self.ent_interval.insert(0, str(seconds))
        self._save_interval()

    def _save_interval(self):
        val_str = self.ent_interval.get().strip()
        ok, msg = self.config_mgr.update_interval(val_str)
        if ok:
            messagebox.showinfo("Kaydedildi", f"Tarama aralığı {val_str} saniye olarak güncellendi.")
        else:
            messagebox.showerror("Geçersiz Değer", msg)

    def _save_url(self):
        url = self.ent_url.get().strip()
        self.config_mgr.config.target_url = url
        ok, msg = self.config_mgr.save()
        if ok:
            messagebox.showinfo("Kaydedildi", "Takip URL'si güncellendi.")
        else:
            messagebox.showerror("Hata", msg)

    def _save_filters(self):
        inc_raw = self.ent_include.get().split(",")
        exc_raw = self.ent_exclude.get().split(",")
        inc = [k.strip() for k in inc_raw if k.strip()]
        exc = [k.strip() for k in exc_raw if k.strip()]

        self.filter_engine.update_rules(inc, exc)
        ok, msg = self.config_mgr.update_keywords(inc, exc)
        if ok:
            messagebox.showinfo("Kaydedildi", "Filtreler güncellendi ve hemen aktif edildi.")
        else:
            messagebox.showerror("Hata", msg)

    def _test_filters_preview(self):
        """Eski kaydedilmiş ilanlar üzerinde filtre önizlemesi yapar (Bildirim GÖNDERMEZ)."""
        inc_raw = self.ent_include.get().split(",")
        exc_raw = self.ent_exclude.get().split(",")
        temp_filter = FilterEngine(
            included_keywords=[k.strip() for k in inc_raw if k.strip()],
            excluded_keywords=[k.strip() for k in exc_raw if k.strip()],
        )

        recent = self.storage.get_recent_listings(limit=50)
        if not recent:
            messagebox.showinfo("Önizleme", "Veritabanında test edilecek kayıtlı ilan bulunmuyor.")
            return

        preview_win = tk.Toplevel(self.root)
        preview_win.title("Filtre Önizleme (Test - Bildirim Gönderilmez)")
        preview_win.geometry("700x450")

        lbl = ttk.Label(preview_win, text="Kayıtlı son ilanların güncel filtrelere göre durumu:", font=("Segoe UI", 10, "bold"))
        lbl.pack(anchor="w", padx=10, pady=8)

        text_area = tk.Text(preview_win, wrap=tk.WORD, font=("Segoe UI", 9))
        text_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        match_count = 0
        for item in recent:
            res = temp_filter.evaluate(item.title, item.description)
            durum = "✅ EŞLEŞTİ" if res.is_match else "❌ ELENDİ"
            if res.is_match:
                match_count += 1
            text_area.insert(
                tk.END,
                f"[{durum}] {item.title}\nSebep: {res.reason}\n{'-'*60}\n"
            )

        text_area.configure(state=tk.DISABLED)
        preview_win.title(f"Filtre Önizleme ({match_count}/{len(recent)} İlan Eşleşti)")

    def _toggle_sound(self):
        enabled = self.var_sound.get()
        self.config_mgr.config.sound_enabled = enabled
        self.notifier.sound_enabled = enabled
        self.config_mgr.save()

    def _toggle_autostart(self):
        enabled = self.var_autostart.get()
        ok = set_autostart(enabled)
        if ok:
            self.config_mgr.config.autostart_enabled = enabled
            self.config_mgr.save()
            durum = "etkinleştirildi" if enabled else "kaldırıldı"
            messagebox.showinfo("Başlangıç Ayarı", f"Windows başlangıcında otomatik başlatma {durum}.")
        else:
            self.var_autostart.set(not enabled)
            messagebox.showerror("Hata", "Windows başlangıç kaydı güncellenemedi.")

    def _open_selected_listing(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Seçim Yok", "Lütfen açmak istediğiniz ilanı listeden seçin.")
            return

        listing_id = selected[0]
        # Veritabanından linki al
        recent = self.storage.get_recent_listings(limit=200)
        target_url = None
        for item in recent:
            if item.listing_id == listing_id:
                target_url = item.url
                break

        if target_url and (target_url.startswith("http://") or target_url.startswith("https://")):
            webbrowser.open(target_url)
        else:
            messagebox.showerror("Hata", "İlan bağlantısı bulunamadı veya geçersiz.")

    # --- DURUM VE KUYRUK YÖNETİMİ ---

    def _on_scheduler_status(self, status: SchedulerStatus):
        self.msg_queue.put(("STATUS", status))

    def _on_new_listing(self, item: Listing, matched_keyword: str):
        self.msg_queue.put(("NEW_LISTING", item, matched_keyword))

    def _process_queue(self):
        while not self.msg_queue.empty():
            try:
                msg = self.msg_queue.get_nowait()
                msg_type = msg[0]

                if msg_type == "STATUS":
                    status: SchedulerStatus = msg[1]
                    self._update_status_ui(status)
                elif msg_type == "NEW_LISTING":
                    item: Listing = msg[1]
                    matched_kw: str = msg[2]
                    stored = StoredListing(
                        listing_id=item.id,
                        url=item.url,
                        title=item.title,
                        description=item.description,
                        budget=item.budget,
                        category=item.category,
                        first_seen_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                        notified=True,
                        matched_keyword=matched_kw,
                    )
                    self._insert_tree_item(stored)
            except queue.Empty:
                break
            except Exception as e:
                logger.error(f"Kuyruk işlenirken hata: {e}")

        self.root.after(200, self._process_queue)

    def _update_status_ui(self, status: SchedulerStatus):
        if status.is_running:
            if status.is_scanning_now:
                self.badge_lbl.configure(text="TARANIYOR", bg="#e0f2fe", fg="#0369a1")
                self.lbl_status_msg.configure(fg="#0284c7")
            else:
                self.badge_lbl.configure(text="ÇALIŞIYOR", bg="#ecfdf5", fg="#047857")
                self.lbl_status_msg.configure(fg="#00a885")
            self._set_btn_state(self.btn_start, False, "#00a885")
            self._set_btn_state(self.btn_stop, True, "#ef4444")
        else:
            self.badge_lbl.configure(text="DURDURULDU", bg="#f1f5f9", fg="#64748b")
            self.lbl_status_msg.configure(fg="#64748b")
            self._set_btn_state(self.btn_start, True, "#00a885")
            self._set_btn_state(self.btn_stop, False, "#ef4444")

        if status.requires_login:
            self.badge_lbl.configure(text="GİRİŞ GEREKİYOR", bg="#fef2f2", fg="#991b1b")
            self.lbl_status_msg.configure(fg="#dc2626")

        # Durum mesajı (Bağlantı ve oturum durumu)
        status_text = status.status_message or "Hazır"
        self.lbl_status_msg.configure(text=f"Durum: {status_text}")

        # Kalan Süre
        if status.seconds_until_next_scan > 0 and status.is_running:
            self.lbl_next_countdown.configure(text=f"Kalan Süre: {status.seconds_until_next_scan} sn")
        else:
            self.lbl_next_countdown.configure(text="Kalan Süre: --")

        if status.last_scan_time:
            self.lbl_last_scan.configure(text=f"Son Tarama: {status.last_scan_time}")

        if status.last_successful_scan_time:
            self.lbl_last_success.configure(text=f"Son Başarılı: {status.last_successful_scan_time}")

    # --- SİSTEM TEPSİSİ VE KAPATMA ---

    def _create_tray_image(self):
        """Sistem tepsisi için Bionluk zümrüt yeşili simge üretir."""
        img = Image.new("RGBA", (64, 64), color=(0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # Arka plan yuvarlak hap
        draw.ellipse((4, 4, 60, 60), fill=(0, 168, 133, 255))
        # İç çember / B harfi benzeri stil
        draw.ellipse((16, 16, 48, 48), fill=(255, 255, 255, 255))
        draw.ellipse((24, 24, 40, 40), fill=(0, 168, 133, 255))
        return img

    def _setup_tray(self):
        if self.tray_icon and self.is_tray_running:
            return

        image = self._create_tray_image()
        menu = pystray.Menu(
            pystray.MenuItem("Pencereyi Göster", lambda: self.root.after(0, self._restore_window), default=True),
            pystray.MenuItem("Konsolu Göster", lambda: self.root.after(0, show_console)),
            pystray.MenuItem("Şimdi Tara", lambda: self.root.after(0, self.scheduler.trigger_now)),
            pystray.MenuItem("Tamamen Kapat", lambda: self.root.after(0, self._exit_app_completely)),
        )
        self.tray_icon = pystray.Icon("BionlukBot", image, "Bionluk İlan Takipçisi", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True, name="TrayThread").start()
        self.is_tray_running = True

    def _show_window_from_tray(self):
        self.root.after(0, self._restore_window)

    def _restore_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _minimize_to_tray(self):
        """Uygulama arayüzünü ve konsol penceresini sistem tepsisine gizler."""
        hide_console()
        self.root.withdraw()
        self._setup_tray()
        self.notifier.send_notification(
            title="Bionluk Takipçisi",
            message="Uygulama arka planda ve sistem tepsisinde çalışmaya devam ediyor.",
            sound=False,
        )

    def _on_close_requested(self):
        """Kapatma (X) düğmesine basıldığında seçenek penceresi sunar."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Kapat veya Arka Planda Çalıştır")
        dialog.geometry("500x280")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg="#ffffff")

        # Pencereyi ana pencerenin tam ortasına konumlandır
        self.root.update_idletasks()
        rx = self.root.winfo_x() + (self.root.winfo_width() // 2) - 250
        ry = self.root.winfo_y() + (self.root.winfo_height() // 2) - 140
        dialog.geometry(f"+{max(0, rx)}+{max(0, ry)}")

        container = tk.Frame(dialog, bg="#ffffff", padx=24, pady=20)
        container.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            container,
            text="🛡️  Bionluk Takipçisi Kapatılıyor",
            font=("Segoe UI", 12, "bold"),
            bg="#ffffff",
            fg="#0f172a",
        ).pack(anchor="w")

        tk.Label(
            container,
            text="Uygulamanın arka planda yeni ilanları takip etmeye devam etmesini mi yoksa tamamen kapanmasını mı istersiniz?\n\n"
                 "• Arka Plan: Pencere ve siyah konsol ekranı sistem tepsisine gizlenir, yeni ilan düştüğünde bildirim gönderir.\n"
                 "• Tamamen Kapat: Takipçi ve tarayıcı motoru tamamen sonlandırılır.",
            font=("Segoe UI", 9),
            bg="#ffffff",
            fg="#475569",
            wraplength=450,
            justify="left",
        ).pack(anchor="w", pady=(8, 16))

        def on_tray_choice():
            dialog.destroy()
            self._minimize_to_tray()

        def on_exit_choice():
            dialog.destroy()
            self._exit_app_completely()

        btn_tray = tk.Button(
            container,
            text="🔄  Arka Planda Çalışmaya Devam Et (Önerilen)",
            font=("Segoe UI", 10, "bold"),
            bg="#00a885",
            fg="#ffffff",
            activebackground="#008f71",
            activeforeground="#ffffff",
            relief="flat",
            padx=16,
            pady=8,
            cursor="hand2",
            command=on_tray_choice,
        )
        btn_tray.pack(fill=tk.X, pady=(0, 8))

        btn_exit = tk.Button(
            container,
            text="❌  Tamamen Kapat",
            font=("Segoe UI", 9, "bold"),
            bg="#fef2f2",
            fg="#dc2626",
            activebackground="#fee2e2",
            activeforeground="#991b1b",
            relief="flat",
            padx=16,
            pady=6,
            cursor="hand2",
            command=on_exit_choice,
        )
        btn_exit.pack(fill=tk.X, pady=(0, 6))

        btn_cancel = tk.Button(
            container,
            text="Vazgeç (Pencerede Kal)",
            font=("Segoe UI", 8),
            bg="#ffffff",
            fg="#94a3b8",
            relief="flat",
            cursor="hand2",
            command=dialog.destroy,
        )
        btn_cancel.pack()

    def _exit_app_completely(self):
        """Uygulamayı ve çalışan tüm thread'leri temiz biçimde kapatır."""
        logger.info("Uygulama tamamen kapatılıyor...")
        try:
            self.scheduler.stop()
        except Exception:
            pass

        try:
            self.scraper_adapter.close()
        except Exception:
            pass

        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass

        self.root.after(50, self.root.destroy)

    def run(self):
        self.root.mainloop()


import time
