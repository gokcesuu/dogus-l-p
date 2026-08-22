import os

from PyQt5.QtCore import Qt, QTimer, pyqtSignal as Signal
from PyQt5.QtGui import QColor, QFont, QPainter, QPen
from PyQt5.QtWidgets import (
    QApplication, QLabel, QProgressBar, QVBoxLayout, QHBoxLayout, QWidget
)

# 1B/1G kokpit paleti — ui_theme.py'deki KOKPIT_* sabitleriyle aynı değerler
# (splash_screen.py bağımsız kalması için burada tekrar tanımlanıyor, döngüsel
# import'a gerek kalmıyor).
_ZEMIN   = "#16222e"
_PANEL   = "#1d2d3d"
_KENAR   = "rgba(148,188,227,0.22)"
_VURGU   = "#94bce3"
_VURGU2  = "#bdd8f2"
_IYI     = "#8fbf7a"
_UYARI   = "#d9a24a"


class SplashEkrani(QWidget):
    """
    Uygulama açılırken gösterilen açılış ekranı (1G).
    Sol: marka + yükleme ilerlemesi. Sağ: SİSTEM ÖN KONTROLÜ (gerçek
    bağımlılık/dosya kontrolleri) + UÇUŞ ALANI (alan_verisi.npz durumu).
    Tamamlanınca ana pencereye geçiş sinyali verir.
    """

    tamamlandi = Signal()

    _ADIMLAR = [
        (15,  "Konfigürasyon yükleniyor…"),
        (35,  "Arayüz bileşenleri hazırlanıyor…"),
        (55,  "MAVLink modülü başlatılıyor…"),
        (75,  "Terrain analiz motoru yükleniyor…"),
        (90,  "Harita ve sensör modülleri…"),
        (100, "Hazır — hoş geldiniz!"),
    ]

    def __init__(self):
        super().__init__()
        self._adim_idx = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._sonraki_adim)
        self._ui_olustur()

    # ── Gerçek sistem ön kontrolü ──────────────────────────────────────────────

    def _sistem_kontrolleri(self) -> list:
        """(etiket, ok, detay) listesi döner — hepsi gerçek kontrol, dekor değil."""
        kontroller = []

        try:
            from PyQt5.QtWebEngineWidgets import QWebEngineView  # noqa: F401
            kontroller.append(("Harita motoru (QtWebEngine)", True, "kurulu"))
        except Exception:
            kontroller.append(("Harita motoru (QtWebEngine)", False, "eksik — pip install PyQtWebEngine"))

        try:
            import pyqtgraph  # noqa: F401
            kontroller.append(("Grafik motoru (pyqtgraph)", True, "kurulu"))
        except Exception:
            kontroller.append(("Grafik motoru (pyqtgraph)", False, "eksik — pip install pyqtgraph"))

        try:
            import pyttsx3  # noqa: F401
            kontroller.append(("Sesli uyarı (pyttsx3)", True, "kurulu"))
        except Exception:
            kontroller.append(("Sesli uyarı (pyttsx3)", False, "eksik — sesli uyarılar devre dışı"))

        taban = os.path.dirname(__file__)
        cfg_yollari = (os.path.join(taban, "config.json"), os.path.join(taban, "..", "config.json"))
        cfg_var = any(os.path.isfile(p) for p in cfg_yollari)
        kontroller.append(("Konfigürasyon (config.json)", cfg_var,
                            "bulundu" if cfg_var else "bulunamadı — varsayılanlar kullanılacak"))

        try:
            from pymavlink import mavutil  # noqa: F401
            kontroller.append(("MAVLink kütüphanesi (pymavlink)", True, "kurulu"))
        except Exception:
            kontroller.append(("MAVLink kütüphanesi (pymavlink)", False, "eksik — bağlantı kurulamaz"))

        return kontroller

    def _ucus_alani_durumu(self) -> tuple:
        """(satırlar, hazir_mi) — alan_verisi.npz'nin durumu."""
        taban = os.path.dirname(__file__)
        for yol in (os.path.join(taban, "alan_verisi.npz"), "alan_verisi.npz"):
            if os.path.isfile(yol):
                try:
                    import numpy as np
                    data = np.load(yol, allow_pickle=True)
                    dem = data["dem"] if "dem" in data else None
                    boyut = os.path.getsize(yol) / (1024 * 1024)
                    satirlar = [
                        f"Dosya: {os.path.basename(yol)} ({boyut:.1f} MB)",
                        f"DEM ızgarası: {dem.shape[0]}×{dem.shape[1]}" if dem is not None else "DEM: eski format",
                    ]
                    return satirlar, True
                except Exception as e:
                    return [f"Dosya var ama okunamadı: {e}"], False
        return ["alan_verisi.npz bulunamadı",
                "GPS fix alınca otomatik oluşturulacak"], False

    # ── UI ────────────────────────────────────────────────────────────────────

    def _ui_olustur(self):
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setFixedSize(920, 480)

        ekran = QApplication.primaryScreen().geometry()
        self.move(
            ekran.center().x() - self.width()  // 2,
            ekran.center().y() - self.height() // 2,
        )
        self.setStyleSheet(f"background-color: {_ZEMIN};")

        satir = QHBoxLayout(self)
        satir.setContentsMargins(0, 0, 0, 0)
        satir.setSpacing(0)

        # ── Sol: marka + ilerleme ──────────────────────────────────────────
        sol = QWidget()
        sol.setFixedWidth(480)
        ana = QVBoxLayout(sol)
        ana.setContentsMargins(48, 40, 40, 32)
        ana.setSpacing(0)

        logo_lbl = QLabel("🛸")
        logo_lbl.setAlignment(Qt.AlignCenter)
        logo_lbl.setStyleSheet("font-size: 56px; background: transparent;")
        ana.addWidget(logo_lbl)
        ana.addSpacing(8)

        baslik = QLabel("DOĞUŞ ÜNİVERSİTESİ LÖP")
        baslik.setAlignment(Qt.AlignCenter)
        baslik.setWordWrap(True)
        baslik.setFont(QFont("Barlow Condensed", 18, QFont.Bold))
        baslik.setStyleSheet(f"color:{_VURGU2}; background:transparent;")
        ana.addWidget(baslik)

        altyazi = QLabel("Türkçe İnsansız Hava Aracı Yer İstasyonu")
        altyazi.setAlignment(Qt.AlignCenter)
        altyazi.setFont(QFont("Barlow", 11))
        altyazi.setStyleSheet("color:#7e9cb8; background:transparent;")
        ana.addWidget(altyazi)
        ana.addSpacing(14)

        ozellikler = QLabel(
            "Çok Katmanlı Güvenli İniş Analizi  ·  Gerçek Zamanlı LIDAR Zemin Doğrulaması\n"
            "RTL İzleyici & Otomatik Fallback  ·  Copernicus GLO-30 Terrain Entegrasyonu"
        )
        ozellikler.setAlignment(Qt.AlignCenter)
        ozellikler.setWordWrap(True)
        ozellikler.setFont(QFont("Barlow", 9))
        ozellikler.setStyleSheet(f"color:{_IYI}; background:transparent;")
        ana.addWidget(ozellikler)

        ana.addStretch()

        self._durum_lbl = QLabel("Başlatılıyor…")
        self._durum_lbl.setAlignment(Qt.AlignCenter)
        self._durum_lbl.setFont(QFont("Barlow", 9))
        self._durum_lbl.setStyleSheet("color:#7e9cb8; background:transparent;")
        ana.addWidget(self._durum_lbl)
        ana.addSpacing(8)

        self._pb = QProgressBar()
        self._pb.setRange(0, 100)
        self._pb.setValue(0)
        self._pb.setTextVisible(False)
        self._pb.setFixedHeight(4)
        self._pb.setStyleSheet(f"""
            QProgressBar {{ background:{_PANEL}; border:none; border-radius:2px; }}
            QProgressBar::chunk {{ background:{_VURGU}; border-radius:2px; }}
        """)
        ana.addWidget(self._pb)
        ana.addSpacing(10)

        versiyon = QLabel("Sürüm 1.0  ·  2026  ·  Lisans Öğrenci Projesi")
        versiyon.setAlignment(Qt.AlignCenter)
        versiyon.setFont(QFont("Barlow", 8))
        versiyon.setStyleSheet("color:#4a6478; background:transparent;")
        ana.addWidget(versiyon)

        satir.addWidget(sol)

        # ── Sağ: SİSTEM ÖN KONTROLÜ + UÇUŞ ALANI ────────────────────────────
        sag = QWidget()
        sag.setStyleSheet(f"background:{_PANEL}; border-left:1px solid {_KENAR};")
        sag_lay = QVBoxLayout(sag)
        sag_lay.setContentsMargins(28, 32, 28, 28)
        sag_lay.setSpacing(16)

        baslik1 = QLabel("SİSTEM ÖN KONTROLÜ")
        baslik1.setStyleSheet(
            f"color:{_VURGU2}; font-size:12px; font-weight:700; letter-spacing:0.16em; "
            "background:transparent;"
        )
        sag_lay.addWidget(baslik1)

        for etiket, ok, detay in self._sistem_kontrolleri():
            satir_w = QWidget()
            satir_lay = QHBoxLayout(satir_w)
            satir_lay.setContentsMargins(0, 0, 0, 0)
            satir_lay.setSpacing(8)
            nokta = QLabel("●")
            nokta.setStyleSheet(f"color:{_IYI if ok else _UYARI}; background:transparent; font-size:11px;")
            nokta.setFixedWidth(14)
            satir_lay.addWidget(nokta)
            metin = QLabel(f"{etiket} — {detay}")
            metin.setStyleSheet("color:#9ebbd8; font-size:11px; background:transparent;")
            metin.setWordWrap(True)
            satir_lay.addWidget(metin, 1)
            sag_lay.addWidget(satir_w)

        sag_lay.addSpacing(6)
        ayirici = QWidget()
        ayirici.setFixedHeight(1)
        ayirici.setStyleSheet(f"background:{_KENAR};")
        sag_lay.addWidget(ayirici)
        sag_lay.addSpacing(6)

        baslik2 = QLabel("UÇUŞ ALANI")
        baslik2.setStyleSheet(
            f"color:{_VURGU2}; font-size:12px; font-weight:700; letter-spacing:0.16em; "
            "background:transparent;"
        )
        sag_lay.addWidget(baslik2)

        alan_satirlari, alan_hazir = self._ucus_alani_durumu()
        for s in alan_satirlari:
            l = QLabel(("✓ " if alan_hazir else "— ") + s)
            l.setStyleSheet(
                f"color:{_IYI if alan_hazir else '#7e9cb8'}; font-size:11px; background:transparent;"
            )
            l.setWordWrap(True)
            sag_lay.addWidget(l)

        sag_lay.addStretch()
        satir.addWidget(sag, 1)

    def goster_ve_yukle(self):
        """Splash'ı göster, 300ms sonra yükleme adımlarını başlat."""
        self.show()
        QTimer.singleShot(300, lambda: self._timer.start(280))

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
        p.setPen(QPen(QColor(148, 188, 227, 76), 1))
        p.drawRect(0, 0, self.width() - 1, self.height() - 1)
