# DogusFC — ArduPilot Board Tanımı

Bu klasör, DogusFC uçuş kontrol kartının ArduPilot (ChibiOS) board tanım
dosyalarını içerir. BOM'a göre hazırlanmış ve ArduPilot'un kendi parser'ı
(`chibios_hwdef.py`) ile pin çakışması olmadığı doğrulanmıştır.

**Durum: Uçtan uca DERLENİYOR (bootloader + ana firmware), GERÇEK DONANIMDA
HENÜZ TEST EDİLMEDİ** (kart henüz üretilmedi).

`./waf configure --board DogusFC && ./waf bootloader && ./waf copter`
gerçekten çalıştırılıp doğrulandı:
- `Tools/bootloaders/DogusFC_bl.bin` — 20228 B flash
- `build/DogusFC/bin/arducopter.bin` — 1.498.448 B flash kullanılan, 467.620 B boş

Bu derleme sırasında statik parser'ın yakalamadığı **2 gerçek hata** bulunup
düzeltildi:
1. `SERIAL_ORDER`'da hiçbir pine atanmamış bir `UART7` girdisi vardı —
   derleyici `SD7` sürücüsünü bulamayıp hata veriyordu.
2. `BARO BMP390` yazılmıştı ama ArduPilot'ta böyle bir sürücü sınıfı yok —
   BMP390, register uyumlu olduğu için resmi kartlarda da (örn.
   Airvolute-DCS2) `BARO BMP388` sürücüsüyle kullanılıyor.

## Dosyalar
- `hwdef.dat` — ana firmware board tanımı (dual IMU: ICM-42688-P + BMI088
  ayrı SPI hatlarında, FM25CL64B FRAM, TCAN334GDCNT CAN, tek MCU — IOMCU yok)
- `hwdef-bl.dat` — bootloader board tanımı
- `sdcard.inc` — SD kart pin tanımı
- `defaults.parm` — varsayılan ArduPilot parametreleri

## Kullanım (ArduPilot ana reposu içinde)

Bu dosyaları resmi ArduPilot kaynak ağacında derlemek için:

```bash
git clone --recurse-submodules https://github.com/ArduPilot/ardupilot.git
cp firmware/DogusFC/*.dat firmware/DogusFC/*.inc firmware/DogusFC/*.parm \
   ardupilot/libraries/AP_HAL_ChibiOS/hwdef/DogusFC/
cd ardupilot
python3 Tools/scripts/build_bootloaders.py DogusFC   # -> Tools/bootloaders/DogusFC_bl.bin
./waf configure --board DogusFC
./waf copter                                          # -> build/DogusFC/bin/arducopter.bin
```

## Bilinen Donanım Riskleri (PCB/Şematik Ekibine)

`FCU_Tasarim_ve_Entegrasyon_Kilavuzu.pdf` referans alınarak:

1. **Harici manyetometre zorunlu** — kartta dahili pusula yok, yön kestirimi
   için harici GPS modülü içine entegre (I2C) manyetometre kullanılmalı.
2. **Tek işlemcili RC/PWM yönetimi** — IOMCU (STM32F103) kaldırıldığı için
   RC alıcı (S.Bus/CRSF/DSM) doğrudan STM32H753 UART'ına bağlanmalı;
   S.Bus kullanılacaksa UART donanımının dahili Invert özelliği aktifleştirilmeli.
3. **PWM port izolasyonu** — ESC/motor sinyal hatlarına seri **33 Ω – 100 Ω**
   sönümleme direnci eklenmeli, ESC besleme hattı FCU'nun 3.3V hattına
   **kesinlikle temas etmemeli**. (`hwdef.dat`'ta PWM tanımlarının yanına
   yorum olarak da not düşüldü — bu satırlar PCB seviyesinde çözülür.)

## Kart Üretildikten Sonra — 7 Aşamalı Bring-Up Yol Haritası

`FCU_Yazilim_ve_Firmware_Entegrasyon_Kilavuzu.pdf` referans alınarak,
sıfırdan ilk güvenli test uçuşuna kadar:

| # | Aşama | Amaç | Geçiş Kriteri |
|---|-------|------|----------------|
| 1 | **Güç Katmanı & LDO Doğrulaması** | Kısa devre yok, TPS62132/LP5907 çıkışları doğru | 3.3V ±%1, <10mV ripple, <50mA bekleme akımı |
| 2 | **MCU Bring-Up & Bootloader** | SWD ile uyandırma, osilatör testi, bootloader flaşlama | USB takılınca kart DFU/VCP olarak tanınıyor |
| 3 | **Dahili Sensörler & Hafıza Bus Testleri** | SPI sensörlerinin WHO_AM_I okunması, FRAM/SDMMC doğrulama | Sensörler %0 bus hatasıyla 1-2 kHz'de okunuyor |
| 4 | **Harici Portlar & Çevre Birimleri** | GNSS+Pusula, RC, telemetri, CAN doğrulama | EKF "Good", GPS 3D Fix |
| 5 | **Gövde Entegrasyonu & Failsafe** (⚠️ pervanesiz) | Motor/ESC bağlama, RC kaybı/düşük pil/kill-switch testi | Tüm failsafe senaryoları masa başında %100 başarılı |
| 6 | **Tethered (İple Sabitlenmiş) Yer Testi** | Pervaneli kapalı çevrim kontrolü güvenle sınırlama | Kararlı itki, titreşim <15 m/s² |
| 7 | **İlk Serbest Test Uçuşu (Maiden Flight)** | Bağımsız uçuş kararlılığı | Titreşimsiz hover, EKF inovasyon sınırda, güvenli iniş |

**Altın kurallar**: pervanesiz test kuralına asla istisna yok · sürücüler
non-blocking (DMA/interrupt) olmalı, `while(!ready)` gibi bloklayan kod
400 Hz kontrol döngüsünü kilitler · CPU yükü (`PM: Load`) MAVLink
üzerinden %60'ın altında tutulmalı, bağımsız donanımsal watchdog (IWDG)
100ms içinde güvenli moda geçirir.

## Referans Kaynaklar
Bu README, ekibe iletilen iki mühendislik kılavuzuna dayanıyor (repoya eklenmedi,
harici belge olarak saklanıyor):
- *FCU Tasarım ve Entegrasyon Kılavuzu* — donanım mimarisi, risk analizi
- *FCU Yazılım ve Firmware Entegrasyon Kılavuzu* — firmware katmanları, derleme adımları, yazılım test aşamaları
