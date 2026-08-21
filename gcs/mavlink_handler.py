"""
MAVLink bağlantı yöneticisi – thread-safe, sinyal/slot tabanlı.
SITL veya gerçek donanıma udp/tcp/serial üzerinden bağlanır.
Bağlantı kopunca otomatik olarak yeniden bağlanmayı dener.
"""

from pymavlink import mavutil
from PyQt5.QtCore import QThread, pyqtSignal
import time
import math
import os
import queue as _queue

import numpy as np

try:
    import config_yukleyici as _cfg
    _VARSAYILAN_DIZE = _cfg.al("baglanti.varsayilan_dize", "tcp:127.0.0.1:5762")
except Exception:
    _VARSAYILAN_DIZE = "tcp:127.0.0.1:5762"


UÇUŞ_MODLARI = {
    0:  "SABİTLEME",       # STABILIZE
    1:  "AKROBASI",         # ACRO
    2:  "İRTİFA TUT",       # ALT_HOLD
    3:  "OTOMATİK",         # AUTO
    4:  "KILAVUZ",           # GUIDED
    5:  "LOITER",           # LOITER
    6:  "EV'E DÖN",         # RTL
    7:  "DAİRE",            # CIRCLE
    9:  "LAND",             # LAND
    11: "OTOMATİK AYAR",    # AUTOTUNE
    12: "FREN",             # BRAKE
    13: "ATMA",             # THROW
    14: "KAÇIŞ (ADSB)",     # AVOID_ADSB
    15: "GPS KAPALI",       # GUIDED_NOGPS
    16: "KONUM TUT",        # POSHOLD
    17: "FIRLATMA",         # FOLLOW
    18: "ZİGZAG",           # ZIGZAG
    19: "AKIŞ TUT",         # FLOWHOLD
    20: "TAKİP",            # FOLLOW
    21: "KAPLUMBAĞA",       # TURTLE (ters düşünce kurtarma)
    22: "AKILLI EV DÖN",    # SMART_RTL
    23: "BATON",            # BATON (v4.4+)
    24: "SALLANMA",         # SWARM
    25: "YAVAŞ LOITER",     # LOITER (yavaş)
}

# Komut kodu → isim (MISSION_ITEM okumak için)
_KOMUT_ADLARI = {
    16: "NAV_WAYPOINT",
    22: "TAKEOFF",
    21: "LAND",
    18: "LOITER_TURNS",
    19: "LOITER_TIME",
    17: "LOITER_UNLIMITED",
    20: "RTL",
    93: "DELAY",
   177: "DO_JUMP",
   178: "DO_CHANGE_SPEED",
   189: "DO_LAND_START",
   203: "DO_DIGICAM_CONTROL",
   206: "DO_SET_CAM_TRIGG_DIST",
}

EKF_BAYRAKLARI = {
    0x0001: "Tutum",
    0x0002: "Yatay Hız",
    0x0004: "Dikey Hız",
    0x0008: "Yatay Konum (mutlak)",
    0x0010: "Dikey Konum (mutlak)",
    0x0020: "Yatay Konum (bağıl)",
    0x0040: "Dikey Konum (bağıl)",
    0x0080: "Yatay Tahmini Hata Küçük",
    0x0100: "Dikey Tahmini Hata Küçük",
}


class MAVLinkBaglantisi(QThread):
    """
    Ayrı thread'de MAVLink mesajlarını okur ve sinyal olarak yayar.
    Tüm sinyaller Qt ana iş parçacığına güvenli şekilde iletilir.
    """

    # --- Sinyaller ---
    baglandi = pyqtSignal()
    baglanti_kesildi = pyqtSignal()
    hata = pyqtSignal(str)

    kalp_atisi = pyqtSignal(int, bool)           # (mod_id, arm_durumu)
    batarya_guncellendi = pyqtSignal(float, float, int)  # (volt, amper, yuzde)
    vfr_guncellendi = pyqtSignal(float, float, float, float)  # (irtifa, hiz, dikey_hiz, eve_uzaklik)
    gps_guncellendi = pyqtSignal(int, int, float, float)  # (fix, uydu, lat, lon)
    tutum_guncellendi = pyqtSignal(float, float, float)  # (roll_deg, pitch_deg, yaw_deg)
    ruzgar_guncellendi = pyqtSignal(float, float)   # (hiz_ms, yon_derece)
    lidar_guncellendi  = pyqtSignal(float)          # mesafe_m (DISTANCE_SENSOR)
    imu_sicakligi = pyqtSignal(int, float)          # (imu_no 0-2, sicaklik_c)
    durum_mesaji = pyqtSignal(int, str)             # (severity 0-7, metin)
    ekf_durumu = pyqtSignal(int, float)             # (bayraklar, hata_puani)
    parametre_guncellendi = pyqtSignal(str, float, int, int)  # (ad, deger, indeks, toplam)
    parametre_tamamlandi = pyqtSignal()
    adsb_guncellendi  = pyqtSignal(int, float, float, float, float, str)
    # (icao_address, lat_deg, lon_deg, alt_m, heading_deg, callsign)
    esc_guncellendi   = pyqtSignal(object)
    # list: [{"motor": 0..7, "rpm": int, "sicaklik": float, "volt": float, "akim": float}, ...]
    terrain_rapor     = pyqtSignal(float, int, int)
    # (guncel_yukseklik_m, bekleyen_tile, yuklenen_tile)
    vibrasyon_guncellendi = pyqtSignal(float, int)
    # (vib_toplam_mss: RMS m/s², klipping_toplam: IMU saturation sayısı)
    mission_yuklendi  = pyqtSignal(bool, str)
    # (basarili: bool, mesaj: str)
    mission_alindi    = pyqtSignal(list)
    # okunan waypoint listesi: [{"lat": float, "lon": float, "alt": float}, ...]

    mission_wp_degisti = pyqtSignal(int)          # aktif WP sıra no (MISSION_CURRENT)
    komut_onaylandi    = pyqtSignal(int, int)      # (komut_id, mav_result: 0=OK)
    rc_guncellendi     = pyqtSignal(int, bool)     # (rssi 0-255, failsafe: bool)
    fence_ihlal        = pyqtSignal(int)           # fence breach_status (0=OK, >0=ihlal)
    ev_noktasi_guncellendi  = pyqtSignal(float, float, float)  # (lat, lon, alt_m) HOME_POSITION
    batarya_hucre_guncellendi = pyqtSignal(float, int)         # (min_hucre_volt, hucre_sayisi)
    servo_doyum_guncellendi = pyqtSignal(list)
    # [{"kanal": 1..8, "pwm": int, "doyum": bool}, ...]  — SERVO_OUTPUT_RAW
    log_listesi_alindi  = pyqtSignal(list)
    # [{"id": int, "size": int, "time_utc": int}, ...]  — LOG_ENTRY listesi
    log_ilerleme        = pyqtSignal(int, int)   # (alinan_bayt, toplam_bayt)
    log_tamamlandi      = pyqtSignal(str)         # kaydedilen dosya yolu
    log_hata            = pyqtSignal(str)          # hata mesajı

    def __init__(self, baglanti_dizesi: str = _VARSAYILAN_DIZE):
        super().__init__()
        self.baglanti_dizesi = baglanti_dizesi
        self._calis = True
        self._baglanti = None
        self._son_hb_zamani = 0.0
        self._ev_lat: float | None = None
        self._ev_lon: float | None = None
        self._guncel_lat: float = 0.0
        self._guncel_lon: float = 0.0
        self._parametreler: dict[str, float] = {}
        self._param_toplam = 0
        self._param_alinan = 0
        # Thread-safe komut kuyruğu — ana thread'den MAVLink yazımları buraya gider,
        # _mesaj_dongusu içinde tüketilir (race condition önler).
        self._komut_kuyrugu: _queue.Queue = _queue.Queue()

        # Terrain server — alan_verisi.npz varsa DEM yükle
        self._terrain_dem       = None   # float32 yükseklik array'i
        self._terrain_transform = None   # rasterio Affine (veya tuple)
        self._terrain_yukle()

    @property
    def son_heartbeat_zamani(self) -> float:
        return self._son_hb_zamani

    def ayarla(self, baglanti_dizesi: str):
        self.baglanti_dizesi = baglanti_dizesi

    def durdur(self):
        self._calis = False
        self.wait(3000)

    # ------------------------------------------------------------------
    def run(self):
        while self._calis:
            try:
                self._baglan()
                # _baglan() döndüyse mesaj döngüsü bitti = bağlantı koptu
                if self._calis:
                    self.baglanti_kesildi.emit()
                    time.sleep(3)
            except Exception as e:
                self.hata.emit(f"Bağlantı hatası: {e}")
                self.baglanti_kesildi.emit()
                time.sleep(3)

    def _baglan(self):
        self._baglanti = mavutil.mavlink_connection(
            self.baglanti_dizesi,
            autoreconnect=False,
            source_system=255,
        )
        self._baglanti.wait_heartbeat(timeout=15)
        self.baglandi.emit()
        self._son_hb_zamani = time.time()
        self._baglanti.mav.request_data_stream_send(
            self._baglanti.target_system,
            self._baglanti.target_component,
            mavutil.mavlink.MAV_DATA_STREAM_ALL,
            10,  # 10 Hz
            1,
        )
        self._mesaj_dongusu()

    def _mesaj_dongusu(self):
        """Bağlantı kopana kadar MAVLink mesajlarını işler (hem şifreli hem düz)."""
        while self._calis:
            msg = self._baglanti.recv_match(blocking=True, timeout=0.5)

            # ── Komut kuyruğunu boşalt ──────────────────────────────────────
            # Ana thread'den gelen tüm socket yazımları burada, MAVLink
            # thread'i içinde gerçekleşir → race condition olmaz.
            while True:
                try:
                    fn, args, kwargs = self._komut_kuyrugu.get_nowait()
                    fn(*args, **kwargs)
                except _queue.Empty:
                    break
                except Exception:
                    pass  # Komut hatası → sessiz geç, döngüyü kırma

            if msg is None:
                continue  # timeout → bağlantıyı kesme, döngüye devam

            tip = msg.get_type()
            self._son_hb_zamani = time.time()

            if tip == "HEARTBEAT":
                self._isle_hb(msg)
            elif tip == "SYS_STATUS":
                self._isle_batarya(msg)
            elif tip == "VFR_HUD":
                self._isle_vfr(msg)
            elif tip == "GPS_RAW_INT":
                self._isle_gps(msg)
            elif tip == "GLOBAL_POSITION_INT":
                self._isle_konum(msg)
            elif tip == "ATTITUDE":
                self._isle_tutum(msg)
            elif tip == "WIND":
                self._isle_ruzgar(msg)
            elif tip == "DISTANCE_SENSOR":
                self._isle_lidar(msg)
            elif tip == "TERRAIN_REQUEST":
                self._isle_terrain_request(msg)
            elif tip == "SCALED_IMU":
                self._isle_imu_sicaklik(msg, 0)
            elif tip == "SCALED_IMU2":
                self._isle_imu_sicaklik(msg, 1)
            elif tip == "SCALED_IMU3":
                self._isle_imu_sicaklik(msg, 2)
            elif tip == "NAMED_VALUE_FLOAT":
                self._isle_named_float(msg)
            elif tip == "STATUSTEXT":
                self.durum_mesaji.emit(msg.severity, msg.text)
            elif tip == "EKF_STATUS_REPORT":
                self.ekf_durumu.emit(msg.flags, msg.velocity_variance)
            elif tip == "PARAM_VALUE":
                self._isle_parametre(msg)
            elif tip == "ADSB_VEHICLE":
                self._isle_adsb(msg)
            elif tip in ("ESC_TELEMETRY_1_TO_4", "ESC_TELEMETRY_5_TO_8"):
                self._isle_esc(msg, 0 if tip.endswith("1_TO_4") else 4)
            elif tip == "TERRAIN_REPORT":
                self._isle_terrain_rapor(msg)
            elif tip == "VIBRATION":
                self._isle_vibrasyon(msg)
            elif tip == "MISSION_CURRENT":
                self.mission_wp_degisti.emit(msg.seq)
            elif tip == "COMMAND_ACK":
                self.komut_onaylandi.emit(msg.command, msg.result)
            elif tip == "RC_CHANNELS":
                # rssi=255 → geçersiz/bağlı değil; chan3_raw <950 → throttle failsafe
                failsafe = (msg.rssi == 0 or
                            (msg.chan3_raw < 950 and msg.chan3_raw > 0))
                self.rc_guncellendi.emit(msg.rssi, failsafe)
            elif tip == "FENCE_STATUS":
                self.fence_ihlal.emit(msg.breach_status)
            elif tip == "HOME_POSITION":
                self._isle_home(msg)
            elif tip == "BATTERY_STATUS":
                self._isle_batarya_status(msg)
            elif tip == "SERVO_OUTPUT_RAW":
                self._isle_servo(msg)

    # ------------------------------------------------------------------
    def _isle_hb(self, msg):
        arm = bool(msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
        self.kalp_atisi.emit(msg.custom_mode, arm)

    def _isle_batarya(self, msg):
        volt = msg.voltage_battery / 1000.0 if msg.voltage_battery != 65535 else 0.0
        amper = msg.current_battery / 100.0 if msg.current_battery != -1 else 0.0
        yuzde = msg.battery_remaining if msg.battery_remaining != -1 else -1
        self.batarya_guncellendi.emit(volt, amper, yuzde)

    def _isle_vfr(self, msg):
        if self._ev_lat and self._guncel_lat:
            uzaklik = self._hesapla_uzaklik(
                self._ev_lat, self._ev_lon, self._guncel_lat, self._guncel_lon
            )
        else:
            uzaklik = 0.0
        self.vfr_guncellendi.emit(
            msg.alt, msg.groundspeed, msg.climb, uzaklik
        )

    def _isle_gps(self, msg):
        fix = msg.fix_type
        uydu = msg.satellites_visible
        lat = msg.lat / 1e7
        lon = msg.lon / 1e7
        self.gps_guncellendi.emit(fix, uydu, lat, lon)

    def _isle_konum(self, msg):
        self._guncel_lat = msg.lat / 1e7
        self._guncel_lon = msg.lon / 1e7
        if self._ev_lat is None:
            self._ev_lat = self._guncel_lat
            self._ev_lon = self._guncel_lon

    def _isle_tutum(self, msg):
        import math
        self.tutum_guncellendi.emit(
            math.degrees(msg.roll),
            math.degrees(msg.pitch),
            math.degrees(msg.yaw),
        )

    def _isle_ruzgar(self, msg):
        self.ruzgar_guncellendi.emit(msg.speed, msg.direction)

    def _isle_lidar(self, msg):
        """
        DISTANCE_SENSOR mesajı — yalnızca zemine bakan (orientation=25,
        MAV_SENSOR_ROTATION_PITCH_270) sensör kabul edilir. Drone'da ileri/yana
        bakan ek bir mesafe sensörü (engel algılama vb.) varsa, onun verisi
        "zemine mesafe" diye yanlış kullanılmasın.
        """
        if getattr(msg, "orientation", 25) != 25:
            return
        # current_distance: cm cinsinden; 65535 = geçersiz/out-of-range
        if msg.current_distance < 65535:
            mesafe_m = msg.current_distance / 100.0
            self.lidar_guncellendi.emit(mesafe_m)

    # ── Terrain server ────────────────────────────────────────────────────────

    def _terrain_yukle(self):
        """
        alan_verisi.npz içindeki 'dem' array'ini yükler.
        ucus_alani_hazirla.py v2 ile üretilen NPZ bu array'i içerir.
        """
        for npz_yol in ("alan_verisi.npz",
                        os.path.join(os.path.dirname(__file__), "alan_verisi.npz")):
            if not os.path.isfile(npz_yol):
                continue
            try:
                data = np.load(npz_yol, allow_pickle=True)
                if "dem" not in data:
                    break   # Eski format — terrain server desteklenmiyor
                self._terrain_dem = data["dem"].astype(np.float32)
                t = data["transform"]
                # Affine tuple (a, b, c, d, e, f) olarak sakla
                self._terrain_transform = tuple(float(x) for x in t)
                print(f"[TerrainServer] DEM yüklendi: {self._terrain_dem.shape}  ({npz_yol})")
                break
            except Exception as e:
                print(f"[TerrainServer] DEM yüklenemedi: {e}")
                break

    def terrain_dem_yenile(self, npz_yol: str = "alan_verisi.npz"):
        """GCS'ten çağrılabilir — yeni NPZ yüklendiğinde terrain server'ı güncelle."""
        try:
            data = np.load(npz_yol, allow_pickle=True)
            if "dem" in data:
                self._terrain_dem = data["dem"].astype(np.float32)
                t = data["transform"]
                self._terrain_transform = tuple(float(x) for x in t)
                print(f"[TerrainServer] DEM yenilendi: {self._terrain_dem.shape}")
        except Exception as e:
            print(f"[TerrainServer] Yenileme hatası: {e}")

    def _terrain_yukseklik(self, lat: float, lon: float) -> int:
        """
        DEM array'inden koordinat bazlı yükseklik okur.
        Döndürür: int16 yükseklik (metre), bulunamazsa 0.
        """
        if self._terrain_dem is None or self._terrain_transform is None:
            return 0
        a, b, c, d, e, f = self._terrain_transform
        # Affine ters dönüşüm: (lon, lat) → (col, row)
        det = a * e - b * d
        if abs(det) < 1e-15:
            return 0
        col = (e * (lon - c) - b * (lat - f)) / det
        row = (a * (lat - f) - d * (lon - c)) / det
        r, c_ = int(row), int(col)
        dem = self._terrain_dem
        if 0 <= r < dem.shape[0] and 0 <= c_ < dem.shape[1]:
            v = dem[r, c_]
            if not math.isnan(v):
                return int(max(-32768, min(32767, v)))
        return 0

    def _isle_terrain_request(self, msg):
        """
        ArduPilot'un TERRAIN_REQUEST mesajına TERRAIN_DATA ile cevap verir.

        Protokol:
          TERRAIN_REQUEST (133):
            lat          – SW corner lat (degE7)
            lon          – SW corner lon (degE7)
            grid_spacing – metre cinsinden nokta aralığı
            mask         – 64-bit bitmask; her bit bir 4×4 bloku temsil eder

          Her bit i için:
            row = i // 8,  col = i % 8   (8×8 blok grid)
            blok SW corner'ı = (base_lat + row*4*spacing, base_lon + col*4*spacing)
            16 int16 yükseklik değeri → TERRAIN_DATA (134) gönder
        """
        if self._terrain_dem is None or self._baglanti is None:
            return

        base_lat_deg  = msg.lat / 1e7
        base_lon_deg  = msg.lon / 1e7
        spacing_m     = int(msg.grid_spacing)
        mask          = int(msg.mask)

        lat_m_per_deg = 111320.0

        for bit in range(64):
            if not (mask >> bit) & 1:
                continue

            blok_row = bit // 8
            blok_col = bit % 8

            # Blok SW corner
            blok_lat = base_lat_deg + blok_row * 4 * spacing_m / lat_m_per_deg
            lon_m_per_deg = lat_m_per_deg * math.cos(math.radians(blok_lat))
            blok_lon = (base_lon_deg + blok_col * 4 * spacing_m / lon_m_per_deg
                        if lon_m_per_deg > 0 else base_lon_deg)

            # 4×4 = 16 yükseklik noktası örnekle
            data = []
            for i in range(4):
                for j in range(4):
                    pt_lat = blok_lat + i * spacing_m / lat_m_per_deg
                    pt_lon = (blok_lon + j * spacing_m / lon_m_per_deg
                              if lon_m_per_deg > 0 else blok_lon)
                    data.append(self._terrain_yukseklik(pt_lat, pt_lon))

            # TERRAIN_DATA gönder
            try:
                self._baglanti.mav.terrain_data_send(
                    int(blok_lat * 1e7),   # lat degE7
                    int(blok_lon * 1e7),   # lon degE7
                    spacing_m,             # grid_spacing
                    bit,                   # gridbit
                    data,                  # 16× int16
                )
            except Exception:
                pass   # MAVLink versiyonu desteklemiyorsa sessiz geç

    # ── IMU / Parametre ───────────────────────────────────────────────────────

    def _isle_imu_sicaklik(self, msg, imu_no: int):
        if hasattr(msg, "temperature"):
            sicaklik = msg.temperature / 100.0
            self.imu_sicakligi.emit(imu_no, sicaklik)

    def _isle_parametre(self, msg):
        ad = msg.param_id.strip("\x00")
        deger = float(msg.param_value)
        toplam = int(msg.param_count)
        indeks = int(msg.param_index)
        self._parametreler[ad] = deger
        if toplam > 0:
            self._param_toplam = toplam
        self._param_alinan = len(self._parametreler)
        self.parametre_guncellendi.emit(ad, deger, self._param_alinan, self._param_toplam)
        if self._param_alinan >= self._param_toplam > 0:
            self.parametre_tamamlandi.emit()

    def _isle_named_float(self, msg):
        ad = msg.name.strip("\x00")
        for i in range(3):
            if ad == f"IMU{i}_TEMP":
                self.imu_sicakligi.emit(i, msg.value)

    def _isle_adsb(self, msg):
        """ADSB_VEHICLE — yakın hava araçlarını bildir."""
        try:
            callsign = msg.callsign.strip("\x00").strip() if hasattr(msg, "callsign") else ""
            lat  = msg.lat / 1e7
            lon  = msg.lon / 1e7
            alt  = msg.altitude / 1000.0        # mm → m
            hdg  = msg.heading / 100.0           # cdeg → deg
            icao = int(msg.ICAO_address)
            self.adsb_guncellendi.emit(icao, lat, lon, alt, hdg, callsign)
        except Exception:
            pass

    def _isle_esc(self, msg, baslangic: int):
        """ESC_TELEMETRY_1_TO_4 / 5_TO_8 — motor RPM, sıcaklık, voltaj, akım."""
        try:
            motorlar = []
            for i in range(4):
                motorlar.append({
                    "motor":    baslangic + i,
                    "rpm":      int(msg.rpm[i]),
                    "sicaklik": msg.temperature[i] / 100.0,  # centidegC → °C
                    "volt":     msg.voltage[i]    / 100.0,   # cV → V
                    "akim":     msg.current[i]    / 100.0,   # cA → A
                })
            self.esc_guncellendi.emit(motorlar)
        except Exception:
            pass

    def _isle_terrain_rapor(self, msg):
        """TERRAIN_REPORT — terrain follow durumu."""
        try:
            yukseklik  = float(msg.current_height)  # AGL metre
            bekleyen   = int(msg.pending)
            yuklenen   = int(msg.loaded)
            self.terrain_rapor.emit(yukseklik, bekleyen, yuklenen)
        except Exception:
            pass

    def _isle_vibrasyon(self, msg):
        """
        VIBRATION mesajı — IMU titreşim seviyesi.
        vibration_x/y/z: m/s² RMS (Cube Orange için normal < 15 m/s²)
        clipping_0/1/2:  IMU saturation sayacı (> 0 → ciddi titreşim)
        """
        try:
            import math
            vib_rms = math.sqrt(
                msg.vibration_x ** 2 +
                msg.vibration_y ** 2 +
                msg.vibration_z ** 2
            )
            klipping = int(msg.clipping_0) + int(msg.clipping_1) + int(msg.clipping_2)
            self.vibrasyon_guncellendi.emit(vib_rms, klipping)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Thread-safe yardımcı — tüm socket yazımları bu kuyruktan geçer.
    def _kuyruga_ekle(self, fn, *args, **kwargs):
        """
        Verilen callable'ı MAVLink thread kuyruğuna ekler.
        Ana thread'den çağrılabilir; asıl yürütme _mesaj_dongusu içinde olur.
        """
        self._komut_kuyrugu.put((fn, args, kwargs))

    # ── İç (gerçek) gönderim fonksiyonları — sadece MAVLink thread'inden çağrılır ──

    def _komut_gonder_ic(self, komut_id: int, param1, param2, param3,
                         param4, param5, param6, param7):
        if self._baglanti is None:
            return
        self._baglanti.mav.command_long_send(
            self._baglanti.target_system,
            self._baglanti.target_component,
            komut_id, 0,
            param1, param2, param3, param4, param5, param6, param7,
        )

    def _parametreleri_iste_ic(self):
        if self._baglanti is None:
            return
        self._parametreler.clear()
        self._param_alinan = 0
        self._param_toplam = 0
        self._baglanti.mav.param_request_list_send(
            self._baglanti.target_system,
            self._baglanti.target_component,
        )

    def _parametre_ayarla_ic(self, ad: str, deger: float):
        if self._baglanti is None:
            return
        self._baglanti.mav.param_set_send(
            self._baglanti.target_system,
            self._baglanti.target_component,
            ad.encode("utf-8"),
            deger,
            mavutil.mavlink.MAV_PARAM_TYPE_REAL32,
        )

    def _mod_degistir_ic(self, mod_id: int):
        if self._baglanti is None:
            return
        self._baglanti.set_mode(mod_id)

    # ── Genel API — ana thread'den çağrılabilir, kuyruk üzerinden iletilir ──

    def komut_gonder(self, komut_id: int, param1=0, param2=0, param3=0,
                     param4=0, param5=0, param6=0, param7=0):
        self._kuyruga_ekle(self._komut_gonder_ic,
                           komut_id, param1, param2, param3,
                           param4, param5, param6, param7)

    def parametreleri_iste(self):
        self._kuyruga_ekle(self._parametreleri_iste_ic)

    def parametre_ayarla(self, ad: str, deger: float):
        self._kuyruga_ekle(self._parametre_ayarla_ic, ad, deger)

    def mod_degistir(self, mod_id: int):
        self._kuyruga_ekle(self._mod_degistir_ic, mod_id)

    def hiz_kisitla(self, hiz_ms: float):
        """
        MAV_CMD_DO_CHANGE_SPEED (178) ile uçuş hızını kısıtlar.
        Rüzgar yüksekken motorları korumak için çağrılır.
        hiz_ms: hedef airspeed/groundspeed (m/s)
        """
        self._kuyruga_ekle(self._hiz_kisitla_ic, float(hiz_ms))

    def _hiz_kisitla_ic(self, hiz_ms: float):
        if self._baglanti is None:
            return
        self._baglanti.mav.command_long_send(
            self._baglanti.target_system,
            self._baglanti.target_component,
            178,   # MAV_CMD_DO_CHANGE_SPEED
            0,
            1,       # param1: speed type — 1=groundspeed
            hiz_ms,  # param2: speed (m/s)
            -1,      # param3: throttle (-1=no change)
            0, 0, 0, 0,
        )

    def guided_git(self, lat: float, lon: float, alt_m: float = 30.0):
        """GUIDED moda geç ve belirtilen koordinata uç."""
        self._kuyruga_ekle(self._guided_git_ic, lat, lon, alt_m)

    def _guided_git_ic(self, lat: float, lon: float, alt_m: float):
        if self._baglanti is None:
            return
        # Önce GUIDED moda geç (ArduCopter mod 4)
        self._baglanti.set_mode(4)
        import time as _t; _t.sleep(0.2)
        # Konum hedefi gönder
        self._baglanti.mav.set_position_target_global_int_send(
            0,
            self._baglanti.target_system,
            self._baglanti.target_component,
            mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
            0b0000111111111000,  # sadece konum
            int(lat * 1e7),
            int(lon * 1e7),
            alt_m,
            0, 0, 0,
            0, 0, 0,
            0, 0,
        )

    def irtifa_degistir(self, hedef_m: float):
        """
        MAV_CMD_DO_CHANGE_ALT (186) ile drone'un irtifasını değiştirir.
        Rüzgar gust yönetimi tarafından çağrılır — mevcut konumu korur, sadece yüksekliği ayarlar.
        hedef_m: eve göre bağıl irtifa (m), MAV_FRAME_GLOBAL_RELATIVE_ALT (frame=3).
        """
        self._kuyruga_ekle(self._irtifa_degistir_ic, float(hedef_m))

    def _irtifa_degistir_ic(self, hedef_m: float):
        if self._baglanti is None:
            return
        self._baglanti.mav.command_long_send(
            self._baglanti.target_system,
            self._baglanti.target_component,
            186,   # MAV_CMD_DO_CHANGE_ALT
            0,     # confirmation
            hedef_m,   # param1: hedef irtifa (m)
            3,         # param2: MAV_FRAME_GLOBAL_RELATIVE_ALT
            0, 0, 0, 0, 0,
        )

    def ev_noktasi_sifirla(self):
        # Sadece Python değişkeni günceller — socket yazımı yok, thread-safe.
        self._ev_lat = self._guncel_lat
        self._ev_lon = self._guncel_lon

    def _isle_home(self, msg):
        """HOME_POSITION: drone'un resmi ev noktasını güncelle."""
        lat = msg.latitude  / 1e7
        lon = msg.longitude / 1e7
        alt = msg.altitude  / 1000.0   # mm → m
        # Ev noktasını resmi koordinatla override et
        self._ev_lat = lat
        self._ev_lon = lon
        self.ev_noktasi_guncellendi.emit(lat, lon, alt)

    def _isle_batarya_status(self, msg):
        """BATTERY_STATUS: hücre başına voltaj — kritik hücre tespiti."""
        # voltages dizisi: mV cinsinden, 65535 = geçersiz
        voltlar = [v / 1000.0 for v in msg.voltages if v != 65535 and v > 0]
        if not voltlar:
            return
        self.batarya_hucre_guncellendi.emit(min(voltlar), len(voltlar))

    def _isle_servo(self, msg):
        """SERVO_OUTPUT_RAW: kanal PWM değerlerini kontrol et, doyum (>1950µs) uyar."""
        servo_bilgi = []
        for k in range(1, 9):          # kanal 1-8
            attr = f"servo{k}_raw"
            pwm = getattr(msg, attr, 0) or 0
            if pwm == 0:
                continue
            doyum = pwm >= 1950        # ArduPilot PWM max ~2000µs → doyum eşiği
            servo_bilgi.append({"kanal": k, "pwm": pwm, "doyum": doyum})
        if servo_bilgi:
            self.servo_doyum_guncellendi.emit(servo_bilgi)

    # ── MAVLink MISSION Protokolü ─────────────────────────────────────────────

    def mission_yukle(self, wp_listesi: list):
        """
        Waypoint listesini MAVLink MISSION protokolüyle drone'a yükler.
        Kuyruk üzerinden MAVLink thread'inde çalışır — thread-safe.
        """
        self._kuyruga_ekle(self._mission_yukle_ic, list(wp_listesi))

    def _mission_yukle_ic(self, wp_listesi: list):
        """
        MAVLink MISSION upload sırası:
          1. MISSION_CLEAR_ALL → drone listesini sıfırla
          2. MISSION_COUNT     → toplam item sayısı
          3. Her MISSION_REQUEST/MISSION_REQUEST_INT için MISSION_ITEM_INT gönder
          4. MISSION_ACK bekle
        """
        if self._baglanti is None:
            self.mission_yuklendi.emit(False, "Bağlantı yok")
            return
        mav = self._baglanti.mav
        ts  = self._baglanti.target_system
        tc  = self._baglanti.target_component

        # 1. Mevcut görevi temizle
        mav.mission_clear_all_send(ts, tc)
        import time as _time
        _time.sleep(0.4)

        # 2. Toplam item sayısı = ev noktası (0) + waypointler
        toplam = len(wp_listesi) + 1
        mav.mission_count_send(ts, tc, toplam,
                               mission_type=0)   # MAV_MISSION_TYPE_MISSION

        # 3. Request'lere cevap ver
        gonderilen = set()
        bitis = _time.monotonic() + 15.0
        while _time.monotonic() < bitis:
            msg = self._baglanti.recv_match(
                type=['MISSION_REQUEST', 'MISSION_REQUEST_INT', 'MISSION_ACK'],
                blocking=True, timeout=2.0
            )
            if msg is None:
                continue
            t = msg.get_type()
            if t in ('MISSION_REQUEST', 'MISSION_REQUEST_INT'):
                seq = msg.seq
                if seq in gonderilen:
                    continue
                gonderilen.add(seq)
                if seq == 0:
                    # Ev noktası — drone'un mevcut konumu, AGL 0
                    mav.mission_item_int_send(
                        ts, tc,
                        0,   # seq
                        0,   # frame: MAV_FRAME_GLOBAL
                        16,  # command: MAV_CMD_NAV_WAYPOINT
                        1,   # current (home point)
                        1,   # autocontinue
                        0, 0, 0, 0,
                        int(self._guncel_lat * 1e7),
                        int(self._guncel_lon * 1e7),
                        0.0,   # ev noktası AGL = 0
                        mission_type=0
                    )
                elif seq - 1 < len(wp_listesi):
                    wp = wp_listesi[seq - 1]
                    _KOMUT_KODLARI = {
                        "NAV_WAYPOINT":      16,
                        "TAKEOFF":           22,
                        "LAND":              21,
                        "LOITER_TURNS":      18,
                        "LOITER_TIME":       19,
                        "LOITER_UNLIMITED":  17,
                        "RTL":               20,
                        "DELAY":             93,
                        "DO_LAND_START":     189,
                    }
                    cmd_id = _KOMUT_KODLARI.get(wp.get("komut", "NAV_WAYPOINT"), 16)
                    mav.mission_item_int_send(
                        ts, tc,
                        seq,
                        3,       # frame: MAV_FRAME_GLOBAL_RELATIVE_ALT
                        cmd_id,
                        0,       # current
                        1,       # autocontinue
                        float(wp.get('p1', 0)),   # param1
                        float(wp.get('p2', 0)),   # param2: yarıçap, tekrar vb.
                        float(wp.get('p3', 0)),   # param3: ivme, dikey bekleme vb.
                        0,                         # param4: yaw
                        int(wp['lat'] * 1e7),
                        int(wp['lon'] * 1e7),
                        float(wp.get('alt', 50)),
                        mission_type=0
                    )
            elif t == 'MISSION_ACK':
                ok  = (msg.type == 0)   # MAV_MISSION_ACCEPTED = 0
                msg_str = "Görev yüklendi ✓" if ok else f"Drone hatası: {msg.type}"
                self.mission_yuklendi.emit(ok, msg_str)
                return

        self.mission_yuklendi.emit(False, "Zaman aşımı — drone yanıt vermedi (15 sn)")

    def mission_wp_atla(self, seq: int):
        """Uçuş sırasında belirtilen seq numaralı WP'yi aktif yapar (MISSION_SET_CURRENT)."""
        self._kuyruga_ekle(self._mission_wp_atla_ic, seq)

    def _mission_wp_atla_ic(self, seq: int):
        if self._baglanti is None:
            return
        self._baglanti.mav.mission_set_current_send(
            self._baglanti.target_system,
            self._baglanti.target_component,
            seq
        )

    def mission_temizle(self):
        """Drone'daki görev listesini temizler."""
        self._kuyruga_ekle(self._mission_temizle_ic)

    def _mission_temizle_ic(self):
        if self._baglanti is None:
            return
        self._baglanti.mav.mission_clear_all_send(
            self._baglanti.target_system,
            self._baglanti.target_component,
            mission_type=0
        )

    def mission_oku(self):
        """Drone'daki waypoint listesini okur; tamamlanınca mission_alindi sinyali gönderir."""
        self._kuyruga_ekle(self._mission_oku_ic)

    def _mission_oku_ic(self):
        if self._baglanti is None:
            self.mission_alindi.emit([])
            return
        import time as _time
        mav = self._baglanti.mav
        ts  = self._baglanti.target_system
        tc  = self._baglanti.target_component

        # Drone'dan waypoint listesi iste
        mav.mission_request_list_send(ts, tc, mission_type=0)

        # MISSION_COUNT bekle
        msg = self._baglanti.recv_match(
            type='MISSION_COUNT', blocking=True, timeout=5.0
        )
        if msg is None:
            self.mission_alindi.emit([])
            return

        toplam = msg.count
        wp_listesi = []
        for seq in range(toplam):
            mav.mission_request_int_send(ts, tc, seq, mission_type=0)
            item = self._baglanti.recv_match(
                type='MISSION_ITEM_INT', blocking=True, timeout=3.0
            )
            if item is None:
                continue
            # seq 0 = ev noktası, atla
            if item.seq == 0:
                continue
            wp_listesi.append({
                'lat': item.x / 1e7,
                'lon': item.y / 1e7,
                'alt':    float(item.z),
                'komut':  _KOMUT_ADLARI.get(item.command, "NAV_WAYPOINT"),
                'p1':     float(item.param1),
                'p2':     float(item.param2),
                'p3':     float(item.param3),
            })

        # Okuma tamamlandı bildirimi
        mav.mission_ack_send(ts, tc, 0, mission_type=0)
        self.mission_alindi.emit(wp_listesi)

    # ------------------------------------------------------------------
    @staticmethod
    def _hesapla_uzaklik(lat1, lon1, lat2, lon2) -> float:
        import math
        R = 6371000
        f1, f2 = math.radians(lat1), math.radians(lat2)
        df = math.radians(lat2 - lat1)
        dl = math.radians(lon2 - lon1)
        a = math.sin(df / 2) ** 2 + math.cos(f1) * math.cos(f2) * math.sin(dl / 2) ** 2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    @staticmethod
    def mod_adi(mod_id: int) -> str:
        return UÇUŞ_MODLARI.get(mod_id, f"MOD-{mod_id}")

    # ── Uçuş Logu İndirme (LOG_REQUEST_LIST + LOG_DATA) ───────────────────────

    def log_listesi_iste(self):
        """Drone'daki log listesini ister → log_listesi_alindi sinyali."""
        self._kuyruga_ekle(self._log_listesi_iste_ic)

    def _log_listesi_iste_ic(self):
        if self._baglanti is None:
            self.log_hata.emit("Bağlantı yok")
            return
        mav = self._baglanti.mav
        ts, tc = self._baglanti.target_system, self._baglanti.target_component
        mav.log_request_list_send(ts, tc, 0, 0xFFFF)
        loglar = []
        bitis = time.time() + 8.0
        while time.time() < bitis:
            msg = self._baglanti.recv_match(
                type=["LOG_ENTRY", "LOG_REQUEST_END"],
                blocking=True, timeout=2.0
            )
            if msg is None:
                continue
            t = msg.get_type()
            if t == "LOG_ENTRY":
                loglar.append({
                    "id":       msg.id,
                    "size":     msg.size,
                    "time_utc": getattr(msg, "time_utc", 0),
                })
                if msg.id == msg.last_log_num:
                    break
            elif t == "LOG_REQUEST_END":
                break
        self.log_listesi_alindi.emit(loglar)

    def log_indir(self, log_id: int, kayit_yolu: str):
        """Belirtilen log_id'yi indirir. Bloklamalı — ayrı bir kuyruk thread'inde çalışır."""
        self._kuyruga_ekle(self._log_indir_ic, log_id, kayit_yolu)

    def _log_indir_ic(self, log_id: int, kayit_yolu: str):
        if self._baglanti is None:
            self.log_hata.emit("Bağlantı yok")
            return
        mav = self._baglanti.mav
        ts, tc = self._baglanti.target_system, self._baglanti.target_component
        # Log boyutunu bul
        mav.log_request_list_send(ts, tc, log_id, log_id)
        boyut = 0
        bitis = time.time() + 5.0
        while time.time() < bitis:
            msg = self._baglanti.recv_match(type="LOG_ENTRY", blocking=True, timeout=2.0)
            if msg and msg.id == log_id:
                boyut = msg.size
                break
        if boyut == 0:
            self.log_hata.emit(f"Log {log_id} bulunamadı veya boyut 0")
            return

        CHUNK = 90   # LOG_REQUEST_DATA ofs + count (max 90 bayt/mesaj)
        ofs = 0
        parca_sayisi = (boyut + CHUNK - 1) // CHUNK
        tampun = bytearray()
        import struct
        mav.log_request_data_send(ts, tc, log_id, 0, boyut)
        bitis = time.time() + 120.0
        alinan = {}
        while len(alinan) < parca_sayisi and time.time() < bitis:
            msg = self._baglanti.recv_match(type="LOG_DATA", blocking=True, timeout=3.0)
            if msg is None:
                continue
            if msg.id != log_id:
                continue
            chunk_data = bytes(msg.data[:msg.count])
            alinan[msg.ofs] = chunk_data
            self.log_ilerleme.emit(len(alinan) * CHUNK, boyut)
        # Sıralı birleştir
        for ofs_k in sorted(alinan.keys()):
            tampun.extend(alinan[ofs_k])

        try:
            with open(kayit_yolu, "wb") as f:
                f.write(tampun[:boyut])
            self.log_tamamlandi.emit(kayit_yolu)
        except Exception as e:
            self.log_hata.emit(f"Dosya kaydetme hatası: {e}")
