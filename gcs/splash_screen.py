from PyQt5.QtCore import Qt, QTimer, pyqtSignal as Signal
from PyQt5.QtGui import QColor, QFont, QPainter, QPen
from PyQt5.QtWidgets import QApplication, QLabel, QProgressBar, QVBoxLayout, QWidget


class SplashEkrani(QWidget):
    """
    Uygulama açılırken gösterilen tam ekran splash.
    Yükleme adımlarını progress bar ile gösterir,
    tamamlanınca ana pencereye geçiş sinyali verir.
    """

    tamamlandi = Signal()

    _ADIMLAR = [
        (10,  "Konfigürasyon yükleniyor…"),
        (25,  "Arayüz bileşenleri hazırlanıyor…"),
        (45,  "MAVLink modülü başlatılıyor…"),
        (60,  "Terrain analiz motoru yükleniyor…"),
        (78,  "Harita ve sensör modülleri…"),
        (92,  "Son kontroller yapılıyor…"),
        (100, "Hazır — hoş geldiniz!"),
    ]

    def __init__(self):
        super().__init__()
        self._adim_idx = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._sonraki_adim)
        self._ui_olustur()

    def _ui_olustur(self):
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setFixedSize(680, 400)

        ekran = QApplication.primaryScreen().geometry()
        self.move(
            ekran.center().x() - self.width()  // 2,
            ekran.center().y() - self.height() // 2,
        )

        self.setStyleSheet("background-color: #0d1117;")

        ana = QVBoxLayout(self)
        ana.setContentsMargins(56, 40, 56, 36)
        ana.setSpacing(0)

        logo_lbl = QLabel("🛸")
        logo_lbl.setAlignment(Qt.AlignCenter)
        logo_lbl.setStyleSheet("font-size: 60px; background: transparent;")
        ana.addWidget(logo_lbl)

        ana.addSpacing(10)

        baslik = QLabel("DOĞUŞ ÜNİVERSİTESİ LÖP")
        baslik.setAlignment(Qt.AlignCenter)
        baslik.setFont(QFont("Segoe UI", 22, QFont.Bold))
        baslik.setStyleSheet("color: #58a6ff; background: transparent;")
        ana.addWidget(baslik)

        altyazi = QLabel("Türkçe İnsansız Hava Aracı Yer İstasyonu")
        altyazi.setAlignment(Qt.AlignCenter)
        altyazi.setFont(QFont("Segoe UI", 12))
        altyazi.setStyleSheet("color: #8b949e; background: transparent;")
        ana.addWidget(altyazi)

        ana.addSpacing(10)

        ayirici = QLabel("─" * 64)
        ayirici.setAlignment(Qt.AlignCenter)
        ayirici.setStyleSheet("color: #21262d; background: transparent;")
        ana.addWidget(ayirici)

        ana.addSpacing(16)

        ozellikler = QLabel(
            "Çok Katmanlı Güvenli İniş Analizi  ·  Gerçek Zamanlı LIDAR Zemin Doğrulaması\n"
            "RTL İzleyici & Otomatik Fallback  ·  Copernicus GLO-30 Terrain Entegrasyonu"
        )
        ozellikler.setAlignment(Qt.AlignCenter)
        ozellikler.setWordWrap(True)
        ozellikler.setFont(QFont("Segoe UI", 10))
        ozellikler.setStyleSheet("color: #3fb950; background: transparent;")
        ana.addWidget(ozellikler)

        ana.addStretch()

        self._durum_lbl = QLabel("Başlatılıyor…")
        self._durum_lbl.setAlignment(Qt.AlignCenter)
        self._durum_lbl.setFont(QFont("Segoe UI", 9))
        self._durum_lbl.setStyleSheet("color: #8b949e; background: transparent;")
        ana.addWidget(self._durum_lbl)

        ana.addSpacing(8)

        self._pb = QProgressBar()
        self._pb.setRange(0, 100)
        self._pb.setValue(0)
        self._pb.setTextVisible(False)
        self._pb.setFixedHeight(4)
        self._pb.setStyleSheet("""
            QProgressBar {
                background: #21262d;
                border: none;
                border-radius: 2px;
            }
            QProgressBar::chunk {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1f6feb, stop:1 #58a6ff
                );
                border-radius: 2px;
            }
        """)
        ana.addWidget(self._pb)

        ana.addSpacing(12)

        versiyon = QLabel("Sürüm 1.0  ·  2026  ·  Lisans Öğrenci Projesi")
        versiyon.setAlignment(Qt.AlignCenter)
        versiyon.setFont(QFont("Segoe UI", 8))
        versiyon.setStyleSheet("color: #444c56; background: transparent;")
        ana.addWidget(versiyon)

    def goster_ve_yukle(self):
        """Splash'ı göster, 300ms sonra yükleme adımlarını başlat."""
        self.show()
        QTimer.singleShot(300, lambda: self._timer.start(340))

    def _sonraki_adim(self):
        if self._adim_idx >= len(self._ADIMLAR):
            self._timer.stop()
            QTimer.singleShot(350, self.tamamlandi.emit)
            return
        yuzde, metin = self._ADIMLAR[self._adim_idx]
        self._pb.setValue(yuzde)
        self._durum_lbl.setText(metin)
        self._adim_idx += 1

    def paintEvent(self, event):
        """İnce kenarlık çiz."""
        super().paintEvent(event)
        p = QPainter(self)
        p.setPen(QPen(QColor("#21262d"), 1))
        p.drawRect(0, 0, self.width() - 1, self.height() - 1)
