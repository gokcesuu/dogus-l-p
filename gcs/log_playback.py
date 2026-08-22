"""
Uçuş kaydı oynatma — gcs_logger.py'nin yazdığı telemetri CSV dosyasını
okuyup, mevcut UI güncelleme fonksiyonlarını (aynı anda MAVLink bağlantısı
yokken) sırayla çağırarak geçmiş bir uçuşu "oynatır".

Sadece bağlantı yokken (self._bagli == False) kullanılmalı; aksi halde
canlı veriyle oynatılan veri karışabilir — bu kontrol gcs_main.py
tarafında yapılıyor.
"""

import csv

from PyQt5.QtCore import QObject, QTimer, pyqtSignal


class LogOynatici(QObject):
    """CSV telemetri logunu satır satır okuyup GCS penceresindeki
    güncelleme fonksiyonlarını (VFR/GPS/Batarya/Tutum) tetikler."""

    ilerleme = pyqtSignal(int, int)   # (mevcut_satir, toplam_satir)
    bitti = pyqtSignal()

    def __init__(self, gcs_pencere, csv_yolu: str):
        super().__init__()
        self._gcs = gcs_pencere
        self._satirlar = self._csv_oku(csv_yolu)
        self._idx = 0
        self._hiz = 1.0
        self._timer = QTimer()
        self._timer.timeout.connect(self._sonraki_satir)

    @staticmethod
    def _csv_oku(yol: str) -> list:
        with open(yol, encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))

    def satir_sayisi(self) -> int:
        return len(self._satirlar)

    def calisiyor_mu(self) -> bool:
        return self._timer.isActive()

    def baslat(self, hiz: float = 1.0):
        """Oynatmayı başlatır/devam ettirir. hiz: 1.0=normal, 2.0=2x, 5.0=5x."""
        self._hiz = max(0.1, hiz)
        self._timer.start(max(20, int(1000 / self._hiz)))

    def duraklat(self):
        self._timer.stop()

    def durdur(self):
        """Oynatmayı tamamen durdurur ve baştan başlatılabilir hale getirir."""
        self._timer.stop()
        self._idx = 0

    @staticmethod
    def _f(satir: dict, anahtar: str, varsayilan=0.0) -> float:
        try:
            return float(satir.get(anahtar, varsayilan) or varsayilan)
        except (TypeError, ValueError):
            return varsayilan

    @staticmethod
    def _i(satir: dict, anahtar: str, varsayilan=0) -> int:
        try:
            return int(float(satir.get(anahtar, varsayilan) or varsayilan))
        except (TypeError, ValueError):
            return varsayilan

    def _sonraki_satir(self):
        if self._idx >= len(self._satirlar):
            self._timer.stop()
            self.bitti.emit()
            return
        s = self._satirlar[self._idx]
        g = self._gcs
        try:
            g._vfr_guncelle(
                self._f(s, "irtifa"), self._f(s, "hiz"),
                self._f(s, "dikey_hiz"), self._f(s, "eve_uzaklik"),
            )
            g._gps_guncelle(
                self._i(s, "gps_fix"), self._i(s, "gps_uydu"),
                self._f(s, "lat"), self._f(s, "lon"),
            )
            g._batarya_guncelle(
                self._f(s, "bat_volt"), self._f(s, "bat_amper"), self._i(s, "bat_yuzde"),
            )
            g._tutum_guncelle(
                self._f(s, "roll"), self._f(s, "pitch"), self._f(s, "yaw"),
            )
        except Exception:
            pass   # oynatma sırasında tekil satır hatası tüm akışı durdurmasın
        self._idx += 1
        self.ilerleme.emit(self._idx, len(self._satirlar))
