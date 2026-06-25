"""
tests/test_gcs_logger.py
GCSLogger birim testleri: CSV yazma, thread-safety, alan isimleri.

Çalıştırmak için (repo kökünden):
    pytest tests/test_gcs_logger.py -v
"""

import csv
import os
import sys
import tempfile
import threading
import time
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "gcs"))
from gcs_logger import GCSLogger


# ── Fixture ───────────────────────────────────────────────────────────────────

@pytest.fixture
def gecici_logger(tmp_path):
    """Geçici dizinde başlatılmış logger döndürür; test sonrası durdurur."""
    logger = GCSLogger(log_klasoru=str(tmp_path))
    logger.baslat()
    yield logger
    logger.durdur()


# ── Alan isimleri ─────────────────────────────────────────────────────────────

class TestAlanIsimleri:

    BEKLENEN_ALANLAR = [
        "zaman", "irtifa", "hiz", "dikey_hiz", "eve_uzaklik",
        "bat_volt", "bat_amper", "bat_yuzde",
        "gps_fix", "gps_uydu", "lat", "lon",
        "roll", "pitch", "yaw",
        "ruzgar_ms", "ruzgar_yon",
        "ruzgar_zemin_ms", "ruzgar_trend",
        "imu0_c", "imu1_c", "imu2_c",
        "ekf_bayrak", "ekf_hata",
        "mod_id", "lidar_m",
    ]

    def test_tum_alanlar_mevcut(self, gecici_logger, tmp_path):
        """CSV başlığındaki tüm beklenen sütunlar mevcut olmalı."""
        gecici_logger.kaydet_satir({"irtifa": 10.0})
        gecici_logger.durdur()

        # CSV dosyasını bul
        csv_dosyalar = list(tmp_path.glob("telemetri_*.csv"))
        assert len(csv_dosyalar) == 1, "Tam olarak bir CSV dosyası oluşturulmalı"

        with open(csv_dosyalar[0], encoding="utf-8") as f:
            okuyucu = csv.DictReader(f)
            alanlar = okuyucu.fieldnames or []

        for alan in self.BEKLENEN_ALANLAR:
            assert alan in alanlar, f"'{alan}' CSV başlığında eksik"

    def test_csv_alan_sayisi(self, gecici_logger, tmp_path):
        """CSV alanlarının sayısı tam olmalı."""
        gecici_logger.durdur()
        csv_dosyalar = list(tmp_path.glob("telemetri_*.csv"))
        with open(csv_dosyalar[0], encoding="utf-8") as f:
            okuyucu = csv.DictReader(f)
            assert len(okuyucu.fieldnames) == len(self.BEKLENEN_ALANLAR)


# ── CSV Yazma ─────────────────────────────────────────────────────────────────

class TestCSVYazma:

    def test_satir_yazilir(self, gecici_logger, tmp_path):
        """kaydet_satir() çağrısı CSV'ye bir satır eklemeli."""
        gecici_logger.kaydet_satir({
            "irtifa": 42.5,
            "hiz":    3.2,
            "bat_yuzde": 87,
        })
        gecici_logger.durdur()

        csv_dosyalar = list(tmp_path.glob("telemetri_*.csv"))
        with open(csv_dosyalar[0], encoding="utf-8") as f:
            satirlar = list(csv.DictReader(f))

        assert len(satirlar) == 1
        assert float(satirlar[0]["irtifa"]) == pytest.approx(42.5)
        assert float(satirlar[0]["hiz"])    == pytest.approx(3.2)
        assert satirlar[0]["bat_yuzde"]     == "87"

    def test_birden_fazla_satir(self, gecici_logger, tmp_path):
        """Birden fazla satır sırayla yazılabilmeli."""
        for i in range(10):
            gecici_logger.kaydet_satir({"irtifa": float(i * 5)})
        gecici_logger.durdur()

        csv_dosyalar = list(tmp_path.glob("telemetri_*.csv"))
        with open(csv_dosyalar[0], encoding="utf-8") as f:
            satirlar = list(csv.DictReader(f))

        assert len(satirlar) == 10
        for i, satir in enumerate(satirlar):
            assert float(satir["irtifa"]) == pytest.approx(i * 5.0)

    def test_zaman_otomatik_eklenir(self, gecici_logger, tmp_path):
        """'zaman' alanı sağlanmazsa otomatik eklenmeli."""
        gecici_logger.kaydet_satir({"irtifa": 10.0})  # zaman yok
        gecici_logger.durdur()

        csv_dosyalar = list(tmp_path.glob("telemetri_*.csv"))
        with open(csv_dosyalar[0], encoding="utf-8") as f:
            satirlar = list(csv.DictReader(f))

        assert satirlar[0]["zaman"] != ""

    def test_eksik_alan_bos_kalir(self, gecici_logger, tmp_path):
        """Verilmeyen alanlar boş string olarak yazılmalı."""
        gecici_logger.kaydet_satir({"irtifa": 5.0})
        gecici_logger.durdur()

        csv_dosyalar = list(tmp_path.glob("telemetri_*.csv"))
        with open(csv_dosyalar[0], encoding="utf-8") as f:
            satirlar = list(csv.DictReader(f))

        assert satirlar[0]["bat_volt"] == ""
        assert satirlar[0]["gps_fix"]  == ""

    def test_aktif_olmadan_yazma_sessiz(self, tmp_path):
        """baslat() çağrılmadan kaydet_satir() çakmamalı."""
        logger = GCSLogger(log_klasoru=str(tmp_path))
        # baslat() çağırılmıyor — sessizce geçmeli
        logger.kaydet_satir({"irtifa": 10.0})


# ── Sistem Mesajı ─────────────────────────────────────────────────────────────

class TestSistemMesaji:

    def test_log_dosyasi_olusur(self, gecici_logger, tmp_path):
        """baslat() sonrası .log dosyası oluşturulmuş olmalı."""
        log_dosyalar = list(tmp_path.glob("sistem_*.log"))
        assert len(log_dosyalar) == 1

    def test_mesaj_yazilir(self, gecici_logger, tmp_path):
        """kaydet_mesaj() içeriği .log dosyasına yazılmalı."""
        gecici_logger.kaydet_mesaj(5, "Test mesaj 123")
        gecici_logger.durdur()

        log_dosyalar = list(tmp_path.glob("sistem_*.log"))
        icerik = log_dosyalar[0].read_text(encoding="utf-8")
        assert "Test mesaj 123" in icerik

    def test_severity_yazilir(self, gecici_logger, tmp_path):
        """Severity seviyesi (SEVx) log satırında görünmeli."""
        gecici_logger.kaydet_mesaj(2, "Kritik hata")
        gecici_logger.durdur()

        log_dosyalar = list(tmp_path.glob("sistem_*.log"))
        icerik = log_dosyalar[0].read_text(encoding="utf-8")
        assert "SEV2" in icerik
        assert "Kritik hata" in icerik

    def test_baslat_durdur_mesajlari(self, tmp_path):
        """'Loglama başladı' ve 'Loglama durduruldu' otomatik yazılmalı."""
        logger = GCSLogger(log_klasoru=str(tmp_path))
        logger.baslat()
        logger.durdur()

        log_dosyalar = list(tmp_path.glob("sistem_*.log"))
        icerik = log_dosyalar[0].read_text(encoding="utf-8")
        assert "Loglama başladı" in icerik
        assert "Loglama durduruldu" in icerik


# ── Thread-Safety ─────────────────────────────────────────────────────────────

class TestThreadSafety:

    def test_cok_thread_eş_zamanli_yazma(self, tmp_path):
        """Birden fazla thread aynı anda yazabilmeli — satır kayıp olmamalı."""
        logger = GCSLogger(log_klasoru=str(tmp_path))
        logger.baslat()

        N_THREAD  = 8
        N_SATIR   = 25
        hatalar   = []

        def yaz(thread_id):
            for i in range(N_SATIR):
                try:
                    logger.kaydet_satir({
                        "irtifa": float(thread_id * 1000 + i),
                        "hiz":    float(thread_id),
                    })
                except Exception as exc:
                    hatalar.append(exc)

        threadler = [threading.Thread(target=yaz, args=(t,)) for t in range(N_THREAD)]
        for t in threadler:
            t.start()
        for t in threadler:
            t.join()

        logger.durdur()

        assert len(hatalar) == 0, f"Thread hatası: {hatalar[0]}"

        csv_dosyalar = list(tmp_path.glob("telemetri_*.csv"))
        with open(csv_dosyalar[0], encoding="utf-8") as f:
            satirlar = list(csv.DictReader(f))

        assert len(satirlar) == N_THREAD * N_SATIR

    def test_cok_thread_mesaj_yazma(self, tmp_path):
        """Birden fazla thread sistem mesajı yazabilmeli — çakışma olmamalı."""
        logger = GCSLogger(log_klasoru=str(tmp_path))
        logger.baslat()

        N_THREAD = 5
        N_MESAJ  = 20
        hatalar  = []

        def mesaj_yaz(tid):
            for i in range(N_MESAJ):
                try:
                    logger.kaydet_mesaj(6, f"Thread {tid} mesaj {i}")
                except Exception as exc:
                    hatalar.append(exc)

        threadler = [threading.Thread(target=mesaj_yaz, args=(t,)) for t in range(N_THREAD)]
        for t in threadler:
            t.start()
        for t in threadler:
            t.join()

        logger.durdur()
        assert len(hatalar) == 0

        log_dosyalar = list(tmp_path.glob("sistem_*.log"))
        icerik = log_dosyalar[0].read_text(encoding="utf-8")
        # En az N_THREAD * N_MESAJ + 2 (başlat/durdur) satır olmalı
        assert icerik.count("\n") >= N_THREAD * N_MESAJ + 2


# ── Başlat / Durdur Yaşam Döngüsü ────────────────────────────────────────────

class TestYasamDongusu:

    def test_durdur_dosyalari_kapatir(self, tmp_path):
        """durdur() sonrası logger'a yazma, hata fırlatmamalı (sessiz geçmeli)."""
        logger = GCSLogger(log_klasoru=str(tmp_path))
        logger.baslat()
        logger.durdur()
        # Durdurulduktan sonra yazmak sessizce geçmeli
        logger.kaydet_satir({"irtifa": 1.0})
        logger.kaydet_mesaj(6, "Geç mesaj")

    def test_cift_durdur_guvenli(self, tmp_path):
        """durdur() iki kez çağrılınca hata fırlatmamalı."""
        logger = GCSLogger(log_klasoru=str(tmp_path))
        logger.baslat()
        logger.durdur()
        logger.durdur()  # ikinci çağrı güvenli olmalı

    def test_dosya_yollari_tutarli(self, tmp_path):
        """csv_yolu() ve log_yolu() baslat() sonrası geçerli yollar döndürmeli."""
        logger = GCSLogger(log_klasoru=str(tmp_path))
        logger.baslat()

        csv_yol = logger.csv_yolu()
        log_yol = logger.log_yolu()

        assert csv_yol.endswith(".csv")
        assert log_yol.endswith(".log")
        assert os.path.exists(csv_yol)
        assert os.path.exists(log_yol)

        logger.durdur()

    def test_oturum_adi_tarih_iceriyor(self, tmp_path):
        """Oturum dosya isimleri tarih/saat içermeli."""
        logger = GCSLogger(log_klasoru=str(tmp_path))
        logger.baslat()
        csv_yol = logger.csv_yolu()
        logger.durdur()

        dosya_adi = os.path.basename(csv_yol)
        # Örn: telemetri_20260524_134521.csv
        assert dosya_adi.startswith("telemetri_")
        # Tarih kısmı: YYYYMMDD_HHMMSS = 15 karakter
        oturum = dosya_adi[len("telemetri_"):len("telemetri_") + 15]
        assert len(oturum) == 15
        assert oturum[8] == "_"

    def test_klasor_yoksa_olusturulur(self, tmp_path):
        """Belirtilen log klasörü yoksa otomatik oluşturulmalı."""
        yeni_klasor = str(tmp_path / "alt" / "klasor")
        assert not os.path.exists(yeni_klasor)
        logger = GCSLogger(log_klasoru=yeni_klasor)
        assert os.path.exists(yeni_klasor)

    def test_flush_anlik(self, tmp_path):
        """kaydet_satir() sonrası veri diske yazılmış (flush) olmalı."""
        logger = GCSLogger(log_klasoru=str(tmp_path))
        logger.baslat()
        logger.kaydet_satir({"irtifa": 99.9})

        # durdur() çağrılmadan CSV'yi oku — flush sayesinde veri orada olmalı
        csv_dosyalar = list(tmp_path.glob("telemetri_*.csv"))
        with open(csv_dosyalar[0], encoding="utf-8") as f:
            satirlar = list(csv.DictReader(f))

        assert len(satirlar) == 1
        assert float(satirlar[0]["irtifa"]) == pytest.approx(99.9)
        logger.durdur()
