"""
MAVLink bağlantı yöneticisi – thread-safe, sinyal/slot tabanlı.
SITL veya gerçek donanıma udp/tcp/serial üzerinden bağlanır.
Şifreli mod: Pi'ye tcp bağlanır, tüm trafik AES-256-GCM ile korunur.
"""

from pymavlink import mavutil
from PyQt5.QtCore import QThread, pyqtSignal
import time
import socket
import struct
import threading
import os

try:
    from sifreleme import SifreliKanal, PaketToplama, anahtari_yukle
    from cryptography.exceptions import InvalidTag
    SIFRELEME_MEVCUT = True
except ImportError:
    SIFRELEME_MEVCUT = False

try:
    import config_yukleyici as _cfg
    _VARSAYILAN_DIZE  = _cfg.al("baglanti.varsayilan_dize", "tcp:127.0.0.1:5762")
    _PROXY_PORT       = int(_cfg.al("baglanti.proxy_port", 14560))
    _ANAHTAR_DOSYA    = os.path.expanduser(_cfg.al("baglanti.anahtar_dosya", "~/dogus-gcs/gcs_anahtar.key"))
except Exception:
    _VARSAYILAN_DIZE  = "tcp:127.0.0.1:5762"
    _PROXY_PORT       = 14560
    _ANAHTAR_DOSYA    = os.path.expanduser("~/dogus-gcs/gcs_anahtar.key")


UÇUŞ_MODLARI = {
    0:  "SABİTLEME",       # STABILIZE
    1:  "AKROBASI",         # ACRO
    2:  "İRTİFA TUT",       # ALT_HOLD
    3:  "OTOMATİK",         # AUTO
    4:  "GÜDÜMLÜ",          # GUIDED
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
    20: "TAKİP",            # FOLLOW (v4+)
    21: "ZİGZAG",           # ZIGZAG
    22: "AKILLI EV DÖN",    # SMART_RTL
    23: "AKIŞ TUT",         # FLOWHOLD
    24: "SALLANMA",         # SWARM (eski: unused)
    25: "YAVAŞ LOITER",     # LOITER (yavaş)
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
    imu_sicakligi = pyqtSignal(int, float)          # (imu_no 0-2, sicaklik_c)
    durum_mesaji = pyqtSignal(int, str)             # (severity 0-7, metin)
    ekf_durumu = pyqtSignal(int, float)             # (bayraklar, hata_puani)
    parametre_guncellendi = pyqtSignal(str, float, int, int)  # (ad, deger, indeks, toplam)
    parametre_tamamlandi = pyqtSignal()

    def __init__(self, baglanti_dizesi: str = _VARSAYILAN_DIZE,
                 anahtar_dosya: str = None):
        super().__init__()
        self.baglanti_dizesi = baglanti_dizesi
        self._calis = True
        self._baglanti = None
        # Şifreleme
        self._sifreli_mod = False
        self._kanal: "SifreliKanal | None" = None
        if anahtar_dosya and SIFRELEME_MEVCUT:
            try:
                anahtar = anahtari_yukle(anahtar_dosya)
                self._kanal = SifreliKanal(anahtar)
                self._sifreli_mod = True
            except Exception as e:
                pass  # Şifresiz devam et
        self._son_hb_zamani = 0.0
        self._ev_lat: float | None = None
        self._ev_lon: float | None = None
        self._guncel_lat: float = 0.0
        self._guncel_lon: float = 0.0
        self._parametreler: dict[str, float] = {}
        self._param_toplam = 0
        self._param_alinan = 0

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
        if self._sifreli_mod:
            self._sifreli_baglan()
        else:
            self._baglanti = mavutil.mavlink_connection(
                self.baglanti_dizesi,
                autoreconnect=False,
                source_system=255,
            )
            self._baglanti.wait_heartbeat(timeout=60)
            self.baglandi.emit()
            self._son_hb_zamani = time.time()
            # Veri akışı iste
            self._baglanti.mav.request_data_stream_send(
                self._baglanti.target_system,
                self._baglanti.target_component,
                mavutil.mavlink.MAV_DATA_STREAM_ALL,
                10,  # 10 Hz
                1,
            )
            self._mesaj_dongusu()

    def _sifreli_baglan(self):
        """Pi'ye şifreli TCP bağlantısı. Pi'de pi_kopru.py çalışıyor olmalı."""
        parcalar = self.baglanti_dizesi.replace("tcp:", "").split(":")
        host, port = parcalar[0], int(parcalar[1])

        self._sifre_sok = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sifre_sok.connect((host, port))

        # Şifreli soketi saran yerel UDP proxy başlat
        self._proxy_port = _PROXY_PORT
        self._proxy_baslat()

        yerel_dize = f"udp:127.0.0.1:{self._proxy_port}"
        self._baglanti = mavutil.mavlink_connection(
            yerel_dize, autoreconnect=False, source_system=255
        )
        self._baglanti.wait_heartbeat(timeout=60)
        self.baglandi.emit()
        self._son_hb_zamani = time.time()

    def _proxy_baslat(self):
        """
        Yerel UDP proxy: GCS←→localhost:14560 (düz) ←→ Pi (şifreli TCP)
        """
        self._proxy_sok = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._proxy_sok.bind(("127.0.0.1", self._proxy_port))
        self._proxy_gcs_adres = None
        self._proxy_toplayici = PaketToplama()

        def pi_dan_gcs_e():
            while self._calis:
                try:
                    veri = self._sifre_sok.recv(65536)
                    if not veri:
                        break
                    for paket in self._proxy_toplayici.veri_ekle(veri):
                        try:
                            acik = self._kanal.coz(paket)
                            if self._proxy_gcs_adres:
                                self._proxy_sok.sendto(acik, self._proxy_gcs_adres)
                        except Exception:
                            pass
                except Exception:
                    break

        def gcs_den_pi_ye():
            while self._calis:
                try:
                    veri, adres = self._proxy_sok.recvfrom(65536)
                    self._proxy_gcs_adres = adres
                    sifreli = self._kanal.sifrele(veri)
                    self._sifre_sok.sendall(sifreli)
                except Exception:
                    break

        threading.Thread(target=pi_dan_gcs_e, daemon=True).start()
        threading.Thread(target=gcs_den_pi_ye, daemon=True).start()

        # Veri akışı iste
        self._baglanti.mav.request_data_stream_send(
            self._baglanti.target_system,
            self._baglanti.target_component,
            mavutil.mavlink.MAV_DATA_STREAM_ALL,
            10,  # 10 Hz
            1,   # başlat
        )
        self._mesaj_dongusu()

    def _mesaj_dongusu(self):
        """Bağlantı kopana kadar MAVLink mesajlarını işler (hem şifreli hem düz)."""
        while self._calis:
            msg = self._baglanti.recv_match(blocking=True, timeout=2.0)
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

    # ------------------------------------------------------------------
    def komut_gonder(self, komut_id: int, param1=0, param2=0, param3=0,
                     param4=0, param5=0, param6=0, param7=0):
        if self._baglanti is None:
            return
        self._baglanti.mav.command_long_send(
            self._baglanti.target_system,
            self._baglanti.target_component,
            komut_id, 0,
            param1, param2, param3, param4, param5, param6, param7,
        )

    def parametreleri_iste(self):
        if self._baglanti is None:
            return
        self._parametreler.clear()
        self._param_alinan = 0
        self._param_toplam = 0
        self._baglanti.mav.param_request_list_send(
            self._baglanti.target_system,
            self._baglanti.target_component,
        )

    def parametre_ayarla(self, ad: str, deger: float):
        if self._baglanti is None:
            return
        self._baglanti.mav.param_set_send(
            self._baglanti.target_system,
            self._baglanti.target_component,
            ad.encode("utf-8"),
            deger,
            mavutil.mavlink.MAV_PARAM_TYPE_REAL32,
        )

    def mod_degistir(self, mod_id: int):
        if self._baglanti is None:
            return
        self._baglanti.set_mode(mod_id)

    def ev_noktasi_sifirla(self):
        self._ev_lat = self._guncel_lat
        self._ev_lon = self._guncel_lon

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
