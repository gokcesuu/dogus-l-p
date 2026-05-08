# Doğuş Üniversitesi LÖP – Yerli Uçuş Kontrol Kartı
## Yazılım Bileşenleri

Bu klasör, Doğuş Üniversitesi LÖP (Lisans Öğrenci Araştırma Projesi) kapsamında
geliştirilen yerli uçuş kontrol kartı için üç yazılım bileşeni içerir.

---

## Klasör Yapısı

```
dogus-lop-gcs/
├── gcs/                        ← Türkçe Yer İstasyonu (GCS)
│   ├── gcs_main.py             ← Ana uygulama (buradan başlat)
│   ├── mavlink_handler.py      ← MAVLink bağlantı yöneticisi
│   ├── ui_widgets.py           ← Özel arayüz bileşenleri
│   └── requirements.txt        ← Python bağımlılıkları
├── lua/
│   └── imu_thermal_control.lua ← ArduPilot IMU ısı kontrol scripti
├── docs/
│   └── SITL_KURULUM.md         ← SITL kurulum rehberi (detaylı)
└── README.md                   ← Bu dosya
```

---

## Ne Yaptık?

### 1. Türkçe Yer İstasyonu (GCS)
Mission Planner'ın yerini alacak, kartımıza özel Türkçe arayüz.

**Özellikler:**
- Yapay ufuk (roll / pitch / yaw animasyonu)
- Batarya durumu: voltaj, akım, yüzde (renkli doluluk çubuğu)
- Uçuş parametreleri: irtifa, hız, dikey hız, eve uzaklık
- GPS durumu: fix tipi, uydu sayısı, koordinat
- IMU sıcaklıkları: 3 ayrı IMU için renk kodlu gösterge
- Rüzgar: hız (m/s ve km/s) + yön oku
- Acil komut butonları: **EV'E DÖN (RTL)**, **ACİL İNİŞ**, Hovering, Devam Et
- Mod değiştirici: Sabitleme, Loiter, Otomatik, Kılavuz
- Sistem mesajları: tüm ArduPilot mesajları Türkçe loglanır
- EKF sağlık göstergesi

### 2. IMU Isı Kontrol Lua Scripti
ArduPilot üzerinde doğrudan çalışan, PCB'deki ısıtma dirençlerini yöneten script.

**Çalışma mantığı:**
- Her 200ms'de 3 IMU sıcaklığını okur
- `< 30°C` → ısıtıcıyı AÇAR (GPIO HIGH)
- `> 35°C` → ısıtıcıyı KAPATIR (GPIO LOW)
- `-10°C altı` → soğuk hava protokolü (hedef 40°C)
- Durum mesajlarını GCS'e Türkçe gönderir

### 3. SITL (Yazılımsal Uçuş Simülatörü)
PCB hazır olmadan önce tüm yazılımı test etmeye yarayan sanal ortam.
ArduPilot gerçek donanım yerine bilgisayarda çalışır.

---

## Kurulum (İlk Kez)

### Python GCS için:
```powershell
cd C:\Users\gkc_a\Desktop\dogus-lop-gcs\gcs
pip install -r requirements.txt
```

### SITL için (WSL2 + Ubuntu 22.04):
```bash
# Ubuntu terminalinde (bir kez yapılır):
cd ~
git clone https://github.com/ArduPilot/ardupilot.git
cd ardupilot
git submodule update --init --recursive
Tools/environment_install/install-prereqs-ubuntu.sh -y
source ~/.profile
```

---

## Her Oturumda Çalıştırma

### Adım 1 – SITL'i Başlat (Ubuntu terminali)
```bash
cd ~/ardupilot/ArduCopter
sim_vehicle.py -v ArduCopter --console --map --out=udp:172.20.0.1:14550
```
> `172.20.0.1` WSL2'nin Windows ana makine IP'si.
> Bu IP değişirse: `ip route | grep default | awk '{print $3}'` komutuyla öğren.

### Adım 2 – GCS'i Başlat (PowerShell)
```powershell
cd C:\Users\gkc_a\Desktop\dogus-lop-gcs\gcs
python gcs_main.py
```

### Adım 3 – Bağlan
- Bağlantı kutusuna: `udpin:0.0.0.0:14550`
- **Bağlan** butonuna tıkla
- Alt çubukta "Bağlantı kuruldu" yazınca hazır

---

## Lua Scriptini Kullanma (Gerçek Kart / SITL)

1. `imu_thermal_control.lua` dosyasını SD karttaki `/APM/scripts/` klasörüne koy
2. ArduPilot parametresini ayarla: `SCR_ENABLE = 1`
3. Yeniden başlat — script otomatik çalışır
4. GCS mesaj logunda `IMU-ISI:` ile başlayan mesajlar görünür

GPIO pin numaralarını kart pinout tablosuna göre `HEAT_PIN` dizisinde güncelle:
```lua
local HEAT_PIN = {54, 55, 56}  -- IMU 0, 1, 2 için GPIO pinleri
```

---

## Bağlantı Sorun Giderme

| Sorun | Çözüm |
|-------|-------|
| "Bağlantı bekleniyor" kalıyor | SITL çalışıyor mu kontrol et |
| Paneller `--` gösteriyor | SITL'de `output add 172.20.0.1:14550` yaz |
| IP değişti | `ip route \| grep default \| awk '{print $3}'` ile yeni IP'yi öğren |
| Port meşgul hatası | Başka bir GCS (Mission Planner) portu kullanıyor olabilir |

---

## MAVLink Test Araci

SITL veya Pi kopru baglantisini hizli kontrol etmek icin minimal bir test araci:

```powershell
cd C:\Users\gkc_a\Desktop\dogus-lop-gcs\gcs
python tools\mavlink_probe.py --conn udp:127.0.0.1:14550 --duration 10
```

Sifreli TCP (Pi kopru) icin:

```powershell
python tools\mavlink_probe.py --conn tcp:PI_IP:5760 --key C:\path\gcs_anahtar.key --duration 10
```

Beklenen ciktida HEARTBEAT ve STATUSTEXT mesajlarini gormelisiniz.

---

## Teknoloji Yığını

| Bileşen | Teknoloji |
|---------|-----------|
| GCS arayüzü | Python 3 + PyQt5 |
| MAVLink protokolü | pymavlink |
| Gerçek zamanlı grafik | pyqtgraph |
| Uçuş yazılımı | ArduPilot (açık kaynak) |
| Simülatör | ArduPilot SITL + MAVProxy |
| Kart scripti | Lua (ArduPilot yerleşik) |
| Geliştirme ortamı | WSL2 + Ubuntu 22.04 |

---

## Proje Bağlamı

**Üniversite:** Doğuş Üniversitesi  
**Proje Türü:** LÖP (Lisans Öğrenci Katılımlı Araştırma Projesi)  
**Süre:** 12 ay  
**Hedef:** Cube Orange'a alternatif yerli uçuş kontrol kartı  
**MCU:** STM32H743VIT6 (480 MHz, ARM Cortex-M7)  
**IMU:** ICM-42688-P × 2 + BMI088 (üçlü redundancy)  
