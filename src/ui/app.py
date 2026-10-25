"""
Bionluk İlan Takipçisi Tkinter Masaüstü Kullanıcı Arayüzü (GUI).
"""

from __future__ import annotations

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
        self.root.geometry("980x740")
        self.root.minsize(820, 600)

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

    def _apply_styles(self):
        self.style = ttk.Style()
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

        # Renk paleti
        self.color_bg = "#f5f6f8"
        self.color_card = "#ffffff"
        self.color_primary = "#00a885"      # Bionluk Yeşili
        self.color_primary_hover = "#008f71"
        self.color_danger = "#e53e3e"
        self.color_warning = "#dd6b20"
        self.color_text = "#2d3748"
        self.color_muted = "#718096"
        self.color_border = "#e2e8f0"

        self.root.configure(bg=self.color_bg)

        self.style.configure(".", font=("Segoe UI", 9), background=self.color_bg, foreground=self.color_text)
        self.style.configure("Card.TFrame", background=self.color_card, relief="flat")
        self.style.configure("TLabel", background=self.color_bg, foreground=self.color_text)
        self.style.configure("Card.TLabel", background=self.color_card, foreground=self.color_text)
        self.style.configure("Header.TLabel", font=("Segoe UI", 13, "bold"), background=self.color_card, foreground="#1a202c")
        self.style.configure("SubHeader.TLabel", font=("Segoe UI", 10, "bold"), background=self.color_card, foreground="#4a5568")

        # Buton stilleri
        self.style.configure("Primary.TButton", font=("Segoe UI", 9, "bold"), background=self.color_primary, foreground="#ffffff")
        self.style.map("Primary.TButton", background=[("active", self.color_primary_hover)])

        self.style.configure("Danger.TButton", font=("Segoe UI", 9, "bold"), background=self.color_danger, foreground="#ffffff")
        self.style.map("Danger.TButton", background=[("active", "#c53030")])

        # Treeview stili
        self.style.configure(
            "Treeview",
            background="#ffffff",
            fieldbackground="#ffffff",
            foreground="#2d3748",
            rowheight=26,
            font=("Segoe UI", 9),
        )
        self.style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"), background="#edf2f7", foreground="#2d3748")

    def _build_ui(self):
        # Ana Konteyner
        main_frame = ttk.Frame(self.root, padding=12)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 1. ÜST BİLGİ VE DURUM KARTI
        status_card = ttk.Frame(main_frame, style="Card.TFrame", padding=12)
        status_card.pack(fill=tk.X, pady=(0, 10))

        # Başlık ve Rozet
        top_row = ttk.Frame(status_card, style="Card.TFrame")
        top_row.pack(fill=tk.X)

        ttk.Label(top_row, text="Bionluk İlan & Alıcı İstekleri Takipçisi", style="Header.TLabel").pack(side=tk.LEFT)

        self.badge_lbl = tk.Label(
            top_row,
            text="DURDURULDU",
            font=("Segoe UI", 9, "bold"),
            bg="#edf2f7",
            fg="#718096",
            padx=10,
            pady=3,
            relief="flat",
        )
        self.badge_lbl.pack(side=tk.RIGHT)

        # Durum Sayaçları ve Bilgileri
        info_row = ttk.Frame(status_card, style="Card.TFrame")
        info_row.pack(fill=tk.X, pady=(8, 0))

        self.lbl_status_msg = ttk.Label(info_row, text="Durum: Hazır", style="Card.TLabel", font=("Segoe UI", 9, "bold"))
        self.lbl_status_msg.pack(side=tk.LEFT, padx=(0, 20))

        self.lbl_next_countdown = ttk.Label(info_row, text="Kalan Süre: --", style="Card.TLabel")
        self.lbl_next_countdown.pack(side=tk.LEFT, padx=(0, 20))

        self.lbl_last_scan = ttk.Label(info_row, text="Son Tarama: Henüz yapılmadı", style="Card.TLabel")
        self.lbl_last_scan.pack(side=tk.LEFT, padx=(0, 20))

        self.lbl_last_success = ttk.Label(info_row, text="Son Başarılı: Henüz yok", style="Card.TLabel")
        self.lbl_last_success.pack(side=tk.LEFT)

        # 2. SEKMELER (KONTROLLER VE AYARLAR)
        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=tk.X, pady=(0, 10))

        tab_controls = ttk.Frame(notebook, padding=10)
        tab_filters = ttk.Frame(notebook, padding=10)
        tab_settings = ttk.Frame(notebook, padding=10)

        notebook.add(tab_controls, text="  Ana Kontroller  ")
        notebook.add(tab_filters, text="  Filtreler (Dahil / Hariç)  ")
        notebook.add(tab_settings, text="  Tarama & Sistem Ayarları  ")

        # --- SEKME 1: ANA KONTROLLER ---
        ctrl_row = ttk.Frame(tab_controls)
        ctrl_row.pack(fill=tk.X, pady=4)

        self.btn_start = ttk.Button(ctrl_row, text="▶ Taramayı Başlat", style="Primary.TButton", command=self._start_scanning)
        self.btn_start.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_stop = ttk.Button(ctrl_row, text="⏹ Durdur", style="Danger.TButton", command=self._stop_scanning, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_scan_now = ttk.Button(ctrl_row, text="⚡ Şimdi Tara", command=self._scan_now)
        self.btn_scan_now.pack(side=tk.LEFT, padx=(0, 16))

        # Giriş yap ve Test Butonları
        self.btn_login = ttk.Button(ctrl_row, text="🔑 Bionluk'a Giriş Yap (Tarayıcı Aç)", command=self._open_login_browser)
        self.btn_login.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_test_notif = ttk.Button(ctrl_row, text="🔔 Test Bildirimi Gönder", command=self._send_test_notification)
        self.btn_test_notif.pack(side=tk.LEFT)

        # --- SEKME 2: FİLTRELER ---
        filters_grid = ttk.Frame(tab_filters)
        filters_grid.pack(fill=tk.X)

        # Dahil Kelimeler
        ttk.Label(filters_grid, text="Dahil Edilecek Kelimeler (En az biri eşleşmeli, boşsa hepsi kabul edilir):", font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 2))
        self.ent_include = ttk.Entry(filters_grid, width=70)
        self.ent_include.grid(row=1, column=0, sticky="ew", padx=(0, 10), pady=(0, 6))
        ttk.Label(filters_grid, text="Örn: python, flutter, web tasarım, logo, çeviri (Virgülle ayırın)", foreground=self.color_muted).grid(row=2, column=0, sticky="w", pady=(0, 8))

        # Hariç Kelimeler
        ttk.Label(filters_grid, text="Hariç Tutulacak Kelimeler (Önceliklidir, eşleşen elenir):", font=("Segoe UI", 9, "bold")).grid(row=3, column=0, sticky="w", pady=(0, 2))
        self.ent_exclude = ttk.Entry(filters_grid, width=70)
        self.ent_exclude.grid(row=4, column=0, sticky="ew", padx=(0, 10), pady=(0, 6))
        ttk.Label(filters_grid, text="Örn: stajyer, ücretsiz, ödev (Virgülle ayırın)", foreground=self.color_muted).grid(row=5, column=0, sticky="w", pady=(0, 8))

        filter_btn_row = ttk.Frame(filters_grid)
        filter_btn_row.grid(row=6, column=0, sticky="w")

        ttk.Button(filter_btn_row, text="💾 Filtreleri Kaydet", style="Primary.TButton", command=self._save_filters).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(filter_btn_row, text="🔍 Eski İlanlarla Filtre Testi (Önizleme)", command=self._test_filters_preview).pack(side=tk.LEFT)

        filters_grid.columnconfigure(0, weight=1)

        # --- SEKME 3: TARAMA VE SİSTEM AYARLARI ---
        set_grid = ttk.Frame(tab_settings)
        set_grid.pack(fill=tk.X)

        # URL
        ttk.Label(set_grid, text="Takip Edilen Bionluk URL Adresi:", font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 2))
        url_row = ttk.Frame(set_grid)
        url_row.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self.ent_url = ttk.Entry(url_row)
        self.ent_url.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        ttk.Button(url_row, text="URL'yi Kaydet", command=self._save_url).pack(side=tk.LEFT)

        # Tarama Aralığı
        ttk.Label(set_grid, text="Tarama Aralığı (Saniye):", font=("Segoe UI", 9, "bold")).grid(row=2, column=0, sticky="w", pady=(0, 2))
        interval_row = ttk.Frame(set_grid)
        interval_row.grid(row=3, column=0, sticky="w", pady=(0, 8))

        self.ent_interval = ttk.Entry(interval_row, width=8)
        self.ent_interval.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(interval_row, text="Aralığı Kaydet", command=self._save_interval).pack(side=tk.LEFT, padx=(0, 15))

        # Hızlı Seçim Butonları
        ttk.Label(interval_row, text="Hızlı Seçim:").pack(side=tk.LEFT, padx=(0, 5))
        for sec in [15, 30, 60, 90, 120]:
            ttk.Button(interval_row, text=f"{sec}s", width=4, command=lambda s=sec: self._quick_set_interval(s)).pack(side=tk.LEFT, padx=2)

        # Seçenekler (Ses ve Başlangıç)
        options_row = ttk.Frame(set_grid)
        options_row.grid(row=4, column=0, sticky="w", pady=(6, 0))

        self.var_sound = tk.BooleanVar(value=self.config_mgr.config.sound_enabled)
        ttk.Checkbutton(options_row, text="Bildirimde Ses Çal", variable=self.var_sound, command=self._toggle_sound).pack(side=tk.LEFT, padx=(0, 25))

        self.var_autostart = tk.BooleanVar(value=is_autostart_enabled())
        ttk.Checkbutton(options_row, text="Windows Başlangıcında Otomatik Başlat", variable=self.var_autostart, command=self._toggle_autostart).pack(side=tk.LEFT)

        set_grid.columnconfigure(0, weight=1)

        # 3. İLANLAR LİSTESİ (TREEVIEW)
        list_card = ttk.Frame(main_frame, style="Card.TFrame", padding=10)
        list_card.pack(fill=tk.BOTH, expand=True)

        list_header = ttk.Frame(list_card, style="Card.TFrame")
        list_header.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(list_header, text="Yakalanan İlanlar / Alıcı İstekleri", style="SubHeader.TLabel").pack(side=tk.LEFT)

        ttk.Button(list_header, text="🌐 Seçili İlanı Tarayıcıda Aç", command=self._open_selected_listing).pack(side=tk.RIGHT)

        # Tablo
        columns = ("time", "title", "budget", "category", "match", "status")
        self.tree = ttk.Treeview(list_card, columns=columns, show="headings", selectmode="browse")

        self.tree.heading("time", text="Zaman")
        self.tree.heading("title", text="İlan Başlığı")
        self.tree.heading("budget", text="Bütçe")
        self.tree.heading("category", text="Kategori")
        self.tree.heading("match", text="Eşleşen Kelime")
        self.tree.heading("status", text="Bildirim Durumu")

        self.tree.column("time", width=120, anchor="center")
        self.tree.column("title", width=380, anchor="w")
        self.tree.column("budget", width=90, anchor="center")
        self.tree.column("category", width=120, anchor="center")
        self.tree.column("match", width=110, anchor="center")
        self.tree.column("status", width=100, anchor="center")

        scrollbar = ttk.Scrollbar(list_card, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<Double-1>", lambda event: self._open_selected_listing())

        # Bilgi Notu
        ttk.Label(
            main_frame,
            text="* İlana çift tıklayarak veya butona basarak doğrudan Bionluk üzerinde açabilirsiniz.",
            foreground=self.color_muted,
            font=("Segoe UI", 8),
        ).pack(anchor="w", pady=(4, 0))

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
        )

    # --- BUTON VE AKSİYON İŞLEYİCİLERİ ---

    def _start_scanning(self):
        self.btn_start.configure(state=tk.DISABLED)
        self.btn_stop.configure(state=tk.NORMAL)
        self.scheduler.start()

    def _stop_scanning(self):
        self.scheduler.stop()
        self.btn_start.configure(state=tk.NORMAL)
        self.btn_stop.configure(state=tk.DISABLED)

    def _scan_now(self):
        self.scheduler.trigger_now()
        self.btn_start.configure(state=tk.DISABLED)
        self.btn_stop.configure(state=tk.NORMAL)

    def _open_login_browser(self):
        """Kullanıcının güvenle oturum açması için tarayıcı açar."""
        messagebox.showinfo(
            "Bionluk Giriş Penceresi",
            "Açılacak tarayıcı penceresinde Bionluk hesabınıza kendi bilgilerinizle giriş yapın.\n\n"
            "Giriş işlemini ve varsa 2 faktörlü doğrulamayı tamamladıktan sonra tarayıcıyı kapatabilirsiniz. "
            "Oturumunuz bu bilgisayarda güvenle saklanacaktır.",
        )
        url = self.config_mgr.config.target_url
        self.scraper_adapter.open_login_session(url)

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
            self.badge_lbl.configure(text="ÇALIŞIYOR", bg="#c6f6d5", fg="#22543d")
            self.btn_start.configure(state=tk.DISABLED)
            self.btn_stop.configure(state=tk.NORMAL)
        else:
            self.badge_lbl.configure(text="DURDURULDU", bg="#edf2f7", fg="#718096")
            self.btn_start.configure(state=tk.NORMAL)
            self.btn_stop.configure(state=tk.DISABLED)

        if status.requires_login:
            self.badge_lbl.configure(text="GİRİŞ GEREKİYOR", bg="#fed7d7", fg="#9b2c2c")

        self.lbl_status_msg.configure(text=f"Durum: {status.status_message}")

        if status.seconds_until_next_scan > 0:
            self.lbl_next_countdown.configure(text=f"Kalan Süre: {status.seconds_until_next_scan} sn")
        else:
            self.lbl_next_countdown.configure(text="Kalan Süre: --")

        if status.last_scan_time:
            self.lbl_last_scan.configure(text=f"Son Tarama: {status.last_scan_time}")

        if status.last_successful_scan_time:
            self.lbl_last_success.configure(text=f"Son Başarılı: {status.last_successful_scan_time}")

    # --- SİSTEM TEPSİSİ VE KAPATMA ---

    def _create_tray_image(self):
        """Sistem tepsisi için basit bir simge üretir."""
        img = Image.new("RGB", (64, 64), color=(0, 168, 133))
        draw = ImageDraw.Draw(img)
        draw.ellipse((14, 14, 50, 50), fill=(255, 255, 255))
        draw.ellipse((22, 22, 42, 42), fill=(0, 168, 133))
        return img

    def _setup_tray(self):
        if self.tray_icon:
            return

        image = self._create_tray_image()
        menu = pystray.Menu(
            pystray.MenuItem("Pencereyi Göster", self._show_window_from_tray, default=True),
            pystray.MenuItem("Şimdi Tara", lambda: self.scheduler.trigger_now()),
            pystray.MenuItem("Çıkış", self._exit_app_completely),
        )
        self.tray_icon = pystray.Icon("BionlukBot", image, "Bionluk İlan Takipçisi", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()
        self.is_tray_running = True

    def _show_window_from_tray(self):
        self.root.after(0, self._restore_window)

    def _restore_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _minimize_to_tray(self):
        self.root.withdraw()
        self._setup_tray()
        self.notifier.send_notification(
            title="Bionluk Takipçisi",
            message="Uygulama arka planda ve sistem tepsisinde çalışmaya devam ediyor.",
            sound=False,
        )

    def _on_close_requested(self):
        """Kapatma düğmesine basıldığında açık seçenek sunar."""
        if self.scheduler.is_running():
            response = messagebox.askyesnocancel(
                "Kapat veya Küçült",
                "Tarama şu anda arka planda çalışıyor.\n\n"
                "• 'Evet' : Sistem tepsisine küçült (taramaya devam et)\n"
                "• 'Hayır': Uygulamayı tamamen kapat ve taramayı durdur\n"
                "• 'İptal': Pencerede kal",
                icon="question",
            )
            if response is True:
                self._minimize_to_tray()
            elif response is False:
                self._exit_app_completely()
        else:
            self._exit_app_completely()

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
