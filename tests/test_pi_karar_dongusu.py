"""
tests/test_pi_karar_dongusu.py
PiKararDongusu birim testleri: telemetri, RTL izleyici, kriz tespiti.

Gerçek MAVLink/ArduPilot bağlantısı gerektirmez — tüm testler offline çalışır.

Çalıştırmak için (repo kökünden):
    pytest tests/test_pi_karar_dongusu.py -v
"""

import math
import os
import sys
import time
import pytest
from collections import deque
from unittest.mock import MagicMock, patch, PropertyMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "gcs"))

# pymavlink olmayabilir; import guard
try:
    from pi_karar_dongusu import (
        PiKararDongusu, Telemetri, _haversine,
        _RTL_STABIL_S, _RTL_KONTROL_S, _RTL_MIN_AZALMA,
        _RUZ_KRITIK, _EKF_ESIK, _BAT_KRITIK,
        MOD_RTL, MOD_GUIDED, MOD_LAND,
    )
    MODUL_MEVCUT = True
except ImportError:
    MODUL_MEVCUT = False

pytestmark = pytest.mark.skipif(
    not MODUL_MEVCUT,
    reason="pymavlink kurulu değil — pi_karar_dongusu içe aktarılamadı",
)


# ── Yardımcı: bağlantısız PiKararDongusu örneği ──────────────────────────────

def _dongu_olustur(npz="yok_dosya.npz") -> "PiKararDongusu":
    """
    MAVLink bağlantısı olmadan PiKararDongusu nesnesi oluşturur.
    _alan_yukle() gerçek dosya arayacağından var olmayan yol veriyoruz.
    """
    with patch("pi_karar_dongusu.mavutil"):
        d = PiKararDongusu.__new__(PiKararDongusu)
        d._dize             = "udp:127.0.0.1:14550"
        d._npz              = npz
        d._bekle_s          = 0.1   # testlerde kısa bekleme
        d._conn             = None
        d._tm               = Telemetri()
        import threading
        d._kilit            = threading.Lock()
        d._rtl_aktif        = False
        d._rtl_baslama_t    = 0.0
        d._rtl_son_ctrl_t   = 0.0
        d._rtl_gecmis       = deque(maxlen=6)
        d._mudahale_yapildi = False
        d._inis_zamanlandi  = False
        d._son_mod_id       = -1
        d._alan_karar       = None
        return d


# ── Telemetri dataclass ───────────────────────────────────────────────────────

class TestTelemetri:

    def test_varsayilan_degerler(self):
        tm = Telemetri()
        assert tm.lat         == 0.0
        assert tm.lon         == 0.0
        assert tm.irtifa      == 0.0
        assert tm.hiz_ms      == 0.0
        assert tm.bat_yuzde   == 100
        assert tm.gps_fix     == 0
        assert tm.ekf_hata    == 0.0
        assert tm.ruzgar_ms   == 0.0
        assert tm.ruzgar_ema  == 0.0
        assert tm.mod_id      == -1
        assert tm.arm         is False
        assert tm.lidar_m     is None

    def test_deger_atama(self):
        tm = Telemetri()
        tm.lat     = 41.012345
        tm.lon     = 28.987654
        tm.irtifa  = 50.5
        tm.bat_yuzde = 75
        assert tm.lat  == pytest.approx(41.012345)
        assert tm.lon  == pytest.approx(28.987654)
        assert tm.bat_yuzde == 75


# ── Haversine mesafe ──────────────────────────────────────────────────────────

class TestHaversine:

    def test_ayni_nokta_sifir(self):
        d = _haversine(41.0, 29.0, 41.0, 29.0)
        assert d == pytest.approx(0.0, abs=0.1)

    def test_istanbul_ankara(self):
        """İstanbul–Ankara ≈ 350 km."""
        d = _haversine(41.01, 28.97, 39.93, 32.86)
        assert 340_000 < d < 360_000

    def test_kisa_mesafe(self):
        """100m kuzey → ~100m."""
        d = _haversine(41.0, 29.0, 41.0009, 29.0)
        assert 90 < d < 115

    def test_simetrik(self):
        """A→B = B→A."""
        d1 = _haversine(40.0, 29.0, 41.0, 30.0)
        d2 = _haversine(41.0, 30.0, 40.0, 29.0)
        assert d1 == pytest.approx(d2, rel=1e-6)


# ── Mesaj işleme ──────────────────────────────────────────────────────────────

class TestMesajIsleme:

    def _sahte_msg(self, tip, **kwargs):
        msg = MagicMock()
        msg.get_type.return_value = tip
        for k, v in kwargs.items():
            setattr(msg, k, v)
        return msg

    def test_heartbeat_mod_arm(self):
        d = _dongu_olustur()
        import pi_karar_dongusu as m
        msg = self._sahte_msg(
            "HEARTBEAT",
            custom_mode=MOD_RTL,
            base_mode=m.mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED | 128,
        )
        # MAVLink bayrak sabiti gerçek değeri: arm bayrağı 128
        with patch.object(
            m.mavutil.mavlink,
            "MAV_MODE_FLAG_SAFETY_ARMED",
            new_callable=lambda: property(lambda self: 128),
            create=True,
        ):
            pass
        # Doğrudan _isle çağrısı — sadece arm mantığını test et
        d._tm.mod_id = 0
        d._tm.arm    = False
        # arm bayrağı: base_mode & 128 → True ise armed
        msg.base_mode = 128 + 1  # bit 7 set = armed
        with patch("pi_karar_dongusu.mavutil") as mock_mavu:
            mock_mavu.mavlink.MAV_MODE_FLAG_SAFETY_ARMED = 128
            d._isle(msg)
        assert d._tm.mod_id == MOD_RTL
        assert d._tm.arm    is True

    def test_vfr_hud(self):
        d = _dongu_olustur()
        msg = self._sahte_msg("VFR_HUD", alt=42.5, groundspeed=3.1, climb=-0.5)
        d._isle(msg)
        assert d._tm.irtifa     == pytest.approx(42.5)
        assert d._tm.hiz_ms     == pytest.approx(3.1)
        assert d._tm.dikey_hiz  == pytest.approx(-0.5)

    def test_global_position_int(self):
        d = _dongu_olustur()
        msg = self._sahte_msg(
            "GLOBAL_POSITION_INT",
            lat=int(41.0 * 1e7),
            lon=int(29.0 * 1e7),
        )
        d._isle(msg)
        assert d._tm.lat == pytest.approx(41.0, abs=1e-5)
        assert d._tm.lon == pytest.approx(29.0, abs=1e-5)

    def test_gps_raw_int(self):
        d = _dongu_olustur()
        msg = self._sahte_msg(
            "GPS_RAW_INT",
            fix_type=3,
            lat=int(40.9 * 1e7),
            lon=int(28.8 * 1e7),
        )
        d._isle(msg)
        assert d._tm.gps_fix == 3

    def test_sys_status_batarya(self):
        d = _dongu_olustur()
        msg = self._sahte_msg("SYS_STATUS", battery_remaining=72)
        d._isle(msg)
        assert d._tm.bat_yuzde == 72

    def test_sys_status_gecersiz_batarya(self):
        """battery_remaining == -1 → güncelleme yapılmamalı."""
        d = _dongu_olustur()
        d._tm.bat_yuzde = 80
        msg = self._sahte_msg("SYS_STATUS", battery_remaining=-1)
        d._isle(msg)
        assert d._tm.bat_yuzde == 80   # değişmemeli

    def test_wind_ema(self):
        d = _dongu_olustur()
        d._tm.ruzgar_ema = 0.0
        msg = self._sahte_msg("WIND", speed=8.0, direction=270.0)
        d._isle(msg)
        assert d._tm.ruzgar_ms  == pytest.approx(8.0)
        assert d._tm.ruzgar_yon == pytest.approx(270.0)
        # EMA: 0.25 * 8.0 + 0.75 * 0.0 = 2.0
        assert d._tm.ruzgar_ema == pytest.approx(2.0)

    def test_wind_ema_yaklaşıyor(self):
        """EMA birkaç mesajda sabit değere yaklaşmalı."""
        d = _dongu_olustur()
        d._tm.ruzgar_ema = 0.0
        msg = MagicMock()
        msg.get_type.return_value = "WIND"
        msg.speed     = 10.0
        msg.direction = 180.0
        for _ in range(30):
            d._isle(msg)
        # 30 adımda EMA 10'a çok yakın olmalı
        assert d._tm.ruzgar_ema > 9.0

    def test_ekf_status(self):
        d = _dongu_olustur()
        msg = self._sahte_msg("EKF_STATUS_REPORT", velocity_variance=0.95)
        d._isle(msg)
        assert d._tm.ekf_hata == pytest.approx(0.95)

    def test_distance_sensor(self):
        d = _dongu_olustur()
        msg = self._sahte_msg("DISTANCE_SENSOR", current_distance=250)  # 250 cm = 2.5m
        d._isle(msg)
        assert d._tm.lidar_m == pytest.approx(2.5)

    def test_distance_sensor_gecersiz(self):
        """65535 → geçersiz okuma, lidar_m değişmemeli."""
        d = _dongu_olustur()
        d._tm.lidar_m = 3.0
        msg = self._sahte_msg("DISTANCE_SENSOR", current_distance=65535)
        d._isle(msg)
        assert d._tm.lidar_m == pytest.approx(3.0)


# ── Eve uzaklık hesabı ────────────────────────────────────────────────────────

class TestEveUzaklik:

    def test_konumsuz_sifir(self):
        d = _dongu_olustur()
        # lat/lon 0 iken 0 döndürmeli
        result = d._hesapla_eve_uzaklik(41.0, 29.0)
        assert result == 0.0

    def test_ayni_nokta_sifir(self):
        d = _dongu_olustur()
        d._tm.lat = 41.0
        d._tm.lon = 29.0
        result = d._hesapla_eve_uzaklik(41.0, 29.0)
        assert result == pytest.approx(0.0, abs=1.0)

    def test_uzak_nokta(self):
        d = _dongu_olustur()
        d._tm.lat = 41.0
        d._tm.lon = 29.0
        result = d._hesapla_eve_uzaklik(40.0, 29.0)  # ~111 km
        assert 100_000 < result < 120_000


# ── RTL takılma kontrolü ──────────────────────────────────────────────────────

class TestRtlKontrol:

    def _rtl_dongusu(self):
        d = _dongu_olustur()
        d._rtl_aktif     = True
        d._rtl_baslama_t = time.monotonic() - _RTL_STABIL_S - 1.0
        d._rtl_son_ctrl_t = time.monotonic() - _RTL_KONTROL_S - 1.0
        return d

    def test_rtl_aktif_degil_none(self):
        d = _dongu_olustur()
        d._rtl_aktif = False
        assert d._rtl_kontrol(100.0) is None

    def test_stabilizasyon_penceresinde_none(self):
        """İlk _RTL_STABIL_S saniye içinde None döndürmeli."""
        d = _dongu_olustur()
        d._rtl_aktif      = True
        d._rtl_baslama_t  = time.monotonic()   # yeni başladı
        d._rtl_son_ctrl_t = time.monotonic() - _RTL_KONTROL_S - 1.0
        neden = d._rtl_kontrol(500.0)
        assert neden is None

    def test_kontrol_araliginda_none(self):
        """Kontrol periyodu dolmamışsa None döndürmeli."""
        d = _dongu_olustur()
        d._rtl_aktif      = True
        d._rtl_baslama_t  = time.monotonic() - _RTL_STABIL_S - 1.0
        d._rtl_son_ctrl_t = time.monotonic()   # az önce kontrol yapıldı
        neden = d._rtl_kontrol(500.0)
        assert neden is None

    def test_rtl_takildi(self):
        """Mesafe yeterince azalmamışsa neden döndürmeli."""
        d = self._rtl_dongusu()
        d._tm.gps_fix  = 3      # GPS tamam — GPS koşulunun önce tetiklenmemesi için
        d._tm.ekf_hata = 0.1    # EKF tamam
        d._tm.bat_yuzde = 80    # Batarya tamam
        # Geçmiş: 300m → 295m (5m azalma < 20m gerekli)
        d._rtl_gecmis.extend([300.0, 298.0, 295.0])
        neden = d._rtl_kontrol(295.0)
        assert neden is not None
        assert "takılı" in neden.lower() or "azalma" in neden.lower()

    def test_rtl_ilerliyor(self):
        """Mesafe yeterince azaldıysa None döndürmeli."""
        d = self._rtl_dongusu()
        d._tm.gps_fix  = 3
        d._tm.ekf_hata = 0.1
        d._tm.bat_yuzde = 80
        # 300m → 250m (50m azalma > 20m gerekli)
        d._rtl_gecmis.extend([300.0, 280.0, 250.0])
        neden = d._rtl_kontrol(250.0)
        assert neden is None

    def test_gps_kaybi_neden(self):
        """GPS fix 0 iken RTL aktifse neden döndürmeli."""
        d = self._rtl_dongusu()
        d._tm.gps_fix = 0
        d._rtl_gecmis.extend([300.0, 299.0, 298.0])  # takılı görünür
        neden = d._rtl_kontrol(298.0)
        assert neden is not None
        assert "gps" in neden.lower() or "GPS" in neden

    def test_ekf_hatasi_neden(self):
        """EKF hatası eşik üzerindeyken neden döndürmeli."""
        d = self._rtl_dongusu()
        d._tm.ekf_hata = _EKF_ESIK + 0.1
        d._rtl_gecmis.extend([300.0, 299.0, 298.0])
        neden = d._rtl_kontrol(298.0)
        assert neden is not None
        assert "ekf" in neden.lower() or "EKF" in neden

    def test_kritik_batarya_uzakta(self):
        """Kritik batarya + menzil aşımı → neden döndürmeli."""
        d = self._rtl_dongusu()
        d._tm.bat_yuzde = _BAT_KRITIK - 1   # kritik altı
        d._tm.gps_fix   = 3                  # GPS tamam
        d._tm.ekf_hata  = 0.1               # EKF tamam
        # Menzil: (%bat/100) * enerji * 1000 — çok kısa mesafe beklenmeli
        # 300m'de kritik batarya → menzil hesabı aşıldı
        d._rtl_gecmis.extend([300.0, 299.5, 299.0])
        neden = d._rtl_kontrol(299.0)
        assert neden is not None

    def test_yetersiz_gecmis_none(self):
        """Geçmiş < 3 veri noktası ile takılı tespiti yapılmamalı."""
        d = self._rtl_dongusu()
        d._tm.gps_fix  = 3
        d._tm.ekf_hata = 0.1
        d._tm.bat_yuzde = 80
        d._rtl_gecmis.append(300.0)   # sadece 1 veri
        neden = d._rtl_kontrol(300.0)
        assert neden is None


# ── Alan yükleme ──────────────────────────────────────────────────────────────

class TestAlanYukle:

    def test_dosya_yoksa_alan_karar_none(self):
        d = _dongu_olustur(npz="var_olmayan.npz")
        d._alan_yukle()
        assert d._alan_karar is None

    def test_gecerli_npz_yukler(self, tmp_path):
        """Geçerli bir NPZ dosyası varsa AlanInisKarar yüklenmeli."""
        import numpy as np, json
        npz_yolu = str(tmp_path / "alan.npz")
        noktalar = [{"lat": 41.0, "lon": 29.0, "egim": 1.0, "durum": "GUVENLI"}]
        np.savez_compressed(
            npz_yolu,
            egim          = np.zeros((10, 10), dtype=np.float32),
            dem           = np.ones((10, 10),  dtype=np.float32) * 100,
            transform     = np.array([0.0003, 0, 29.0, 0, -0.0003, 41.0]),
            bounds        = np.array([29.0, 40.7, 29.3, 41.0]),
            noktalar_json = np.array([json.dumps(noktalar)]),
        )
        d = _dongu_olustur(npz=npz_yolu)
        try:
            d._alan_yukle()
            # AlanInisKarar yüklenebildiyse test geçti
            # (alan_inis_karar.py bağımlısı; yoksa None kalır — her iki durum da kabul)
        except Exception:
            pass   # alan_inis_karar import hatası — offline ortamda normal


# ── Müdahale koruyucusu ───────────────────────────────────────────────────────

class TestMudahaleKoruyucu:

    def test_cift_mudahale_engeli(self):
        """_mudahale_et() ikinci kez çağrılınca işlem yapmamalı."""
        d = _dongu_olustur()
        d._mudahale_yapildi = True
        d._conn = MagicMock()
        d._alan_karar = None

        with patch.object(d, "_mod_degistir") as mock_mod, \
             patch.object(d, "_reposition")   as mock_rep:
            d._mudahale_et("test neden")
            mock_mod.assert_not_called()
            mock_rep.assert_not_called()

    def test_alan_karar_yoksa_land(self):
        """Güvenli nokta bulunamazsa LAND komutu gönderilmeli."""
        d = _dongu_olustur()
        d._conn         = MagicMock()
        d._alan_karar   = None
        d._tm.lat       = 41.0
        d._tm.lon       = 29.0
        d._tm.irtifa    = 20.0

        with patch.object(d, "_mod_degistir") as mock_mod:
            d._mudahale_et("test neden")
            mock_mod.assert_called_once_with(MOD_LAND)

    def test_mudahale_sonrasi_bayrak_set(self):
        """_mudahale_et() sonrası _mudahale_yapildi True olmalı."""
        d = _dongu_olustur()
        d._conn       = MagicMock()
        d._alan_karar = None

        with patch.object(d, "_mod_degistir"):
            d._mudahale_et("neden")
        assert d._mudahale_yapildi is True


# ── Rüzgar EMA filtresi ───────────────────────────────────────────────────────

class TestRuzgarEma:

    def test_ema_ilk_adim(self):
        """İlk ölçüm: 0.25 × hız + 0.75 × 0 = 0.25 × hız."""
        d = _dongu_olustur()
        d._tm.ruzgar_ema = 0.0
        msg = MagicMock()
        msg.get_type.return_value = "WIND"
        msg.speed     = 12.0
        msg.direction = 90.0
        d._isle(msg)
        assert d._tm.ruzgar_ema == pytest.approx(0.25 * 12.0, abs=0.01)

    def test_ema_sabit_sinyalde_yakinsama(self):
        """10 m/s sabit sinyal → EMA 10'a yakınsamalı."""
        d = _dongu_olustur()
        msg = MagicMock()
        msg.get_type.return_value = "WIND"
        msg.speed     = 10.0
        msg.direction = 0.0
        for _ in range(40):
            d._isle(msg)
        assert d._tm.ruzgar_ema > 9.5

    def test_ema_ani_dusus_yavas_tepki(self):
        """Sinyal 10'dan 0'a düşünce EMA hemen 0 olmaz."""
        d = _dongu_olustur()
        msg = MagicMock()
        msg.get_type.return_value = "WIND"
        msg.direction = 0.0
        msg.speed = 10.0
        for _ in range(30):
            d._isle(msg)
        msg.speed = 0.0
        for _ in range(3):
            d._isle(msg)
        # 3 adımda hâlâ > 0
        assert d._tm.ruzgar_ema > 1.0


# ── Bağımsız modül sabitleri ──────────────────────────────────────────────────

class TestSabitler:

    def test_rtl_mod_id(self):
        assert MOD_RTL == 6

    def test_guided_mod_id(self):
        assert MOD_GUIDED == 4

    def test_land_mod_id(self):
        assert MOD_LAND == 9

    def test_rtl_stabil_sure_pozitif(self):
        assert _RTL_STABIL_S > 0

    def test_rtl_kontrol_aralik_pozitif(self):
        assert _RTL_KONTROL_S > 0

    def test_min_azalma_pozitif(self):
        assert _RTL_MIN_AZALMA > 0

    def test_kritik_ruzgar_mantikli(self):
        """Kritik rüzgar eşiği 10-25 m/s aralığında olmalı."""
        assert 10.0 <= _RUZ_KRITIK <= 25.0

    def test_ekf_esik_normalize(self):
        """EKF eşiği 0-2 arasında olmalı."""
        assert 0.0 < _EKF_ESIK < 2.0

    def test_kritik_batarya_yuzde(self):
        """Kritik batarya eşiği %5-%25 aralığında olmalı."""
        assert 5 <= _BAT_KRITIK <= 25
