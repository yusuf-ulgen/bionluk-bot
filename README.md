# Bionluk İlan & Alıcı İstekleri Takip Botu

Bionluk alıcı isteklerini ve R10 Yazılım & Kodlama İş Verenler forumundaki yeni konuları takip eden, anahtar kelimelere göre filtreleyen ve Windows masaüstü bildirimi gönderen yerel uygulama.

R10 için **R10 Girişi (Chrome)** düğmesine basın. Açılan iş verenler sayfasının sağ üstündeki **Giriş Yap** bağlantısıyla R10 hesabınıza giriş yapın, ardından Chrome penceresini kapatın. R10 oturumu `data/r10_chrome_profile` içinde, Bionluk oturumu ise `data/chrome_profile` içinde ayrı tutulur. **Taramayı Başlat** her iki siteyi bağımsız izler; biri giriş beklerken diğeri çalışabilir. R10 kategorisinin ilk başarılı okuması mevcut konuları sessizce kaydeder; sonraki yeni konular bildirilir. R10 kayıtları `data/r10_database.sqlite3` içindedir.

R10 sayfası güvenlik doğrulaması veya erişim sınırı gösterirse uygulama bunu durum alanında bildirir. Doğrulamayı Chrome'da elle tamamlayın; uygulama güvenlik kontrolünü aşmaya çalışmaz.

**Tarama & Sistem Ayarları** sekmesinde Bionluk adresini değiştirebilir, izlenen R10 kategori bağlantısını açabilir ve R10 takibini açıp kapatabilirsiniz. Tarama aralığı iki site için ortaktır. **Şimdi Tara** etkin kaynakların ikisini de tetikler; üst bölümde her sitenin durumu, sonraki taraması ve son başarılı taraması ayrı görünür. İlan listesindeki **İlan Sitesi** seçimi ile Tümü, Bionluk veya R10 kayıtlarını görüntüleyebilirsiniz. Bildirim başlığı ve metni kaynağı açıkça belirtir.

---

## 🚀 Öne Çıkan Özellikler

1. **Tamamen Yerel ve Güvenli (Google ile Giriş Uyumlu):**
   - Şifrenizi veya hesap bilgilerinizi herhangi bir dosyaya ya da koda yazmanız gerekmez.
   - Uygulama içindeki **"Bionluk'a Giriş Yap"** butonu, bilgisayarınızda kurulu standart Google Chrome'u otomasyon veya test bayrakları olmadan bağımsız bir süreç olarak açar. Böylece Google'ın "Bu tarayıcı veya uygulama güvenli olmayabilir" engeline takılmadan Google hesabınızla rahatça giriş yapabilirsiniz.
   - Günlük kullandığınız Chrome profilinize dokunulmaz; uygulamaya özel `data/chrome_profile` dizininde oturumunuz yerel ve kalıcı olarak korunur.
   - Tarama aşamasında Playwright `channel="chrome"` kullanarak bu profille tutarlı çalışır.
   - Sunucu, bulut veya harici ücretli API gerektirmez.

2. **Dinamik Tarama Süresi ve Akıllı Bekleme:**
   - Arayüzden 15, 30, 60, 90, 120 saniye hızlı seçim yapabilir veya istediğiniz pozitif tam sayıyı yazabilirsiniz.
   - Tarama aralığı, **bir önceki tarama tamamlandıktan sonra bir sonraki taramaya kadar geçen bekleme süresi** olarak çalışır. Böylece uzun süren taramalarda görevler üst üste binmez.
   - Değer değiştirildiği an bir sonraki döngüye otomatik uygulanır, uygulamayı yeniden başlatmak gerekmez.
   - **"Şimdi Tara"** butonu ile periyodu beklemeden anlık kontrol yapılabilir.

3. **Gelişmiş Türkçe Arama & Filtreleme:**
   - **Dahil Edilecek Kelimeler:** En az biri eşleşen ilanlar yakalanır. Boş bırakılırsa hariç tutulanlar dışındaki tüm ilanlar kabul edilir.
   - **Hariç Tutulacak Kelimeler:** Önceliklidir. Eşleşen ilan elenir.
   - Türkçe karakter (İ/i, I/ı, Ş/s, Ç/c vb.) ve çok kelimeli ifadeler ("web tasarım", "mobil uygulama") desteklenir.
   - **Filtre Testi (Önizleme):** Yeni filtrelerinizi geçmiş ilanlar üzerinde bildirim göndermeden deneyebilirsiniz.

4. **Kalıcılık ve Bildirim Yağmuru Koruması:**
   - **İlk Tarama Koruması (Baseline):** Uygulama ilk açıldığında sayfadaki mevcut ilanları başlangıç kaydı olarak alır; yüzlerce eski ilan için bildirim yağmuru oluşturmaz.
   - **Deduplication (Tekilleştirme):** İlanlar benzersiz ID veya doğrulanmış kalıcı URL ile SQLite veritabanına kaydedilir. Uygulama kapatılıp açılsa bile eski ilanlar tekrar bildirilmez.
   - Başlık değişse dahi ilan yeni ilan muamelesi görmez.

5. **Windows Bildirimleri ve Sistem Tepsisi:**
   - Windows 10/11 yerel bildirim kartları (tıklayarak doğrudan ilanı açma desteği).
   - İsteğe bağlı Windows bildirim sesi.
   - Arayüzdeki ilana çift tıklayarak veya "İlanı Aç" butonuyla tarayıcıda açma.
   - Sistem tepsisine (Tray) küçültme ve arka planda sessizce çalışma.
   - Windows başlangıcında otomatik başlatma seçeneği (yönetici yetkisi gerektirmez).

---

## 🛠️ Kurulum Adımları (Windows PowerShell)

Uygulamanın çalışması için bilgisayarınızda **Python 3.10+** kurulu olmalıdır.

1. **PowerShell'i açın ve proje klasörüne gidin:**
   ```powershell
   cd d:\freelance\bionluk-bot
   ```

2. **Python Sanal Ortamını (venv) oluşturun ve aktif edin:**
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. **Gereksinimleri yükleyin:**
   ```powershell
   pip install -r requirements.txt
   ```

4. **Playwright Chromium tarayıcısını kurun:**
   ```powershell
   playwright install chromium
   ```

---

## ▶️ Uygulamayı Başlatma

### 1. Yöntem: Başlatıcı Dosyalar ile (Önerilen)
- Proje klasöründeki **`baslat.bat`** dosyasına çift tıklayın, veya
- PowerShell'de:
  ```powershell
  .\baslat.ps1
  ```
*(Hata oluşursa pencere hemen kapanmaz, hata mesajını okuyabilirsiniz).*

### 2. Yöntem: Doğrudan Komut Satırından
```powershell
.\.venv\Scripts\python.exe main.py
```

---

## 📖 Adım Adım Kullanım Rehberi

1. **Uygulamayı Açın:**
   - İlk açılışta veritabanı ve ayarlar otomatik hazırlanır.
2. **Hesabınıza Giriş Yapın:**
   - Üstteki **"Bionluk'a Giriş Yap (Tarayıcı Aç)"** butonuna tıklayın.
   - Bilgisayarınızda kurulu normal Google Chrome açılacaktır. "Google ile Giriş Yap" veya e-posta/şifrenizle Bionluk hesabınıza giriş yapın.
   - Giriş tamamlandıktan sonra bu açılan Chrome penceresini kapatın.
   - Uygulama oturumunuzu otomatik olarak doğrulayacak ve durum rozetini "OTURUM AKTİF" yapacaktır. Oturumunuz bu bilgisayarda saklanır.
3. **Takip URL'sini Belirleyin:**
   - "Tarama & Sistem Ayarları" sekmesinde Bionluk alıcı istekleri sayfasının bağlantısını girin ve "URL'yi Kaydet"e tıklayın.
4. **Filtrelerinizi Ayarlayın:**
   - "Filtreler" sekmesinde ilgilendiğiniz kelimeleri (örn: `python, bot, otomasyon, scraping`) girin.
   - İstemediğiniz kelimeleri hariç tutun (örn: `stajyer, ödev`).
   - "Filtreleri Kaydet"e tıklayın.
5. **Taramayı Başlatın:**
   - "Ana Kontroller" sekmesinden **"Taramayı Başlat"** butonuna basın.
   - Yeni bir ilan düştüğünde Windows masaüstünüzün sağ alt köşesinde bildirim çıkacak ve listede görüntülenecektir.

---

## 🧪 Otomatik Testleri Çalıştırma

Tüm filtreleme, tekilleştirme, zamanlayıcı ve hata toparlanma testlerini çalıştırmak için:
```powershell
.\.venv\Scripts\pytest -v
```
*(Tüm testler sahte adaptörler ile çalışır, gerçek hesap gerektirmez ve saniyeler içinde tamamlanır).*

---

## 📂 Dosya ve Dizin Yapısı

- `main.py` : Uygulama ana giriş noktası ve tekil kopya koruması.
- `src/config.py` : Ayarların okunması, doğrulanması ve saklanması (`data/config.json`).
- `src/storage.py` : SQLite veritabanı işlemleri (`data/bot_database.sqlite3`).
- `src/filter_engine.py` : Türkçe karakter uyumlu kelime eşleştirme motoru.
- `src/notifier.py` : Windows 10/11 Toast bildirimi ve ses kontrolü.
- `src/scheduler.py` : Arka plan tarama iş döngüsü, bekleme sayacı ve hata yönetimi.
- `src/scraper/playwright_adapter.py` : Playwright tabanlı Bionluk oturum ve veri çıkarma adaptörü.
- `src/scraper/r10_adapter.py` : R10 forumu için ayrı oturum ve konu çıkarma adaptörü.
- `src/ui/app.py` : Tkinter masaüstü arayüzü ve sistem tepsisi entegrasyonu.
- `baslat.bat` / `baslat.ps1` : Windows tek tıkla başlatıcıları.
