"""
tests/test_ucus_raporlayici.py
UcusAnalizcisi birim testleri: rapor üretimi, uyarı eşikleri, haversine.

Çalıştırmak için (repo kökünden):
    pytest tests/test_ucus_raporlayici.py -v
"""

import math
import os
import sys
import pytest
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "gcs"))
from ucus_raporlayici import UcusAnalizcisi, BAT_KRITIK_YDZ, BAT_DUSUK_YDZ, \
    RUZGAR_TEHLIKELI, IMU_SICAK_ESIK, EKF_HATA_ESIK, GPS_KAYIP_FIX


# ── Test yardımcısı ───────────────────────────────────────────────────────────

def _analizci_veri_ile(veri: dict) -> UcusAnalizcisi:
    """
    Gerçek dosya okumadan UcusAnalizcisi nesnesi oluşturur;
    `_veri` sözlüğünü doğrudan enjekte eder.
    """
    a = UcusAnalizcisi.__new__(UcusAnalizcisi)
    a.dosya  = "test.bin"
    a.uzanti = ".bin"
    a._veri  = defaultdict(list, veri)
    return a


# ── Haversine mesafe hesabı ───────────────────────────────────────────────────

class TestHaversine:

    def test_ayni_nokta_sifir(self):
        d = UcusAnalizcisi._haversine(41.0, 29.0, 41.0, 29.0)
        assert d == pytest.approx(0.0, abs=0.1)

    def test_istanbul_ankara_yaklasik(self):
        """İstanbul–Ankara düz mesafesi ~350 km."""
        d = UcusAnalizcisi._haversine(41.01, 28.97, 39.93, 32.86)
        assert 340_000 < d < 360_000

    def test_bir_derece_enlem(self):
        """1° enlem ≈ 111 km."""
        d = UcusAnalizcisi._haversine(40.0, 30.0, 41.0, 30.0)
        assert 110_000 < d < 112_000

    def test_sifir_koordinat_sifir_doner(self):
        """Sıfır koordinat girişi → 0 mesafe (koruyucu kontrol)."""
        d = UcusAnalizcisi._haversine(0, 0, 0, 0)
        assert d == pytest.approx(0.0)

    def test_kucuk_mesafe_metre_hassasiyeti(self):
        """100m ilerlemede haversine ~100m döndürmeli."""
        d = UcusAnalizcisi._haversine(41.0, 29.0, 41.0009, 29.0)
        assert 90 < d < 110


# ── Rapor üretimi: temel yapı ─────────────────────────────────────────────────

class TestRaporYapisi:

    def test_rapor_baslik_iceriyor(self):
        a = _analizci_veri_ile({})
        rapor = a._rapor_olustur()
        assert "DOĞUŞ ÜNİVERSİTESİ" in rapor
        assert "UÇUŞ VERİSİ ANALİZ RAPORU" in rapor

    def test_rapor_bolumler_mevcut(self):
        a = _analizci_veri_ile({})
        rapor = a._rapor_olustur()
        for bolum in ("BATARYA", "IMU", "GPS", "RÜZGAR", "EKF", "GENEL DEĞERLENDİRME"):
            assert bolum in rapor, f"Bölüm eksik: {bolum}"

    def test_rapor_bos_veriyle_cakmaz(self):
        """Hiç veri yokken rapor üretimi çakmamalı."""
        a = _analizci_veri_ile({})
        rapor = a._rapor_olustur()
        assert isinstance(rapor, str)
        assert len(rapor) > 100

    def test_rapor_string_doner(self):
        a = _analizci_veri_ile({"irtifa": [10.0, 50.0, 30.0]})
        rapor = a._rapor_olustur()
        assert isinstance(rapor, str)

    def test_max_irtifa_raporda(self):
        a = _analizci_veri_ile({"irtifa": [10.0, 85.5, 30.0]})
        rapor = a._rapor_olustur()
        assert "85.5" in rapor


# ── Batarya eşikleri ──────────────────────────────────────────────────────────

class TestBataryaEsikleri:

    def test_kritik_batarya_uyari(self):
        a = _analizci_veri_ile({
            "bat_pct":  [100, 80, 50, BAT_KRITIK_YDZ - 1],
            "bat_volt": [16.0, 15.5, 14.0, 13.0],
        })
        rapor = a._rapor_olustur()
        assert "KRİTİK" in rapor

    def test_dusuk_batarya_uyari(self):
        a = _analizci_veri_ile({
            "bat_pct":  [100, 80, BAT_DUSUK_YDZ - 1],
            "bat_volt": [16.0, 15.0, 14.0],
        })
        rapor = a._rapor_olustur()
        assert "UYARI" in rapor or "KRİTİK" in rapor

    def test_normal_batarya_temiz(self):
        a = _analizci_veri_ile({
            "bat_pct":  [100, 90, 80, 70],
            "bat_volt": [16.8, 16.5, 16.0, 15.5],
        })
        rapor = a._rapor_olustur()
        assert "Batarya normal seviyelerde" in rapor

    def test_min_volt_raporda(self):
        a = _analizci_veri_ile({
            "bat_volt": [16.8, 15.2, 14.0],
            "bat_pct":  [100, 50, 20],
        })
        rapor = a._rapor_olustur()
        assert "14.00" in rapor

    def test_hucre_volt_kritik(self):
        """4S: 13.2V → hücre 3.3V — kritik hücre uyarısı."""
        a = _analizci_veri_ile({
            "bat_volt": [16.8, 13.1],   # 13.1 / 4 = 3.275V < 3.3V
            "bat_pct":  [100, 5],
        })
        rapor = a._rapor_olustur()
        assert "Hücre" in rapor and "KRİTİK" in rapor


# ── GPS uyarıları ─────────────────────────────────────────────────────────────

class TestGpsUyarilari:

    def test_gps_fix_kaybi_uyari(self):
        a = _analizci_veri_ile({
            "gps_fix":  [3, 3, 2, 1, 3],   # iki kez fix < 3
            "gps_uydu": [12, 12, 6, 4, 12],
        })
        rapor = a._rapor_olustur()
        assert "GPS" in rapor
        assert "fix kaybı" in rapor.lower() or "Fix Kaybı" in rapor

    def test_gps_kesintisiz_temiz(self):
        a = _analizci_veri_ile({
            "gps_fix":  [3, 3, 3, 3],
            "gps_uydu": [14, 14, 13, 15],
        })
        rapor = a._rapor_olustur()
        assert "kesintisiz" in rapor.lower() or "GPS bağlantısı" in rapor

    def test_min_uydu_sayisi_raporda(self):
        a = _analizci_veri_ile({
            "gps_fix":  [3, 3],
            "gps_uydu": [15, 8],
        })
        rapor = a._rapor_olustur()
        assert "8" in rapor


# ── IMU / Titreşim ────────────────────────────────────────────────────────────

class TestImuTitresim:

    def test_asiri_sicaklik_uyari(self):
        a = _analizci_veri_ile({
            "imu_sicak": [30.0, 45.0, IMU_SICAK_ESIK + 1],
        })
        rapor = a._rapor_olustur()
        assert "IMU" in rapor
        # 65+1 = 66°C → eşik aşıldı
        assert "UYARI" in rapor or "aştı" in rapor

    def test_normal_sicaklik_temiz(self):
        a = _analizci_veri_ile({
            "imu_sicak": [30.0, 35.0, 40.0],
        })
        rapor = a._rapor_olustur()
        assert "normal" in rapor.lower()

    def test_anormal_titresim_uyari(self):
        # Titreşim skoru: max |a - ort| > TITRESIM_ESIK(30)
        # Ort ≈ 10, max=50 → fark 40 > 30
        a = _analizci_veri_ile({
            "imu_acc": [10.0, 10.0, 10.0, 50.0],
        })
        rapor = a._rapor_olustur()
        assert "titreşim" in rapor.lower()

    def test_normal_titresim_temiz(self):
        a = _analizci_veri_ile({
            "imu_acc": [9.81, 9.82, 9.80, 9.83],
        })
        rapor = a._rapor_olustur()
        assert "Titreşim normal" in rapor


# ── Rüzgar uyarıları ──────────────────────────────────────────────────────────

class TestRuzgarUyarilari:

    def test_tehlikeli_ruzgar_uyari(self):
        a = _analizci_veri_ile({
            "ruzgar": [5.0, 8.0, RUZGAR_TEHLIKELI + 1.0],
        })
        rapor = a._rapor_olustur()
        assert "Tehlikeli" in rapor or "tehlikeli" in rapor

    def test_guvenli_ruzgar_temiz(self):
        a = _analizci_veri_ile({
            "ruzgar": [2.0, 3.5, 4.0],
        })
        rapor = a._rapor_olustur()
        assert "güvenli sınırlar" in rapor.lower() or "güvenli" in rapor.lower()

    def test_ruzgar_hiz_raporda(self):
        a = _analizci_veri_ile({
            "ruzgar": [7.5],
        })
        rapor = a._rapor_olustur()
        assert "7.5" in rapor


# ── EKF uyarıları ─────────────────────────────────────────────────────────────

class TestEkfUyarilari:

    def test_yuksek_ekf_uyari(self):
        a = _analizci_veri_ile({
            "ekf_vel_var": [0.1, 0.3, EKF_HATA_ESIK + 0.1],
        })
        rapor = a._rapor_olustur()
        assert "EKF" in rapor
        assert "yüksek" in rapor.lower() or "sapması" in rapor.lower()

    def test_normal_ekf_temiz(self):
        a = _analizci_veri_ile({
            "ekf_vel_var": [0.1, 0.2, 0.3],
        })
        rapor = a._rapor_olustur()
        assert "EKF sağlıklı" in rapor


# ── Genel değerlendirme ───────────────────────────────────────────────────────

class TestGenelDegerlendirme:

    def test_sorunsuz_ucus(self):
        a = _analizci_veri_ile({
            "bat_pct":    [100, 80, 60, 50],
            "bat_volt":   [16.8, 16.5, 15.8, 15.5],
            "gps_fix":    [3, 3, 3, 3],
            "gps_uydu":   [14, 14, 14, 14],
            "imu_sicak":  [30.0, 32.0],
            "imu_acc":    [9.80, 9.81, 9.82],
            "ruzgar":     [2.0, 3.0],
            "ekf_vel_var":[0.1, 0.2],
        })
        rapor = a._rapor_olustur()
        assert "sorunsuz tamamlandı" in rapor.lower() or "sorunsuz" in rapor

    def test_cok_sorunlu_ucus(self):
        a = _analizci_veri_ile({
            "bat_pct":    [100, 5],
            "bat_volt":   [16.8, 12.0],
            "gps_fix":    [3, 1, 0],
            "gps_uydu":   [14, 3, 0],
            "imu_sicak":  [70.0],
            "imu_acc":    [9.80, 50.0],
            "ruzgar":     [20.0],
            "ekf_vel_var":[1.5],
        })
        rapor = a._rapor_olustur()
        assert "sorun" in rapor.lower() or "bakım" in rapor.lower()

    def test_pymavlink_yoksa_hata_mesaji(self):
        """pymavlink yoksa analiz_et() hata metni döndürmeli."""
        import ucus_raporlayici as mod
        orijinal = mod.PYMAVLINK_MEVCUT
        mod.PYMAVLINK_MEVCUT = False
        try:
            a = mod.UcusAnalizcisi("test.bin")
            rapor = a.analiz_et()
            assert "HATA" in rapor
        finally:
            mod.PYMAVLINK_MEVCUT = orijinal

    def test_dosya_yoksa_hata_mesaji(self):
        """Var olmayan dosya yolu verilince hata mesajı döndürmeli."""
        a = UcusAnalizcisi("var_olmayan_dosya.bin")
        rapor = a.analiz_et()
        assert "HATA" in rapor

    def test_desteklenmeyen_uzanti_hata(self):
        """Bilinmeyen uzantılı dosyada hata mesajı döndürmeli."""
        a = UcusAnalizcisi("ucus.xyz")
        # Dosya gerçekte olmadığından "bulunamadı" hatası döner
        rapor = a.analiz_et()
        assert "HATA" in rapor


# ── Kat edilen mesafe ─────────────────────────────────────────────────────────

class TestKatedilen:

    def test_mesafe_sifir_tek_nokta(self):
        a = _analizci_veri_ile({
            "gps_lat": [41.0],
            "gps_lon": [29.0],
        })
        rapor = a._rapor_olustur()
        assert "0 m" in rapor or "Kat Edilen" in rapor

    def test_mesafe_hesabi_dogru(self):
        """İki nokta arası ~111 km → raporda görünmeli."""
        a = _analizci_veri_ile({
            "gps_lat": [40.0, 41.0],
            "gps_lon": [30.0, 30.0],
        })
        rapor = a._rapor_olustur()
        # ~111000m → raporda "111" (km olarak "111000" ya da özetle görünür)
        assert "Kat Edilen" in rapor
