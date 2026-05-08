"""
tests/test_terrain_analiz.py
Horn eğim hesabı ve terrain analiz birim testleri.

Çalıştırmak için (repo kökünden):
    pytest tests/test_terrain_analiz.py -v
"""

import math
import os
import sys
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "gcs"))


# ── Horn yöntemi bağımsız unit testi ─────────────────────────────────────────

def horn_egim(grid: list[list[float]], ofset_m: float) -> float:
    """
    3×3 grid'den Horn yöntemi ile eğim hesaplar (derece).
    grid[satir][sutun], (0,0) = sol-üst
    """
    nw, n, ne = grid[0]
    w,  c, e  = grid[1]
    sw, s, se = grid[2]
    dzdx = ((ne + 2*e + se) - (nw + 2*w + sw)) / (8 * ofset_m)
    dzdy = ((sw + 2*s + se) - (nw + 2*n + ne)) / (8 * ofset_m)
    return math.degrees(math.atan(math.sqrt(dzdx**2 + dzdy**2)))


class TestHornEgim:

    def test_duz_arazi_sifir_egim(self):
        grid = [[100.0]*3 for _ in range(3)]
        egim = horn_egim(grid, 30.0)
        assert abs(egim) < 0.001

    def test_dik_yamac_yuksek_egim(self):
        # Her 30m'de 30m yükseklik farkı → ~45 derece
        grid = [
            [60.0, 90.0, 120.0],
            [60.0, 90.0, 120.0],
            [60.0, 90.0, 120.0],
        ]
        egim = horn_egim(grid, 30.0)
        assert egim > 40.0  # ~45 derece bekleniyor

    def test_hafif_egim(self):
        # Her 30m'de 1m yükseklik → ~2 derece
        grid = [
            [98.0, 99.0, 100.0],
            [98.0, 99.0, 100.0],
            [98.0, 99.0, 100.0],
        ]
        egim = horn_egim(grid, 30.0)
        assert 1.5 < egim < 3.5

    def test_diagonal_egim_simetrik(self):
        grid = [
            [100.0, 100.0, 110.0],
            [100.0, 100.0, 110.0],
            [90.0,  90.0,  100.0],
        ]
        egim = horn_egim(grid, 30.0)
        assert egim > 0

    def test_negatif_egim_mutlak_deger(self):
        # Her 30m'de 10m düşüş: ~18.4 derece (negatif yön de pozitif açı verir)
        grid = [
            [120.0, 110.0, 100.0],
            [120.0, 110.0, 100.0],
            [120.0, 110.0, 100.0],
        ]
        egim = horn_egim(grid, 30.0)
        assert 15.0 < egim < 22.0  # ~18.4 derece bekleniyor

    def test_ofset_etkisi(self):
        # Aynı yükseklik farkı, iki kat ofset → yarı eğim
        grid = [
            [0.0, 30.0, 60.0],
            [0.0, 30.0, 60.0],
            [0.0, 30.0, 60.0],
        ]
        e1 = horn_egim(grid, 30.0)
        e2 = horn_egim(grid, 60.0)
        assert e1 > e2  # büyük ofset → küçük eğim açısı


# ── GuvenliInisAnalizci mock testi ────────────────────────────────────────────

class TestGuvenliInisAnalizci:

    def _mock_srtm(self, yukseklikler: dict):
        """lat/lon çiftine göre yükseklik döndüren mock srtm verisi."""
        data = MagicMock()
        def get_elevation(lat, lon):
            # En yakın anahtarı bul (toleranslı)
            for (klat, klon), y in yukseklikler.items():
                if abs(lat - klat) < 0.01 and abs(lon - klon) < 0.01:
                    return y
            return 100.0
        data.get_elevation.side_effect = get_elevation
        return data

    @patch("terrain_analiz.srtm")
    def test_duz_arazi_guvenli_nokta_bulur(self, mock_srtm_mod):
        from terrain_analiz import GuvenliInisAnalizci
        # Tüm noktalar aynı yükseklikte → güvenli
        mock_srtm_mod.get_data.return_value = self._mock_srtm({})
        analizci = GuvenliInisAnalizci()
        analizci._srtm_verisi = mock_srtm_mod.get_data.return_value
        sonuc = analizci.analiz_et(41.0, 29.0, batarya_yuzde=80, hiz_ms=5.0)
        assert sonuc is not None

    @patch("terrain_analiz.srtm")
    def test_batarya_mesafe_hesabi(self, mock_srtm_mod):
        from terrain_analiz import GuvenliInisAnalizci
        mock_srtm_mod.get_data.return_value = self._mock_srtm({})
        analizci = GuvenliInisAnalizci()
        analizci._srtm_verisi = mock_srtm_mod.get_data.return_value
        # Düşük batarya → küçük yarıçap
        sonuc_dusuk = analizci.analiz_et(41.0, 29.0, batarya_yuzde=10, hiz_ms=5.0)
        sonuc_dolu  = analizci.analiz_et(41.0, 29.0, batarya_yuzde=80, hiz_ms=5.0)
        assert sonuc_dusuk.yaricap_m <= sonuc_dolu.yaricap_m


# ── Config yükleyici testi ────────────────────────────────────────────────────

class TestConfigYukleyici:

    def test_varsayilan_deger(self):
        import config_yukleyici as cfg
        deger = cfg.al("var_olmayan.anahtar", varsayilan=42)
        assert deger == 42

    def test_batarya_acil_yuklendi(self):
        import config_yukleyici as cfg
        acil = cfg.al("batarya.acil_yuzde")
        assert acil is not None
        assert int(acil) < 20  # config.json'da 8 olmalı

    def test_terrain_adim_yuklendi(self):
        import config_yukleyici as cfg
        adim = cfg.al("terrain.analiz_adim_m")
        assert adim is not None
        assert float(adim) > 0
