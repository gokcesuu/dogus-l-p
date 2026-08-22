# DogusFC — ArduPilot Board Tanımı

Bu klasör, DogusFC uçuş kontrol kartının ArduPilot (ChibiOS) board tanım
dosyalarını içerir. BOM'a göre hazırlanmış ve ArduPilot'un kendi parser'ı
(`chibios_hwdef.py`) ile pin çakışması olmadığı doğrulanmıştır.

**Durum: Statik olarak doğrulandı, GERÇEK DONANIMDA TEST EDİLMEDİ**
(kart henüz üretilmedi). Bootloader `.bin` dosyası da henüz derlenip
flaşlanmadı.

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
python libraries/AP_HAL_ChibiOS/hwdef/scripts/chibios_hwdef.py \
  libraries/AP_HAL_ChibiOS/hwdef/DogusFC/hwdef.dat  # statik doğrulama
./waf configure --board DogusFC
./waf copter   # ana firmware derlemesi
./waf bootloader   # bootloader derlemesi (henüz denenmedi)
```

## Kart üretildikten sonra yapılacaklar
1. PCB'de SWD header (4 pin: SWDIO/SWCLK/GND/3.3V) olduğundan emin ol
2. ST-Link/J-Link ile bootloader'ı `0x08000000`'a flaşla
3. USB üzerinden ana firmware'i yükle (bootloader artık DFU/MAVLink upload kabul eder)
4. GCS'den (`../gcs/`) bağlanıp Pre-Arm kontrol listesini çalıştır
