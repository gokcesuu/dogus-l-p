"""
Özel PyQt5 widget'ları:
  - YapayUfukWidget  : roll/pitch animasyonu
  - BataryaBar       : renkli doluluk çubuğu
  - SicaklikGostergesi: renk kodlu IMU sıcaklık etiketi
  - RuzgarGostergesi : hız + yön paneli
"""

import math
from PyQt5.QtWidgets import QWidget, QLabel, QVBoxLayout, QHBoxLayout
from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QPolygonF, QLinearGradient
)


class YapayUfukWidget(QWidget):
    """Roll ve pitch değerlerini görsel olarak gösteren yapay ufuk."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(200, 200)
        self._roll = 0.0
        self._pitch = 0.0

    def guncelle(self, roll_deg: float, pitch_deg: float):
        self._roll = roll_deg
        self._pitch = pitch_deg
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        r = min(cx, cy) - 4

        # Dış çember kırpma
        from PyQt5.QtGui import QPainterPath
        path = QPainterPath()
        path.addEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))
        painter.setClipPath(path)

        # Roll dönüşü uygula
        painter.save()
        painter.translate(cx, cy)
        painter.rotate(-self._roll)

        # Pitch kaydırması: her derece h/60 piksel
        pitch_px = self._pitch * (2 * r) / 60.0

        # Gökyüzü (mavi)
        painter.setBrush(QBrush(QColor("#1a6faf")))
        painter.setPen(Qt.NoPen)
        painter.drawRect(int(-r), int(-2 * r + pitch_px), int(2 * r), int(2 * r))

        # Yer (kahverengi)
        painter.setBrush(QBrush(QColor("#7a4a1e")))
        painter.drawRect(int(-r), int(pitch_px), int(2 * r), int(2 * r))

        # Ufuk çizgisi
        painter.setPen(QPen(QColor("white"), 2))
        painter.drawLine(int(-r), int(pitch_px), int(r), int(pitch_px))

        # Pitch ölçek çizgileri
        painter.setPen(QPen(QColor("white"), 1))
        for deg in range(-30, 31, 10):
            if deg == 0:
                continue
            y = pitch_px - deg * (2 * r) / 60.0
            uzunluk = r * 0.3 if deg % 20 == 0 else r * 0.15
            painter.drawLine(int(-uzunluk), int(y), int(uzunluk), int(y))
            painter.setFont(QFont("Arial", 7))
            painter.drawText(int(uzunluk + 2), int(y + 4), str(abs(deg)))

        painter.restore()

        # Kırpmayı kaldır, üst katmanları çiz
        painter.setClipping(False)

        # Dış çember kenarı
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor("#aaaaaa"), 2))
        painter.drawEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))

        # Ortadaki uçak simgesi
        painter.setPen(QPen(QColor("yellow"), 2))
        painter.drawLine(int(cx - 20), int(cy), int(cx - 5), int(cy))
        painter.drawLine(int(cx + 5), int(cy), int(cx + 20), int(cy))
        painter.drawLine(int(cx), int(cy - 5), int(cx), int(cy + 5))

        # Roll göstergesi (üst yay)
        painter.setPen(QPen(QColor("white"), 1))
        for a in range(-60, 61, 30):
            rad = math.radians(a - 90)
            x1 = cx + (r - 2) * math.cos(rad)
            y1 = cy + (r - 2) * math.sin(rad)
            x2 = cx + (r - 10) * math.cos(rad)
            y2 = cy + (r - 10) * math.sin(rad)
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))

        # Roll okı
        painter.setPen(QPen(QColor("yellow"), 2))
        roll_rad = math.radians(-self._roll - 90)
        ox = cx + (r - 14) * math.cos(roll_rad)
        oy = cy + (r - 14) * math.sin(roll_rad)
        painter.drawLine(int(cx), int(cy - r + 4), int(ox), int(oy))

        painter.end()


# ---------------------------------------------------------------------------

class BataryaBar(QWidget):
    """Yüzde doluluk çubuğu; kritik seviyelerde renk değiştir."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(18)
        self._yuzde = -1   # -1 = veri yok (gri gösterim)
        self._volt = 0.0
        self._amper = 0.0

    def guncelle(self, volt: float, amper: float, yuzde: int):
        self._volt = volt
        self._amper = amper
        self._yuzde = max(0, min(100, yuzde)) if yuzde >= 0 else 0
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        y = 3

        # Arka plan
        painter.setBrush(QBrush(QColor("#1e2a3a")))
        painter.setPen(QPen(QColor("#445566"), 1))
        painter.drawRoundedRect(0, y, w, h - y * 2, 4, 4)

        # Veri yok → gri
        if self._yuzde < 0:
            painter.setPen(QPen(QColor("#667788")))
            painter.setFont(QFont("Arial", 8))
            painter.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, "Batarya: veri yok")
            painter.end()
            return

        # Doluluk rengi
        if self._yuzde > 50:
            renk = QColor("#4caf50")
        elif self._yuzde > 30:
            renk = QColor("#ffc107")
        elif self._yuzde > 20:
            renk = QColor("#ff9800")
        else:
            renk = QColor("#f44336")

        dolu_w = int((self._yuzde / 100.0) * (w - 2))
        painter.setBrush(QBrush(renk))
        painter.setPen(Qt.NoPen)
        if dolu_w > 0:
            painter.drawRoundedRect(1, y + 1, dolu_w, h - y * 2 - 2, 3, 3)

        # Metin
        painter.setPen(QPen(QColor("white")))
        painter.setFont(QFont("Arial", 8, QFont.Bold))
        metin = f"%{self._yuzde}  {self._volt:.1f}V  {self._amper:.1f}A"
        painter.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, metin)
        painter.end()


# ---------------------------------------------------------------------------

class SicaklikGostergesi(QLabel):
    """IMU sıcaklık etiketi; renk kodlamalı."""

    SOGUK_RENK = "#64b5f6"    # mavi  – 30°C altı
    NORMAL_RENK = "#81c784"   # yeşil – 30-40°C
    SICAK_RENK = "#ffb74d"    # turuncu – 40-50°C
    TEHLIKE_RENK = "#e53935"  # kırmızı – 50°C üstü

    def __init__(self, imu_no: int, parent=None):
        super().__init__(parent)
        self._imu_no = imu_no
        self.setAlignment(Qt.AlignCenter)
        self.setFont(QFont("Courier", 10))
        self.setMinimumWidth(110)
        self.guncelle(None)

    def guncelle(self, sicaklik):
        if sicaklik is None:
            self.setText(f"IMU {self._imu_no + 1}: --°C")
            self.setStyleSheet("color: #888888; border: 1px solid #444; border-radius: 4px; padding: 2px;")
            return

        if sicaklik < 30:
            renk = self.SOGUK_RENK
            durum = "❄"
        elif sicaklik < 40:
            renk = self.NORMAL_RENK
            durum = "✓"
        elif sicaklik < 50:
            renk = self.SICAK_RENK
            durum = "!"
        else:
            renk = self.TEHLIKE_RENK
            durum = "⚠"

        self.setText(f"IMU {self._imu_no + 1}: {sicaklik:.1f}°C {durum}")
        self.setStyleSheet(
            f"color: {renk}; border: 1px solid {renk}; border-radius: 4px; padding: 2px;"
        )


# ---------------------------------------------------------------------------

class RuzgarGostergesi(QWidget):
    """Rüzgar hızı (renkli) ve yön paneli."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(160, 80)
        self._hiz = 0.0
        self._yon = 0.0

    def guncelle(self, hiz_ms: float, yon_derece: float):
        self._hiz = hiz_ms
        self._yon = yon_derece
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()

        # Renk skalası: m/s cinsinden hız
        hiz_kmh = self._hiz * 3.6
        if hiz_kmh < 20:
            renk = QColor("#4caf50")
            seviye = "Normal"
        elif hiz_kmh < 40:
            renk = QColor("#ffc107")
            seviye = "Dikkat"
        elif hiz_kmh < 60:
            renk = QColor("#ff9800")
            seviye = "Tehlikeli"
        else:
            renk = QColor("#f44336")
            seviye = "KRİTİK"

        # Arka plan
        painter.fillRect(0, 0, w, h, QColor("#0d1b2a"))

        # Ok çizimi (ön planda)
        cx, cy = w * 0.75, h / 2
        r = min(cx - 10, h / 2 - 8)

        rad = math.radians(self._yon - 90)
        uc_x = cx + r * math.cos(rad)
        uc_y = cy + r * math.sin(rad)
        kuyruk_x = cx - r * 0.6 * math.cos(rad)
        kuyruk_y = cy - r * 0.6 * math.sin(rad)

        painter.setPen(QPen(renk, 3))
        painter.drawLine(int(kuyruk_x), int(kuyruk_y), int(uc_x), int(uc_y))

        # Ok ucu
        yon_rad = math.atan2(uc_y - kuyruk_y, uc_x - kuyruk_x)
        for a in [0.4, -0.4]:
            px = uc_x - 10 * math.cos(yon_rad + a)
            py = uc_y - 10 * math.sin(yon_rad + a)
            painter.drawLine(int(uc_x), int(uc_y), int(px), int(py))

        # Metin
        painter.setPen(QPen(renk))
        painter.setFont(QFont("Arial", 10, QFont.Bold))
        painter.drawText(QRectF(2, 2, w * 0.65, h / 2), Qt.AlignLeft,
                         f"{self._hiz:.1f} m/s")
        painter.setFont(QFont("Arial", 8))
        painter.drawText(QRectF(2, h / 2, w * 0.65, h / 2), Qt.AlignLeft,
                         f"{hiz_kmh:.0f} km/h – {seviye}")

        painter.end()
