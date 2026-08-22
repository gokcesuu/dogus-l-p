"""
Kalibrasyon Sihirbazı — Gyro / İvmeölçer / Manyetometre için adım adım
rehberli kalibrasyon akışı.

Mevcut tek-tık kalibrasyon butonlarının (gcs_main.py: _hizli_kalibrasyon)
yerini almaz, üstüne bir rehberlik katmanı ekler: her adımda Türkçe talimat
gösterir, MAV_CMD_PREFLIGHT_CALIBRATION (241) komutunu gönderir ve gelen
STATUSTEXT mesajlarını (ArduPilot'un "Place vehicle level", "Calibration
successful" gibi kendi yönlendirmesini) canlı olarak büyük punto gösterir.

Dürüst sınır: İvmeölçer kalibrasyonu ArduPilot'ta 6 pozisyonlu interaktif
bir protokoldür (drone sırayla düz/ters/yan çevrilir, her pozisyonda
ArduPilot onay bekler). Bu protokolün otomatik pozisyon-onayı gerçek
donanımla doğrulanmadan güvenle yazılamayacağı için, bu sihirbaz o adımda
sadece ArduPilot'un kendi STATUSTEXT talimatlarını okunaklı şekilde
gösterir; sahte bir "otomatik onay" iddiası yapmaz.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QProgressBar, QWidget,
)

_ADIMLAR = [
    {
        "ad": "GYRO",
        "baslik": "1/3 — Gyro (Jiroskop) Kalibrasyonu",
        "talimat": (
            "Drone'u sabit, düz bir zemine koyun.\n"
            "Kalibrasyon sırasında DOKUNMAYIN — birkaç saniye sürer.\n\n"
            "Başlat'a bastığınızda drone'a gyro kalibrasyon komutu gönderilecek."
        ),
        "p1": 1, "p2": 0, "p5": 0,
        "basari_anahtar": ["gyro cal", "calibration successful", "gyro calibration ok"],
        "hata_anahtar": ["gyro cal fail", "calibration failed"],
    },
    {
        "ad": "ACCEL",
        "baslik": "2/3 — İvmeölçer Kalibrasyonu",
        "talimat": (
            "Bu adım İNTERAKTİFTİR: ArduPilot, drone'u sırasıyla 6 farklı\n"
            "pozisyonda (düz, ters, sağ yana, sol yana, burun yukarı,\n"
            "burun aşağı) tutmanızı isteyecek.\n\n"
            "Başlat'a bastıktan sonra AŞAĞIDAKİ CANLI MESAJ PANELİNİ takip\n"
            "edin — ArduPilot her pozisyon için ayrı talimat gönderir.\n"
            "Bu sihirbaz pozisyon onayını otomatik yapmaz; talimatları\n"
            "olduğu gibi burada gösterir."
        ),
        "p1": 0, "p2": 0, "p5": 1,
        "basari_anahtar": ["accel cal", "calibration successful"],
        "hata_anahtar": ["accel cal fail", "calibration failed"],
    },
    {
        "ad": "MAG",
        "baslik": "3/3 — Manyetometre (Compass) Kalibrasyonu",
        "talimat": (
            "Drone'u elinize alın ve tüm eksenlerde (X, Y, Z) yavaşça\n"
            "360° döndürün — her eksende en az bir tam tur yapın.\n\n"
            "Başlat'a bastığınızda kalibrasyon başlar, ilerleme yüzdesini\n"
            "STATUSTEXT mesajlarında göreceksiniz."
        ),
        "p1": 0, "p2": 1, "p5": 0,
        "basari_anahtar": ["mag cal", "compass", "calibration successful"],
        "hata_anahtar": ["mag cal fail", "calibration failed"],
    },
]


class KalibrasyonSihirbazi(QDialog):
    """3 adımlı (Gyro → Accel → Mag) rehberli kalibrasyon dialogu."""

    def __init__(self, gcs_pencere):
        super().__init__(gcs_pencere)
        self._gcs = gcs_pencere
        self._adim_no = 0
        self._basladi = False
        self.setWindowTitle("🔧 Kalibrasyon Sihirbazı")
        self.setMinimumSize(520, 460)
        self._ui_kur()
        self._adimi_yukle()

    def _ui_kur(self):
        lay = QVBoxLayout(self)

        self._progress = QProgressBar()
        self._progress.setMaximum(len(_ADIMLAR))
        self._progress.setValue(0)
        self._progress.setFormat("Adım %v / %m")
        lay.addWidget(self._progress)

        self._baslik_lbl = QLabel()
        self._baslik_lbl.setFont(QFont("Barlow Condensed", 15, QFont.Bold))
        self._baslik_lbl.setStyleSheet("color:#bdd8f2;")
        lay.addWidget(self._baslik_lbl)

        self._talimat_lbl = QLabel()
        self._talimat_lbl.setWordWrap(True)
        self._talimat_lbl.setStyleSheet("color:#dce8f5; font-size:13px;")
        lay.addWidget(self._talimat_lbl)

        self._basla_btn = QPushButton("▶ Bu Adımı Başlat")
        self._basla_btn.setFixedHeight(34)
        self._basla_btn.clicked.connect(self._adimi_baslat)
        lay.addWidget(self._basla_btn)

        lay.addWidget(QLabel("Canlı STATUSTEXT (ArduPilot mesajları):"))
        self._mesaj_kutu = QTextEdit()
        self._mesaj_kutu.setReadOnly(True)
        self._mesaj_kutu.setStyleSheet(
            "background:#0c1620; color:#a8cf94; font-family:'Consolas',monospace; font-size:12px;"
        )
        lay.addWidget(self._mesaj_kutu, 1)

        btn_row = QHBoxLayout()
        self._geri_btn = QPushButton("◀ Geri")
        self._geri_btn.clicked.connect(self._onceki_adim)
        btn_row.addWidget(self._geri_btn)
        btn_row.addStretch()
        self._ileri_btn = QPushButton("İleri ▶")
        self._ileri_btn.clicked.connect(self._sonraki_adim)
        btn_row.addWidget(self._ileri_btn)
        self._kapat_btn = QPushButton("Kapat")
        self._kapat_btn.clicked.connect(self.accept)
        btn_row.addWidget(self._kapat_btn)
        lay.addLayout(btn_row)

    def _adimi_yukle(self):
        adim = _ADIMLAR[self._adim_no]
        self._progress.setValue(self._adim_no + 1)
        self._baslik_lbl.setText(adim["baslik"])
        self._talimat_lbl.setText(adim["talimat"])
        self._mesaj_kutu.clear()
        self._basla_btn.setEnabled(True)
        self._basla_btn.setText("▶ Bu Adımı Başlat")
        self._geri_btn.setEnabled(self._adim_no > 0)
        self._ileri_btn.setEnabled(self._adim_no < len(_ADIMLAR) - 1)
        self._basladi = False
        # Önceki adımdan kalan bağlantıyı temizle
        try:
            self._gcs._mavlink.durum_mesaji.disconnect(self._statustext_yakala)
        except (TypeError, RuntimeError):
            pass
        self._gcs._mavlink.durum_mesaji.connect(self._statustext_yakala)

    def _adimi_baslat(self):
        adim = _ADIMLAR[self._adim_no]
        if not self._gcs._komut_izinli_mi():
            return
        self._gcs._mavlink.komut_gonder(
            241, adim["p1"], adim["p2"], 0, 0, adim["p5"], 0, 0
        )
        self._basladi = True
        self._basla_btn.setText("⏳ Kalibrasyon gönderildi — mesajları izleyin")
        self._basla_btn.setEnabled(False)
        self._mesaj_kutu.append(f"[{adim['ad']}] Kalibrasyon komutu gönderildi (MAV_CMD_PREFLIGHT_CALIBRATION).")

    def _statustext_yakala(self, severity, metin: str):
        """MavlinkHandler.durum_mesaji sinyalinden gelen her STATUSTEXT'i gösterir."""
        if not self._basladi:
            return
        self._mesaj_kutu.append(metin)
        alt_metin = metin.lower()
        adim = _ADIMLAR[self._adim_no]
        if any(k in alt_metin for k in adim["hata_anahtar"]):
            self._mesaj_kutu.append(f"✗ [{adim['ad']}] BAŞARISIZ — talimatı tekrar deneyin.")
            self._basla_btn.setText("▶ Tekrar Dene")
            self._basla_btn.setEnabled(True)
        elif any(k in alt_metin for k in adim["basari_anahtar"]):
            self._mesaj_kutu.append(f"✓ [{adim['ad']}] Tamamlandı.")
            self._basla_btn.setText("✓ Tamamlandı")

    def _onceki_adim(self):
        if self._adim_no > 0:
            self._adim_no -= 1
            self._adimi_yukle()

    def _sonraki_adim(self):
        if self._adim_no < len(_ADIMLAR) - 1:
            self._adim_no += 1
            self._adimi_yukle()

    def closeEvent(self, event):
        try:
            self._gcs._mavlink.durum_mesaji.disconnect(self._statustext_yakala)
        except (TypeError, RuntimeError):
            pass
        super().closeEvent(event)
