"""
tests/test_alan_inis_karar.py
AlanInisKarar modülü için birim testler.

Çalıştırmak (repo kökünden):
    pytest tests/test_alan_inis_karar.py -v
"""

import json
import math
import os
import sys
import tempfile

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "gcs"))

from alan_inis_karar import AlanInisKarar, InisKarari, GUVENLI_EGIM, RISKLI_EGIM, LIDAR_MIN_M


# ── NPZ oluşturucu yardımcı fonksiyon ────────────────────────────────────────

def _npz_olustur(egim_grid: np.ndarray,
                 lat_min: float, lat_max: float,
                 lon_min: float, lon_max: float,
                 noktalar: list) -> str:
    """
    Gerçek bir .npz dosyası üretir ve geçici yolunu döndürür.
    alan_verisi.npz formatıyla birebir uyumlu.

    Affine transform (satır=lat, sütun=lon):
        c = lon_min   (sol kenar)
        f = lat_max   (üst kenar)
        a = sütun genişliği (pozitif)
        e = satır yüksekliği (negatif)
    """
    nrows, ncols = egim_grid.shape
    a = (lon_max - lon_min) / ncols   # piksel genişliği (lon yönü)
    e = (lat_min - lat_max) / nrows   # piksel yüksekliği (lat yönü — negatif)
    transform = np.array([a, 0.0, lon_min, 0.0, e, lat_max], dtype=np.float64)
    bounds    = np.array([lon_min, lat_min, lon_max, lat_max], dtype=np.float64)
    dem       = np.zeros_like(egim_grid, dtype=np.float32) + 100.0

    tf = tempfile.NamedTemporaryFile(suffix=".npz", delete=False)
    tf.close()
    np.savez_compressed(
        tf.name,
        egim=egim_grid.astype(np.float32),
        dem=dem,
        transform=transform,
        bounds=bounds,
        noktalar_json=np.array([json.dumps(noktalar, ensure_ascii=False)]),
    )
    return tf.name


# ── Paylaşılan fixture ────────────────────────────────────────────────────────

# 10×10 grid: İstanbul çevresini temsil eder (1°×1° / 10 = 0.01°/piksel ≈ ~1 km)
# Koordinat aralığı: lat 40.95–41.05, lon 28.95–29.05
LAT_MIN, LAT_MAX = 40.95, 41.05
LON_MIN, LON_MAX = 28.95, 29.05
GRID_BOYUT = 10

MERKEZ_LAT, MERKEZ_LON = 41.00, 29.00   # grid ortası


def _duz_grid(egim: float = 2.0) -> np.ndarray:
    """Sabit eğimli düz bir grid."""
    return np.full((GRID_BOYUT, GRID_BOYUT), egim, dtype=np.float32)


def _karmik_grid() -> np.ndarray:
    """Sol yarı düz (2°), sağ yarı dik (20°)."""
    g = np.zeros((GRID_BOYUT, GRID_BOYUT), dtype=np.float32)
    g[:, :5]  = 2.0
    g[:, 5:]  = 20.0
    return g


def _guvenli_noktalar(n: int = 5, merkez_lat=MERKEZ_LAT, merkez_lon=MERKEZ_LON) -> list:
    """Test için n adet GUVENLI nokta üretir."""
    return [
        {
            "id": f"G{i+1:04d}",
            "lat": round(merkez_lat + i * 0.001, 6),
            "lon": round(merkez_lon + i * 0.001, 6),
            "egim": 2.0,
            "durum": "GUVENLI",
        }
        for i in range(n)
    ]


def _riskli_noktalar(n: int = 3) -> list:
    """Test için n adet RISKLI nokta üretir."""
    return [
        {
            "id": f"R{i+1:04d}",
            "lat": round(MERKEZ_LAT - 0.02 + i * 0.001, 6),
            "lon": round(MERKEZ_LON - 0.02 + i * 0.001, 6),
            "egim": 10.0,
            "durum": "RISKLI",
        }
        for i in range(n)
    ]


@pytest.fixture
def duz_npz():
    """Tüm alana 2° eğimli, 5 güvenli noktalı NPZ döndürür."""
    yol = _npz_olustur(_duz_grid(2.0), LAT_MIN, LAT_MAX, LON_MIN, LON_MAX,
                       _guvenli_noktalar())
    yield yol
    os.unlink(yol)


@pytest.fixture
def dik_npz():
    """Tüm alana 20° eğimli, güvenli nokta yok NPZ döndürür."""
    yol = _npz_olustur(_duz_grid(20.0), LAT_MIN, LAT_MAX, LON_MIN, LON_MAX,
                       _riskli_noktalar())
    yield yol
    os.unlink(yol)


@pytest.fixture
def karisik_npz():
    """Sol yarı güvenli, sağ yarı tehlikeli — 5 güvenli + 3 riskli nokta."""
    noktalar = _guvenli_noktalar(5, merkez_lat=MERKEZ_LAT, merkez_lon=28.98) + _riskli_noktalar(3)
    yol = _npz_olustur(_karmik_grid(), LAT_MIN, LAT_MAX, LON_MIN, LON_MAX, noktalar)
    yield yol
    os.unlink(yol)


@pytest.fixture
def bos_npz():
    """Hiç nokta olmayan NPZ (boş liste)."""
    yol = _npz_olustur(_duz_grid(2.0), LAT_MIN, LAT_MAX, LON_MIN, LON_MAX, [])
    yield yol
    os.unlink(yol)


# ── Testler ───────────────────────────────────────────────────────────────────

class TestNpzYukleme:

    def test_yuklenme_basarili(self, duz_npz):
        karar = AlanInisKarar(duz_npz)
        assert karar._egim is not None
        assert karar._egim.shape == (GRID_BOYUT, GRID_BOYUT)

    def test_noktalar_yuklendi(self, duz_npz):
        karar = AlanInisKarar(duz_npz)
        assert len(karar._noktalar) == 5

    def test_transform_yuklendi(self, duz_npz):
        karar = AlanInisKarar(duz_npz)
        assert karar._transform is not None

    def test_gecersiz_dosya_exception(self):
        with pytest.raises(Exception):
            AlanInisKarar("/var/olmayan/dosya.npz")


class TestEgimSor:

    def test_merkez_koordinat_egim_doner(self, duz_npz):
        karar = AlanInisKarar(duz_npz)
        egim = karar.egim_sor(MERKEZ_LAT, MERKEZ_LON)
        assert egim is not None
        assert abs(egim - 2.0) < 0.1

    def test_alan_disi_none_doner(self, duz_npz):
        karar = AlanInisKarar(duz_npz)
        # İstanbul'dan çok uzakta
        egim = karar.egim_sor(0.0, 0.0)
        assert egim is None

    def test_kose_koordinat_gecerli(self, duz_npz):
        karar = AlanInisKarar(duz_npz)
        # Köşeye yakın ama içeride
        egim = karar.egim_sor(LAT_MIN + 0.002, LON_MIN + 0.002)
        assert egim is not None

    def test_sol_yari_dusuk_egim(self, karisik_npz):
        karar = AlanInisKarar(karisik_npz)
        # Sol yarı: lon < 29.0
        egim = karar.egim_sor(MERKEZ_LAT, 28.98)
        assert egim is not None
        assert egim < 10.0

    def test_sag_yari_yuksek_egim(self, karisik_npz):
        karar = AlanInisKarar(karisik_npz)
        # Sağ yarı: lon >= 29.0
        egim = karar.egim_sor(MERKEZ_LAT, 29.02)
        assert egim is not None
        assert egim > 10.0


class TestInisKarari:

    def test_duz_arazi_inebilir(self, duz_npz):
        karar = AlanInisKarar(duz_npz)
        sonuc = karar.inis_karari(MERKEZ_LAT, MERKEZ_LON)
        assert isinstance(sonuc, InisKarari)
        assert sonuc.inebilir is True

    def test_dik_arazi_inemez(self, dik_npz):
        karar = AlanInisKarar(dik_npz)
        sonuc = karar.inis_karari(MERKEZ_LAT, MERKEZ_LON)
        assert sonuc.inebilir is False
        assert "Eğim" in sonuc.neden or "egim" in sonuc.neden.lower()

    def test_alan_disi_inemez(self, duz_npz):
        karar = AlanInisKarar(duz_npz)
        sonuc = karar.inis_karari(0.0, 0.0)
        assert sonuc.inebilir is False
        assert "dışında" in sonuc.neden.lower() or "alan" in sonuc.neden.lower()

    def test_lidar_cok_yakin_inemez(self, duz_npz):
        karar = AlanInisKarar(duz_npz)
        # LIDAR_MIN_M = 0.3 m altı → abort
        sonuc = karar.inis_karari(MERKEZ_LAT, MERKEZ_LON, lidar_m=0.1)
        assert sonuc.inebilir is False
        assert "LIDAR" in sonuc.neden or "lidar" in sonuc.neden.lower()

    def test_lidar_normal_mesafe_inebilir(self, duz_npz):
        karar = AlanInisKarar(duz_npz)
        # 5m mesafe → sorun yok
        sonuc = karar.inis_karari(MERKEZ_LAT, MERKEZ_LON, lidar_m=5.0)
        assert sonuc.inebilir is True

    def test_lidar_sinir_degeri(self, duz_npz):
        karar = AlanInisKarar(duz_npz)
        # Tam LIDAR_MIN_M — eşik üstü → inebilir
        sonuc = karar.inis_karari(MERKEZ_LAT, MERKEZ_LON, lidar_m=LIDAR_MIN_M)
        assert sonuc.inebilir is True

    def test_lidar_sinir_altı(self, duz_npz):
        karar = AlanInisKarar(duz_npz)
        # LIDAR_MIN_M - epsilon → inemez
        sonuc = karar.inis_karari(MERKEZ_LAT, MERKEZ_LON, lidar_m=LIDAR_MIN_M - 0.01)
        assert sonuc.inebilir is False

    def test_sonuc_egim_dolu(self, duz_npz):
        karar = AlanInisKarar(duz_npz)
        sonuc = karar.inis_karari(MERKEZ_LAT, MERKEZ_LON)
        assert sonuc.egim_derece >= 0.0

    def test_lidar_none_gecerli(self, duz_npz):
        """LIDAR verisi olmadan da karar verebilmeli."""
        karar = AlanInisKarar(duz_npz)
        sonuc = karar.inis_karari(MERKEZ_LAT, MERKEZ_LON, lidar_m=None)
        assert sonuc.inebilir is True

    def test_ruzgar_parametresi_gecerli(self, duz_npz):
        karar = AlanInisKarar(duz_npz)
        sonuc = karar.inis_karari(MERKEZ_LAT, MERKEZ_LON, ruzgar_ms=8.0, ruzgar_yonu=180.0)
        assert sonuc.inebilir is True  # Rüzgar tek başına reddetmez

    def test_guvenli_nokta_ekleniyor(self, duz_npz):
        karar = AlanInisKarar(duz_npz)
        sonuc = karar.inis_karari(MERKEZ_LAT, MERKEZ_LON)
        # 5 güvenli nokta varsa en_yakin_nokta dolu olmalı
        assert sonuc.en_yakin_nokta is not None

    def test_bos_noktalar_en_yakin_none(self, bos_npz):
        karar = AlanInisKarar(bos_npz)
        sonuc = karar.inis_karari(MERKEZ_LAT, MERKEZ_LON)
        assert sonuc.en_yakin_nokta is None

    def test_neden_str_dolu(self, duz_npz):
        karar = AlanInisKarar(duz_npz)
        sonuc = karar.inis_karari(MERKEZ_LAT, MERKEZ_LON)
        assert isinstance(sonuc.neden, str) and len(sonuc.neden) > 0


class TestEnYakinGuvenli:

    def test_en_yakin_guvenli_doner(self, duz_npz):
        karar = AlanInisKarar(duz_npz)
        nokta = karar.en_yakin_guvenli(MERKEZ_LAT, MERKEZ_LON)
        assert nokta is not None
        assert nokta["durum"] == "GUVENLI"

    def test_bos_noktalar_none_doner(self, bos_npz):
        karar = AlanInisKarar(bos_npz)
        nokta = karar.en_yakin_guvenli(MERKEZ_LAT, MERKEZ_LON)
        assert nokta is None

    def test_sadece_riskli_varsa_none(self, dik_npz):
        """Sadece RISKLI noktalar varsa en_yakin_guvenli None döner."""
        karar = AlanInisKarar(dik_npz)
        nokta = karar.en_yakin_guvenli(MERKEZ_LAT, MERKEZ_LON)
        assert nokta is None

    def test_mesafe_hesaplaniyor(self, duz_npz):
        karar = AlanInisKarar(duz_npz)
        nokta = karar.en_yakin_guvenli(MERKEZ_LAT, MERKEZ_LON)
        assert "mesafe_m" in nokta
        assert nokta["mesafe_m"] >= 0.0

    def test_en_yakin_seciliyor(self, duz_npz):
        """Birden fazla güvenli nokta varsa en yakın olanı seçiyor mu?"""
        karar = AlanInisKarar(duz_npz)
        nokta = karar.en_yakin_guvenli(MERKEZ_LAT, MERKEZ_LON)
        # Tüm güvenli noktalar arasında en küçük mesafeyi kontrol et
        min_mesafe = min(
            AlanInisKarar._haversine(MERKEZ_LAT, MERKEZ_LON, n["lat"], n["lon"])
            for n in karar._noktalar if n["durum"] == "GUVENLI"
        )
        assert abs(nokta["mesafe_m"] - min_mesafe) < 1.0  # 1m tolerans


class TestEnIyiNokta:

    def test_guvenli_noktayi_tercih_eder(self, karisik_npz):
        karar = AlanInisKarar(karisik_npz)
        nokta = karar.en_iyi_nokta(MERKEZ_LAT, MERKEZ_LON)
        assert nokta is not None
        assert nokta["durum"] == "GUVENLI"

    def test_ruzgar_skoru_etkisi(self, duz_npz):
        karar = AlanInisKarar(duz_npz)
        # Rüzgarlı / rüzgarsız sonuçlar döner (hata vermez)
        n1 = karar.en_iyi_nokta(MERKEZ_LAT, MERKEZ_LON, ruzgar_ms=0.0)
        n2 = karar.en_iyi_nokta(MERKEZ_LAT, MERKEZ_LON, ruzgar_ms=12.0, ruzgar_yonu=90.0)
        assert n1 is not None
        assert n2 is not None

    def test_bos_noktalar_none(self, bos_npz):
        karar = AlanInisKarar(bos_npz)
        nokta = karar.en_iyi_nokta(MERKEZ_LAT, MERKEZ_LON)
        assert nokta is None

    def test_mesafe_dolu(self, duz_npz):
        karar = AlanInisKarar(duz_npz)
        nokta = karar.en_iyi_nokta(MERKEZ_LAT, MERKEZ_LON)
        assert "mesafe_m" in nokta and nokta["mesafe_m"] >= 0.0

    def test_skor_dolu(self, duz_npz):
        karar = AlanInisKarar(duz_npz)
        nokta = karar.en_iyi_nokta(MERKEZ_LAT, MERKEZ_LON)
        assert "skor" in nokta
        assert 0.0 <= nokta["skor"] <= 1.0


class TestHaversine:

    def test_sifir_mesafe(self):
        mesafe = AlanInisKarar._haversine(41.0, 29.0, 41.0, 29.0)
        assert mesafe == pytest.approx(0.0, abs=0.01)

    def test_bilinen_mesafe(self):
        # İstanbul (41.01, 28.98) → Kadıköy (40.99, 29.02) ≈ ~3.5 km
        mesafe = AlanInisKarar._haversine(41.01, 28.98, 40.99, 29.02)
        assert 3000 < mesafe < 5000

    def test_simetrik(self):
        m1 = AlanInisKarar._haversine(41.0, 29.0, 40.5, 28.5)
        m2 = AlanInisKarar._haversine(40.5, 28.5, 41.0, 29.0)
        assert m1 == pytest.approx(m2, rel=1e-6)

    def test_pozitif_deger(self):
        mesafe = AlanInisKarar._haversine(41.0, 29.0, 42.0, 30.0)
        assert mesafe > 0

    def test_uzak_mesafe_km_mertebesi(self):
        # İstanbul (41, 29) → Ankara (39.9, 32.86) ≈ ~350 km
        mesafe = AlanInisKarar._haversine(41.0, 29.0, 39.9, 32.86)
        assert 300_000 < mesafe < 400_000


class TestRuzgarSkoru:

    def test_ruzgar_yok_tam_skor(self):
        # Rüzgar < 1 m/s → skor = 1.0
        skor = AlanInisKarar._ruzgar_skoru(41.0, 29.0, 41.001, 29.001, 0.5, 0.0)
        assert skor == pytest.approx(1.0)

    def test_skor_aralik(self):
        # Her koşulda [0, 1] içinde
        skor = AlanInisKarar._ruzgar_skoru(41.0, 29.0, 41.01, 29.01, 15.0, 90.0)
        assert 0.0 <= skor <= 1.0

    def test_yuksek_ruzgar_dusuk_skor(self):
        # Güçlü rüzgar + karşı yön → düşük skor
        skor_guclü = AlanInisKarar._ruzgar_skoru(41.0, 29.0, 41.01, 29.01, 15.0, 270.0)
        skor_sakin = AlanInisKarar._ruzgar_skoru(41.0, 29.0, 41.01, 29.01, 0.5, 270.0)
        assert skor_sakin >= skor_guclü

    def test_ruzgar_golu_yonu_yuksek_skor(self):
        # Nokta rüzgar gölgesinde → yüksek skor
        # Rüzgar kuzeyden geliyor (0°), gölge güney tarafında
        skor_gole = AlanInisKarar._ruzgar_skoru(
            41.0, 29.0,    # merkez
            40.99, 29.0,   # güneyde — rüzgar gölgesi
            10.0, 0.0      # kuzeyden 10 m/s rüzgar
        )
        skor_acik = AlanInisKarar._ruzgar_skoru(
            41.0, 29.0,
            41.01, 29.0,   # kuzeyde — rüzgara karşı
            10.0, 0.0
        )
        assert skor_gole > skor_acik


class TestInisKarariGuvenlikSinıflari:
    """Eğim eşiği sınır değer testleri."""

    def _karar_al(self, egim: float, lat=MERKEZ_LAT, lon=MERKEZ_LON):
        grid = np.full((GRID_BOYUT, GRID_BOYUT), egim, dtype=np.float32)
        yol = _npz_olustur(grid, LAT_MIN, LAT_MAX, LON_MIN, LON_MAX, _guvenli_noktalar())
        try:
            karar = AlanInisKarar(yol)
            return karar.inis_karari(lat, lon)
        finally:
            os.unlink(yol)

    def test_egim_tam_guvenli_siniri(self):
        # GUVENLI_EGIM = 5.0° → inebilir
        sonuc = self._karar_al(GUVENLI_EGIM)
        assert sonuc.inebilir is True
        assert "Güvenli" in sonuc.neden

    def test_egim_guvenli_ustunde(self):
        # 7° → riskli ama kabul edilebilir
        sonuc = self._karar_al(7.0)
        assert sonuc.inebilir is True
        assert "Riskli" in sonuc.neden or "riskli" in sonuc.neden.lower()

    def test_egim_tam_riskli_siniri(self):
        # RISKLI_EGIM = 15.0° → eşik — inebilir (<=) ya da inemez (>), kodun davranışına göre
        sonuc = self._karar_al(RISKLI_EGIM)
        # 15.0 > 15.0 → False (kod: if egim > RISKLI_EGIM)
        assert sonuc.inebilir is True

    def test_egim_riskli_ustunde_inemez(self):
        # 16° > RISKLI_EGIM → inebilir=False
        sonuc = self._karar_al(16.0)
        assert sonuc.inebilir is False

    def test_sifir_egim_guvenli(self):
        # Sıfır eğim → kesinlikle güvenli
        sonuc = self._karar_al(0.0)
        assert sonuc.inebilir is True
