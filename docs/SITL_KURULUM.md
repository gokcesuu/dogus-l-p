# ArduPilot SITL Kurulum Rehberi
## Windows 11 + WSL2 — Doğuş ÜNİ LÖP

Bu rehber, ArduPilot Yazılımsal Uçuş Simülatörü'nü (SITL) Windows üzerinde
WSL2 aracılığıyla çalıştırmayı ve Türkçe GCS'e bağlamayı anlatır.

---

## 1. WSL2 Kurulumu

**PowerShell (Yönetici olarak aç):**
```powershell
wsl --install -d Ubuntu-22.04
```

Yükleme tamamlanınca bilgisayarı yeniden başlatın.
Ubuntu açıldığında kullanıcı adı ve şifre belirleyin.

> **Not:** Daha önce WSL1 kuruluysa önce WSL2'ye yükseltin:
> ```powershell
> wsl --set-default-version 2
> wsl --set-version Ubuntu-22.04 2
> ```

---

## 2. Ubuntu'yu Hazırlama

WSL2 Ubuntu terminalini açın:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git python3-pip python3-venv curl wget
```

---

## 3. ArduPilot Kaynak Kodu

```bash
cd ~
git clone https://github.com/ArduPilot/ardupilot.git
cd ardupilot
git submodule update --init --recursive
```

> Submodule işlemi 5-10 dakika sürebilir.

### Gerekli Bağımlılıkları Yükle

```bash
Tools/environment_install/install-prereqs-ubuntu.sh -y
source ~/.profile
```

Yükleme sonunda terminali kapatıp yeniden açın (PATH güncellemesi için).

---

## 4. SITL'i Başlatma

### ArduCopter (Multikopter)

```bash
cd ~/ardupilot/ArduCopter
sim_vehicle.py -v ArduCopter --console --map
```

İstanbul konumu için başlangıç noktasını ayarlamak isterseniz:

```bash
sim_vehicle.py -v ArduCopter --console --map \
  --home=41.015137,28.979530,30,0
# 41.015137, 28.979530 = İstanbul (Doğuş Üniversitesi yakını)
```

İlk çalıştırmada derleme birkaç dakika sürer.

### Başarılı Başlatma Çıktısı (örnek)

```
SIM_VEHICLE: Searching for a free TCP port for SITL...
SIM_VEHICLE: Starting SITL: ...
SIM_VEHICLE: Frame:       +
SIM_VEHICLE: Connect ...  MAVLink 2
Waiting for heartbeat from 127.0.0.1:14550
```

SITL varsayılan olarak şu portları açar:
| Port | Amaç |
|------|------|
| `tcp:5760` | MAVProxy ana bağlantısı |
| `udp:127.0.0.1:14550` | GCS çıkışı (Python GCS buraya bağlanır) |
| `udp:127.0.0.1:14551` | İkincil bağlantı |

---

## 5. Türkçe GCS'i Bağlama (Windows tarafı)

### Python Ortamı Kurulumu

Windows PowerShell veya CMD'de:

```powershell
cd <proje-klasörü>\flight-control\gcs
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### GCS'i Başlatma

```powershell
python gcs_main.py
```

Arayüz açıldığında bağlantı kutusuna yazın:

```
udp:127.0.0.1:14550
```

**Bağlan** butonuna tıklayın. SITL'den heartbeat geldiğinde tüm paneller dolmaya başlar.

> **WSL2 ağ notu:** WSL2, Windows ana makinesinin ağ yığınını paylaşır.
> `127.0.0.1:14550`'e Windows uygulamasından erişmek için WSL2'nin
> `localhost` yönlendirmesi otomatik çalışır (Windows 10 2004+ ve WSL2).

---

## 6. IMU Isı Kontrol Scriptini Test Etme

### Parametreyi Ayarla

MAVProxy konsolunda (SITL terminali):

```
param set SCR_ENABLE 1
```

### Scripti SITL'e Bağla

SITL scripts dizinini oluşturun ve scripti kopyalayın:

```bash
mkdir -p ~/ardupilot/ArduCopter/scripts
cp <proje>/flight-control/lua/imu_thermal_control.lua \
   ~/ardupilot/ArduCopter/scripts/
```

SITL'i yeniden başlatın:

```bash
sim_vehicle.py -v ArduCopter --console --map \
  --home=41.015137,28.979530,30,0 \
  -A "--scripting-enable"
```

### Beklenen GCS Çıktısı

```
[STATUSTEXT] IMU-ISI: IMU isi kontrolu basladi. Pinler: 54/55/56 | Normal: <30°C ac, >35°C kapat
[STATUSTEXT] IMU-ISI: IMU0:25.3°C(ON) | IMU1:24.8°C(ON) | IMU2:26.1°C(ON)
```

SITL'de IMU sıcaklıkları genellikle oda sıcaklığına yakın (~25°C) başlar; dolayısıyla ısıtıcılar açık konuma geçer.

---

## 7. MAVProxy ile Manuel Test

SITL konsoluyla ayrı bir terminalde MAVProxy da kullanabilirsiniz:

```bash
mavproxy.py --master=tcp:127.0.0.1:5762 \
            --out=udp:127.0.0.1:14550
```

Faydalı MAVProxy komutları:

```
mode GUIDED         # Mod değiştir
arm throttle        # Arm et
rc 3 1500           # Gaz ver
param show SCR*     # Script parametrelerini göster
script list         # Yüklü Lua scriptlerini listele
```

---

## 8. Sık Karşılaşılan Sorunlar

### "sim_vehicle.py: command not found"
```bash
source ~/.profile   # PATH'i yenile
# veya
export PATH=$PATH:$HOME/.local/bin
```

### UDP 14550 Portu Alınamıyor (Windows)
Güvenlik duvarı kuralı ekleyin (PowerShell, yönetici):
```powershell
New-NetFirewallRule -DisplayName "ArduPilot SITL" `
  -Direction Inbound -Protocol UDP -LocalPort 14550 -Action Allow
```

### WSL2'den Windows'a Erişilemiyor
```bash
# Windows ana makine IP'sini öğren:
cat /etc/resolv.conf | grep nameserver | awk '{print $2}'
# Bu IP'yi GCS bağlantı kutusuna girin (127.0.0.1 yerine)
```

### pymavlink "No module named 'pymavlink'"
```powershell
.venv\Scripts\activate
pip install pymavlink --upgrade
```

---

## 9. Hızlı Başvuru Kartı

| Görev | Komut |
|-------|-------|
| SITL başlat | `sim_vehicle.py -v ArduCopter --console --map` |
| GCS başlat | `python gcs_main.py` |
| Script etkinleştir | `param set SCR_ENABLE 1` |
| ARM et | `arm throttle` (MAVProxy) |
| EV'E DÖN | GCS'de **EV'E DÖN** butonuna bas veya `mode RTL` |
| Log dosyası | `~/ardupilot/ArduCopter/logs/` |

---

## 10. Referanslar

- ArduPilot SITL Dokümantasyonu: https://ardupilot.org/dev/docs/sitl-simulator-software-in-the-loop.html
- ArduPilot Lua Scripting: https://ardupilot.org/dev/docs/common-lua-scripts.html
- pymavlink: https://github.com/ArduPilot/pymavlink
- MAVLink Mesaj Referansı: https://mavlink.io/en/messages/common.html
