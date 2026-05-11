"""
pi_karar_dongusu.py
Doğuş Üniversitesi LÖP — Raspberry Pi Katman 1 Araya Girme Döngüsü

Raspberry Pi'de arka planda çalışır (servis veya tmux ile).
GCS laptop bağlı olmasa bile Pi, ArduPilot'u izler ve kriz anında devreye girer.

Bağlantı:  Pi ↔ ArduPilot UART  (varsayılan: /dev/ttyAMA0, 115200)
           veya SITL testi için:  tcp:127.0.0.1:5762

Kriz koşulları (herhangi biri):
  1. RTL takılı: eve uzaklık 25 sn içinde 20m azalmadı
  2. Kritik rüzgar: hız > kritik_ms (config'den)
  3. Batarya kritik + mesafe > kalan menzil
  4. GPS fix < 3
  5. EKF hatası > 0.8

Kriz anında:
  → alan_verisi.npz'den rüzgar gölgesine en uygun güvenli nokta
  → ArduPilot'u GUIDED moda al
  → MAV_CMD_DO_REPOSITION ile güvenli noktaya gönder
  → 25 sn sonra MAV_CMD_NAV_LAND

Kullanım:
    # UART (Pi üzerinde):
    python pi_karar_dongusu.py --baglanti /dev/ttyAMA0 --baud 115200

    # SITL test (laptop):
    python pi_karar_dongusu.py --baglanti tcp:127.0.0.1:5762

    # Belirli alan verisi:
    python pi_karar_dongusu.py --baglanti /dev/ttyAMA0 --npz /home/pi/alan_verisi.npz
"""

import os
import sys
import time
import json
import math
import logging
import argparse
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from pymavlink import mavutil

# ── Ayarlar (config.json yoksa bu varsayılanlar kullanılır) ───────────────────
try:
    import config_yukleyici as _cfg
    _SERI_PORT    = _cfg.al("pi_kopru.seri_port",    "/dev/ttyAMA0")
    _SERI_BAUD    = int(_cfg.al("pi_kopru.seri_baud", 115200))
    _RUZ_TEHLIKELI = float(_cfg.al("ruzgar.tehlikeli_ms", 11.1))
    _RUZ_KRITIK    = float(_cfg.al("ruzgar.kritik_ms",    16.7))
    _EKF_ESIK      = float(_cfg.al("guvenlik.ekf_hata_esik", 0.8))
    _BAT_KRITIK    = int(_cfg.al("rtl_izleyici.batarya_kritik_yuzde", 15))
except Exception:
    _SERI_PORT    = "/dev/ttyAMA0"
    _SERI_BAUD    = 115200
    _RUZ_TEHLIKELI = 11.1
    _RUZ_KRITIK    = 16.7
    _EKF_ESIK      = 0.8
    _BAT_KRITIK    = 15

# RTL izleyici sabitleri
_RTL_STABIL_S   = 15.0   # İlk kaç saniye yoksay (irtifa alınıyor)
_RTL_KONTROL_S  = 25.0   # Kontrol periyodu
_RTL_MIN_AZALMA = 20.0   # Bu kadar azalmamışsa "takılı"
_RTL_GECMIS     = 6      # Kaç ölçüm tutulsun

# Müdahale parametreleri
_MUDAHALE_BEKLE_S  = 25.0   # Güvenli noktaya gittikten kaç sn sonra iniş komutu
_INIS_MIN_IRTIFA_M = 10.0   # Minimum iniş irtifası
_BAGLANTI_TIMEOUT  = 10     # Heartbeat timeout

# ArduCopter mod numaraları
MOD_STABILIZE = 0
MOD_GUIDED    = 4
MOD_RTL       = 6
MOD_LAND      = 9

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pi_karar")


# ── Telemetri durumu ──────────────────────────────────────────────────────────

@dataclass
class Telemetri:
    lat:          float = 0.0
    lon:          float = 0.0
    irtifa:       float = 0.0
    hiz_ms:       float = 0.0
    dikey_hiz:    float = 0.0
    eve_uzaklik:  float = 0.0
    bat_yuzde:    int   = 100
    gps_fix:      int   = 0
    ekf_hata:     float = 0.0
    ruzgar_ms:    float = 0.0
    ruzgar_yon:   float = 0.0
    ruzgar_ema:   float = 0.0    # filtrelenmiş rüzgar (α=0.25)
    mod_id:       int   = -1
    arm:          bool  = False
    lidar_m:      Optional[float] = None
    son_hb:       float = field(default_factory=time.monotonic)


# ── Pi Karar Döngüsü ──────────────────────────────────────────────────────────

class PiKararDongusu:
    """
    ArduPilot'u izler. Kriz durumunda alan_verisi.npz'den
    en uygun güvenli noktayı seçip GUIDED + REPOSITION komutu gönderir.
    """

    def __init__(
        self,
        baglanti_dizesi: str,
        npz_dosya: str = "alan_verisi.npz",
        mudahale_bekle_s: float = _MUDAHALE_BEKLE_S,
    ):
        self._dize    = baglanti_dizesi
        self._npz     = npz_dosya
        self._bekle_s = mudahale_bekle_s

        self._conn: mavutil.mavudp = None
        self._tm   = Telemetri()
        self._kilit = threading.Lock()

        # RTL izleyici
        self._rtl_aktif      = False
        self._rtl_baslama_t  = 0.0
        self._rtl_son_ctrl_t = 0.0
        self._rtl_gecmis     = deque(maxlen=_RTL_GECMIS)

        # Müdahale durumu
        self._mudahale_yapildi   = False
        self._inis_zamanlandi    = False
        self._son_mod_id         = -1

        # Alan iniş kararı — yükle
        self._alan_karar = None
        self._alan_yukle()

    # ── Alan verisi yükleme ───────────────────────────────────────────────────

    def _alan_yukle(self):
        if not os.path.isfile(self._npz):
            log.warning(f"alan_verisi.npz bulunamadı: {self._npz}  "
                        f"— eğim bazlı karar devre dışı")
            return
        try:
            from alan_inis_karar import AlanInisKarar
            self._alan_karar = AlanInisKarar(self._npz)
            log.info(f"Alan verisi yüklendi: {self._npz}")
        except Exception as e:
            log.error(f"Alan verisi yüklenemedi: {e}")

    # ── MAVLink bağlantı ─────────────────────────────────────────────────────

    def _baglan(self) -> bool:
        log.info(f"Bağlanılıyor: {self._dize}")
        try:
            self._conn = mavutil.mavlink_connection(
                self._dize,
                autoreconnect=False,
                source_system=1,    # Companion computer genellikle sys=1
            )
            log.info("Heartbeat bekleniyor...")
            msg = self._conn.wait_heartbeat(timeout=_BAGLANTI_TIMEOUT)
            if msg is None:
                log.error("Heartbeat alınamadı.")
                return False
            log.info(
                f"Bağlandı — sys={self._conn.target_system}, "
                f"comp={self._conn.target_component}"
            )
            # Veri akışı iste (10 Hz)
            self._conn.mav.request_data_stream_send(
                self._conn.target_system,
                self._conn.target_component,
                mavutil.mavlink.MAV_DATA_STREAM_ALL,
                10, 1,
            )
            return True
        except Exception as e:
            log.error(f"Bağlantı hatası: {e}")
            return False

    # ── Mesaj işleme ─────────────────────────────────────────────────────────

    def _isle(self, msg):
        tip = msg.get_type()

        if tip == "HEARTBEAT":
            with self._kilit:
                self._tm.mod_id = msg.custom_mode
                self._tm.arm    = bool(msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
                self._tm.son_hb = time.monotonic()

        elif tip == "VFR_HUD":
            with self._kilit:
                self._tm.irtifa     = msg.alt
                self._tm.hiz_ms     = msg.groundspeed
                self._tm.dikey_hiz  = msg.climb

        elif tip == "GLOBAL_POSITION_INT":
            with self._kilit:
                self._tm.lat = msg.lat / 1e7
                self._tm.lon = msg.lon / 1e7

        elif tip == "GPS_RAW_INT":
            with self._kilit:
                self._tm.gps_fix = msg.fix_type
                if self._tm.lat == 0.0:
                    self._tm.lat = msg.lat / 1e7
                    self._tm.lon = msg.lon / 1e7

        elif tip == "SYS_STATUS":
            if msg.battery_remaining != -1:
                with self._kilit:
                    self._tm.bat_yuzde = msg.battery_remaining

        elif tip == "WIND":
            with self._kilit:
                self._tm.ruzgar_ms  = msg.speed
                self._tm.ruzgar_yon = msg.direction
                # EMA filtre (α=0.25)
                self._tm.ruzgar_ema = (
                    0.25 * msg.speed + 0.75 * self._tm.ruzgar_ema
                )

        elif tip == "EKF_STATUS_REPORT":
            with self._kilit:
                self._tm.ekf_hata = msg.velocity_variance

        elif tip == "DISTANCE_SENSOR":
            if msg.current_distance < 65535:
                with self._kilit:
                    self._tm.lidar_m = msg.current_distance / 100.0

        elif tip == "NAV_CONTROLLER_OUTPUT":
            # Eve uzaklık VFR_HUD'da yok bazen, buradan da alınabilir
            pass

    def _hesapla_eve_uzaklik(self, ev_lat, ev_lon):
        """Pi'de ev konumu bilinmiyorsa 0 döner."""
        if ev_lat == 0.0 or self._tm.lat == 0.0:
            return 0.0
        return _haversine(ev_lat, ev_lon, self._tm.lat, self._tm.lon)

    # ── Kriz tespiti ─────────────────────────────────────────────────────────

    def _rtl_kontrol(self, uzaklik: float) -> Optional[str]:
        """RTL ilerlemiyor mu? Neden varsa döndür, yoksa None."""
        simdi = time.monotonic()

        if not self._rtl_aktif:
            return None

        if uzaklik > 0:
            self._rtl_gecmis.append(uzaklik)

        # Stabilizasyon penceresi
        if simdi - self._rtl_baslama_t < _RTL_STABIL_S:
            return None
        if simdi - self._rtl_son_ctrl_t < _RTL_KONTROL_S:
            return None
        self._rtl_son_ctrl_t = simdi

        neden = None

        if len(self._rtl_gecmis) >= 3:
            en_eski = self._rtl_gecmis[0]
            en_yeni = self._rtl_gecmis[-1]
            if en_eski > 0 and en_yeni > en_eski - _RTL_MIN_AZALMA:
                neden = (f"RTL takılı: {en_eski:.0f}m → {en_yeni:.0f}m "
                         f"(beklenen azalma gelmedi)")

        tm = self._tm
        if 0 < tm.bat_yuzde <= _BAT_KRITIK:
            enerji_katsayi = 44.4 / 10.0 * 0.6
            menzil_m = (tm.bat_yuzde / 100.0) * enerji_katsayi * 1000
            if uzaklik > menzil_m:
                neden = (f"Batarya %{tm.bat_yuzde} ama mesafe {uzaklik:.0f}m "
                         f"> menzil {menzil_m:.0f}m")

        if tm.gps_fix < 3:
            neden = f"GPS fix kaybı (fix={tm.gps_fix})"

        if tm.ekf_hata > _EKF_ESIK:
            neden = f"EKF hata yüksek ({tm.ekf_hata:.2f})"

        return neden

    # ── Güvenli nokta seçimi ─────────────────────────────────────────────────

    def _guvenli_nokta_sec(self) -> Optional[dict]:
        """
        Rüzgar gölgesini (leeward) dikkate alarak en uygun güvenli noktayı seçer.
        alan_verisi.npz yoksa None döner.
        """
        if self._alan_karar is None:
            return None
        tm = self._tm

        try:
            # alan_inis_karar'daki _noktalar listesine eriş
            noktalar = self._alan_karar._noktalar
            guvenli = [n for n in noktalar if n.get("durum") == "GUVENLI"]
            if not guvenli:
                return None

            # Rüzgar gölgesi skoru: drone'dan rüzgar yönünün tersine olan noktalar tercih edilir
            # Rüzgar yönü: rüzgar nereden EsiYOR (meteoroloji standardı)
            # Leeward = rüzgarın gideceği yön = yon + 180
            ruz_hiz  = tm.ruzgar_ema
            ruz_yon  = tm.ruzgar_yon   # rüzgarın estiği yön (°)
            leeward  = (ruz_yon + 180) % 360

            def skor(nokta):
                # Mesafe cezası (m)
                d = _haversine(tm.lat, tm.lon, nokta["lat"], nokta["lon"])
                # Yön ödülü: leeward tarafına yakın noktaları tercih et
                nokta_yon = math.degrees(math.atan2(
                    nokta["lon"] - tm.lon,
                    nokta["lat"] - tm.lat,
                )) % 360
                yon_fark = abs((nokta_yon - leeward + 180) % 360 - 180)
                # Rüzgar zayıfsa yön ödülü ihmal et
                ruzgar_agirlik = min(ruz_hiz / _RUZ_KRITIK, 1.0)
                yon_ceza = ruzgar_agirlik * (yon_fark / 180.0) * 200   # maks 200m eşdeğer
                return d + yon_ceza + nokta["egim"] * 20               # eğim cezası

            en_iyi = min(guvenli, key=skor)
            return en_iyi

        except Exception as e:
            log.error(f"Güvenli nokta seçim hatası: {e}")
            return None

    # ── ArduPilot komutları ───────────────────────────────────────────────────

    def _mod_degistir(self, mod_id: int):
        log.info(f"Mod değiştiriliyor → {mod_id}")
        self._conn.mav.command_long_send(
            self._conn.target_system,
            self._conn.target_component,
            mavutil.mavlink.MAV_CMD_DO_SET_MODE,
            0,
            mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
            mod_id, 0, 0, 0, 0, 0,
        )

    def _reposition(self, lat: float, lon: float, irtifa_m: float):
        log.info(f"REPOSITION → {lat:.6f}, {lon:.6f}  {irtifa_m:.0f}m")
        self._conn.mav.command_long_send(
            self._conn.target_system,
            self._conn.target_component,
            mavutil.mavlink.MAV_CMD_DO_REPOSITION,
            0,
            -1,       # hız: mevcut hız
            0, 0, 0,  # loiter_radius, yaw, reserved
            lat, lon, max(irtifa_m, _INIS_MIN_IRTIFA_M),
        )

    def _inis_komutu(self, lat: float, lon: float):
        log.info(f"NAV_LAND → {lat:.6f}, {lon:.6f}")
        self._conn.mav.command_long_send(
            self._conn.target_system,
            self._conn.target_component,
            mavutil.mavlink.MAV_CMD_NAV_LAND,
            0,
            0, 0, 0, 0,
            lat, lon, 0,
        )

    # ── Müdahale ─────────────────────────────────────────────────────────────

    def _mudahale_et(self, neden: str):
        if self._mudahale_yapildi:
            return
        self._mudahale_yapildi = True

        log.warning(f"MÜDAHALEGEREKİYOR: {neden}")

        nokta = self._guvenli_nokta_sec()
        if nokta is None:
            log.error("Güvenli nokta bulunamadı — LAND komutu gönderiliyor.")
            self._mod_degistir(MOD_LAND)
            return

        lat, lon = nokta["lat"], nokta["lon"]
        log.info(
            f"Güvenli nokta seçildi: {lat:.6f}, {lon:.6f}  "
            f"eğim={nokta['egim']:.1f}°"
        )

        # 1. GUIDED moda geç
        self._mod_degistir(MOD_GUIDED)
        time.sleep(0.5)

        # 2. Güvenli noktaya git
        self._reposition(lat, lon, max(self._tm.irtifa, _INIS_MIN_IRTIFA_M))

        # 3. N saniye sonra iniş komutu gönder (ayrı thread)
        def zamanli_inis():
            time.sleep(self._bekle_s)
            if not self._inis_zamanlandi:
                return
            log.info(f"Zamanlanmış iniş komutu gönderiliyor ({self._bekle_s:.0f}s)")
            self._inis_komutu(lat, lon)

        self._inis_zamanlandi = True
        t = threading.Thread(target=zamanli_inis, daemon=True)
        t.start()

    # ── Ana döngü ─────────────────────────────────────────────────────────────

    def calistir(self, ev_lat: float = 0.0, ev_lon: float = 0.0):
        """
        Ana döngü — sonsuza kadar çalışır (KeyboardInterrupt ile dur).
        ev_lat, ev_lon: ev noktası koordinatı. 0,0 ise ilk konum ev sayılır.
        """
        while True:
            if not self._baglan():
                log.warning("Bağlantı başarısız — 5 sn sonra tekrar.")
                time.sleep(5)
                continue

            log.info("İzleme başladı.")
            try:
                self._dongu(ev_lat, ev_lon)
            except Exception as e:
                log.error(f"Döngü hatası: {e}")
            finally:
                log.warning("Bağlantı kesildi — yeniden bağlanılıyor.")
                time.sleep(3)
                # Durum sıfırla
                self._rtl_aktif        = False
                self._mudahale_yapildi = False
                self._inis_zamanlandi  = False
                self._rtl_gecmis.clear()

    def _dongu(self, ev_lat: float, ev_lon: float):
        ev_belirlendi = (ev_lat != 0.0)

        while True:
            msg = self._conn.recv_match(blocking=True, timeout=2.0)
            if msg is None:
                # Bağlantı kontrolü
                if time.monotonic() - self._tm.son_hb > 10.0:
                    log.error("Heartbeat kesildi.")
                    return
                continue

            self._isle(msg)
            tm = self._tm

            # İlk konum gelince ev noktasını belirle
            if not ev_belirlendi and tm.lat != 0.0 and not tm.arm:
                ev_lat = tm.lat
                ev_lon = tm.lon
                ev_belirlendi = True
                log.info(f"Ev noktası: {ev_lat:.6f}, {ev_lon:.6f}")

            # Eve uzaklık hesapla
            uzaklik = self._hesapla_eve_uzaklik(ev_lat, ev_lon)
            with self._kilit:
                tm.eve_uzaklik = uzaklik

            # ── Mod değişimi izle ─────────────────────────────────────────
            if tm.mod_id != self._son_mod_id:
                log.info(f"Mod: {self._son_mod_id} → {tm.mod_id}")
                if tm.mod_id == MOD_RTL and self._son_mod_id != MOD_RTL:
                    # RTL yeni başladı
                    self._rtl_aktif      = True
                    self._mudahale_yapildi = False
                    self._rtl_baslama_t  = time.monotonic()
                    self._rtl_son_ctrl_t = time.monotonic()
                    self._rtl_gecmis.clear()
                    if uzaklik > 0:
                        self._rtl_gecmis.append(uzaklik)
                    log.info(f"RTL başladı — eve uzaklık: {uzaklik:.0f}m")
                elif tm.mod_id not in (MOD_RTL,):
                    self._rtl_aktif = False
                self._son_mod_id = tm.mod_id

            if self._mudahale_yapildi:
                continue

            # ── Kriz 1: Kritik rüzgar ────────────────────────────────────
            if tm.ruzgar_ema >= _RUZ_KRITIK and tm.arm:
                self._mudahale_et(
                    f"Kritik rüzgar: {tm.ruzgar_ema*3.6:.0f} km/h"
                )
                continue

            # ── Kriz 2: RTL takılı / koşul bozuldu ──────────────────────
            if self._rtl_aktif:
                neden = self._rtl_kontrol(uzaklik)
                if neden:
                    self._mudahale_et(neden)

            # ── Kriz 3: Uçuşta kritik batarya, uzakta ───────────────────
            if (tm.arm and tm.mod_id not in (MOD_LAND,)
                    and 0 < tm.bat_yuzde <= _BAT_KRITIK):
                enerji_katsayi = 44.4 / 10.0 * 0.6
                menzil_m = (tm.bat_yuzde / 100.0) * enerji_katsayi * 1000
                if uzaklik > menzil_m:
                    self._mudahale_et(
                        f"Kritik batarya %{tm.bat_yuzde} + "
                        f"mesafe {uzaklik:.0f}m > menzil {menzil_m:.0f}m"
                    )


# ── Yardımcı ─────────────────────────────────────────────────────────────────

def _haversine(lat1, lon1, lat2, lon2) -> float:
    R = 6371000.0
    f1, f2 = math.radians(lat1), math.radians(lat2)
    df = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(df/2)**2 + math.cos(f1)*math.cos(f2)*math.sin(dl/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Pi Karar Döngüsü — ArduPilot izleyici + kriz müdahalesi"
    )
    parser.add_argument(
        "--baglanti",
        default=_SERI_PORT,
        help=f"MAVLink bağlantı dizesi (varsayılan: {_SERI_PORT})",
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=_SERI_BAUD,
        help=f"Seri port baud hızı (varsayılan: {_SERI_BAUD})",
    )
    parser.add_argument(
        "--npz",
        default="alan_verisi.npz",
        help="Pre-computed alan verisi (ucus_alani_hazirla.py çıktısı)",
    )
    parser.add_argument(
        "--mudahale-bekle",
        type=float,
        default=_MUDAHALE_BEKLE_S,
        dest="mudahale_bekle",
        help=f"Güvenli noktaya gidince kaç sn sonra inis (varsayılan: {_MUDAHALE_BEKLE_S})",
    )
    parser.add_argument(
        "--ev-lat",
        type=float,
        default=0.0,
        dest="ev_lat",
        help="Ev noktası enlemi (0=ilk GPS konumu)",
    )
    parser.add_argument(
        "--ev-lon",
        type=float,
        default=0.0,
        dest="ev_lon",
        help="Ev noktası boylamı",
    )
    args = parser.parse_args()

    # UART bağlantısı için baud'u dizeye ekle
    baglanti = args.baglanti
    if not baglanti.startswith(("tcp:", "udp:")):
        baglanti = f"{baglanti},{args.baud}"

    dongu = PiKararDongusu(
        baglanti_dizesi=baglanti,
        npz_dosya=args.npz,
        mudahale_bekle_s=args.mudahale_bekle,
    )

    try:
        dongu.calistir(ev_lat=args.ev_lat, ev_lon=args.ev_lon)
    except KeyboardInterrupt:
        log.info("Döngü durduruldu.")


if __name__ == "__main__":
    main()
