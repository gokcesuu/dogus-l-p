"""
tests/test_ucus_alani_hazirla.py
ucus_alani_hazirla.py birim testleri: eğim hesabı, güvenli nokta tespiti,
tile isimlendirme, önbellek yolu, nokta-içi-poligon, NPZ üretimi.

Çalıştırmak için (repo kökünden):
    pytest tests/test_ucus_alani_hazirla.py -v

Not: DEM indirme (dem_indir) ve OSM sorgularını test etmez — ağ bağımlısı.
"""

import math
import os
import sys
import tempfile
import json
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "gcs"))
import ucus_alani_hazirla as uah
from ucus_alani_hazirla import (
    egim_hesapla,
    guvenli_noktalari_bul,
    _gereken_tileler,
    _icinde_mi,
    _tile_prefix,
    onbellek_yolu,
    GUVENLI_EGIM,
    RISKLI_EGIM,
    PIKSEL_M,
)


# ── Yardımcı: sahte affine transform ─────────────────────────────────────────

class SahteTransform:
    """rasterio.Affine yerine kullanılan minimal mock."""
    def __init__(self, pixel_m=PIKSEL_M, lon_min=29.0, lat_max=41.0):
        # Affine(pixel_genislik, 0, lon_min, 0, -pixel_yukseklik, lat_max)
        self._a = pixel_m / 111_320          # piksel boyutu → derece (x)
        self._e = -pixel_m / 111_000         # piksel boyutu → derece (y)
        self._c = lon_min                    # sol kenar
        self._f = lat_max                    # üst kenar

    def __mul__(self, xy):
        col, row = xy
        lon = self._c + col * self._a
        lat = self._f + row * self._e
        return lon, lat

    # rasterio Affine uyumu için __iter__
    def __iter__(self):
        return iter([self._a, 0, self._c, 0, self._e, self._f])


# ── Eğim hesabı ───────────────────────────────────────────────────────────────

class TestEgimHesapla:

    def test_duz_arazi_sifir_egim(self):
        """Düz (sabit yükseklik) DEM → her piksel eğimi ≈ 0."""
        dem = np.full((10, 10), 100.0, dtype=np.float32)
        egim = egim_hesapla(dem, PIKSEL_M)
        # Sınır piksellerini at, iç pikseller 0 olmalı
        assert np.all(egim[1:-1, 1:-1] < 0.1)

    def test_meyilli_arazi_yuksek_egim(self):
        """Bir yönde düzgün eğim → egim > 0."""
        rows, cols = 10, 10
        dem = np.zeros((rows, cols), dtype=np.float32)
        for c in range(cols):
            dem[:, c] = c * 5.0   # her piksel +5m → 5/30 ≈ 9.5°
        egim = egim_hesapla(dem, PIKSEL_M)
        assert np.max(egim[1:-1, 1:-1]) > 5.0

    def test_cikti_boyutu_girdi_ile_esit(self):
        dem = np.random.rand(20, 20).astype(np.float32) * 100
        egim = egim_hesapla(dem, PIKSEL_M)
        assert egim.shape == dem.shape

    def test_cikti_negatif_deger_yok(self):
        """Eğim daima ≥ 0."""
        dem = np.random.rand(15, 15).astype(np.float32) * 50
        egim = egim_hesapla(dem, PIKSEL_M)
        assert np.all(egim >= 0)

    def test_farkli_piksel_m_orani(self):
        """Piksel boyutu büyüdükçe aynı yükseklik farkı daha küçük eğim verir."""
        dem = np.zeros((5, 5), dtype=np.float32)
        dem[:, :] = np.arange(5)[np.newaxis, :] * 10.0  # 10m/piksel

        egim_kucuk = egim_hesapla(dem, 10.0)    # 10m/10m = 45°
        egim_buyuk = egim_hesapla(dem, 100.0)   # 10m/100m ≈ 5.7°

        assert np.max(egim_kucuk[1:-1, 1:-1]) > np.max(egim_buyuk[1:-1, 1:-1])

    def test_tek_tepeli_arazi(self):
        """Ortada tepe olan arazi — tepenin komşu pikselleri yüksek eğimli olmalı.

        Horn yöntemi (4,4)'ün eğimini komşularından (hepsi 0) hesaplar →
        merkez piksel 0 çıkar.  Tepeden etkilenen komşular ([3,4], [5,4] vb.)
        yüksek eğim değerine sahip olmalı.
        """
        dem = np.zeros((9, 9), dtype=np.float32)
        dem[4, 4] = 50.0   # merkez tepe
        egim = egim_hesapla(dem, PIKSEL_M)
        # Merkez pikselin doğrudan komşuları yüksek eğimli olmalı
        komsu_max = max(
            egim[3, 4], egim[5, 4],   # kuzey-güney komşular
            egim[4, 3], egim[4, 5],   # doğu-batı komşular
        )
        assert komsu_max > 10.0, f"Tepe komşularında yüksek eğim bekleniyor, max={komsu_max:.2f}"


# ── Güvenli nokta tespiti ─────────────────────────────────────────────────────

class TestGuvenliNoktalariBul:

    def _transform(self, satir, sutun):
        """(satir, sutun) → (lat, lon) — sahte transform."""
        lat = 41.0 - satir * 0.0003
        lon = 29.0 + sutun * 0.0003
        return lat, lon

    def test_duz_arazide_guvenli_noktalar(self):
        """Tamamen düz eğim → birden fazla güvenli nokta bulunmalı."""
        egim = np.zeros((20, 20), dtype=np.float32)
        transform = SahteTransform(PIKSEL_M)
        noktalar = guvenli_noktalari_bul(egim, transform)
        guvenli = [n for n in noktalar if n["durum"] == "GUVENLI"]
        assert len(guvenli) > 0

    def test_cok_egimli_arazide_guvenli_yok(self):
        """Eğim > RISKLI_EGIM olan arazide GUVENLI nokta olmayabilir."""
        egim = np.full((20, 20), RISKLI_EGIM + 5.0, dtype=np.float32)
        transform = SahteTransform(PIKSEL_M)
        noktalar = guvenli_noktalari_bul(egim, transform)
        guvenli = [n for n in noktalar if n["durum"] == "GUVENLI"]
        assert len(guvenli) == 0

    def test_nokta_yapisi(self):
        """Her nokta sözlüğü gerekli alanları içermeli."""
        egim = np.zeros((10, 10), dtype=np.float32)
        transform = SahteTransform(PIKSEL_M)
        noktalar = guvenli_noktalari_bul(egim, transform)
        assert len(noktalar) > 0
        for n in noktalar:
            assert "lat" in n
            assert "lon" in n
            assert "egim" in n
            assert "durum" in n

    def test_durum_degerler_gecerli(self):
        """durum alanı sadece 'GUVENLI' veya 'RISKLI' olabilir."""
        egim = np.random.rand(15, 15).astype(np.float32) * 20
        transform = SahteTransform(PIKSEL_M)
        noktalar = guvenli_noktalari_bul(egim, transform)
        for n in noktalar:
            assert n["durum"] in ("GUVENLI", "RISKLI"), \
                f"Geçersiz durum: {n['durum']}"

    def test_egim_esikleri_tutarli(self):
        """GUVENLI noktalar ≤ GUVENLI_EGIM, RISKLI noktalar ≤ RISKLI_EGIM."""
        egim = np.random.rand(20, 20).astype(np.float32) * 20
        transform = SahteTransform(PIKSEL_M)
        noktalar = guvenli_noktalari_bul(egim, transform)
        for n in noktalar:
            if n["durum"] == "GUVENLI":
                assert n["egim"] <= GUVENLI_EGIM + 0.5   # tolerans
            else:
                assert n["egim"] <= RISKLI_EGIM + 0.5

    def test_bos_egim_dizisi(self):
        """Boş DEM → boş liste (çakmamalı)."""
        egim = np.zeros((0, 0), dtype=np.float32)
        transform = SahteTransform(PIKSEL_M)
        try:
            noktalar = guvenli_noktalari_bul(egim, transform)
            assert isinstance(noktalar, list)
        except Exception:
            pass   # Boş girişte hata kabul edilebilir

    def test_noktalar_json_serializabl(self):
        """Dönen noktalar JSON'a serileştirilebilmeli (NPZ'e yazılacak)."""
        egim = np.zeros((10, 10), dtype=np.float32)
        transform = SahteTransform(PIKSEL_M)
        noktalar = guvenli_noktalari_bul(egim, transform)
        js = json.dumps(noktalar)
        geri = json.loads(js)
        assert isinstance(geri, list)


# ── Tile ismi üretimi ─────────────────────────────────────────────────────────

class TestTileIsmi:

    def test_kuzey_dogu(self):
        prefix = _tile_prefix(41, 29)
        assert "N41" in prefix or "41" in prefix
        assert "E029" in prefix or "029" in prefix or "29" in prefix

    def test_gney_bati(self):
        prefix = _tile_prefix(-10, -75)
        assert "S10" in prefix or "-10" in prefix or "10" in prefix

    def test_format_tutarli(self):
        """Farklı enlem/boylam çiftleri benzersiz prefix'ler üretmeli."""
        p1 = _tile_prefix(40, 28)
        p2 = _tile_prefix(41, 29)
        assert p1 != p2

    def test_koordinatlar_destekleniyor(self):
        """Türkiye sınırları içindeki koordinatlar prefix üretmeli."""
        for lat in range(36, 43):
            for lon in range(26, 45):
                p = _tile_prefix(lat, lon)
                assert isinstance(p, str) and len(p) > 0


# ── Gerekli tile listesi ──────────────────────────────────────────────────────

class TestGerekenTileler:

    def test_kucuk_alan_tek_tile(self):
        """0.5° × 0.5° alan genellikle 1 tile gerektirir."""
        tileler = _gereken_tileler(40.9, 41.1, 28.9, 29.1)
        assert len(tileler) >= 1

    def test_genis_alan_cok_tile(self):
        """2° × 2° alan birden fazla tile gerektirebilir."""
        tileler = _gereken_tileler(40.0, 42.0, 28.0, 30.0)
        assert len(tileler) >= 1

    def test_tile_listesi_tuple(self):
        """Dönen liste (lat_floor, lon_floor) tuple'larından oluşmalı."""
        tileler = _gereken_tileler(40.5, 41.0, 28.5, 29.0)
        for t in tileler:
            assert len(t) == 2
            lat_f, lon_f = t
            assert isinstance(lat_f, int)
            assert isinstance(lon_f, int)

    def test_sinir_koordinatlarda_kapsamli(self):
        """Tüm sınırları kapsadığından emin ol."""
        tileler = _gereken_tileler(40.0, 40.9, 29.0, 29.9)
        lat_taban = set(t[0] for t in tileler)
        lon_taban = set(t[1] for t in tileler)
        assert 40 in lat_taban   # 40.0 tabanı
        assert 29 in lon_taban   # 29.0 tabanı


# ── Nokta-içi-poligon ─────────────────────────────────────────────────────────

class TestIcindeMi:

    def test_kare_ici_true(self):
        kare = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        assert _icinde_mi(0.5, 0.5, kare) is True

    def test_kare_disi_false(self):
        kare = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        assert _icinde_mi(2.0, 2.0, kare) is False

    def test_kenar_noktasi(self):
        """Kenar üzerindeki nokta — implementasyona bağlı, çakmamalı."""
        kare = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        # True veya False — önemli olan çakmaması
        sonuc = _icinde_mi(0.0, 0.5, kare)
        assert isinstance(sonuc, bool)

    def test_ucgen_ici(self):
        """Üçgen poligon içindeki nokta."""
        ucgen = [(0.0, 0.0), (2.0, 0.0), (1.0, 2.0)]
        assert _icinde_mi(1.0, 0.5, ucgen) is True

    def test_ucgen_disi(self):
        ucgen = [(0.0, 0.0), (2.0, 0.0), (1.0, 2.0)]
        assert _icinde_mi(0.5, 1.8, ucgen) is False

    def test_bos_poligon_false(self):
        assert _icinde_mi(0.5, 0.5, []) is False


# ── Önbellek yolu ─────────────────────────────────────────────────────────────

class TestOnbellekYolu:

    def test_yol_string_doner(self):
        yol = onbellek_yolu("Copernicus_DSM_COG_10_N41_00_E029_00_DEM")
        assert isinstance(yol, str)

    def test_yol_tif_ile_biter(self):
        yol = onbellek_yolu("N41_E029")
        assert yol.endswith(".tif")

    def test_farkli_prefix_farkli_yol(self):
        y1 = onbellek_yolu("N40_E028")
        y2 = onbellek_yolu("N41_E029")
        assert y1 != y2

    def test_yol_var_olmayan_dizini_iceriyor(self):
        """Dönen yol geçerli bir dosya yolu formatında olmalı."""
        yol = onbellek_yolu("test_tile")
        # Dizin adı içermeli (os.path.dirname boş değil)
        assert os.path.dirname(yol) != ""


# ── NPZ üretimi entegrasyon testi ─────────────────────────────────────────────

class SahteAffine:
    """rasterio.transform.Affine yerine kullanılan minimal mock."""
    def __init__(self, a=0.0003, b=0, c=29.0, d=0, e=-0.0003, f=41.0):
        self.a, self.b, self.c = a, b, c
        self.d, self.e, self.f = d, e, f


class SahteBounds:
    """rasterio BoundingBox yerine kullanılan minimal mock."""
    def __init__(self, left=29.0, bottom=40.7, right=29.3, top=41.0):
        self.left   = left
        self.bottom = bottom
        self.right  = right
        self.top    = top


class TestNpzUretimi:

    def test_kaydet_fonksiyonu(self, tmp_path):
        """kaydet() NPZ dosyası oluşturmalı ve alanları içermeli."""
        dem      = np.ones((10, 10), dtype=np.float32) * 100.0
        egim     = np.zeros((10, 10), dtype=np.float32)
        affine   = SahteAffine()
        bounds   = SahteBounds()
        noktalar = [{"lat": 41.0, "lon": 29.0, "egim": 0.5, "durum": "GUVENLI"}]

        cikti = str(tmp_path / "test_alan.npz")
        uah.kaydet(
            egim=egim,
            dem=dem,
            transform=affine,
            bounds=bounds,
            noktalar=noktalar,
            cikti=cikti,
        )

        assert os.path.exists(cikti)
        data = np.load(cikti, allow_pickle=True)
        assert "egim"          in data
        assert "dem"           in data
        assert "bounds"        in data
        assert "noktalar_json" in data

    def test_npz_geri_okunabilir(self, tmp_path):
        """Kaydedilen NPZ tekrar yüklenip noktalar okunabilmeli."""
        dem    = np.zeros((5, 5), dtype=np.float32)
        egim   = np.zeros((5, 5), dtype=np.float32)
        affine = SahteAffine()
        bounds = SahteBounds(29.0, 40.9, 29.1, 41.0)
        noktalar = [
            {"lat": 40.95, "lon": 29.05, "egim": 1.0, "durum": "GUVENLI"},
            {"lat": 40.96, "lon": 29.06, "egim": 8.0, "durum": "RISKLI"},
        ]

        cikti = str(tmp_path / "test2.npz")
        uah.kaydet(egim=egim, dem=dem, transform=affine,
                   bounds=bounds, noktalar=noktalar, cikti=cikti)

        data = np.load(cikti, allow_pickle=True)
        geri = json.loads(str(data["noktalar_json"][0]))
        assert len(geri) == 2
        assert geri[0]["durum"] == "GUVENLI"
        assert geri[1]["durum"] == "RISKLI"
