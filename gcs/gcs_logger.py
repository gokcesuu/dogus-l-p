"""
gcs_logger.py
Doğuş Üniversitesi LÖP – GCS Kalıcı Loglama Modülü

Tüm telemetri verisini ve sistem mesajlarını eşzamanlı olarak
diske yazar. İki çıktı:
  - telemetri_YYYYMMDD_HHMMSS.csv  : sayısal sensör verisi
  - sistem_YYYYMMDD_HHMMSS.log     : STATUSTEXT ve GCS olayları

Thread-safe — mavlink_handler sinyallerinden doğrudan çağrılır.
"""

import os
import csv
import threading
from datetime import datetime


LOG_KLASORU = os.path.join(os.path.expanduser("~"), ".dogus_gcs", "loglar")


class GCSLogger:
    """
    GCS'e bağlan → logger.baslat()
    Her sinyal gelişinde ilgili kaydet_* metodunu çağır.
    İniş/bağlantı kesilince → logger.durdur()
    """

    def __init__(self, log_klasoru: str = LOG_KLASORU):
        self._klasor = log_klasoru
        os.makedirs(self._klasor, exist_ok=True)
        self._kilit = threading.Lock()
        self._aktif = False
        self._csv_f = None
        self._csv_yazar = None
        self._log_f = None
        self._oturum = ""

    # ── Başlat / Durdur ───────────────────────────────────────────────────────

    def baslat(self):
        self._oturum = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_yolu = os.path.join(self._klasor, f"telemetri_{self._oturum}.csv")
        log_yolu = os.path.join(self._klasor, f"sistem_{self._oturum}.log")

        self._csv_f = open(csv_yolu, "w", newline="", encoding="utf-8")
        self._csv_yazar = csv.DictWriter(self._csv_f, fieldnames=[
            "zaman", "irtifa", "hiz", "dikey_hiz", "eve_uzaklik",  # eve_uzaklik: VFR_HUD'dan
            "bat_volt", "bat_amper", "bat_yuzde",
            "gps_fix", "gps_uydu", "lat", "lon",
            "roll", "pitch", "yaw",
            "ruzgar_ms", "ruzgar_yon",
            "ruzgar_zemin_ms", "ruzgar_trend",
            "imu0_c", "imu1_c", "imu2_c",
            "ekf_bayrak", "ekf_hata",
            "mod_id",
        ])
        self._csv_yazar.writeheader()

        self._log_f = open(log_yolu, "w", encoding="utf-8")
        self._aktif = True
        self._olay_kaydet("GCS", "Loglama başladı")

    def durdur(self):
        with self._kilit:
            if not self._aktif:
                return
            self._aktif = False
        self._olay_kaydet("GCS", "Loglama durduruldu")
        with self._kilit:
            if self._csv_f:
                self._csv_f.close()
                self._csv_f = None
            if self._log_f:
                self._log_f.close()
                self._log_f = None

    # ── Telemetri kaydı ───────────────────────────────────────────────────────

    def kaydet_satir(self, satir: dict):
        """Bir telemetri satırını CSV'ye yazar."""
        if not self._aktif or not self._csv_yazar:
            return
        satir.setdefault("zaman", datetime.now().isoformat(timespec="milliseconds"))
        with self._kilit:
            try:
                self._csv_yazar.writerow(satir)
                self._csv_f.flush()
            except Exception:
                pass

    # ── Sistem mesajı kaydı ───────────────────────────────────────────────────

    def kaydet_mesaj(self, severity: int, metin: str):
        """STATUSTEXT mesajını .log dosyasına yazar."""
        self._olay_kaydet(f"SEV{severity}", metin)

    def _olay_kaydet(self, kaynak: str, metin: str):
        if not self._log_f:
            return
        zaman = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        satir = f"[{zaman}] [{kaynak:8s}] {metin}\n"
        with self._kilit:
            try:
                self._log_f.write(satir)
                self._log_f.flush()
            except Exception:
                pass

    # ── Log dosyası yolları ───────────────────────────────────────────────────

    def csv_yolu(self) -> str:
        return os.path.join(self._klasor, f"telemetri_{self._oturum}.csv")

    def log_yolu(self) -> str:
        return os.path.join(self._klasor, f"sistem_{self._oturum}.log")
