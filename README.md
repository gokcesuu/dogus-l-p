# Doğuş Üniversitesi LÖP – Yerli Uçuş Kontrol Kartı

## Yazılım Bileşenleri

Bu klasör, Doğuş Üniversitesi LÖP (Lisans Öğrenci Katılımlı Araştırma Projesi) kapsamında
geliştirilen yerli uçuş kontrol kartı için yer istasyonu, güvenlik ve otomasyon yazılımlarını içerir.

---

## Klasör Yapısı

```
dogus-lop-gcs/
├── gcs/                              ← Türkçe Yer İstasyonu + Yardımcı Araçlar
│   ├── gcs_main.py                   ← Ana GCS uygulaması (buradan başlat)
│   ├── mavlink_handler.py            ← MAVLink bağlantı yöneticisi (QThread)
│   ├── ui_widgets.py                 ← Özel arayüz bileşenleri (yapay ufuk, batarya barı)
│   ├── gcs_logger.py                 ← Thread-safe CSV uçuş logu yazıcısı
│   ├── config_yukleyici.py           ← config.json okuyucu (noktalı yol erişimi)
│   ├── sifreleme.py                  ← AES-256-GCM şifreli MAVLink katmanı
│   ├── anahtar_olustur.py            ← GCS ↔ Pi bağlantı anahtarı üreteci
│   ├── fence_yukle.py                ← AC_Fence dikdörtgen/çokgen yükleme aracı
│   ├── rally_yukle.py                ← Rally noktası yükleme aracı
│   ├── param_yukle.py                ← ArduPilot parametre yedekleme / geri yükleme
│   ├── terrain_analiz.py             ← Çok katmanlı güvenli iniş noktası analizörü
│   ├── alan_inis_karar.py            ← Uçuş alanı iniş uygunluğu karar motoru
│   ├── ucus_alani_hazirla.py         ← DEM indirme + arazi analizi + fence yükleme
│   ├── pi_karar_dongusu.py           ← Raspberry Pi'de çalışan otonom karar döngüsü
│   ├── ucus_raporu.py                ← Uçuş sonrası HTML rapor üreteci
│   ├── ucus_raporlayici.py           ← Rapor arayüz entegrasyonu
│   └── tools/
│       └── mavlink_probe.py          ← Hızlı MAVLink bağlantı test aracı
├── lua/                              ← ArduPilot Lua Scriptleri (SD kart → APM/scripts/)
│   ├── imu_thermal_control.lua       ← IMU ısı PID kontrolü (GPIO ısıtıcı)
│   ├── terrain_brake.lua             ← Düşük AGL'de otomatik BRAKE modu
│   ├── deadreckon_home.lua           ← GPS kayıpsa GUIDED_NOGPS + eve git
│   ├── acil_inis.lua                 ← Çok koşullu acil iniş tetikleyici
│   └── ana_sistem.lua                ← Batarya / rüzgar / EKF izleme ana scripti
├── tests/                            ← Otomatik testler
│   ├── conftest.py                   ← pytest fikstürleri
│   ├── test_terrain_analiz.py        ← Terrain analiz birim testleri
│   ├── test_sifreleme.py             ← AES-256 şifreleme testleri
│   ├── sitl_senaryo_test.py          ← SITL entegrasyon senaryoları
│   └── sitl_aes256_test.py           ← Şifreli bağlantı SITL testi
├── pi_kopru.py                       ← Raspberry Pi şifreli MAVLink köprüsü
├── config.json                       ← Merkezi konfigürasyon (tüm eşikler burada)
├── docs/
│   └── SITL_KURULUM.md               ← SITL kurulum rehberi (detaylı)
└── README.md                         ← Bu dosya
```

---

## Özellikler

### Türkçe Yer İstasyonu (GCS)

| Kategori                    | Özellik                                                                                  |
| --------------------------- | ----------------------------------------------------------------------------------------- |
| **Telemetri**         | Yapay ufuk (roll/pitch/yaw), batarya volt/akım/%, irtifa, hız, dikey hız, eve uzaklık |
| **GPS**               | Fix tipi, uydu sayısı, koordinat, Leaflet harita entegrasyonu                           |
| **IMU**               | 3 IMU için renk kodlu sıcaklık göstergesi                                             |
| **ESC Telemetrisi**   | 8 motora kadar RPM, sıcaklık (°C), voltaj, akım; 80°C+ kırmızı uyarı             |
| **Rüzgar**           | EMA filtreli hız (m/s) + yön oku; dikkat/tehlikeli/kritik eşikli uyarılar             |
| **EKF**               | Sağlık skoru renk göstergesi                                                           |
| **ADSB**              | 500m içindeki hava araçları haritada ✈ simgesiyle gösterilir, sesli uyarı           |
| **Terrain**           | AGL yüksekliği, bekleyen/yüklenen tile sayısı canlı izleme                          |
| **Acil Komutlar**     | EV'E DÖN (RTL), ACİL İNİŞ, Hovering, Devam Et, Güvenli İnişe Git                  |
| **Mod Değiştirici** | Sabitleme, Loiter, Otomatik, Kılavuz                                                     |
| **Mesaj Logu**        | Tüm ArduPilot STATUSTEXT mesajları Türkçe olarak loglanır                            |

### Güvenlik Katmanları

```
Katman 1 — GCS Failsafe
  GCS bağlantısı kesilince ArduPilot otomatik RTL başlatır
  (FS_GCS_ENABLE=1, timeout config.json'dan)

Katman 2 — RTL İzleyici
  RTL başladıktan sonra eve uzaklığı izler
  15sn stabil pencere + 25sn kontrol → ilerleme yoksa terrain analizi tetikler

Katman 3 — Rüzgar Koruma
  5.5 m/s → dikkat | 11.1 m/s → RTL + hız kısıtla | 16.7 m/s → güvenli iniş analizi

Katman 4 — Terrain Analizi (Çok Katmanlı)
  L1: SRTM Horn offset + bileşik skor
  L2: Ayak izi analizi (düz alan gereksinimi)
  L3: OSM engel kontrolü (ağaç/bina/su kütlesi)
  L4: Rüzgar skoru entegrasyonu

Katman 5 — Lua Scriptleri (ArduPilot üzerinde)
  terrain_brake.lua  → AGL < 30m ise BRAKE modu
  deadreckon_home.lua → GPS kayıpsa GUIDED_NOGPS + eve hızlan
```

### Arazi ve İniş Yeri Hazırlığı (`ucus_alani_hazirla.py`)

- **Copernicus GLO-30 DEM** indirme (S3 API, ücretsiz)
- Eğim haritası ve görsel çıktı (`--gorsel`)
- Güvenli iniş noktası skorlaması (eğim + OSM + rüzgar)
- AC_Fence dikdörtgen çit otomatik yükleme (`--fence-yukle`)

### Parametre Yönetimi (`param_yukle.py`)

```powershell
# Tüm parametreleri yedekle
python gcs/param_yukle.py yedekle --baglanti tcp:127.0.0.1:5762 --cikti yedek.json

# Belirli prefix'leri yedekle
python gcs/param_yukle.py yedekle --prefix BATT FS EKF

# Geri yükle
python gcs/param_yukle.py geri-yukle --json yedek.json

# Yedek ile mevcut karşılaştır
python gcs/param_yukle.py fark --json yedek.json
```

### Fence ve Rally Yükleme

```powershell
# Dikdörtgen fence yükle (bounding box)
python gcs/fence_yukle.py --lat-min 40.9 --lat-max 41.0 --lon-min 28.8 --lon-max 28.9

# NPZ'den otomatik fence
python gcs/ucus_alani_hazirla.py --alan 40.9 41.0 28.8 28.9 --fence-yukle tcp:127.0.0.1:5762

# Rally noktası yükle
python gcs/rally_yukle.py --noktalar rally.json
```

### Raspberry Pi Köprüsü (`pi_kopru.py`)

- Seri port (UART) ↔ TCP köprüsü
- AES-256-GCM şifreli tünel
- config.json'dan port/baud/anahtar okur
- Otomatik yeniden bağlantı

---

## Kurulum

### Python GCS için (Sıfırdan Kurulum — Adım Adım)

> 💡 Python'u daha önce hiç kurmadıysan buradan başla. Her adımı sırayla uygula.

---

#### Adım 1 — Python'u İndir ve Kur

1. Tarayıcıda şu adresi aç: **https://www.python.org/downloads/**
2. Büyük sarı **"Download Python 3.11.x"** düğmesine tıkla (sürüm numarası değişebilir, 3.11 veya daha yeni olsun)
3. İndirilen `.exe` dosyasını çalıştır
4. Kurulum ekranı açılınca **ilk şeyi yap: altta "Add Python to PATH"** kutucuğunu **mutlaka işaretle** ✅
   - Bu kutucuğu işaretlemezsen Python komutları çalışmaz!
5. **"Install Now"** düğmesine tıkla
6. Kurulum bitince **"Close"** düğmesine bas

---

#### Adım 2 — Python'un Düzgün Kurulduğunu Kontrol Et

1. Windows tuşuna bas, `powershell` yaz, **Enter**'a bas
2. Açılan siyah/mavi pencereye şunu yaz ve Enter'a bas:

```powershell
python --version
```

Ekranda `Python 3.11.x` gibi bir şey çıkmalı. Eğer:
- `'python' tanımlı değil` hatası çıkıyorsa → Python kurulurken "Add to PATH" kutucuğunu işaretlemedin. Python'u kaldırıp yeniden kur, bu sefer kutucuğu işaretle.
- `Python 2.7.x` çıkıyorsa → Eski Python var, `python3 --version` dene.

---

#### Adım 3 — Proje Klasörünü Bilgisayarına Al

**ZIP dosyası olarak aldıysan:**
1. ZIP dosyasına sağ tıkla → **"Tümünü Ayıkla"**
2. Hedef olarak Masaüstü'nü seç → **"Ayıkla"** düğmesine bas
3. Masaüstünde `dogus-lop-gcs` adlı bir klasör oluşmalı

**Zaten bilgisayarında klasör varsa:** Bu adımı atla, devam et.

---

#### Adım 4 — Doğru Klasörde Terminal Aç

1. **Dosya Gezgini**'ni aç (Başlat → "Dosya Gezgini" veya `Win + E`)
2. `dogus-lop-gcs` klasörüne gir
3. İçindeki **`gcs`** klasörüne çift tıkla
4. Üstteki **adres çubuğuna** tıkla (içinde `C:\...\gcs` gibi bir yol yazıyor)
5. Oraya `powershell` yaz ve **Enter**'a bas
6. Siyah/mavi bir PowerShell penceresi açılmalı — başında `PS C:\...\gcs>` yazıyor olmalı

> ⚠️ Bu adım önemli: Terminal'in `gcs` klasörünün **içinde** açılmış olması gerekiyor.

---

#### Adım 5 — Gerekli Kütüphaneleri Kur

Açık olan PowerShell penceresine şunu yaz ve Enter'a bas:

```powershell
pip install -r requirements.txt
```

- Yükleme **3–10 dakika** sürebilir, ekranda bir sürü yazı akacak — bu normal.
- En sonda `Successfully installed ...` yazısı görünmeli.
- İnternet bağlantın olduğundan emin ol.

---

#### Adım 6 — GCS Uygulamasını Başlat

Aynı PowerShell penceresinde:

```powershell
python gcs_main.py
```

GCS penceresi açılmalı. Açılmıyorsa aşağıdaki hata tablosuna bak.

---

#### Sorun Giderme — Kurulum Hataları

| Hata Mesajı | Neden Oluyor | Çözüm |
|-------------|-------------|-------|
| `'python' tanımlı değil` veya `'python' is not recognized` | Python PATH'e eklenmemiş | Python'u kaldır → yeniden kur → kurulumda **"Add to PATH"** kutusunu işaretle |
| `'pip' tanımlı değil` | Eski Python sürümü | `python -m pip install -r requirements.txt` komutunu dene |
| `Microsoft Visual C++ 14.0 required` | C++ derleme aracı eksik | Şu adresten "Build Tools" kur: https://visualstudio.microsoft.com/visual-cpp-build-tools/ |
| `rasterio` veya `GDAL` kurulumu başarısız | Windows'ta derleme sorunu | Aşağıdaki özel talimatı uygula ↓ |
| `No module named 'PyQt5'` | Kurulum başarısız olmuş | `pip install PyQt5 PyQtWebEngine` komutunu tekrar dene |
| `No module named 'gcs_main'` | Yanlış klasörde terminal açık | Adım 4'ü tekrar uygula, `gcs` klasörünün **içinde** olmalısın |
| GCS penceresi açılıp hemen kapanıyor | Hata var, terminal çıktısına bak | Terminal penceresinde kırmızı hata mesajını kopyala, ara |

---

#### Özel Durum — `rasterio` Windows'ta Kurulmuyorsa

`rasterio` kütüphanesi Windows'ta bazen hata verir. Bu durumda:

**Yöntem A (önerilen):**
```powershell
pip install rasterio --find-links https://github.com/cgohlke/geospatial-wheels/releases/latest
```

**Yöntem B (elle indirme):**
1. Şu adresi aç: https://github.com/cgohlke/geospatial-wheels/releases
2. En son sürümde `rasterio‑1.3.x‑cp311‑cp311‑win_amd64.whl` dosyasını indir
   - `cp311` = Python 3.11, `win_amd64` = 64-bit Windows
3. İndirilen `.whl` dosyasının tam yolunu bul (örn. `C:\Users\gkc_a\Downloads\rasterio-...whl`)
4. PowerShell'de çalıştır:
```powershell
pip install C:\Users\gkc_a\Downloads\rasterio-1.3.x-cp311-cp311-win_amd64.whl
```
5. Sonra tekrar `pip install -r requirements.txt` komutunu çalıştır

---

### SITL için (WSL2 + Ubuntu 22.04):

```bash
cd ~
git clone https://github.com/ArduPilot/ardupilot.git
cd ardupilot
git submodule update --init --recursive
Tools/environment_install/install-prereqs-ubuntu.sh -y
source ~/.profile
```

---

## Her Oturumda Çalıştırma

### Adım 1 – SITL'i Başlat (WSL / Ubuntu terminali)

**İstanbul konumunda başlat (önerilen):**
```bash
cd ~/ardupilot/ArduCopter && python3 ../Tools/autotest/sim_vehicle.py -v ArduCopter --console --map --custom-location=41.0082,28.9784,50,0
```

Her seferinde yazmamak için WSL'de alias tanımla (bir kere çalıştır):
```bash
echo "alias sitl='cd ~/ardupilot/ArduCopter && python3 ../Tools/autotest/sim_vehicle.py -v ArduCopter --console --map --custom-location=41.0082,28.9784,50,0'" >> ~/.bashrc && source ~/.bashrc
```
Bundan sonra sadece `sitl` yazmak yeterli.

Farklı şehirler için `--home` koordinatları:
| Şehir    | Koordinat                        |
|----------|----------------------------------|
| İstanbul | `41.0082,28.9784,50,0`           |
| Ankara   | `39.9334,32.8597,900,0`          |
| İzmir    | `38.4192,27.1287,30,0`           |

### Adım 2 – GCS'i Başlat (PowerShell)

```powershell
cd C:\Users\gkc_a\Desktop\dogus-lop-gcs\gcs
python gcs_main.py
```

### Adım 3 – Bağlan

- Bağlantı kutusuna: `tcp:127.0.0.1:5762`
- **Bağlan** butonuna tıkla
- GCS Failsafe otomatik ayarlanır

---

## Lua Scriptleri (SD Kart Kurulumu)

1. `lua/` klasöründeki `.lua` dosyalarını SD karttaki `/APM/scripts/` klasörüne kopyala
2. `SCR_ENABLE = 1` parametresini ayarla
3. Yeniden başlat — scriptler otomatik çalışır

| Script                      | Amaç                  | Kilit Parametre                            |
| --------------------------- | ---------------------- | ------------------------------------------ |
| `imu_thermal_control.lua` | IMU ısı kontrolü    | `HEAT_PIN` GPIO pinleri                  |
| `terrain_brake.lua`       | Düşük AGL'de BRAKE  | `SCR_USER1` = tetikleme yüksekliği (m) |
| `deadreckon_home.lua`     | GPS kayıpsa eve git   | Sabit kodlu (GPS_KAYIP_MS, MIN_IRTIFA_M)   |
| `acil_inis.lua`           | Acil iniş tetikleyici | `SCR_USER2` = tetikleme koşulu          |
| `ana_sistem.lua`          | Batarya/rüzgar izleme | `SCR_USER3` = düşük batarya eşiği   |

---

## Bağlantı Sorun Giderme

| Sorun                            | Çözüm                                                              |
| -------------------------------- | --------------------------------------------------------------------- |
| "Bağlantı bekleniyor" kalıyor | SITL çalışıyor mu kontrol et                                      |
| Paneller `--` gösteriyor      | SITL'de `output add 172.20.0.1:14550` yaz                           |
| IP değişti                     | `ip route \| grep default \| awk '{print $3}'` ile yeni IP'yi öğren |
| Port meşgul hatası             | Başka bir GCS (Mission Planner) portu kullanıyor olabilir           |
| GCS Failsafe tetikleniyor        | `FS_GCS_TIMEOUT` config.json'dan artırılabilir (varsayılan 10s)  |

---

## Testler

```powershell
cd C:\Users\gkc_a\Desktop\dogus-lop-gcs
pytest tests/ -v
```

| Test Dosyası              | Ne Test Eder                                       |
| -------------------------- | -------------------------------------------------- |
| `test_terrain_analiz.py` | Güvenli iniş noktası skoru, OSM engel kontrolü |
| `test_sifreleme.py`      | AES-256-GCM şifreleme/çözme                     |
| `sitl_senaryo_test.py`   | RTL, rüzgar, batarya, GPS kaybı senaryoları     |
| `sitl_aes256_test.py`    | Şifreli Pi köprüsü uçtan uca testi            |

---

## MAVLink Test Aracı

```powershell
# SITL bağlantısı
python gcs/tools/mavlink_probe.py --conn udp:127.0.0.1:14550 --duration 10

# Şifreli TCP (Pi köprüsü)
python gcs/tools/mavlink_probe.py --conn tcp:PI_IP:5760 --key gcs_anahtar.key --duration 10
```

---

## Teknoloji Yığını

| Bileşen                | Teknoloji                            |
| ----------------------- | ------------------------------------ |
| GCS arayüzü           | Python 3 + PyQt5                     |
| MAVLink protokolü      | pymavlink                            |
| Gerçek zamanlı grafik | pyqtgraph                            |
| Harita                  | PyQtWebEngine + Leaflet.js           |
| Terrain analizi         | numpy, rasterio, scipy               |
| OSM engel kontrolü     | overpy                               |
| DEM indirme             | boto3, pystac-client (Copernicus S3) |
| Şifreleme              | cryptography (AES-256-GCM)           |
| Uçuş yazılımı      | ArduPilot (açık kaynak)            |
| Simülatör             | ArduPilot SITL + MAVProxy            |
| Kart scriptleri         | Lua (ArduPilot yerleşik)            |
| Geliştirme ortamı     | WSL2 + Ubuntu 22.04                  |

---

## config.json

Tüm eşikler ve bağlantı parametreleri `config.json`'da toplanmıştır:

```json
{
  "baglanti":       { "varsayilan_dize": "tcp:127.0.0.1:5762" },
  "batarya":        { "dusuk_yuzde": 25, "kritik_yuzde": 15 },
  "ruzgar":         { "dikkat_ms": 5.5, "tehlikeli_ms": 11.1, "kritik_ms": 16.7 },
  "terrain":        { "analiz_adim_m": 150, "horn_ofset_m": 30 },
  "gcs_failsafe":   { "timeout_s": 10 },
  "adsb":           { "uyari_mesafe_m": 500 },
  "fence":          { "alt_max": 120.0, "action": 1 },
  "rtl_izleyici":   { "stabil_sure_s": 15, "kontrol_aralik_s": 25 },
  "copernicus":     { "kullanici_adi": "", "sifre": "" }
}
```

Copernicus DEM indirme için [dataspace.copernicus.eu](https://dataspace.copernicus.eu) adresinden
ücretsiz hesap aç ve S3 anahtarlarını `config.json`'a ekle.

---

## Proje Bağlamı

**Üniversite:** Doğuş Üniversitesi
**Proje Türü:** LÖP (Lisans Öğrenci Katılımlı Araştırma Projesi)
**Süre:** 12 ay
**Hedef:** Cube Orange'a alternatif yerli uçuş kontrol kartı
**MCU:** STM32H743VIT6 (480 MHz, ARM Cortex-M7)
**IMU:** ICM-42688-P × 2 + BMI088 (üçlü redundancy)
