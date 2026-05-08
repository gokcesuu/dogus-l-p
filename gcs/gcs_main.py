"""
Doğuş Üniversitesi LÖP – Türkçe Yer İstasyonu (GCS)
Çalıştırmak için: python gcs_main.py
SITL bağlantısı: tcp:127.0.0.1:5762
"""

import os
import sys
import time

# QWebEngineView Windows GPU crash fix — pencere taşınırken/küçültülürken çöküyor
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing")
import json
from collections import deque
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton,
    QLineEdit, QTextEdit, QGridLayout, QHBoxLayout, QVBoxLayout,
    QGroupBox, QStatusBar, QTabWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QProgressBar, QMessageBox, QAbstractItemView,
)
from PyQt5.QtCore import Qt, QDateTime, QTimer, QThread, pyqtSignal as Signal
from PyQt5.QtGui import QFont, QColor

try:
    from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEnginePage
    from PyQt5.QtCore import QUrl
    HARITA_MEVCUT = True
except ImportError:
    HARITA_MEVCUT = False

from pymavlink import mavutil
from mavlink_handler import MAVLinkBaglantisi, UÇUŞ_MODLARI
from ui_widgets import YapayUfukWidget, BataryaBar, SicaklikGostergesi, RuzgarGostergesi

try:
    from terrain_analiz import GuvenliInisAnalizci
    TERRAIN_MEVCUT = True
except ImportError:
    TERRAIN_MEVCUT = False

from gcs_logger import GCSLogger
import config_yukleyici as _cfg


# ── RTL İzleyici ─────────────────────────────────────────────────────────────

class RtlIzleyici:
    """
    RTL başladıktan sonra 'eve uzaklık' trendini izler.
    İlerleme yoksa veya kritik koşul tespit edilirse tetiklendi_cb çağrılır.
    """

    STABIL_SURE_S    = float(_cfg.al("rtl_izleyici.stabil_sure_s",    15))
    KONTROL_ARALIK_S = float(_cfg.al("rtl_izleyici.kontrol_aralik_s", 25))
    MIN_AZALMA_M     = float(_cfg.al("rtl_izleyici.min_azalma_m",     20))
    BAT_KRITIK_YZD   = int(_cfg.al("rtl_izleyici.batarya_kritik_yuzde", 15))
    GECMIS_BOYUT     = 6

    def __init__(self, tetiklendi_cb):
        self._cb          = tetiklendi_cb
        self._aktif       = False
        self._baslama_t   = 0.0
        self._son_kontrol = 0.0
        self._gecmis: deque = deque(maxlen=self.GECMIS_BOYUT)
        self._tetiklendi  = False

    def baslat(self, baslama_uzakligi: float):
        self._aktif       = True
        self._tetiklendi  = False
        self._baslama_t   = time.monotonic()
        self._son_kontrol = self._baslama_t
        self._gecmis.clear()
        self._gecmis.append(baslama_uzakligi)

    def guncelle(self, uzaklik: float, batarya_yuzde: int,
                 ruzgar_ms: float, ekf_hata: float, gps_fix: int):
        if not self._aktif or self._tetiklendi:
            return
        simdi = time.monotonic()

        # Başlangıç mesafesi henüz gelmemişse deque'yi güncelle ama takılı say
        if uzaklik > 0:
            self._gecmis.append(uzaklik)

        if simdi - self._baslama_t < self.STABIL_SURE_S:
            return
        if simdi - self._son_kontrol < self.KONTROL_ARALIK_S:
            return
        self._son_kontrol = simdi

        neden = None

        if len(self._gecmis) >= 3:
            en_eski = self._gecmis[0]
            en_yeni = self._gecmis[-1]
            # Sadece sıfır olmayan başlangıç mesafesiyle karşılaştır
            if en_eski > 0 and en_yeni > en_eski - self.MIN_AZALMA_M:
                neden = (f"RTL takılı: {en_eski:.0f}m → {en_yeni:.0f}m "
                         f"(beklenen azalma yok)")

        # Batarya telemetrisi henüz gelmediyse (-1 veya 0) bu kontrolü atla
        if 0 < batarya_yuzde <= self.BAT_KRITIK_YZD:
            menzil_m = (batarya_yuzde / 100.0) * 44.4 / 10.0 * 1000 * 0.6
            if uzaklik > menzil_m:
                neden = (f"Batarya %{batarya_yuzde} ama mesafe {uzaklik:.0f}m "
                         f"> menzil {menzil_m:.0f}m")

        if gps_fix < 3:
            neden = f"GPS fix kaybı (fix={gps_fix})"

        if ekf_hata > 0.8:
            neden = f"EKF hata yüksek ({ekf_hata:.2f})"

        if neden:
            self._tetiklendi = True
            self._aktif      = False
            self._cb(neden)

    def durdur(self):
        self._aktif = False


# ── Stiller ──────────────────────────────────────────────────────────────────

KOYU_TEMA = """
QMainWindow, QWidget { background-color: #0d1b2a; color: #c8d8e8; }
QTabWidget::pane { border: 1px solid #2a4060; }
QTabBar::tab {
    background: #0a1520; color: #7eb8e0; padding: 8px 20px;
    border: 1px solid #2a4060; border-bottom: none;
}
QTabBar::tab:selected { background: #1a3050; color: #ffffff; }
QGroupBox {
    border: 1px solid #2a4060; border-radius: 6px;
    margin-top: 8px; font-weight: bold; color: #7eb8e0;
}
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
QPushButton {
    background-color: #1a3050; color: #c8d8e8;
    border: 1px solid #2a4060; border-radius: 4px;
    padding: 6px 12px; font-size: 11px;
}
QPushButton:hover { background-color: #2a4a70; }
QPushButton:pressed { background-color: #0a2040; }
QPushButton:disabled { background-color: #0a1520; color: #445566; }
QLineEdit, QTextEdit {
    background-color: #0a1520; color: #c8d8e8;
    border: 1px solid #2a4060; border-radius: 4px; padding: 4px;
}
QTableWidget {
    background-color: #0a1520; color: #c8d8e8;
    border: 1px solid #2a4060; gridline-color: #1a3050;
}
QTableWidget::item:selected { background-color: #1a4060; }
QHeaderView::section {
    background-color: #0d2040; color: #7eb8e0;
    border: 1px solid #2a4060; padding: 4px; font-weight: bold;
}
QProgressBar {
    background-color: #0a1520; border: 1px solid #2a4060;
    border-radius: 4px; text-align: center; color: #c8d8e8;
}
QProgressBar::chunk { background-color: #1a6faf; border-radius: 3px; }
QLabel { color: #c8d8e8; }
QStatusBar { background-color: #0a1520; color: #7eb8e0; }
"""

ACİL_STILI = """
QPushButton {
    background-color: #7b1414; color: #ffffff;
    border: 1px solid #b22222; border-radius: 4px;
    padding: 8px 16px; font-weight: bold; font-size: 12px;
}
QPushButton:hover { background-color: #b22222; }
"""

BAĞLAN_STILI = """
QPushButton {
    background-color: #1a5c2a; color: #ffffff;
    border: 1px solid #2e8b57; border-radius: 4px;
    padding: 6px 16px; font-weight: bold;
}
QPushButton:hover { background-color: #2e8b57; }
"""

UYARI_STILI = "background-color: #7b1414; color: white; font-weight: bold; padding: 4px;"

# ── Harita HTML (Leaflet.js) ──────────────────────────────────────────────────

HARITA_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { width: 100%; height: 100%; overflow: hidden; background: #0d1b2a; }
  #map { position: absolute; top: 0; left: 0; right: 0; bottom: 0; }
  #toolbar {
    position: absolute; top: 0; left: 0; right: 0; z-index: 1000;
    background: rgba(13,27,42,0.88);
    display: flex; align-items: center; gap: 6px;
    padding: 5px 8px; border-bottom: 1px solid #2a4060;
  }
  #toolbar button {
    background: #1a3050; color: #c8d8e8; border: 1px solid #2a4060;
    border-radius: 4px; padding: 5px 13px; cursor: pointer; font-size: 14px;
  }
  #toolbar button:hover { background: #2a4060; }
  #toolbar button.green { background: #1a5c2a; border-color: #2a8c3a; }
  #toolbar button.green:hover { background: #2a6c3a; }
  #toolbar button.red { background: #7b1414; border-color: #b02020; }
  #toolbar button.red:hover { background: #9b1a1a; }
  #toolbar button:disabled { opacity: 0.4; cursor: default; }
  #konum { margin-left: auto; color: #7eb8e0; font-size: 14px; white-space: nowrap; }
  #durum {
    position: absolute; bottom: 8px; left: 50%; transform: translateX(-50%);
    z-index: 1000; background: rgba(13,27,42,0.88);
    color: #7eb8e0; font-size: 15px; padding: 7px 18px;
    border-radius: 4px; border: 1px solid #2a4060;
    display: none; white-space: nowrap;
  }
</style>
</head>
<body>
<div id="map"></div>
<div id="toolbar">
  <button onclick="window.location.href='gcs://ucus-yolu-temizle'">Uçuş Yolunu Temizle</button>
  <button class="green" id="analizBtn" onclick="window.location.href='gcs://guvenli-inis-baslat'">Güvenli İniş Analizi</button>
  <button onclick="window.location.href='gcs://analiz-temizle'">Analizi Temizle</button>
  <button class="red" id="inisBtn" disabled onclick="window.location.href='gcs://guvenli-inise-git'">🚨 Güvenli İnişe Git</button>
  <span id="konum">Konum: --</span>
</div>
<div id="durum"></div>
<script>
var map = L.map('map', {zoomControl: true}).setView([-35.363, 149.165], 15);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: 'OSM', maxZoom: 19
}).addTo(map);

var droneIcon = L.divIcon({
  html: '<div style="width:14px;height:14px;background:#f44336;border:2px solid white;border-radius:50%;"></div>',
  iconSize: [14,14], iconAnchor: [7,7]
});
var evIcon = L.divIcon({
  html: '<div style="width:12px;height:12px;background:#4caf50;border:2px solid white;transform:rotate(45deg);"></div>',
  iconSize: [12,12], iconAnchor: [6,6]
});

var droneMark = L.marker([-35.363, 149.165], {icon: droneIcon}).addTo(map);
var evMark    = L.marker([-35.363, 149.165], {icon: evIcon}).addTo(map);
var ucusYolu  = L.polyline([], {color: '#64b5f6', weight: 2, opacity: 0.7}).addTo(map);
var ucusKoord = [];
var ilkKonum  = true;

function droneyiGuncelle(lat, lon, irtifa) {
  var pos = [lat, lon];
  droneMark.setLatLng(pos);
  droneMark.bindTooltip('Drone<br>İrtifa: ' + irtifa.toFixed(1) + ' m', {permanent: false});
  ucusKoord.push(pos);
  if (ucusKoord.length > 500) ucusKoord.shift();
  ucusYolu.setLatLngs(ucusKoord);
  if (ilkKonum) { map.setView(pos, 15); ilkKonum = false; }
}

function konumuGuncelle(metin) {
  document.getElementById('konum').textContent = metin;
}

function evNoktasiGuncelle(lat, lon) {
  evMark.setLatLng([lat, lon]);
  evMark.bindTooltip('Ev Noktası', {permanent: false});
}

function ucusYolunuTemizle() {
  ucusKoord = [];
  ucusYolu.setLatLngs([]);
}

function durumGoster(metin) {
  var d = document.getElementById('durum');
  d.textContent = metin;
  d.style.display = metin ? 'block' : 'none';
}

var guvenliKatman  = L.layerGroup().addTo(map);
var yaricapDairesi = null;

function guvenliNoktalariGoster(noktalarJson, yaricap_m, merkez_lat, merkez_lon) {
  guvenliKatman.clearLayers();
  if (yaricapDairesi) { map.removeLayer(yaricapDairesi); }
  yaricapDairesi = L.circle([merkez_lat, merkez_lon], {
    radius: yaricap_m, color: '#64b5f6',
    fillColor: '#64b5f6', fillOpacity: 0.04,
    weight: 1, dashArray: '6,4'
  }).bindTooltip('Uçuş yarıçapı: ' + yaricap_m.toFixed(0) + ' m').addTo(map);
  var noktalar = JSON.parse(noktalarJson);
  noktalar.forEach(function(n) {
    var renk  = n.guvenlik === 'GUVENLI' ? '#4caf50' : '#ffc107';
    var yarim = n.guvenlik === 'GUVENLI' ? 55 : 35;
    L.circle([n.lat, n.lon], {
      radius: yarim, color: renk,
      fillColor: renk, fillOpacity: 0.55, weight: 1
    }).bindTooltip(
      '<b>' + n.guvenlik + '</b><br>Eğim: ' + n.egim.toFixed(1) + '°<br>' +
      'Yükseklik: ' + n.yukseklik.toFixed(0) + ' m<br>' +
      'Mesafe: ' + n.mesafe.toFixed(0) + ' m',
      {sticky: true}
    ).addTo(guvenliKatman);
  });
  map.setView([merkez_lat, merkez_lon], 14);
}

function guvenliNoktalariTemizle() {
  guvenliKatman.clearLayers();
  if (yaricapDairesi) { map.removeLayer(yaricapDairesi); yaricapDairesi = null; }
  document.getElementById('inisBtn').disabled = true;
}

var _enYakinLat = null, _enYakinLon = null;

function enYakinNoktayiKaydet(lat, lon) {
  _enYakinLat = lat; _enYakinLon = lon;
  document.getElementById('inisBtn').disabled = false;
}
</script>
</body>
</html>"""


# ── Harita sayfa sınıfı (gcs:// URL'lerini yakalar) ──────────────────────────

if HARITA_MEVCUT:
    class HaritaSayfa(QWebEnginePage):
        def __init__(self, gcs_pencere, parent=None):
            super().__init__(parent)
            self._gcs = gcs_pencere

        def acceptNavigationRequest(self, url, nav_type, is_main_frame):
            if url.scheme() == 'gcs':
                eylem = url.host()
                if eylem == 'ucus-yolu-temizle':
                    self._gcs._harita_yol_temizle()
                elif eylem == 'guvenli-inis-baslat':
                    self._gcs._guvenli_inis_baslat()
                elif eylem == 'analiz-temizle':
                    self._gcs._guvenli_noktalar_temizle()
                elif eylem == 'guvenli-inise-git':
                    self._gcs._guvenli_inise_git()
                return False  # gezinme yapma
            return super().acceptNavigationRequest(url, nav_type, is_main_frame)


# ── Arkaplan analiz thread'i ──────────────────────────────────────────────────

class TerrainAnalizThread(QThread):
    tamamlandi = Signal(object)   # AnalizSonucu
    hata       = Signal(str)

    def __init__(self, lat, lon, batarya_yuzde,
                 ruzgar_ms: float = 0.0, ruzgar_yonu_derece: float = 0.0):
        super().__init__()
        self.lat = lat
        self.lon = lon
        self.batarya_yuzde = batarya_yuzde
        self.ruzgar_ms = ruzgar_ms
        self.ruzgar_yonu_derece = ruzgar_yonu_derece

    def run(self):
        try:
            analizci = GuvenliInisAnalizci()
            sonuc = analizci.analiz_et(
                self.lat, self.lon, self.batarya_yuzde,
                ruzgar_ms=self.ruzgar_ms,
                ruzgar_yonu_derece=self.ruzgar_yonu_derece,
            )
            self.tamamlandi.emit(sonuc)
        except Exception as e:
            self.hata.emit(str(e))


# ── Ana Pencere ───────────────────────────────────────────────────────────────

class AnaPencere(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Doğuş ÜNİ – Türkçe Yer İstasyonu v0.2")
        self.resize(1366, 800)
        self.setMinimumSize(900, 600)
        self.setStyleSheet(KOYU_TEMA)

        self._mavlink = MAVLinkBaglantisi()
        self._sinyalleri_bagla()
        self._ui_olustur()

        # Heartbeat izleme timer'ı (2 sn'de bir)
        self._hb_timer = QTimer()
        self._hb_timer.setInterval(2000)
        self._hb_timer.timeout.connect(self._heartbeat_kontrol)

        self._guncel_irtifa = 0.0
        self._guncel_lat = 0.0
        self._guncel_lon = 0.0
        self._ev_lat = 0.0
        self._logger = GCSLogger()
        self._log_satiri: dict = {}  # her saniye doldurulup CSV'ye yazılır
        self._log_timer = QTimer()
        self._log_timer.setInterval(1000)
        self._log_timer.timeout.connect(self._log_yaz)
        self._ev_lon = 0.0
        self._bagli = False

        # Telemetri anlık değerleri (handler'larda saklanır)
        self._guncel_eve_uzaklik = 0.0
        self._guncel_ekf_hata    = 0.0
        self._guncel_gps_fix     = 0

        # RTL izleyici
        self._rtl_izleyici = RtlIzleyici(tetiklendi_cb=self._rtl_fallback_tetiklendi)
        self._son_mod_id   = -1
        self._ruzgar_acil_inis_bekliyor = False

        self._durum_guncelle("Bağlantı bekleniyor…", "#ffc107")

    # ── Sinyaller ────────────────────────────────────────────────────────────

    def _sinyalleri_bagla(self):
        m = self._mavlink
        m.baglandi.connect(self._baglanti_oldu)
        m.baglanti_kesildi.connect(self._baglanti_kesildi)
        m.hata.connect(self._hata)
        m.kalp_atisi.connect(self._hb_guncelle)
        m.batarya_guncellendi.connect(self._batarya_guncelle)
        m.vfr_guncellendi.connect(self._vfr_guncelle)
        m.gps_guncellendi.connect(self._gps_guncelle)
        m.tutum_guncellendi.connect(self._tutum_guncelle)
        m.ruzgar_guncellendi.connect(self._ruzgar_guncelle)
        m.imu_sicakligi.connect(self._imu_guncelle)
        m.durum_mesaji.connect(self._mesaj_ekle)
        m.ekf_durumu.connect(self._ekf_guncelle)
        m.parametre_guncellendi.connect(self._param_guncelle)
        m.parametre_tamamlandi.connect(self._param_tamam)

    # ── UI ───────────────────────────────────────────────────────────────────

    def _ui_olustur(self):
        merkez = QWidget()
        self.setCentralWidget(merkez)
        ana = QVBoxLayout(merkez)
        ana.setSpacing(4)
        ana.setContentsMargins(6, 6, 6, 6)

        ana.addLayout(self._baglanti_cubugu())

        # Bağlantı kopma uyarı bandı
        self._uyari_bant = QLabel("⚠  BAĞLANTI KESİLDİ")
        self._uyari_bant.setAlignment(Qt.AlignCenter)
        self._uyari_bant.setStyleSheet(UYARI_STILI)
        self._uyari_bant.setFont(QFont("Arial", 11, QFont.Bold))
        self._uyari_bant.hide()
        ana.addWidget(self._uyari_bant)

        # Sekmeler
        self._sekmeler = QTabWidget()
        self._sekmeler.addTab(self._ana_sekme(), "✈  Uçuş")
        self._sekmeler.addTab(self._parametre_sekme(), "⚙  Parametreler")
        if HARITA_MEVCUT:
            self._sekmeler.addTab(self._harita_sekme(), "🗺  Harita")
        else:
            eksik = QLabel("Harita için: pip install PyQtWebEngine")
            eksik.setAlignment(Qt.AlignCenter)
            self._sekmeler.addTab(eksik, "🗺  Harita")
        self._sekmeler.currentChanged.connect(self._sekme_degisti)
        ana.addWidget(self._sekmeler)

        self._durum_bar = QStatusBar()
        self.setStatusBar(self._durum_bar)

    # ── Bağlantı çubuğu ──────────────────────────────────────────────────────

    def _baglanti_cubugu(self) -> QHBoxLayout:
        duz = QHBoxLayout()
        duz.addWidget(QLabel("Bağlantı:"))

        self._baglanti_giris = QLineEdit(_cfg.al("baglanti.varsayilan_dize", "tcp:127.0.0.1:5762"))
        self._baglanti_giris.setFixedWidth(200)
        duz.addWidget(self._baglanti_giris)

        self._baglan_btn = QPushButton("Bağlan")
        self._baglan_btn.setStyleSheet(BAĞLAN_STILI)
        self._baglan_btn.clicked.connect(self._baglan_tikla)
        duz.addWidget(self._baglan_btn)

        self._kes_btn = QPushButton("Kes")
        self._kes_btn.clicked.connect(self._kes_tikla)
        self._kes_btn.setEnabled(False)
        duz.addWidget(self._kes_btn)

        duz.addStretch()

        self._mod_lbl = QLabel("MOD: --")
        self._mod_lbl.setFont(QFont("Arial", 11, QFont.Bold))
        duz.addWidget(self._mod_lbl)

        self._arm_lbl = QLabel("DISARM")
        self._arm_lbl.setFont(QFont("Arial", 11, QFont.Bold))
        self._arm_lbl.setStyleSheet("color: #888888;")
        duz.addWidget(self._arm_lbl)

        self._ekf_lbl = QLabel("EKF: --")
        self._ekf_lbl.setStyleSheet("color: #888888;")
        duz.addWidget(self._ekf_lbl)

        return duz

    # ── Uçuş sekmesi ─────────────────────────────────────────────────────────

    def _ana_sekme(self) -> QWidget:
        w = QWidget()
        ana = QVBoxLayout(w)
        ana.setSpacing(4)

        ust = QHBoxLayout()
        ust.setSpacing(6)

        # Sol
        sol = QVBoxLayout()
        sol.addWidget(self._yapay_ufuk_paneli())
        sol.addWidget(self._imu_paneli())
        ust.addLayout(sol, 2)

        # Orta
        ust.addLayout(self._merkez_panel(), 3)

        # Sağ
        ust.addLayout(self._sag_panel(), 2)

        ana.addLayout(ust, 4)
        ana.addWidget(self._mesaj_logu_paneli(), 1)
        return w

    def _yapay_ufuk_paneli(self) -> QGroupBox:
        grp = QGroupBox("Yapay Ufuk")
        duz = QVBoxLayout(grp)
        self._yapay_ufuk = YapayUfukWidget()
        duz.addWidget(self._yapay_ufuk)
        sat = QHBoxLayout()
        self._roll_lbl  = QLabel("Roll: 0.0°")
        self._pitch_lbl = QLabel("Pitch: 0.0°")
        self._yaw_lbl   = QLabel("Yaw: 0.0°")
        for lb in (self._roll_lbl, self._pitch_lbl, self._yaw_lbl):
            lb.setAlignment(Qt.AlignCenter)
            sat.addWidget(lb)
        duz.addLayout(sat)
        return grp

    def _imu_paneli(self) -> QGroupBox:
        grp = QGroupBox("IMU Sıcaklıkları")
        duz = QVBoxLayout(grp)
        self._imu_gosterge = []
        for i in range(3):
            g = SicaklikGostergesi(i)
            self._imu_gosterge.append(g)
            duz.addWidget(g)
        return grp

    def _merkez_panel(self) -> QVBoxLayout:
        duz = QVBoxLayout()

        # Batarya
        bat = QGroupBox("Batarya")
        bd  = QVBoxLayout(bat)
        self._batarya_bar    = BataryaBar()
        self._batarya_detay  = QLabel("--V  --A  Tahmini süre: --")
        self._batarya_detay.setAlignment(Qt.AlignCenter)
        bd.addWidget(self._batarya_bar)
        bd.addWidget(self._batarya_detay)
        duz.addWidget(bat)

        # Uçuş parametreleri
        prm = QGroupBox("Uçuş Parametreleri")
        izgara = QGridLayout(prm)
        self._irtifa_lbl  = self._veri_etiketi("İrtifa",     "0.0 m",   izgara, 0)
        self._hiz_lbl     = self._veri_etiketi("Hız",        "0.0 m/s", izgara, 1)
        self._dikey_lbl   = self._veri_etiketi("Dikey Hız",  "0.0 m/s", izgara, 2)
        self._uzaklik_lbl = self._veri_etiketi("Eve Uzaklık","0 m",     izgara, 3)
        duz.addWidget(prm)

        # GPS
        gps = QGroupBox("GPS Durumu")
        gd  = QHBoxLayout(gps)
        self._gps_fix_lbl   = QLabel("Fix: --")
        self._gps_uydu_lbl  = QLabel("Uydu: --")
        self._gps_konum_lbl = QLabel("Konum: --")
        for lb in (self._gps_fix_lbl, self._gps_uydu_lbl, self._gps_konum_lbl):
            gd.addWidget(lb)
        duz.addWidget(gps)

        # Rüzgar
        ruz = QGroupBox("Rüzgar")
        rd  = QVBoxLayout(ruz)
        self._ruzgar = RuzgarGostergesi()
        rd.addWidget(self._ruzgar)
        duz.addWidget(ruz)

        return duz

    def _sag_panel(self) -> QVBoxLayout:
        duz = QVBoxLayout()

        acil = QGroupBox("Acil Komutlar")
        ag   = QGridLayout(acil)
        btns = [
            ("EV'E DÖN (RTL)", self._rtl_tikla,      True,  0, 0),
            ("HOVERING",        self._hovering_tikla, False, 0, 1),
            ("ACİL İNİŞ",       self._inis_tikla,     True,  1, 0),
            ("DEVAM ET",        self._devam_tikla,    False, 1, 1),
        ]
        for ad, slot, kirmizi, r, c in btns:
            b = QPushButton(ad)
            if kirmizi:
                b.setStyleSheet(ACİL_STILI)
            b.clicked.connect(slot)
            ag.addWidget(b, r, c)
        duz.addWidget(acil)

        mod_grp = QGroupBox("Mod Değiştir")
        md      = QVBoxLayout(mod_grp)
        for satir_modlar in [
            [("SABİTLEME", 0), ("LOITER", 5)],
            [("OTOMATİK",  3), ("KILAVUZ", 4)],
        ]:
            sat = QHBoxLayout()
            for ad, mid in satir_modlar:
                b = QPushButton(ad)
                b.clicked.connect(lambda _, m=mid: self._mod_tikla(m))
                sat.addWidget(b)
            md.addLayout(sat)
        duz.addWidget(mod_grp)

        ev_grp = QGroupBox("Ev Noktası")
        ed     = QVBoxLayout(ev_grp)
        b = QPushButton("Mevcut Konumu Ev Yap")
        b.clicked.connect(self._ev_yap_tikla)
        ed.addWidget(b)
        duz.addWidget(ev_grp)

        duz.addStretch()
        return duz

    def _mesaj_logu_paneli(self) -> QGroupBox:
        grp = QGroupBox("Sistem Mesajları")
        duz = QVBoxLayout(grp)
        self._mesaj_logu = QTextEdit()
        self._mesaj_logu.setReadOnly(True)
        self._mesaj_logu.setMaximumHeight(110)
        self._mesaj_logu.setFont(QFont("Courier New", 9))
        duz.addWidget(self._mesaj_logu)
        return grp

    # ── Parametre sekmesi ─────────────────────────────────────────────────────

    def _parametre_sekme(self) -> QWidget:
        w   = QWidget()
        duz = QVBoxLayout(w)
        duz.setSpacing(6)

        # Araç çubuğu
        araci = QHBoxLayout()

        self._param_indir_btn = QPushButton("Parametreleri İndir")
        self._param_indir_btn.setStyleSheet(BAĞLAN_STILI)
        self._param_indir_btn.clicked.connect(self._param_indir_tikla)
        araci.addWidget(self._param_indir_btn)

        self._param_uygula_btn = QPushButton("Değişiklikleri Uygula")
        self._param_uygula_btn.clicked.connect(self._param_uygula_tikla)
        araci.addWidget(self._param_uygula_btn)

        araci.addStretch()

        araci.addWidget(QLabel("Ara:"))
        self._param_ara = QLineEdit()
        self._param_ara.setPlaceholderText("Parametre adı veya açıklaması…")
        self._param_ara.setFixedWidth(250)
        self._param_ara.textChanged.connect(self._param_filtrele)
        araci.addWidget(self._param_ara)

        duz.addLayout(araci)

        # İlerleme çubuğu
        self._param_progress = QProgressBar()
        self._param_progress.setMaximumHeight(16)
        self._param_progress.setTextVisible(True)
        self._param_progress.setValue(0)
        self._param_progress.hide()
        duz.addWidget(self._param_progress)

        # Tablo
        self._param_tablo = QTableWidget(0, 3)
        self._param_tablo.setHorizontalHeaderLabels(["Parametre Adı", "Değer", "Yeni Değer"])
        self._param_tablo.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._param_tablo.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._param_tablo.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._param_tablo.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._param_tablo.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._param_tablo.doubleClicked.connect(self._param_satir_duzenle)
        self._param_tablo.setSortingEnabled(True)
        duz.addWidget(self._param_tablo)

        # Bilgi etiketi
        self._param_bilgi = QLabel("Parametreleri indirmek için bağlan ve 'Parametreleri İndir' butonuna bas.")
        self._param_bilgi.setAlignment(Qt.AlignCenter)
        self._param_bilgi.setStyleSheet("color: #7eb8e0;")
        duz.addWidget(self._param_bilgi)

        self._degistirilen_parametreler: dict[str, float] = {}
        return w

    # ── Harita sekmesi ────────────────────────────────────────────────────────

    def _harita_sekme(self) -> QWidget:
        w = QWidget()
        duz = QVBoxLayout(w)
        duz.setContentsMargins(0, 0, 0, 0)
        duz.setSpacing(0)

        self._harita = QWebEngineView()
        self._harita.setMinimumSize(400, 300)
        sayfa = HaritaSayfa(self, self._harita)
        self._harita.setPage(sayfa)
        self._harita.setHtml(HARITA_HTML)
        duz.addWidget(self._harita)

        self._terrain_thread = None
        return w

    # ── Yardımcılar ──────────────────────────────────────────────────────────

    def _sekme_degisti(self, index: int):
        if HARITA_MEVCUT and hasattr(self, '_harita') and index == 2:
            QTimer.singleShot(50,  self._harita_boyut_duzelt)
            QTimer.singleShot(300, self._harita_boyut_duzelt)

    def _harita_boyut_duzelt(self):
        if not hasattr(self, '_harita'):
            return
        h = self._harita.height()
        w = self._harita.width()
        js = (
            f"var m=document.getElementById('map');"
            f"m.style.width='{w}px'; m.style.height='{h}px';"
            "map.invalidateSize(true); map.setView(map.getCenter(), map.getZoom());"
        )
        self._harita.page().runJavaScript(js)

    @staticmethod
    def _veri_etiketi(ad: str, deger: str, g: QGridLayout, satir: int) -> QLabel:
        g.addWidget(QLabel(ad + ":"), satir, 0)
        lbl = QLabel(deger)
        lbl.setFont(QFont("Courier New", 11, QFont.Bold))
        lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        g.addWidget(lbl, satir, 1)
        return lbl

    # ── Sinyal alıcıları ─────────────────────────────────────────────────────

    def _baglanti_oldu(self):
        self._bagli = True
        self._uyari_bant.hide()
        self._durum_guncelle("Bağlantı kuruldu", "#4caf50")
        self._baglan_btn.setEnabled(False)
        self._kes_btn.setEnabled(True)
        self._mesaj_ekle(6, "Bağlantı kuruldu.")
        self._hb_timer.start()
        self._logger.baslat()
        self._log_timer.start()
        self._mesaj_ekle(6, f"Log: {self._logger.csv_yolu()}")

    def _baglanti_kesildi(self):
        self._bagli = False
        self._durum_guncelle("Bağlantı kesildi – yeniden deneniyor…", "#f44336")
        self._baglan_btn.setEnabled(True)
        self._kes_btn.setEnabled(False)
        self._mesaj_ekle(4, "Bağlantı kesildi.")
        self._uyari_bant.show()
        QApplication.beep()
        self._log_timer.stop()
        self._logger.durdur()

    def _hata(self, mesaj: str):
        self._mesaj_ekle(3, mesaj)

    def _heartbeat_kontrol(self):
        if not self._bagli:
            return
        gecen = time.time() - self._mavlink.son_heartbeat_zamani
        if gecen > 5:
            self._uyari_bant.show()
            QApplication.beep()
        else:
            self._uyari_bant.hide()

    def _hb_guncelle(self, mod_id: int, arm: bool):
        self._mod_lbl.setText(f"MOD: {UÇUŞ_MODLARI.get(mod_id, f'MOD-{mod_id}')}")
        if arm:
            self._arm_lbl.setText("ARMED")
            self._arm_lbl.setStyleSheet("color: #f44336; font-weight: bold;")
        else:
            self._arm_lbl.setText("DISARM")
            self._arm_lbl.setStyleSheet("color: #888888;")
        # RTL modu yeni başladıysa izleyiciyi başlat
        if mod_id == 6 and self._son_mod_id != 6:
            self._rtl_izleyici.baslat(self._guncel_eve_uzaklik)
            self._mesaj_ekle(4, "RTL başlatıldı — ilerleme izleniyor.")
        elif mod_id != 6:
            self._rtl_izleyici.durdur()
        self._son_mod_id = mod_id

    def _batarya_guncelle(self, volt: float, amper: float, yuzde: int):
        self._guncel_batarya_yuzde = yuzde
        self._batarya_bar.guncelle(volt, amper, yuzde)
        if volt > 0 and amper > 0.5:
            sure_dk = (volt * yuzde / 100.0) / amper * 60
            self._batarya_detay.setText(
                f"{volt:.2f}V  {amper:.2f}A  Tahmini süre: {sure_dk:.0f} dk"
            )
        else:
            self._batarya_detay.setText(f"{volt:.2f}V  {amper:.2f}A  Tahmini süre: --")
        self._log_satiri.update({"bat_volt": volt, "bat_amper": amper, "bat_yuzde": yuzde})

    def _vfr_guncelle(self, irtifa: float, hiz: float, dikey: float, uzaklik: float):
        self._guncel_irtifa      = irtifa
        self._guncel_eve_uzaklik = uzaklik
        self._irtifa_lbl.setText(f"{irtifa:.1f} m")
        self._hiz_lbl.setText(f"{hiz:.1f} m/s")
        self._dikey_lbl.setText(f"{dikey:+.1f} m/s")
        self._uzaklik_lbl.setText(f"{uzaklik:.0f} m")
        self._log_satiri.update({"irtifa": irtifa, "hiz": hiz, "dikey_hiz": dikey, "eve_uzaklik": uzaklik})
        self._rtl_izleyici.guncelle(
            uzaklik,
            getattr(self, "_guncel_batarya_yuzde", 100),
            self._log_satiri.get("ruzgar_ms", 0.0) / 3.6,
            self._guncel_ekf_hata,
            self._guncel_gps_fix,
        )

    def _gps_guncelle(self, fix: int, uydu: int, lat: float, lon: float):
        self._guncel_lat = lat
        self._guncel_lon = lon
        fix_txt = {0:"YOK",1:"YOK",2:"2D",3:"3D",4:"DGPS",5:"RTK",6:"RTK_SABIT"}
        fix_str = fix_txt.get(fix, str(fix))
        if fix < 2:
            fix_renk = "#f44336"   # kırmızı — fix yok
        elif fix == 2:
            fix_renk = "#ffc107"   # sarı — 2D
        else:
            fix_renk = "#4caf50"   # yeşil — 3D+
        self._gps_fix_lbl.setText(f"Fix: {fix_str}")
        self._gps_fix_lbl.setStyleSheet(f"color: {fix_renk}; font-weight: bold;")
        self._gps_uydu_lbl.setText(f"Uydu: {uydu}")
        uydu_renk = "#f44336" if uydu < 6 else ("#ffc107" if uydu < 8 else "#4caf50")
        self._gps_uydu_lbl.setStyleSheet(f"color: {uydu_renk};")
        self._gps_konum_lbl.setText(f"{lat:.5f}, {lon:.5f}")
        if HARITA_MEVCUT and hasattr(self, "_harita"):
            self._harita.page().runJavaScript(
                f"droneyiGuncelle({lat}, {lon}, {self._guncel_irtifa});"
            )
            self._harita.page().runJavaScript(
                f"konumuGuncelle('Konum: {lat:.5f}, {lon:.5f}  |  İrtifa: {self._guncel_irtifa:.1f} m');"
            )
        self._guncel_gps_fix = fix
        self._log_satiri.update({"gps_fix": fix, "gps_uydu": uydu, "lat": lat, "lon": lon})

    def _tutum_guncelle(self, roll: float, pitch: float, yaw: float):
        self._yapay_ufuk.guncelle(roll, pitch)
        self._roll_lbl.setText(f"Roll: {roll:.1f}°")
        self._pitch_lbl.setText(f"Pitch: {pitch:.1f}°")
        self._yaw_lbl.setText(f"Yaw: {yaw:.1f}°")
        self._log_satiri.update({"roll": roll, "pitch": pitch, "yaw": yaw})

    def _ruzgar_guncelle(self, hiz: float, yon: float):
        self._ruzgar.guncelle(hiz, yon)
        self._log_satiri.update({"ruzgar_ms": hiz, "ruzgar_yon": yon})
        hiz_kmh = hiz * 3.6
        if hiz_kmh >= 60 and not getattr(self, "_ruzgar_kritik_gonderildi", False):
            self._ruzgar_kritik_gonderildi = True
            self._mesaj_ekle(2, f"KRİTİK RÜZGAR ({hiz_kmh:.0f} km/h)! Güvenli iniş analizi başlatılıyor.")
            if getattr(self, "_en_yakin_guvenli_nokta", None):
                self._guvenli_inise_git(onay_sor=False)  # Kritik → onaysız
            else:
                # Analiz başlat; tamamlanınca otomatik inişe git
                self._ruzgar_acil_inis_bekliyor = True
                self._guvenli_inis_baslat()
        elif hiz_kmh >= 40 and not getattr(self, "_ruzgar_tehlikeli_gonderildi", False):
            self._ruzgar_tehlikeli_gonderildi = True
            self._mesaj_ekle(3, f"TEHLİKELİ RÜZGAR ({hiz_kmh:.0f} km/h)! Eve dönüş başlatılıyor.")
            self._mavlink.mod_degistir(6)  # RTL
        # Hız normale dönünce bayrakları sıfırla
        if hiz_kmh < 35:
            self._ruzgar_tehlikeli_gonderildi = False
            self._ruzgar_kritik_gonderildi   = False

    def _imu_guncelle(self, imu_no: int, sicaklik: float):
        if 0 <= imu_no < len(self._imu_gosterge):
            self._imu_gosterge[imu_no].guncelle(sicaklik)
        if 0 <= imu_no <= 2:
            self._log_satiri[f"imu{imu_no}_c"] = sicaklik

    def _mesaj_ekle(self, severity: int, metin: str):
        renkler = {0:"#fff",1:"#ff6b6b",2:"#ffa07a",3:"#ffd700",
                   4:"#98fb98",5:"#87ceeb",6:"#c8c8c8",7:"#888"}
        renk = renkler.get(severity, "#c8c8c8")
        zaman = QDateTime.currentDateTime().toString("hh:mm:ss")
        self._mesaj_logu.append(f'<span style="color:{renk}">[{zaman}] {metin}</span>')
        self._logger.kaydet_mesaj(severity, metin)

    def _rtl_fallback_tetiklendi(self, neden: str):
        self._mesaj_ekle(2, f"RTL FALLBACK: {neden}")
        self._mesaj_ekle(3, "Güvenli iniş analizi otomatik başlatılıyor…")
        self._guvenli_inis_baslat()

    def _log_yaz(self):
        """Her saniye mevcut telemetri satırını CSV'ye yazar."""
        if self._log_satiri:
            self._logger.kaydet_satir(dict(self._log_satiri))

    def _ekf_guncelle(self, bayraklar: int, hata: float):
        self._guncel_ekf_hata = hata
        if bayraklar & 0x01F:
            self._ekf_lbl.setText(f"EKF: OK ({hata:.2f})")
            self._ekf_lbl.setStyleSheet("color: #4caf50;")
        else:
            self._ekf_lbl.setText("EKF: HATA")
            self._ekf_lbl.setStyleSheet("color: #f44336; font-weight: bold;")
        self._log_satiri.update({"ekf_bayrak": bayraklar, "ekf_hata": hata})

    # ── Parametre sinyal alıcıları ────────────────────────────────────────────

    def _param_guncelle(self, ad: str, deger: float, alinan: int, toplam: int):
        if toplam > 0:
            self._param_progress.setMaximum(toplam)
            self._param_progress.setValue(alinan)
            self._param_progress.setFormat(f"{alinan} / {toplam} parametre")

        # Tabloya ekle
        self._param_tablo.setSortingEnabled(False)
        satir = self._param_tablo.rowCount()

        # Daha önce eklendiyse güncelle
        for r in range(satir):
            if self._param_tablo.item(r, 0) and self._param_tablo.item(r, 0).text() == ad:
                self._param_tablo.item(r, 1).setText(f"{deger:.6g}")
                self._param_tablo.setSortingEnabled(True)
                return

        self._param_tablo.insertRow(satir)
        ad_item  = QTableWidgetItem(ad)
        val_item = QTableWidgetItem(f"{deger:.6g}")
        val_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._param_tablo.setItem(satir, 0, ad_item)
        self._param_tablo.setItem(satir, 1, val_item)
        self._param_tablo.setItem(satir, 2, QTableWidgetItem(""))
        self._param_tablo.setSortingEnabled(True)

    def _param_tamam(self):
        self._param_progress.hide()
        sayi = self._param_tablo.rowCount()
        self._param_bilgi.setText(f"{sayi} parametre indirildi. Düzenlemek için satıra çift tıkla.")
        self._mesaj_ekle(6, f"{sayi} parametre indirildi.")

    def _param_filtrele(self, metin: str):
        metin = metin.lower()
        for r in range(self._param_tablo.rowCount()):
            item = self._param_tablo.item(r, 0)
            if item:
                self._param_tablo.setRowHidden(r, metin not in item.text().lower())

    def _param_satir_duzenle(self, index):
        satir = index.row()
        ad_item = self._param_tablo.item(satir, 0)
        val_item = self._param_tablo.item(satir, 1)
        if not ad_item:
            return
        ad  = ad_item.text()
        eski = val_item.text() if val_item else ""
        # Düzenleme moduna al (3. sütun)
        self._param_tablo.setEditTriggers(QAbstractItemView.DoubleClicked)
        self._param_tablo.editItem(self._param_tablo.item(satir, 2))
        self._param_tablo.setEditTriggers(QAbstractItemView.NoEditTriggers)
        yeni_item = self._param_tablo.item(satir, 2)
        if yeni_item and yeni_item.text():
            try:
                yeni_deger = float(yeni_item.text())
                self._degistirilen_parametreler[ad] = yeni_deger
                yeni_item.setForeground(QColor("#ffc107"))
                self._param_bilgi.setText(f"{len(self._degistirilen_parametreler)} parametre değiştirildi (uygulanmadı).")
            except ValueError:
                pass

    # ── Buton aksiyonları ─────────────────────────────────────────────────────

    def _baglan_tikla(self):
        dize = self._baglanti_giris.text().strip()
        self._mavlink.ayarla(dize)
        if not self._mavlink.isRunning():
            self._mavlink.start()
        self._durum_guncelle(f"Bağlanılıyor: {dize}…", "#ffc107")

    def _kes_tikla(self):
        self._bagli = False
        self._hb_timer.stop()
        self._mavlink.durdur()
        self._baglan_btn.setEnabled(True)
        self._kes_btn.setEnabled(False)

    def _rtl_tikla(self):
        self._mavlink.mod_degistir(6)
        self._mesaj_ekle(3, "EV'E DÖN (RTL) komutu gönderildi.")

    def _hovering_tikla(self):
        self._mavlink.mod_degistir(5)
        self._mesaj_ekle(6, "HOVERING (LOITER) komutu gönderildi.")

    def _inis_tikla(self):
        self._mavlink.mod_degistir(9)
        self._mesaj_ekle(3, "ACİL İNİŞ komutu gönderildi.")

    def _devam_tikla(self):
        self._mavlink.mod_degistir(3)
        self._mesaj_ekle(6, "DEVAM ET (AUTO) komutu gönderildi.")

    def _mod_tikla(self, mod_id: int):
        self._mavlink.mod_degistir(mod_id)
        self._mesaj_ekle(6, f"Mod: {UÇUŞ_MODLARI.get(mod_id, mod_id)}")

    def _ev_yap_tikla(self):
        self._mavlink.ev_noktasi_sifirla()
        if HARITA_MEVCUT and hasattr(self, "_harita"):
            self._harita.page().runJavaScript(
                f"evNoktasiGuncelle({self._guncel_lat}, {self._guncel_lon});"
            )
        self._mesaj_ekle(6, f"Ev noktası güncellendi: {self._guncel_lat:.5f}, {self._guncel_lon:.5f}")

    def _param_indir_tikla(self):
        if not self._bagli:
            QMessageBox.warning(self, "Bağlantı Yok", "Önce SITL/drone'a bağlanın.")
            return
        self._param_tablo.setRowCount(0)
        self._param_progress.setValue(0)
        self._param_progress.show()
        self._param_bilgi.setText("Parametreler indiriliyor…")
        self._degistirilen_parametreler.clear()
        self._mavlink.parametreleri_iste()

    def _param_uygula_tikla(self):
        if not self._degistirilen_parametreler:
            QMessageBox.information(self, "Değişiklik Yok", "Hiçbir parametre değiştirilmedi.")
            return
        sayi = len(self._degistirilen_parametreler)
        yanit = QMessageBox.question(
            self, "Parametreleri Uygula",
            f"{sayi} parametre değişikliği gönderilsin mi?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if yanit != QMessageBox.Yes:
            return
        for ad, deger in self._degistirilen_parametreler.items():
            self._mavlink.parametre_ayarla(ad, deger)
            self._mesaj_ekle(6, f"Parametre: {ad} = {deger}")
        self._degistirilen_parametreler.clear()
        self._param_bilgi.setText("Değişiklikler gönderildi.")

    def _harita_yol_temizle(self):
        if HARITA_MEVCUT and hasattr(self, "_harita"):
            self._harita.page().runJavaScript("ucusYolunuTemizle();")

    def _guvenli_noktalar_temizle(self):
        if HARITA_MEVCUT and hasattr(self, "_harita"):
            self._harita.page().runJavaScript("guvenliNoktalariTemizle();")
        if HARITA_MEVCUT and hasattr(self, "_harita"):
            self._harita.page().runJavaScript("durumGoster('');")


    def _guvenli_inis_baslat(self):
        if not self._bagli:
            QMessageBox.warning(self, "Bağlantı Yok", "Önce SITL/drone'a bağlanın.")
            return
        if self._guncel_lat == 0.0:
            QMessageBox.warning(self, "GPS Yok", "Drone GPS konumu henüz alınamadı.")
            return
        if self._terrain_thread and self._terrain_thread.isRunning():
            return

        # Mevcut batarya yüzdesini al
        bat = getattr(self, "_guncel_batarya_yuzde", 30)

        if HARITA_MEVCUT and hasattr(self, "_harita"):
            self._harita.page().runJavaScript(
                "document.getElementById('analizBtn').disabled=true;"
                "durumGoster('Arazi verisi indiriliyor, analiz yapılıyor… (ilk kez ~15 sn)');"
            )

        ruz_ms  = self._log_satiri.get("ruzgar_ms", 0.0) / 3.6   # km/h → m/s
        ruz_yon = self._log_satiri.get("ruzgar_yon", 0.0)
        self._terrain_thread = TerrainAnalizThread(
            self._guncel_lat, self._guncel_lon, bat,
            ruzgar_ms=ruz_ms, ruzgar_yonu_derece=ruz_yon,
        )
        self._terrain_thread.tamamlandi.connect(self._guvenli_inis_tamamlandi)
        self._terrain_thread.hata.connect(self._guvenli_inis_hata)
        self._terrain_thread.start()

    def _guvenli_inis_tamamlandi(self, sonuc):
        if HARITA_MEVCUT and hasattr(self, "_harita"):
            self._harita.page().runJavaScript("document.getElementById('analizBtn').disabled=false;")
        self._son_analiz_sonucu = sonuc
        if not sonuc.basarili:
            if HARITA_MEVCUT and hasattr(self, "_harita"):
                self._harita.page().runJavaScript(f"durumGoster('Hata: {sonuc.hata}');")
            return

        # Tüm güvenli + riskli noktaları JS'e gönder
        noktalar = []
        for n in sonuc.guvenli_noktalar:
            noktalar.append({
                "lat": n.lat, "lon": n.lon,
                "yukseklik": n.yukseklik_m, "egim": n.egim_derece,
                "mesafe": n.mesafe_m, "guvenlik": n.guvenlik,
            })
        for n in sonuc.riskli_noktalar:
            noktalar.append({
                "lat": n.lat, "lon": n.lon,
                "yukseklik": n.yukseklik_m, "egim": n.egim_derece,
                "mesafe": n.mesafe_m, "guvenlik": n.guvenlik,
            })

        noktalar_json = json.dumps(noktalar)
        js = (
            f"guvenliNoktalariGoster("
            f"'{noktalar_json}', "
            f"{sonuc.yaricap_m:.0f}, "
            f"{sonuc.merkez_lat}, "
            f"{sonuc.merkez_lon});"
        )
        if HARITA_MEVCUT and hasattr(self, "_harita"):
            self._harita.page().runJavaScript(js)
            if sonuc.en_yakin_guvenli:
                g = sonuc.en_yakin_guvenli
                self._en_yakin_guvenli_nokta = (g.lat, g.lon)
                self._harita.page().runJavaScript(
                    f"enYakinNoktayiKaydet({g.lat}, {g.lon});"
                )

        ozet = sonuc.ozet()
        durum = f"Güvenli: {len(sonuc.guvenli_noktalar)} nokta  |  Riskli: {len(sonuc.riskli_noktalar)} nokta  |  {ozet}"
        if HARITA_MEVCUT and hasattr(self, "_harita"):
            self._harita.page().runJavaScript(f"durumGoster('{durum}');")
        self._mesaj_ekle(6, f"Arazi analizi: {ozet}")

        # Kritik rüzgar veya RTL fallback bekliyorsa otomatik inişe git
        if self._ruzgar_acil_inis_bekliyor:
            self._ruzgar_acil_inis_bekliyor = False
            self._guvenli_inise_git(onay_sor=False)

    def _guvenli_inise_git(self, onay_sor: bool = True):
        nokta = getattr(self, "_en_yakin_guvenli_nokta", None)

        # Güvenli nokta yoksa en az riskli noktayı dene
        if nokta is None:
            son_analiz = getattr(self, "_son_analiz_sonucu", None)
            if son_analiz and son_analiz.riskli_noktalar:
                fallback = min(son_analiz.riskli_noktalar, key=lambda n: n.egim_derece)
                nokta = (fallback.lat, fallback.lon)
                self._mesaj_ekle(3, f"Güvenli nokta yok — en az riskli seçildi: {fallback.egim_derece:.1f}°")
            else:
                self._mesaj_ekle(4, "Önce güvenli iniş analizi yapın.")
                return

        lat, lon = nokta
        if onay_sor:
            onay = QMessageBox.question(
                self, "Güvenli İnişe Git",
                f"Drone şu konuma gidip inecek:\n{lat:.5f}, {lon:.5f}\n\nEmin misiniz?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if onay != QMessageBox.Yes:
                return

        from pymavlink import mavutil as _mu
        # GUIDED moda geç
        self._mavlink.mod_degistir(4)
        # Hedefe git (mevcut irtifada)
        irtifa = getattr(self, "_guncel_irtifa", 20.0)
        self._mavlink.komut_gonder(
            _mu.mavlink.MAV_CMD_DO_REPOSITION,
            -1, 0, 0, 0, lat, lon, max(irtifa, 10.0)
        )
        self._mesaj_ekle(6, f"Güvenli inişe gidiliyor: {lat:.5f}, {lon:.5f}")

        # 20 saniye sonra iniş komutu gönder
        QTimer.singleShot(20000, self._inis_komutu_gonder)

    def _inis_komutu_gonder(self):
        # Güvenli nokta yoksa riskli fallback noktasını kullan
        nokta = getattr(self, "_en_yakin_guvenli_nokta", None)
        if nokta is None:
            son_analiz = getattr(self, "_son_analiz_sonucu", None)
            if son_analiz and son_analiz.riskli_noktalar:
                f = min(son_analiz.riskli_noktalar, key=lambda n: n.egim_derece)
                nokta = (f.lat, f.lon)
            else:
                return
        lat, lon = nokta
        from pymavlink import mavutil as _mu
        self._mavlink.komut_gonder(
            _mu.mavlink.MAV_CMD_NAV_LAND,
            0, 0, 0, 0, lat, lon, 0
        )
        self._mesaj_ekle(6, "İniş komutu gönderildi.")

    def _guvenli_inis_hata(self, mesaj: str):
        if HARITA_MEVCUT and hasattr(self, "_harita"):
            self._harita.page().runJavaScript(
                "document.getElementById('analizBtn').disabled=false;"
                f"durumGoster('Analiz hatası: {mesaj}');"
            )
        self._mesaj_ekle(3, f"Arazi analiz hatası: {mesaj}")

    # ── Genel ────────────────────────────────────────────────────────────────

    def _durum_guncelle(self, metin: str, renk: str):
        self._durum_bar.showMessage(metin)
        self._durum_bar.setStyleSheet(
            f"QStatusBar {{ background-color: #0a1520; color: {renk}; }}"
        )

    def closeEvent(self, event):
        self._hb_timer.stop()
        self._mavlink.durdur()
        super().closeEvent(event)


# ── Giriş noktası ─────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Türkçe GCS – Doğuş ÜNİ LÖP")
    pencere = AnaPencere()
    pencere.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
