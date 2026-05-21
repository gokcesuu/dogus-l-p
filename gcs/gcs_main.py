"""
Doğuş Üniversitesi LÖP – Türkçe Yer İstasyonu (GCS)
Çalıştırmak için: python gcs_main.py
SITL bağlantısı: tcp:127.0.0.1:5762
"""

import os
import sys
import time

# QWebEngineView Windows crash fix
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
    "--disable-gpu --disable-gpu-compositing --no-sandbox --disable-dev-shm-usage")
import json
from collections import deque
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton,
    QLineEdit, QTextEdit, QGridLayout, QHBoxLayout, QVBoxLayout,
    QGroupBox, QStatusBar, QTabWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QProgressBar, QMessageBox, QAbstractItemView,
    QFileDialog, QStackedWidget, QComboBox, QSpinBox,
)
from PyQt5.QtCore import Qt, QDateTime, QTimer, QThread, pyqtSignal as Signal
from PyQt5.QtGui import QFont, QColor

try:
    from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEnginePage
    from PyQt5.QtCore import QUrl, QUrlQuery
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
from ucus_raporu import UcusKaydedici
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
    <select id="katmanSecici" onchange="katmanDegistir(this.value)"
      style="background:#1a2a3a;color:#7eb8e0;border:1px solid #2a4060;border-radius:3px;
             padding:3px 8px;font-size:12px;cursor:pointer;height:28px;"
      title="Harita türünü değiştir">
      <option value="uydu">&#128752; Uydu</option>
      <option value="hibrit">&#127758; Hibrit</option>
      <option value="sokak">&#128506; Sokak</option>
    </select>
    <button onclick="window.location.href='gcs://ucus-yolu-temizle'">U&ccedil;u&#351; Yolunu Temizle</button>
    <button class="green" id="analizBtn" onclick="window.location.href='gcs://guvenli-inis-baslat'">G&uuml;venli &#304;ni&#351; Analizi</button>
    <button onclick="window.location.href='gcs://analiz-temizle'">Analizi Temizle</button>
    <button class="red" id="inisBtn" disabled onclick="window.location.href='gcs://guvenli-inise-git'">&#128680; G&uuml;venli &#304;ni&#351;e Git</button>
    <button id="rallyBtn" style="background:#1a3c6a;border-color:#2a5c9a;" onclick="window.location.href='gcs://rally-yukle'" title="En iyi 5 g&uuml;venli noktay&#305; ArduPilot Rally Point olarak y&uuml;kle (Katman 2)">&#128225; Rally Y&uuml;kle</button>
    <button id="fenceBtn" style="background:#2a1a4a;border-color:#6a3a9a;" onclick="window.location.href='gcs://fence-yukle'" title="U&ccedil;u&#351; alan&#305; bounding box'&#305;ndan AC_Fence polygon y&uuml;kle -- ihlalde RTL">&#128274; Fence Y&uuml;kle</button>
    <button id="wpBtn" style="background:#1a2a3a;border-color:#b8860b;" onclick="wpToggle()" title="Haritaya tikla → waypoint ekle | Tekrar tıkla → modu kapat | Sag tik markera → sil">&#128205; WP Ekle</button>
    <button style="background:#1a3a1a;border-color:#4caf50;" onclick="window.location.href='gcs://wp-yukle'" title="Waypointleri drone'a yukle ve OTOMATİK moda gec">&#9654; Gorevi Yukle</button>
    <button style="background:#3a1a1a;border-color:#f44336;" onclick="window.location.href='gcs://wp-oku'" title="Drone'daki waypointleri oku ve haritada goster">&#11015; Drone'dan Oku</button>
    <button style="background:#2a2a2a;border-color:#666;" onclick="wpTemizle();window.location.href='gcs://wp-temizle'" title="Tum waypointleri sil">&#128465; WP Temizle</button>
    <button id="cizBtn" style="background:#1a3050;border-color:#2a6040;" onclick="cizimBaslat()" title="Haritada ucus alanini faresiyle ciz, sonra terrain otomatik indirilir">&#9999; Alan Ciz</button>
    <button id="alanHazirlaBtn" style="background:#1a3a2a;border-color:#3a8a5a;" onclick="window.location.href='gcs://alan-hazirla'" title="Mevcut GPS konumu icin terrain verisini yeniden indir ve hazirla">&#128205; Alani Yenile</button>
    <button id="droneGitBtn" style="background:#2a1a1a;border-color:#8a3a2a;" onclick="window.location.href='gcs://drone-git'" title="Haritayi drone konumuna odakla">&#127989; Drone</button>
    <span id="konum">Konum: --</span>
</div>
<div id="durum"></div>
<script>
var map = L.map('map', {zoomControl: true}).setView([39.9, 32.8], 6);
var _ERR_TILE = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';
var _ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services/';
// Sadece URL konfigürasyonları — L.tileLayer() seçilince oluşturulur (hafıza tasarrufu)
var _TILE_URL = {
  uydu:   {url: _ESRI + 'World_Imagery/MapServer/tile/{z}/{y}/{x}',           attr:'© Esri',    zoom:19},
  hibrit: {url: _ESRI + 'World_Imagery/MapServer/tile/{z}/{y}/{x}',           attr:'© Esri',    zoom:19, yerAdi:true},
  sokak:  {url: 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', attr:'© CartoDB', zoom:19}
};
var _YERADI_URL = _ESRI + 'Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}';
var _aktifKatman = null;
var _yerAdiKatman = null;

function katmanDegistir(isim) {
  // Eskiyi kaldır ve bellekten temizle
  if (_aktifKatman) { map.removeLayer(_aktifKatman); _aktifKatman = null; }
  if (_yerAdiKatman) { map.removeLayer(_yerAdiKatman); _yerAdiKatman = null; }
  // Sadece seçilen katmanı oluştur
  var cfg = _TILE_URL[isim] || _TILE_URL.uydu;
  _aktifKatman = L.tileLayer(cfg.url, {attribution:cfg.attr, maxZoom:cfg.zoom, errorTileUrl:_ERR_TILE}).addTo(map);
  if (cfg.yerAdi) {
    _yerAdiKatman = L.tileLayer(_YERADI_URL, {attribution:'', maxZoom:19, opacity:0.85, errorTileUrl:_ERR_TILE}).addTo(map);
  }
  var sel = document.getElementById('katmanSecici');
  if (sel) sel.value = isim;
}
katmanDegistir('uydu');   // başlangıçta sadece uydu yükle

var droneIcon = L.divIcon({
  html: '<div style="width:14px;height:14px;background:#f44336;border:2px solid white;border-radius:50%;"></div>',
  iconSize: [14,14], iconAnchor: [7,7]
});
var evIcon = L.divIcon({
  html: '<div style="width:12px;height:12px;background:#4caf50;border:2px solid white;transform:rotate(45deg);"></div>',
  iconSize: [12,12], iconAnchor: [6,6]
});

var droneMark = L.marker([39.9, 32.8], {icon: droneIcon}).addTo(map);
var evMark    = L.marker([39.9, 32.8], {icon: evIcon}).addTo(map);
var ucusYolu  = L.polyline([], {color: '#64b5f6', weight: 2, opacity: 0.7}).addTo(map);
var ucusKoord = [];
var ilkKonum  = true;

function droneyiGuncelle(lat, lon, irtifa) {
  var pos = [lat, lon];
  droneMark.setLatLng(pos);
    droneMark.bindTooltip('Drone<br>\\u0130rtifa: ' + irtifa.toFixed(1) + ' m', {permanent: false});
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
    evMark.bindTooltip('Ev Noktas\\u0131', {permanent: false});
}

var adsbKatman = L.layerGroup().addTo(map);
var adsbMarkers = {};
function adsbGuncelle(icao, lat, lon, alt, hdg, callsign) {
    var label = (callsign || icao.toString(16).toUpperCase()) + '\\\\n' + alt + 'm ' + hdg + '\\u00b0';
  var icon = L.divIcon({
    html: '<div style="color:#ff9800;font-size:18px;transform:rotate(' + hdg + 'deg)">\\u2708</div>',
    iconSize: [20,20], iconAnchor: [10,10], className: ''
  });
  if (adsbMarkers[icao]) {
    adsbMarkers[icao].setLatLng([lat, lon]).setIcon(icon).bindTooltip(label, {permanent:false});
  } else {
    adsbMarkers[icao] = L.marker([lat, lon], {icon: icon})
      .bindTooltip(label, {permanent: false}).addTo(adsbKatman);
  }
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

// -- NPZ'den gelen noktalar (AlanHazirlikThread sonucu) --
// Format: {id, lat, lon, egim, durum} -- guvenliNoktalariGoster'dan farkli
function alanNoktalarGoster(noktalarJsonStr, latMin, latMax, lonMin, lonMax) {
  guvenliKatman.clearLayers();
  if (yaricapDairesi) { map.removeLayer(yaricapDairesi); yaricapDairesi = null; }
  var noktalar;
  try { noktalar = JSON.parse(noktalarJsonStr); }
  catch(e) { durumGoster('⚠ Nokta verisi okunamadi.'); return; }
  var guvenliSayac = 0, riskliSayac = 0;
  noktalar.forEach(function(n) {
    var guvenli = n.durum === 'GUVENLI';
    if (guvenli) guvenliSayac++; else riskliSayac++;
    if (guvenli && guvenliSayac > 20) return;
    if (!guvenli && riskliSayac > 5) return;
    var renk = guvenli ? '#4caf50' : '#ffc107';
    var yarim = guvenli ? 50 : 30;
    L.circle([n.lat, n.lon], {
      radius: yarim, color: renk, fillColor: renk, fillOpacity: 0.55, weight: 1
    }).bindTooltip(
      '<b>' + (guvenli ? '✓ Güvenli' : '⚠ Riskli') + '</b><br>' +
      'Eğim: ' + n.egim.toFixed(1) + '°<br>' +
      n.lat.toFixed(5) + ', ' + n.lon.toFixed(5),
      {sticky: true}
    ).addTo(guvenliKatman);
  });
  if (latMin !== undefined && latMin !== null) {
    map.fitBounds([[latMin, lonMin], [latMax, lonMax]], {padding: [30, 30]});
  }
  var msg = '✓ Terrain hazır: ' + guvenliSayac + ' güvenli nokta (yeşil), ' + riskliSayac + ' riskli nokta (sarı).';
  if (guvenliSayac === 0) {
    msg += ' ⚠ Bu alanda düz iniş yeri bulunamadı!';
  } else {
    msg += ' Drone bağlıysa "Güvenli İniş Analizi" ile en yakın noktasını seçin.';
  }
  durumGoster(msg);
}

function guvenliNoktalariGoster(noktalarJson, yaricap_m, merkez_lat, merkez_lon) {
  guvenliKatman.clearLayers();
  if (yaricapDairesi) { map.removeLayer(yaricapDairesi); }
  yaricapDairesi = L.circle([merkez_lat, merkez_lon], {
    radius: yaricap_m, color: '#64b5f6',
    fillColor: '#64b5f6', fillOpacity: 0.04,
    weight: 1, dashArray: '6,4'
    }).bindTooltip('U\\u00e7u\\u015f yar\\u0131\\u00e7ap\\u0131: ' + yaricap_m.toFixed(0) + ' m').addTo(map);
  var noktalar = JSON.parse(noktalarJson);
  noktalar.forEach(function(n) {
    var renk  = n.guvenlik === 'GUVENLI' ? '#4caf50' : '#ffc107';
    var yarim = n.guvenlik === 'GUVENLI' ? 55 : 35;
    L.circle([n.lat, n.lon], {
      radius: yarim, color: renk,
      fillColor: renk, fillOpacity: 0.55, weight: 1
    }).bindTooltip(
    '<b>' + n.guvenlik + '</b><br>E\\u011fim: ' + n.egim.toFixed(1) + '\\u00b0<br>' +
    'Y\\u00fckseklik: ' + n.yukseklik.toFixed(0) + ' m<br>' +
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

// -- Terrain analiz siniri (mavi kesik) --
var terrainRect = null;
function terrainSinirGoster(lat1, lon1, lat2, lon2) {
  if (terrainRect) map.removeLayer(terrainRect);
  var b = L.latLngBounds([[lat1, lon1], [lat2, lon2]]);
  terrainRect = L.rectangle(b, {
    color:'#5b8dd9', weight:1.5, fillOpacity:0.03, dashArray:'8 5'
  }).addTo(map);
  terrainRect.bindTooltip('Terrain analiz alani', {permanent:false, direction:'center'});
}

// -- Ucus alani cizimi --
var cizimModu      = false;
var cizimBaslangic = null;
var geciciRect     = null;
var kaliciRect     = null;

function cizimBaslat() {
  cizimModu = true;
  map.dragging.disable();
  map.scrollWheelZoom.disable();
  map.getContainer().style.cursor = 'crosshair';
  document.getElementById('cizBtn').style.borderColor = '#4caf50';
  document.getElementById('cizBtn').style.background  = '#1a4a2a';
}

function cizimIptal() {
  cizimModu = false;
  cizimBaslangic = null;
  map.dragging.enable();
  map.scrollWheelZoom.enable();
  map.getContainer().style.cursor = '';
  document.getElementById('cizBtn').style.borderColor = '';
  document.getElementById('cizBtn').style.background  = '#1a3050';
  if (geciciRect) { map.removeLayer(geciciRect); geciciRect = null; }
}

map.on('mousedown', function(e) {
  if (!cizimModu) return;
  L.DomEvent.stopPropagation(e);
  L.DomEvent.preventDefault(e);
  cizimBaslangic = e.latlng;
  if (geciciRect) { map.removeLayer(geciciRect); geciciRect = null; }
});

map.on('mousemove', function(e) {
  if (!cizimModu || !cizimBaslangic) return;
  var b = L.latLngBounds(cizimBaslangic, e.latlng);
  if (geciciRect) { geciciRect.setBounds(b); }
  else { geciciRect = L.rectangle(b, {color:'#4caf50', weight:2, fillOpacity:0.08}).addTo(map); }
});

map.on('mouseup', function(e) {
  if (!cizimModu || !cizimBaslangic) return;
  var b  = L.latLngBounds(cizimBaslangic, e.latlng);
  var sw = b.getSouthWest(), ne = b.getNorthEast();
  // drag ve zoom'u geri aç
  map.dragging.enable();
  map.scrollWheelZoom.enable();
  cizimModu = false; cizimBaslangic = null;
  map.getContainer().style.cursor = '';
  document.getElementById('cizBtn').style.borderColor = '';
  document.getElementById('cizBtn').style.background  = '#1a3050';
  if (geciciRect) { map.removeLayer(geciciRect); geciciRect = null; }
  if (kaliciRect) map.removeLayer(kaliciRect);
  kaliciRect = L.rectangle(b, {color:'#4caf50', weight:2, fillOpacity:0.08,
    dashArray:'6 4'}).addTo(map);
  window.location.href = 'gcs://alan-cizildi?lat1=' + sw.lat
    + '&lon1=' + sw.lng + '&lat2=' + ne.lat + '&lon2=' + ne.lng;
});

// ESC ile çizimi iptal et
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape' && cizimModu) { cizimIptal(); }
  if (e.key === 'Escape' && wpModAktif) { wpModKapat(); }
});

// ── Waypoint Görev Planlaması ────────────────────────────────────────────────
var wpListesi   = [];   // [{lat, lon, alt}, ...]
var wpMarkerlar = [];   // Leaflet marker listesi
var wpYolu      = L.polyline([], {color:'#ffeb3b', weight:2.5, opacity:0.9}).addTo(map);
var wpModAktif  = false;

function wpModAc() {
  wpModAktif = true;
  map.dragging.disable();
  map.scrollWheelZoom.disable();
  map.getContainer().style.cursor = 'crosshair';
  var btn = document.getElementById('wpBtn');
  if (btn) { btn.style.borderColor = '#ffeb3b'; btn.style.background = '#3a3000'; }
  durumGoster('Waypoint modu aktif — haritaya tıkla, ESC ile çık');
}
function wpModKapat() {
  wpModAktif = false;
  map.dragging.enable();
  map.scrollWheelZoom.enable();
  map.getContainer().style.cursor = '';
  var btn = document.getElementById('wpBtn');
  if (btn) { btn.style.borderColor = '#b8860b'; btn.style.background = '#1a2a3a'; }
  if (wpListesi.length > 0)
    durumGoster('WP modu kapatıldı — ' + wpListesi.length + ' waypoint hazır');
}
function wpToggle() {
  if (wpModAktif) wpModKapat(); else wpModAc();
}

// Varsayılan irtifa — Python spinbox'tan güncellenir
var _wpDefAlt = 50;
function wpDefAltGuncelle(alt) { _wpDefAlt = alt; }

// Harita tıklaması — WP ekle (cizim modu veya wp modu)
map.on('click', function(e) {
  _wpCtxKapat();   // Açık context menüyü kapat
  if (!wpModAktif) return;
  var wp = {lat: e.latlng.lat, lon: e.latlng.lng, alt: _wpDefAlt, komut: 'NAV_WAYPOINT'};
  wpListesi.push(wp);
  _wpMarkerEkle(wpListesi.length - 1);
  _wpYoluGuncelle();
  _wpTabloGonder();
  durumGoster('WP ' + wpListesi.length + ' eklendi — ' + wp.lat.toFixed(5) + ', ' + wp.lon.toFixed(5));
});

function _wpMarkerEkle(idx) {
  var wp = wpListesi[idx];
  var ikon = L.divIcon({
    html: '<div style="background:#ffeb3b;color:#000;border-radius:50%;width:24px;height:24px;'
        + 'display:flex;align-items:center;justify-content:center;font-size:12px;'
        + 'font-weight:bold;border:2px solid #f57f17;box-shadow:0 0 4px rgba(0,0,0,0.6);">'
        + (idx + 1) + '</div>',
    iconSize: [24, 24], iconAnchor: [12, 12], className: ''
  });
  var m = L.marker([wp.lat, wp.lon], {icon: ikon, draggable: true})
    .addTo(map)
    .bindTooltip(
      'WP ' + (idx + 1) + '<br>' + wp.lat.toFixed(5) + ', ' + wp.lon.toFixed(5)
      + '<br>İrtifa: ' + wp.alt + ' m<br><i>Sağ tık → menü | Sürükle → taşı</i>',
      {sticky: true}
    );
  m._wpIdx = idx;
  m.on('drag', function(ev) {
    wpListesi[idx].lat = ev.latlng.lat;
    wpListesi[idx].lon = ev.latlng.lng;
    m.setTooltipContent(
      'WP ' + (idx + 1) + '<br>' + ev.latlng.lat.toFixed(5) + ', ' + ev.latlng.lng.toFixed(5)
      + '<br>İrtifa: ' + wpListesi[idx].alt + ' m<br><i>Sağ tık → menü | Sürükle → taşı</i>'
    );
    _wpYoluGuncelle();
  });
  m.on('dragend', function() { _wpTabloGonder(); });
  m.on('contextmenu', function(ev) {
    L.DomEvent.stopPropagation(ev);
    var _menuIcerik =
      '<div style="background:#1a2a3a;border:1px solid #2a4060;border-radius:4px;'
      + 'padding:4px 0;min-width:140px;font-size:12px;font-family:sans-serif;">'
      + '<div style="padding:2px 8px;color:#aaa;font-size:10px;border-bottom:1px solid #2a4060;margin-bottom:2px;">'
      + 'WP ' + (idx + 1) + '</div>'
      + '<div class="wp-ctx-item" style="cursor:pointer;padding:4px 12px;color:#ef9a9a;"'
      + ' onmouseover="this.style.background=\'#2a1a1a\'" onmouseout="this.style.background=\'\'"'
      + ' onclick="_wpCtxKapat();wpSil(' + idx + ')">Sil</div>'
      + '<div class="wp-ctx-item" style="cursor:pointer;padding:4px 12px;color:#80cbc4;"'
      + ' onmouseover="this.style.background=\'#1a2a2a\'" onmouseout="this.style.background=\'\'"'
      + ' onclick="_wpCtxKapat();wpKomutDegistir(' + idx + ',\'LOITER_UNLIMITED\')">Loiter Yap</div>'
      + '<div class="wp-ctx-item" style="cursor:pointer;padding:4px 12px;color:#a5d6a7;"'
      + ' onmouseover="this.style.background=\'#1a2a1a\'" onmouseout="this.style.background=\'\'"'
      + ' onclick="_wpCtxKapat();wpKomutDegistir(' + idx + ',\'TAKEOFF\')">Takeoff Yap</div>'
      + '<div class="wp-ctx-item" style="cursor:pointer;padding:4px 12px;color:#ffcc80;"'
      + ' onmouseover="this.style.background=\'#2a2a1a\'" onmouseout="this.style.background=\'\'"'
      + ' onclick="_wpCtxKapat();wpKomutDegistir(' + idx + ',\'LAND\')">Land Yap</div>'
      + '</div>';
    _wpCtxPopup = L.popup({closeButton: false, offset: [0, -4], className: 'wp-ctx-popup'})
      .setLatLng(ev.latlng)
      .setContent(_menuIcerik)
      .openOn(map);
  });
  wpMarkerlar.push(m);
}

function _wpMarkerlarYenidenNumarala() {
  wpMarkerlar.forEach(function(m, i) {
    m.setIcon(L.divIcon({
      html: '<div style="background:#ffeb3b;color:#000;border-radius:50%;width:24px;height:24px;'
          + 'display:flex;align-items:center;justify-content:center;font-size:12px;'
          + 'font-weight:bold;border:2px solid #f57f17;box-shadow:0 0 4px rgba(0,0,0,0.6);">'
          + (i + 1) + '</div>',
      iconSize: [24, 24], iconAnchor: [12, 12], className: ''
    }));
    m._wpIdx = i;
    m.setTooltipContent(
      'WP ' + (i + 1) + '<br>' + wpListesi[i].lat.toFixed(5) + ', ' + wpListesi[i].lon.toFixed(5)
      + '<br>İrtifa: ' + wpListesi[i].alt + ' m<br><i>Sağ tık → menü | Sürükle → taşı</i>'
    );
  });
}

var _wpCtxPopup = null;

function _wpCtxKapat() {
  if (_wpCtxPopup) { map.closePopup(_wpCtxPopup); _wpCtxPopup = null; }
}

function wpKomutDegistir(idx, komut) {
  if (idx >= 0 && idx < wpListesi.length) {
    wpListesi[idx].komut = komut;
    _wpTabloGonder();
    durumGoster('WP ' + (idx + 1) + ' → ' + komut);
  }
}

function wpSil(idx) {
  map.removeLayer(wpMarkerlar[idx]);
  wpListesi.splice(idx, 1);
  wpMarkerlar.splice(idx, 1);
  _wpMarkerlarYenidenNumarala();
  _wpYoluGuncelle();
  _wpTabloGonder();
  durumGoster(wpListesi.length + ' waypoint kaldı');
}

function wpTemizle() {
  wpMarkerlar.forEach(function(m) { map.removeLayer(m); });
  wpListesi = []; wpMarkerlar = [];
  wpYolu.setLatLngs([]);
  _wpTabloGonder();
  durumGoster('Tüm waypointler silindi');
}

function _wpYoluGuncelle() {
  wpYolu.setLatLngs(wpListesi.map(function(w) { return [w.lat, w.lon]; }));
}

function _wpTabloGonder() {
  // Python'a waypoint listesini gönder (URL query string olarak)
  window.location.href = 'gcs://wp-guncelle?data=' + encodeURIComponent(JSON.stringify(wpListesi));
}

// Python → JS: irtifa güncellemesi (tablodan düzenleme)
function wpIrtifaGuncelle(idx, alt) {
  if (idx >= 0 && idx < wpListesi.length) {
    wpListesi[idx].alt = alt;
    if (wpMarkerlar[idx]) {
      wpMarkerlar[idx].setTooltipContent(
        'WP ' + (idx + 1) + '<br>' + wpListesi[idx].lat.toFixed(5)
        + ', ' + wpListesi[idx].lon.toFixed(5)
        + '<br>İrtifa: ' + alt + ' m<br><i>Sağ tık → menü | Sürükle → taşı</i>'
      );
    }
  }
}

// Python → JS: drone'dan okunan waypointleri haritaya yükle
function wpListeYukle(wpJsonStr) {
  wpTemizle();
  var liste = JSON.parse(wpJsonStr);
  liste.forEach(function(wp) {
    if (!wp.komut) wp.komut = 'NAV_WAYPOINT';
    wpListesi.push(wp);
    _wpMarkerEkle(wpListesi.length - 1);
  });
  _wpYoluGuncelle();
  if (liste.length > 0) {
    var lats = liste.map(function(w) { return w.lat; });
    var lons = liste.map(function(w) { return w.lon; });
    map.fitBounds([
      [Math.min.apply(null, lats), Math.min.apply(null, lons)],
      [Math.max.apply(null, lats), Math.max.apply(null, lons)]
    ], {padding: [50, 50]});
  }
  durumGoster(liste.length + ' waypoint drone\'dan yüklendi');
}
</script>
</body>
</html>"""

# ── Mini-harita HTML (uçuş sekmesi — sadece drone takibi) ────────────────────

MINI_HARITA_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  * { box-sizing:border-box; margin:0; padding:0; }
  html, body { width:100%; height:100%; overflow:hidden; background:#0d1b2a; }
  #map { position:absolute; top:30px; left:0; right:0; bottom:0; }
  #minibar {
    position:absolute; top:0; left:0; right:0; height:30px; z-index:1000;
    background:rgba(13,27,42,0.95); display:flex; align-items:center; gap:4px;
    padding:0 6px; border-bottom:1px solid #2a4060;
  }
  #minibar button {
    background:#1a3050; color:#c8d8e8; border:1px solid #2a4060;
    border-radius:3px; padding:2px 8px; cursor:pointer; font-size:11px; height:22px;
  }
  #minibar button:hover { background:#2a4060; }
  #minibar select {
    background:#1a2a3a; color:#7eb8e0; border:1px solid #2a4060;
    border-radius:3px; padding:1px 4px; font-size:11px; height:22px; cursor:pointer;
  }
  #mini-konum { margin-left:auto; color:#7eb8e0; font-size:10px; white-space:nowrap; padding-right:4px; }
</style>
</head>
<body>
<div id="minibar">
  <select id="katmanSec" onchange="katmanDegistir(this.value)">
    <option value="uydu">Uydu</option>
    <option value="sokak">Sokak</option>
  </select>
  <button onclick="droneOdakla()">Drone</button>
  <button onclick="izTemizle()">Yol Sil</button>
  <span id="mini-konum">--</span>
</div>
<div id="map"></div>
<script>
var _ERR_TILE = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';
var _ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services/';
var _TILE_CFG = {
  uydu:  {url: _ESRI + 'World_Imagery/MapServer/tile/{z}/{y}/{x}', attr:'Esri', zoom:19},
  sokak: {url: 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', attr:'CartoDB', zoom:19}
};
var map = L.map('map', {zoomControl:true, attributionControl:false, preferCanvas:true})
           .setView([39.9, 32.8], 6);
var _aktifKatman = null;

function katmanDegistir(isim) {
  if (_aktifKatman) { map.removeLayer(_aktifKatman); _aktifKatman = null; }
  var cfg = _TILE_CFG[isim] || _TILE_CFG.uydu;
  _aktifKatman = L.tileLayer(cfg.url,
    {attribution:cfg.attr, maxZoom:cfg.zoom, errorTileUrl:_ERR_TILE}).addTo(map);
  var s = document.getElementById('katmanSec');
  if (s) s.value = isim;
}
katmanDegistir('uydu');

function _droneIkon(yaw) {
  var rot = typeof yaw === 'number' ? yaw : 0;
  return L.divIcon({
    html: '<div style="width:0;height:0;'
      + 'border-left:7px solid transparent;border-right:7px solid transparent;'
      + 'border-bottom:20px solid #f44336;transform:rotate(' + rot + 'deg);'
      + 'transform-origin:50% 50%;filter:drop-shadow(0 0 3px rgba(244,67,54,0.6));"></div>',
    iconSize:[14,20], iconAnchor:[7,10], className:''
  });
}
var evIcon = L.divIcon({
  html: '<div style="width:12px;height:12px;background:#4caf50;'
    + 'border:2px solid white;transform:rotate(45deg);'
    + 'box-shadow:0 0 4px rgba(76,175,80,0.7);"></div>',
  iconSize:[12,12], iconAnchor:[6,6], className:''
});

var droneMark   = L.marker([39.9, 32.8], {icon: _droneIkon(0)}).addTo(map);
var evMark      = null;
var izCizgi     = L.polyline([], {color:'#64b5f6', weight:2, opacity:0.8}).addTo(map);
var izKoord     = [];
var ilkKonum    = true;

function droneGuncelle(lat, lon, irtifa, yaw) {
  var pos = [lat, lon];
  droneMark.setLatLng(pos);
  droneMark.setIcon(_droneIkon(yaw));
  izKoord.push(pos);
  if (izKoord.length > 300) izKoord.shift();
  izCizgi.setLatLngs(izKoord);
  if (ilkKonum) { map.setView(pos, 15); ilkKonum = false; }
  else { map.panTo(pos, {animate:true, duration:0.3}); }
  var k = document.getElementById('mini-konum');
  if (k) k.textContent = lat.toFixed(5) + ', ' + lon.toFixed(5) + '  ' + irtifa.toFixed(1) + 'm';
}

function evNoktasiGoster(lat, lon) {
  if (evMark) { evMark.setLatLng([lat, lon]); }
  else { evMark = L.marker([lat, lon], {icon:evIcon}).bindTooltip('Ev').addTo(map); }
}

function izTemizle() {
  izKoord = []; izCizgi.setLatLngs([]);
}

function droneOdakla() {
  var ll = droneMark.getLatLng();
  map.setView(ll, 16);
}

function boyutDuzelt() {
  if (typeof map !== 'undefined') { map.invalidateSize(true); }
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

        def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
            print(f"js: {message} ({sourceID}:{lineNumber})")

        def acceptNavigationRequest(self, url, nav_type, is_main_frame):
            if url.scheme() == 'gcs':
                eylem = url.host()
                def _defer(fn):
                    def _run():
                        try:
                            fn()
                        except Exception as exc:
                            print(f"[Harita] Aksiyon hatasi: {exc}")
                    QTimer.singleShot(0, _run)

                if eylem == 'ucus-yolu-temizle':
                    _defer(self._gcs._harita_yol_temizle)
                elif eylem == 'guvenli-inis-baslat':
                    _defer(self._gcs._guvenli_inis_baslat)
                elif eylem == 'analiz-temizle':
                    _defer(self._gcs._guvenli_noktalar_temizle)
                elif eylem == 'guvenli-inise-git':
                    _defer(self._gcs._guvenli_inise_git)
                elif eylem == 'rally-yukle':
                    _defer(self._gcs._rally_yukle_baslat)
                elif eylem == 'fence-yukle':
                    _defer(self._gcs._fence_yukle_baslat)
                elif eylem == 'alan-hazirla':
                    def _alan_hazirla():
                        lat = self._gcs._guncel_lat
                        lon = self._gcs._guncel_lon
                        if lat != 0.0:
                            self._gcs._alan_hazirlik_yapildi = False
                            self._gcs._alan_karar = None   # yeniden indir → GPS trigger çalışsın
                            self._gcs._alan_hazirligini_baslat(lat, lon)
                        else:
                            self._gcs._mesaj_ekle(3, "GPS fix yok — once GPS kilidini bekle.")
                    _defer(_alan_hazirla)
                elif eylem == 'drone-git':
                    def _drone_git():
                        lat = self._gcs._guncel_lat
                        lon = self._gcs._guncel_lon
                        if lat != 0.0:
                            self._gcs._js(f"map.setView([{lat},{lon}], 14);")
                        else:
                            self._gcs._mesaj_ekle(3, "GPS fix yok — drone konumu bilinmiyor.")
                    _defer(_drone_git)
                elif eylem == 'wp-guncelle':
                    # JS'den gelen waypoint listesi → Python state + tablo güncelle
                    try:
                        raw = QUrlQuery(url).queryItemValue('data')
                        import urllib.parse as _up
                        self._gcs._wp_listesi = json.loads(_up.unquote(raw))
                        QTimer.singleShot(0, self._gcs._wp_tablo_yenile)
                    except Exception:
                        pass
                elif eylem == 'wp-yukle':
                    _defer(self._gcs._wp_yukle_baslat)
                elif eylem == 'wp-oku':
                    _defer(self._gcs._wp_oku_baslat)
                elif eylem == 'wp-temizle':
                    self._gcs._wp_listesi = []
                    QTimer.singleShot(0, self._gcs._wp_tablo_yenile)
                    self._gcs._mavlink.mission_temizle()
                elif eylem == 'alan-cizildi':
                    def _alan_cizildi():
                        try:
                            q = QUrlQuery(url)
                            lat1 = float(q.queryItemValue('lat1'))
                            lon1 = float(q.queryItemValue('lon1'))
                            lat2 = float(q.queryItemValue('lat2'))
                            lon2 = float(q.queryItemValue('lon2'))
                            lat_min = min(lat1, lat2)
                            lat_max = max(lat1, lat2)
                            lon_min = min(lon1, lon2)
                            lon_max = max(lon1, lon2)
                            self._gcs._alan_hazirlik_yapildi = True
                            self._gcs._alan_thread_baslat(
                                lat_min, lat_max, lon_min, lon_max,
                                kaynak="harita cizimi"
                            )
                        except ValueError as _err:
                            self._gcs._mesaj_ekle(3, f"Alan cizimi: koordinat okunamadi ({_err}).")
                    _defer(_alan_cizildi)
                return False  # gezinme yapma
            return super().acceptNavigationRequest(url, nav_type, is_main_frame)

    class MiniHaritaSayfa(QWebEnginePage):
        """Mini-harita için minimal sayfa — hiçbir gcs:// URL'sini işlemez."""
        def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
            # Tile 404 ve diğer ağ hatalarını bastır
            if 'Failed to load' not in message and 'net::ERR' not in message:
                pass  # sessiz

        def acceptNavigationRequest(self, url, nav_type, is_main_frame):
            if url.scheme() == 'gcs':
                return False  # mini-haritadan gcs:// callback gelmez
            return super().acceptNavigationRequest(url, nav_type, is_main_frame)


# ── Arkaplan analiz thread'i ──────────────────────────────────────────────────

class _RallyYuklemeThread(QThread):
    """En iyi N rally noktasını arka planda ArduPilot'a yükler."""
    tamamlandi = Signal(bool, int)   # (basarili, nokta_sayisi)
    hata       = Signal(str)

    def __init__(self, npz_dosya: str, baglanti_dizesi: str,
                 merkez_lat: float = 0.0, merkez_lon: float = 0.0, n: int = 5):
        super().__init__()
        self.npz     = npz_dosya
        self.dize    = baglanti_dizesi
        self.m_lat   = merkez_lat
        self.m_lon   = merkez_lon
        self.n       = n

    def run(self):
        try:
            from rally_yukle import en_iyi_noktalar, rally_yukle
            noktalar = en_iyi_noktalar(
                self.npz, n=self.n,
                merkez_lat=self.m_lat if self.m_lat != 0.0 else None,
                merkez_lon=self.m_lon if self.m_lon != 0.0 else None,
            )
            basarili = rally_yukle(noktalar, baglanti_dizesi=self.dize)
            self.tamamlandi.emit(basarili, len(noktalar))
        except Exception as e:
            self.hata.emit(str(e))


class _FenceYuklemeThread(QThread):
    """alan_verisi.npz bounds'ından AC_Fence polygon arka planda yükler."""
    tamamlandi = Signal(bool)   # basarili
    hata       = Signal(str)

    def __init__(self, npz_dosya: str, baglanti_dizesi: str,
                 alt_max: float = 120.0, fence_action: int = 1):
        super().__init__()
        self.npz          = npz_dosya
        self.dize         = baglanti_dizesi
        self.alt_max      = alt_max
        self.fence_action = fence_action

    def run(self):
        try:
            from fence_yukle import fence_yukle_npz
            basarili = fence_yukle_npz(
                self.npz, self.dize,
                alt_max=self.alt_max,
                fence_action=self.fence_action,
            )
            self.tamamlandi.emit(basarili)
        except Exception as e:
            self.hata.emit(str(e))


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


class TerrainProfilThread(QThread):
    """
    WP yolu boyunca SRTM'den zemin yüksekliklerini arka planda çeker.
    Her WP segmentinde 5 nokta örnekler → mesafe ve yükseklik listesi döndürür.
    """
    tamamlandi = Signal(list, list)   # (mesafeler_m, elevasyonlar_m)

    def __init__(self, wp_listesi: list, mesafeler: list):
        super().__init__()
        self._wp = list(wp_listesi)
        self._mes = list(mesafeler)

    def run(self):
        try:
            import srtm as _srtm
            veri = _srtm.get_data()
            t_mes: list = []
            t_alt: list = []
            n = len(self._wp)
            for i in range(n):
                w0 = self._wp[i]
                w1 = self._wp[i + 1] if i + 1 < n else None
                steps = 5 if w1 else 1
                for s in range(steps):
                    f = s / steps
                    lat = w0['lat'] + (w1['lat'] - w0['lat']) * f if w1 else w0['lat']
                    lon = w0['lon'] + (w1['lon'] - w0['lon']) * f if w1 else w0['lon']
                    elev = veri.get_elevation(lat, lon)
                    if elev is None:
                        elev = 0
                    m_val = (self._mes[i] + (self._mes[i + 1] - self._mes[i]) * f
                             if w1 and i + 1 < len(self._mes) else self._mes[i])
                    t_mes.append(m_val)
                    t_alt.append(float(elev))
            self.tamamlandi.emit(t_mes, t_alt)
        except Exception:
            pass   # SRTM ağ hatası veya import hatası — sessizce geç


class AlanHazirlikThread(QThread):
    """
    GPS fix alındığında arka planda alan_verisi.npz üretir.
    ucus_alani_hazirla.py'deki fonksiyonları import ederek çalışır —
    kullanıcı CLI'a dokunmak zorunda kalmaz.
    """
    ilerleme   = Signal(str)   # mesaj log için
    tamamlandi = Signal(str)   # üretilen npz dosya yolu
    hata       = Signal(str)   # hata mesajı

    def __init__(self, lat_min: float, lat_max: float,
                 lon_min: float, lon_max: float):
        super().__init__()
        self.lat_min = lat_min
        self.lat_max = lat_max
        self.lon_min = lon_min
        self.lon_max = lon_max

    def run(self):
        try:
            import tempfile as _tmp
            from ucus_alani_hazirla import (
                dem_indir, dem_oku, egim_hesapla, guvenli_noktalari_bul, kaydet
            )

            lat_min = self.lat_min
            lat_max = self.lat_max
            lon_min = self.lon_min
            lon_max = self.lon_max

            self.ilerleme.emit(
                f"Terrain: DEM indiriliyor "
                f"({lat_min:.2f}–{lat_max:.2f}, {lon_min:.2f}–{lon_max:.2f})…"
            )
            # dem_indir bir GeoTIFF dosya yolu döndürür; geçici TIF kullan
            with _tmp.NamedTemporaryFile(suffix=".tif", delete=False) as _tf:
                tif_yolu = _tf.name
            dem_indir(lat_min, lat_max, lon_min, lon_max, cikti=tif_yolu)

            self.ilerleme.emit("Terrain: DEM okunuyor…")
            dem, transform, bounds = dem_oku(tif_yolu)

            self.ilerleme.emit("Terrain: Eğim hesaplanıyor…")
            egim = egim_hesapla(dem)

            self.ilerleme.emit("Terrain: Güvenli noktalar belirleniyor…")
            noktalar = guvenli_noktalari_bul(egim, transform)

            # kaydet() doğru NPZ formatını (noktalar_json 1-elemanlı dizi) üretir
            cikti = os.path.join(os.path.dirname(__file__), "alan_verisi.npz")
            kaydet(egim, dem, transform, bounds, noktalar, cikti=cikti)

            # Geçici TIF temizle
            try:
                os.remove(tif_yolu)
            except OSError:
                pass
            self.tamamlandi.emit(cikti)
        except Exception as exc:
            self.hata.emit(f"Terrain hazırlık hatası: {exc}")


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

        # Harita JS kuyruğu — tüm runJavaScript çağrıları buradan geçer,
        # asla sinyal/event handler içinden doğrudan çağrılmaz (re-entrancy crash önlemi)
        self._harita_bekleyen_lat: "float | None" = None
        self._harita_bekleyen_lon: "float | None" = None
        self._js_kuyruk: list = []          # bekleyen JS parçacıkları
        self._js_timer = QTimer()
        self._js_timer.setInterval(200)     # 5 Hz — harita akıcı, renderer daha rahat
        # Önce GPS buffer'ını kuyruğa ekle, sonra kuyruğu tek çağrıyla flush et
        self._js_timer.timeout.connect(self._harita_js_guncelle)
        self._js_timer.timeout.connect(self._js_temizle)
        self._js_timer.start()
        # Eski isim → yeni isim takma adı (eski referanslar bozulmasın)
        self._harita_js_timer = self._js_timer

        # Mini-harita (uçuş sekmesi) JS kuyruğu
        self._mini_js_kuyruk: list = []
        self._mini_harita_hazir = False
        self._mini_harita_tab_hazir = False
        self._mini_harita_bekleyen_lat: "float | None" = None
        self._mini_harita_bekleyen_lon: "float | None" = None
        # Mini-harita timer bağlantıları (aynı _js_timer'a ek)
        self._js_timer.timeout.connect(self._mini_harita_js_guncelle)
        self._js_timer.timeout.connect(self._mini_js_temizle)

        self._guncel_irtifa = 0.0
        self._guncel_lat = 0.0
        self._guncel_lon = 0.0
        self._ev_lat = 0.0
        self._logger = GCSLogger()
        self._ucus_kaydedici = UcusKaydedici()   # uçuş sonrası HTML rapor için
        self._son_rapor_yolu = ""               # son üretilen HTML rapor yolu
        self._log_satiri: dict = {}  # her saniye doldurulup CSV'ye yazılır
        self._log_timer = QTimer()
        self._log_timer.setInterval(1000)
        self._log_timer.timeout.connect(self._log_yaz)
        self._log_timer.timeout.connect(self._ucus_grafik_guncelle)
        self._ev_lon = 0.0
        self._bagli = False

        # Telemetri anlık değerleri (handler'larda saklanır)
        self._guncel_eve_uzaklik = 0.0
        self._guncel_ekf_hata    = 0.0
        self._guncel_gps_fix     = 0
        self._guncel_lidar_m: "float | None" = None   # DISTANCE_SENSOR; None = yok

        # LIDAR hover tarama — iniş öncesi zemin doğrulama
        self._inis_hedef:  "tuple | None" = None   # (lat, lon) mevcut iniş hedefi
        self._inis_lidar:  dict           = {}      # {'merkez': h, 'kuzey': h, 'dogu': h}
        self._inis_denedi: set            = set()   # Denenen noktalar (sonsuz döngü önlemi)

        # Rüzgar: config eşikleri + EMA filtresi
        self._ruz_tehlikeli_ms = float(_cfg.al("ruzgar.tehlikeli_ms", 11.1))
        self._ruz_kritik_ms    = float(_cfg.al("ruzgar.kritik_ms",    16.7))
        self._ruz_ema          = 0.0   # üstel hareketli ortalama (m/s)

        # Rüzgar gradient modeli (Hellmann Güç Yasası)
        self._ruz_hellmann       = float(_cfg.al("ruzgar.hellmann_alpha", 0.14))
        self._ruz_zemin_ref_m    = float(_cfg.al("ruzgar.zemin_ref_m",   2.0))
        self._ruz_trend_pencere  = int(_cfg.al("ruzgar.trend_pencere_sn", 60))
        self._ruz_zemin_ms       = 0.0   # Hellmann ile tahmin edilen zemin rüzgarı (m/s)
        self._ruz_trend_ms_per_s = 0.0   # Trend: m/s/saniye (+ artıyor, - azalıyor)
        from collections import deque as _deque
        self._ruz_gecmis: _deque = _deque(maxlen=self._ruz_trend_pencere)  # (t, hiz_ms) çiftleri

        # Sürekli gust takibi
        # Ham hız EMA'nın belirgin üstünde kaldığı süreyi ölçer.
        # 1 sn → drone absorbe eder; 3+ sn → motor zorlanması / batarya riski
        self._gust_esik_ms    = float(_cfg.al("ruzgar.gust_esik_ms",   3.0))  # EMA üstü fark
        self._gust_min_sure_s = float(_cfg.al("ruzgar.gust_min_sure_s", 3.0)) # alarm süresi
        self._gust_baslangic_t: "float | None" = None   # gust başlangıç zamanı
        self._gust_alarm_verildi = False

        # Rüzgar kalitesi filtreleri — Cube Orange EKF gürültüsünü engeller
        self._ekf_ruzgar_gecerli  = False   # EKF_STATUS_REPORT bayrak 0+1 (tutum+yatay hız)
        self._ekf_bayraklar       = 0       # Son gelen EKF bayrakları (tam)
        self._guncel_vibrasyon_mss = 0.0   # VIBRATION RMS m/s² (Cube Orange normal < 15)
        self._guncel_vib_klip     = 0      # IMU saturation sayacı (> 0 = çok yüksek)
        self._ruz_min_gecerli_ms  = float(_cfg.al("ruzgar.min_gecerli_ms", 2.0))
        # EK3_WIND_P_NSE uyarı takibi
        self._ek3_yuksek_vib_sayac   = 0   # Arka arkaya yüksek vibrasyon sayısı
        self._ek3_uyari_verildi      = False  # Bir oturumda bir kez uyar
        # 2 m/s altı tamamen EKF gürültü tabanı — Hellmann ve gust işleme

        # RTL izleyici
        self._rtl_izleyici = RtlIzleyici(tetiklendi_cb=self._rtl_fallback_tetiklendi)
        self._son_mod_id   = -1
        self._ruzgar_acil_inis_bekliyor = False

        # Parametre cache (yedekleme için)
        self._param_cache: dict = {}
        self._param_ui_hazir = False

        # ADSB — yakın hava araçları
        self._adsb_araclar: dict = {}          # {icao: {lat,lon,alt,hdg,callsign,t}}
        self._adsb_uyari_esik_m  = float(_cfg.al("adsb.uyari_mesafe_m", 500.0))
        self._adsb_son_uyari: dict = {}        # {icao: last_warn_time} debounce

        # ESC telemetri — motor kartı etiketleri (_esc_paneli() tarafından doldurulur)
        self._esc_lbls: list = []   # [{"rpm": QLabel, "sicaklik": QLabel}, ...]

        # Terrain raporu
        self._terrain_yukseklik_lbl: "QLabel | None" = None

        # Alan iniş kararı — alan_verisi.npz varsa yükle
        self._alan_karar = None
        self._alan_karar_son_uyari = 0.0   # uyarı debounce (5 sn)
        self._alan_karar_son_sorgu = 0.0   # hesaplama debounce (5 sn)
        self._alan_hazirlik_thread: "AlanHazirlikThread | None" = None
        self._terrain_thread = None   # _harita_sekme()'de de set edilir; burada erken init
        self._rally_thread = None
        self._fence_thread = None
        self._alan_hazirlik_yapildi = False   # ilk GPS fix'te bir kez tetikle
        self._wp_listesi: list = []            # waypoint görev listesi [{lat,lon,alt}, ...]
        self._alan_bounds: "tuple | None" = None  # (lat_min, lat_max, lon_min, lon_max)
        _npz = os.path.join(os.path.dirname(__file__), "alan_verisi.npz")
        if not os.path.isfile(_npz):
            _npz = "alan_verisi.npz"       # çalışma dizininde ara
        if os.path.isfile(_npz):
            try:
                import numpy as _np_init
                _data = _np_init.load(_npz)
                if "bounds" in _data:
                    _b = _data["bounds"]   # [lon_min, lat_min, lon_max, lat_max]
                    self._alan_bounds = (float(_b[1]), float(_b[3]),
                                         float(_b[0]), float(_b[2]))
                from alan_inis_karar import AlanInisKarar
                self._alan_karar = AlanInisKarar(_npz)
                self._mesaj_ekle(6, f"Alan veri dosyası yüklendi: {os.path.basename(_npz)}")
            except Exception as _e:
                self._mesaj_ekle(3, f"Alan verisi yüklenemedi: {_e}")

        self._durum_guncelle("Bağlantı bekleniyor…", "#ffc107")

        # ── TTS sesli uyarı ────────────────────────────────────────────────────
        self._tts_aktif = False
        try:
            import pyttsx3 as _pyttsx3
            import threading as _threading
            self._tts_motor = _pyttsx3.init()
            self._tts_motor.setProperty('rate', 155)
            self._tts_aktif = True
        except Exception:
            self._tts_motor = None
        self._son_bat_uyari = 0   # batarya uyarı debounce (mod ID)

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
        m.lidar_guncellendi.connect(self._lidar_guncelle)
        m.imu_sicakligi.connect(self._imu_guncelle)
        m.durum_mesaji.connect(self._mesaj_ekle)
        m.ekf_durumu.connect(self._ekf_guncelle)
        m.vibrasyon_guncellendi.connect(self._vibrasyon_guncelle)
        m.parametre_guncellendi.connect(self._param_guncelle)
        m.parametre_tamamlandi.connect(self._param_tamam)
        m.adsb_guncellendi.connect(self._adsb_guncelle)
        m.esc_guncellendi.connect(self._esc_guncelle)
        m.terrain_rapor.connect(self._terrain_rapor_guncelle)
        m.mission_yuklendi.connect(self._wp_mission_yuklendi)
        m.mission_alindi.connect(self._wp_mission_alindi)

    # ── UI ───────────────────────────────────────────────────────────────────

    def _ui_olustur(self):
        merkez = QWidget()
        self.setCentralWidget(merkez)
        ana = QVBoxLayout(merkez)
        ana.setSpacing(4)
        ana.setContentsMargins(6, 6, 6, 6)

        ana.addWidget(self._baglanti_cubugu())

        # Bağlantı kopma uyarı bandı
        self._uyari_bant = QLabel("BAĞLANTI KESİLDİ")
        self._uyari_bant.setAlignment(Qt.AlignCenter)
        self._uyari_bant.setStyleSheet(UYARI_STILI)
        self._uyari_bant.setFont(QFont("Arial", 11, QFont.Bold))
        self._uyari_bant.hide()
        ana.addWidget(self._uyari_bant)

        # Sekmeler
        self._sekmeler = QTabWidget()
        self._sekmeler.addTab(self._ana_sekme(), "Uçuş")
        self._param_tab_hazir = False
        self._param_stack = QStackedWidget()
        _pk = QLabel("Parametreler yükleniyor…")
        _pk.setAlignment(Qt.AlignCenter)
        self._param_stack.addWidget(_pk)          # index 0 = placeholder
        self._param_tab_index = self._sekmeler.addTab(self._param_stack, "Parametreler")
        if HARITA_MEVCUT:
            # QWebEngineView pencere gösterilmeden (show()) oluşturulursa
            # Chromium renderer geçerli HWND bulamaz ve çöker.
            # QStackedWidget placeholder koyuyoruz; showEvent'te WebEngine başlatılır.
            self._harita_tab_hazir = False
            self._harita_stack = QStackedWidget()
            _yk = QLabel("Harita yükleniyor…")
            _yk.setAlignment(Qt.AlignCenter)
            self._harita_stack.addWidget(_yk)          # index 0 = placeholder
            self._harita_tab_index = self._sekmeler.addTab(self._harita_stack, "Harita")
        else:
            eksik = QLabel("Harita için: pip install PyQtWebEngine")
            eksik.setAlignment(Qt.AlignCenter)
            self._harita_tab_hazir = True
            self._harita_tab_index = self._sekmeler.addTab(eksik, "Harita")
        self._sekmeler.currentChanged.connect(self._sekme_degisti)
        ana.addWidget(self._sekmeler)

        self._durum_bar = QStatusBar()
        self.setStatusBar(self._durum_bar)

    # ── Bağlantı çubuğu ──────────────────────────────────────────────────────

    def _baglanti_cubugu(self) -> QWidget:
        _BADGE = (
            "border-radius:3px; padding:2px 8px; font-size:10px;"
        )
        bar = QWidget()
        bar.setFixedHeight(46)
        bar.setStyleSheet(
            "QWidget#baglantiBar { background:#0a1520; border-bottom:1px solid #1a3a5a; }"
            "QLabel { background:transparent; }"
        )
        bar.setObjectName("baglantiBar")
        duz = QHBoxLayout(bar)
        duz.setContentsMargins(10, 6, 10, 6)
        duz.setSpacing(7)

        # ── Status LED ────────────────────────────────────────────────────────
        self._durum_led = QLabel("●")
        self._durum_led.setFont(QFont("Arial", 18))
        self._durum_led.setStyleSheet("color:#f44336; padding:0 2px;")
        self._durum_led.setFixedWidth(26)
        self._durum_led.setToolTip("Bağlantı durumu")
        duz.addWidget(self._durum_led)

        # ── Bağlantı dizesi ───────────────────────────────────────────────────
        self._baglanti_giris = QLineEdit(_cfg.al("baglanti.varsayilan_dize", "tcp:127.0.0.1:5762"))
        self._baglanti_giris.setFixedWidth(195)
        self._baglanti_giris.setFixedHeight(30)
        self._baglanti_giris.setToolTip("tcp:host:port | udp:host:port | /dev/ttyUSB0,115200")
        self._baglanti_giris.setStyleSheet(
            "QLineEdit { background:#0d1b2a; color:#7eb8e0; "
            "border:1px solid #1a4060; border-radius:4px; "
            "padding:2px 8px; font-family:'Courier New'; font-size:12px; }"
            "QLineEdit:focus { border-color:#2a6090; }"
        )
        duz.addWidget(self._baglanti_giris)

        # ── Bağlan butonu ─────────────────────────────────────────────────────
        self._baglan_btn = QPushButton("BAĞLAN")
        self._baglan_btn.setFixedSize(100, 30)
        self._baglan_btn.setStyleSheet(
            "QPushButton { background:#1b5e20; color:#a5d6a7; "
            "border:1px solid #2e7d32; border-radius:4px; "
            "font-weight:bold; font-size:11px; }"
            "QPushButton:hover { background:#2e7d32; }"
            "QPushButton:pressed { background:#145214; }"
        )
        self._baglan_btn.clicked.connect(self._baglan_tikla)
        duz.addWidget(self._baglan_btn)

        # ── Kes butonu ────────────────────────────────────────────────────────
        self._kes_btn = QPushButton("KES")
        self._kes_btn.setFixedSize(72, 30)
        self._kes_btn.setStyleSheet(
            "QPushButton { background:#1a1a1a; color:#555; "
            "border:1px solid #2a2a2a; border-radius:4px; font-size:11px; }"
            "QPushButton:enabled { color:#ef9a9a; border-color:#5a2a2a; "
            "background:#2a1a1a; }"
            "QPushButton:enabled:hover { background:#3a2020; }"
        )
        self._kes_btn.clicked.connect(self._kes_tikla)
        self._kes_btn.setEnabled(False)
        duz.addWidget(self._kes_btn)

        # ── Rapor ─────────────────────────────────────────────────────────────
        self._rapor_btn = QPushButton("Rapor")
        self._rapor_btn.setFixedSize(52, 30)
        self._rapor_btn.setToolTip("Son uçuş için HTML rapor oluştur ve tarayıcıda aç")
        self._rapor_btn.setStyleSheet(
            "QPushButton { background:#1a2a3a; color:#7eb8e0; border:1px solid #2a4060; "
            "border-radius:4px; font-size:11px; }"
            "QPushButton:hover { background:#2a3a5a; }"
        )
        self._rapor_btn.clicked.connect(self._rapor_tikla)
        duz.addWidget(self._rapor_btn)

        # ── Ayraç ─────────────────────────────────────────────────────────────
        _sep = QLabel("│")
        _sep.setStyleSheet("color:#1a4060; font-size:20px; padding:0 4px;")
        duz.addWidget(_sep)

        duz.addStretch()

        # ── MOD rozeti ────────────────────────────────────────────────────────
        self._mod_lbl = QLabel("MOD: —")
        self._mod_lbl.setFont(QFont("Arial", 10, QFont.Bold))
        self._mod_lbl.setStyleSheet(
            f"color:#7eb8e0; background:#0d1b2a; border:1px solid #1a4060; {_BADGE}"
        )
        duz.addWidget(self._mod_lbl)

        # ── ARM rozeti ────────────────────────────────────────────────────────
        self._arm_lbl = QLabel("DISARM")
        self._arm_lbl.setFont(QFont("Arial", 10, QFont.Bold))
        self._arm_lbl.setStyleSheet(
            f"color:#666; background:#111; border:1px solid #2a2a2a; {_BADGE}"
        )
        duz.addWidget(self._arm_lbl)

        # ── EKF rozeti ────────────────────────────────────────────────────────
        self._ekf_lbl = QLabel("EKF: —")
        self._ekf_lbl.setStyleSheet(
            f"color:#666; background:#111; border:1px solid #2a2a2a; {_BADGE}"
        )
        duz.addWidget(self._ekf_lbl)

        return bar

    # ── Uçuş sekmesi ─────────────────────────────────────────────────────────

    def _ana_sekme(self) -> QWidget:
        """Mission Planner tarzı 2-kolonlu uçuş sekmesi.

        Sol kolon  (%55): HUD (esnek yükseklik) + kompakt durum çubuğu + alt sekmeler
        Sağ kolon  (%45): Mini-harita — TAM yükseklikte, tüm zone'larla rekabet etmez
        """
        w = QWidget()
        main_row = QHBoxLayout(w)
        main_row.setSpacing(3)
        main_row.setContentsMargins(4, 4, 4, 4)

        # ── Sol kolon ─────────────────────────────────────────────────────────
        sol_w = QWidget()
        sol = QVBoxLayout(sol_w)
        sol.setSpacing(3)
        sol.setContentsMargins(0, 0, 0, 0)

        # HUD — ekranın çoğunu kullanır, stretch=1 ile esnek büyür
        hud_grp = QGroupBox("Yapay Ufuk")
        hud_grp.setMinimumHeight(260)
        hud_lay = QVBoxLayout(hud_grp)
        hud_lay.setContentsMargins(4, 4, 4, 4)
        self._yapay_ufuk = YapayUfukWidget()
        hud_lay.addWidget(self._yapay_ufuk)
        sol.addWidget(hud_grp, 1)

        # Kompakt durum çubuğu — tek satır, max 32px
        sol.addWidget(self._durum_serit_kompakt())

        # Alt sekmeler — Kontrol / Değerler / IMU-ESC / Grafik / Mesaj
        sol.addWidget(self._alt_sekmeler())

        main_row.addWidget(sol_w, 55)

        # ── Sağ kolon: Mini-harita tam yükseklikte ────────────────────────────
        self._mini_harita_stack = QStackedWidget()
        _ph = QLabel("Mini harita yükleniyor…")
        _ph.setAlignment(Qt.AlignCenter)
        _ph.setStyleSheet("color:#7eb8e0; background:#0d1b2a; font-size:12px;")
        self._mini_harita_stack.addWidget(_ph)      # index 0 = placeholder
        main_row.addWidget(self._mini_harita_stack, 45)

        # Mini-harita lazy-load — pencere gösterildikten 150ms sonra
        QTimer.singleShot(150, self._mini_harita_yukle)

        return w

    def _durum_serit_kompakt(self) -> QWidget:
        """Tek satır durum çubuğu: Batarya | GPS | Rüzgar — max 32px.

        Tüm self._xxx attr isimleri korunur — güncelleme metodları bozulmaz.
        """
        w = QWidget()
        w.setMaximumHeight(32)
        w.setMinimumHeight(28)
        w.setStyleSheet("background:#0d1b2a; border-top:1px solid #1a2a3a;")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(8, 2, 8, 2)
        lay.setSpacing(8)

        # Batarya
        self._batarya_bar = BataryaBar()
        self._batarya_bar.setFixedSize(34, 14)
        lay.addWidget(self._batarya_bar)
        self._batarya_detay = QLabel("—V  —A  —%")
        self._batarya_detay.setStyleSheet("color:#ffb74d; font-size:11px;")
        lay.addWidget(self._batarya_detay)

        _s1 = QLabel("|"); _s1.setStyleSheet("color:#2a4060; font-size:11px;")
        lay.addWidget(_s1)

        # GPS
        self._gps_fix_lbl   = QLabel("Fix: —")
        self._gps_uydu_lbl  = QLabel("Uydu: —")
        self._gps_konum_lbl = QLabel("—, —")
        for _l in (self._gps_fix_lbl, self._gps_uydu_lbl, self._gps_konum_lbl):
            _l.setStyleSheet("color:#7eb8e0; font-size:11px;")
            lay.addWidget(_l)

        _s2 = QLabel("|"); _s2.setStyleSheet("color:#2a4060; font-size:11px;")
        lay.addWidget(_s2)

        # Rüzgar
        self._ruzgar           = None
        self._ruz_seviye_lbl   = QLabel("—")
        self._ruz_hiz_lbl      = QLabel("— km/h")
        self._ruz_yon_lbl      = QLabel("—°")
        self._ruzgar_zemin_lbl = QLabel("Zemin: —")
        for _l in (self._ruz_seviye_lbl, self._ruz_hiz_lbl,
                   self._ruz_yon_lbl, self._ruzgar_zemin_lbl):
            _l.setStyleSheet("color:#80cbc4; font-size:11px;")
            lay.addWidget(_l)

        lay.addStretch()
        return w

    def _alt_sekmeler(self) -> QTabWidget:
        """Alt sekmeli panel: Kontrol / Değerler / IMU-ESC / Grafik / Mesaj."""
        tabs = QTabWidget()
        tabs.setMinimumHeight(130)
        tabs.setMaximumHeight(215)
        tabs.setStyleSheet(
            "QTabWidget::pane { border:1px solid #1a2a3a; background:#0d1b2a; }"
            "QTabBar::tab { background:#0a1520; color:#7eb8e0; padding:4px 11px;"
            "  font-size:11px; border:1px solid #1a2a3a; border-bottom:none;"
            "  margin-right:1px; }"
            "QTabBar::tab:selected { background:#0d1b2a; color:#58a6ff;"
            "  border-bottom:2px solid #58a6ff; }"
            "QTabBar::tab:hover { background:#1a2a3a; }"
        )
        tabs.addTab(self._kontrol_serit(),      "Kontrol")
        tabs.addTab(self._tile_serit(),          "Degerler")
        tabs.addTab(self._imu_esc_sekme(),       "IMU/ESC")
        tabs.addTab(self._ucus_grafik_widget(),  "Grafik")
        tabs.addTab(self._mesaj_logu_paneli(),   "Mesaj")
        return tabs

    def _ucus_grafik_widget(self) -> QWidget:
        """pyqtgraph uçuş grafik widget'ini oluşturur ve self attrs'ı ayarlar."""
        try:
            import pyqtgraph as pg
            pg.setConfigOptions(antialias=True, background='#111827', foreground='#7eb8e0')
            self._ucus_grafik = pg.PlotWidget()
            self._ucus_grafik.showGrid(x=True, y=True, alpha=0.2)
            self._ucus_grafik.addLegend(offset=(10, 10))
            self._ucus_grafik.getPlotItem().getAxis('left').setTextPen('#7eb8e0')
            self._ucus_grafik.getPlotItem().getAxis('bottom').setTextPen('#7eb8e0')
            self._ucus_irtifa_cizgi = self._ucus_grafik.plot(
                name="Irtifa(m)", pen=pg.mkPen('#4fc3f7', width=2))
            self._ucus_hiz_cizgi = self._ucus_grafik.plot(
                name="Hiz(m/s)", pen=pg.mkPen('#81c784', width=2))
            self._ucus_bat_cizgi = self._ucus_grafik.plot(
                name="Bat(%)", pen=pg.mkPen('#ffb74d', width=2))
            # Veri buffer'ları — son 5 dk (300 örnek @ 1Hz)
            self._grafik_t:       deque = deque(maxlen=300)
            self._grafik_irtifa:  deque = deque(maxlen=300)
            self._grafik_hiz:     deque = deque(maxlen=300)
            self._grafik_batarya: deque = deque(maxlen=300)
            self._grafik_t0 = time.monotonic()
            return self._ucus_grafik
        except Exception:
            self._ucus_grafik = None
            _lbl = QLabel("pyqtgraph yuklenemedi")
            _lbl.setAlignment(Qt.AlignCenter)
            _lbl.setStyleSheet("color:#666; font-size:11px;")
            return _lbl

    def _ucus_grafik_guncelle(self):
        """VFR/batarya verisi gelince uçuş grafiğine nokta ekler (1 Hz'de çağrılır)."""
        if not hasattr(self, '_ucus_grafik') or self._ucus_grafik is None:
            return
        t_sn = time.monotonic() - self._grafik_t0
        self._grafik_t.append(t_sn)
        self._grafik_irtifa.append(self._guncel_irtifa)
        self._grafik_hiz.append(self._log_satiri.get("hiz", 0.0))
        self._grafik_batarya.append(float(self._guncel_batarya_yuzde))
        ts = list(self._grafik_t)
        self._ucus_irtifa_cizgi.setData(ts, list(self._grafik_irtifa))
        self._ucus_hiz_cizgi.setData(ts, list(self._grafik_hiz))
        self._ucus_bat_cizgi.setData(ts, list(self._grafik_batarya))

    def _yapay_ufuk_paneli(self) -> QGroupBox:
        grp = QGroupBox("Yapay Ufuk")
        grp.setMinimumHeight(220)
        duz = QVBoxLayout(grp)
        duz.setContentsMargins(4, 4, 4, 4)
        self._yapay_ufuk = YapayUfukWidget()
        duz.addWidget(self._yapay_ufuk)
        return grp

    def _tile_paneli(self) -> QWidget:
        """ArduPilot / Mission Planner tarzı büyük renkli telemetri sayı kutucukları."""
        w = QWidget()
        w.setStyleSheet("background:#0d1117;")
        grid = QGridLayout(w)
        grid.setSpacing(2)
        grid.setContentsMargins(2, 2, 2, 2)

        # (başlık, birim, renk, instance_attr)
        _TILES = [
            ("İrtifa",     "m",   "#4dd0e1", "_irtifa_lbl"),
            ("Bat Volt",   "V",   "#ffb74d", "_bat_volt_tile_lbl"),
            ("Pitch",      "°",   "#f48fb1", "_pitch_lbl"),
            ("Yaw",        "°",   "#80deea", "_yaw_lbl"),
            ("Dikey Hız",  "m/s", "#fff176", "_dikey_lbl"),
            ("Roll",       "°",   "#80cbc4", "_roll_lbl"),
            ("Hız",        "m/s", "#a5d6a7", "_hiz_lbl"),
            ("Mesafe",     "m",   "#ce93d8", "_uzaklik_lbl"),
        ]

        for i, (ad, birim, renk, attr) in enumerate(_TILES):
            r, c = divmod(i, 2)
            tile = QWidget()
            tile.setStyleSheet(
                "QWidget { background:#111827; border:1px solid #1a2535; border-radius:3px; }"
            )
            tlay = QVBoxLayout(tile)
            tlay.setContentsMargins(7, 4, 7, 4)
            tlay.setSpacing(0)

            ad_lbl = QLabel(f"{ad}  ({birim})")
            ad_lbl.setStyleSheet(
                "color:#3a5060; font-size:10px; background:transparent; border:none;"
            )

            val_lbl = QLabel("—")
            val_lbl.setStyleSheet(
                f"color:{renk}; font-size:34px; font-weight:bold; "
                "background:transparent; border:none; letter-spacing:-1px;"
            )
            val_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

            tlay.addWidget(ad_lbl)
            tlay.addWidget(val_lbl)
            grid.addWidget(tile, r, c)
            setattr(self, attr, val_lbl)

        return w

    def _imu_paneli(self) -> QGroupBox:
        grp = QGroupBox("IMU Sıcaklıkları")
        duz = QVBoxLayout(grp)
        self._imu_gosterge = []
        for i in range(3):
            g = SicaklikGostergesi(i)
            self._imu_gosterge.append(g)
            duz.addWidget(g)
        return grp

    def _esc_paneli(self) -> QGroupBox:
        grp = QGroupBox("ESC / Motor")
        grid = QGridLayout(grp)
        grid.setHorizontalSpacing(8)
        baslik_renk = "color:#7eb8e0;"
        for col, baslik in enumerate(["Motor", "RPM", "Sıcak.", "Volt"]):
            lbl = QLabel(baslik)
            lbl.setStyleSheet(baslik_renk)
            lbl.setAlignment(Qt.AlignCenter)
            grid.addWidget(lbl, 0, col)
        self._esc_lbls = []
        for i in range(4):
            row = i + 1
            grid.addWidget(QLabel(f"M{i+1}"), row, 0)
            rpm_l = QLabel("—")
            tmp_l = QLabel("—")
            vlt_l = QLabel("—")
            for l in (rpm_l, tmp_l, vlt_l):
                l.setAlignment(Qt.AlignCenter)
                l.setFont(QFont("Courier New", 9))
            grid.addWidget(rpm_l, row, 1)
            grid.addWidget(tmp_l, row, 2)
            grid.addWidget(vlt_l, row, 3)
            self._esc_lbls.append({"rpm": rpm_l, "sicaklik": tmp_l, "volt": vlt_l})
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

        # GPS
        gps = QGroupBox("GPS Durumu")
        gd  = QHBoxLayout(gps)
        self._gps_fix_lbl   = QLabel("Fix: --")
        self._gps_uydu_lbl  = QLabel("Uydu: --")
        self._gps_konum_lbl = QLabel("Konum: --")
        for lb in (self._gps_fix_lbl, self._gps_uydu_lbl, self._gps_konum_lbl):
            gd.addWidget(lb)
        duz.addWidget(gps)

        # Rüzgar — yeniden tasarım
        ruz = QGroupBox("Rüzgar")
        rd  = QVBoxLayout(ruz)
        rd.setSpacing(4)
        rd.setContentsMargins(8, 6, 8, 6)

        # Üst satır: durum rozeti + hız sayısı
        _r_ust = QHBoxLayout()
        _r_ust.setSpacing(4)
        self._ruz_seviye_lbl = QLabel("● —")
        self._ruz_seviye_lbl.setStyleSheet("color:#555; font-weight:bold; font-size:12px;")
        _r_ust.addWidget(self._ruz_seviye_lbl)
        _r_ust.addStretch()
        self._ruz_hiz_lbl = QLabel("—  m/s")
        self._ruz_hiz_lbl.setStyleSheet("color:#7eb8e0; font-size:16px; font-weight:bold;")
        self._ruz_hiz_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        _r_ust.addWidget(self._ruz_hiz_lbl)
        rd.addLayout(_r_ust)

        # İnce yatay çizgi
        _ayrac = QLabel()
        _ayrac.setFixedHeight(1)
        _ayrac.setStyleSheet("background:#1a3a5a; margin:1px 0;")
        rd.addWidget(_ayrac)

        # Alt satır: yön + zemin
        _r_alt = QHBoxLayout()
        _r_alt.setSpacing(4)
        self._ruz_yon_lbl = QLabel("Yön: —°")
        self._ruz_yon_lbl.setStyleSheet("color:#888; font-size:11px;")
        _r_alt.addWidget(self._ruz_yon_lbl)
        _r_alt.addStretch()
        self._ruzgar_zemin_lbl = QLabel("Zemin: — km/h")
        self._ruzgar_zemin_lbl.setStyleSheet("color:#7eb8e0; font-size:11px;")
        self._ruzgar_zemin_lbl.setAlignment(Qt.AlignRight)
        _r_alt.addWidget(self._ruzgar_zemin_lbl)
        rd.addLayout(_r_alt)

        duz.addWidget(ruz)
        self._ruzgar = None   # canvas widget artık kullanılmıyor

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

        # Terrain raporu satırı
        terrain_grp = QGroupBox("Terrain / ADSB")
        tg = QVBoxLayout(terrain_grp)
        self._terrain_yukseklik_lbl = QLabel("Arazi: —")
        self._terrain_yukseklik_lbl.setFont(QFont("Courier New", 9))
        self._adsb_sayac_lbl = QLabel("ADSB: 0 araç")
        self._adsb_sayac_lbl.setFont(QFont("Courier New", 9))
        tg.addWidget(self._terrain_yukseklik_lbl)
        tg.addWidget(self._adsb_sayac_lbl)
        duz.addWidget(terrain_grp)

        duz.addStretch()
        return duz

    # ── Mission Planner tarzı layout için yardımcı metodlar ─────────────────

    def _batarya_gps_ruzgar_serit(self) -> QWidget:
        """Zone 2 — batarya/GPS/rüzgar tek yatay şerit (max 64px)."""
        w = QWidget()
        w.setMaximumHeight(68)
        lay = QHBoxLayout(w)
        lay.setSpacing(4)
        lay.setContentsMargins(2, 2, 2, 2)

        # Batarya
        bat_grp = QGroupBox("Batarya")
        bat_lay = QVBoxLayout(bat_grp)
        bat_lay.setContentsMargins(6, 4, 6, 4)
        bat_lay.setSpacing(2)
        self._batarya_bar = BataryaBar()
        self._batarya_bar.setMinimumHeight(14)
        self._batarya_detay = QLabel("--V  --A  Tahmini süre: --")
        self._batarya_detay.setAlignment(Qt.AlignCenter)
        self._batarya_detay.setStyleSheet("font-size:10px;")
        bat_lay.addWidget(self._batarya_bar)
        bat_lay.addWidget(self._batarya_detay)
        lay.addWidget(bat_grp, 3)

        # GPS
        gps_grp = QGroupBox("GPS")
        gps_lay = QHBoxLayout(gps_grp)
        gps_lay.setContentsMargins(6, 4, 6, 4)
        gps_lay.setSpacing(8)
        self._gps_fix_lbl   = QLabel("Fix: --")
        self._gps_uydu_lbl  = QLabel("Uydu: --")
        self._gps_konum_lbl = QLabel("Konum: --")
        self._gps_konum_lbl.setStyleSheet("font-size:10px;")
        for lb in (self._gps_fix_lbl, self._gps_uydu_lbl, self._gps_konum_lbl):
            gps_lay.addWidget(lb)
        lay.addWidget(gps_grp, 3)

        # Rüzgar
        ruz_grp = QGroupBox("Rüzgar")
        ruz_lay = QHBoxLayout(ruz_grp)
        ruz_lay.setContentsMargins(6, 4, 6, 4)
        ruz_lay.setSpacing(6)
        self._ruz_seviye_lbl = QLabel("● —")
        self._ruz_seviye_lbl.setStyleSheet("color:#555; font-weight:bold; font-size:12px;")
        self._ruz_hiz_lbl = QLabel("—  m/s")
        self._ruz_hiz_lbl.setStyleSheet("color:#7eb8e0; font-size:14px; font-weight:bold;")
        self._ruz_yon_lbl = QLabel("Yön: —°")
        self._ruz_yon_lbl.setStyleSheet("color:#888; font-size:10px;")
        self._ruzgar_zemin_lbl = QLabel("Zemin: — km/h")
        self._ruzgar_zemin_lbl.setStyleSheet("color:#7eb8e0; font-size:10px;")
        self._ruzgar = None   # canvas widget artık kullanılmıyor
        for lb in (self._ruz_seviye_lbl, self._ruz_hiz_lbl, self._ruz_yon_lbl, self._ruzgar_zemin_lbl):
            ruz_lay.addWidget(lb)
        lay.addWidget(ruz_grp, 2)

        return w

    def _kontrol_serit(self) -> QWidget:
        """Zone 3 — acil + mod + diğer butonlar tek yatay şerit (max 66px)."""
        w = QWidget()
        w.setMaximumHeight(70)
        lay = QHBoxLayout(w)
        lay.setSpacing(4)
        lay.setContentsMargins(2, 2, 2, 2)

        # Acil komutlar
        acil_grp = QGroupBox("Acil")
        acil_lay = QHBoxLayout(acil_grp)
        acil_lay.setContentsMargins(4, 4, 4, 4)
        acil_lay.setSpacing(3)
        for (ad, slot, kirmizi) in [
            ("EV'E DÖN (RTL)", self._rtl_tikla,      True),
            ("ACİL İNİŞ",      self._inis_tikla,      True),
            ("HOVERING",       self._hovering_tikla,  False),
            ("DEVAM ET",       self._devam_tikla,     False),
        ]:
            b = QPushButton(ad)
            b.setMaximumHeight(32)
            if kirmizi:
                b.setStyleSheet(ACİL_STILI)
            b.clicked.connect(slot)
            acil_lay.addWidget(b)
        lay.addWidget(acil_grp, 4)

        # Mod seçici
        mod_grp = QGroupBox("Mod")
        mod_lay = QHBoxLayout(mod_grp)
        mod_lay.setContentsMargins(4, 4, 4, 4)
        mod_lay.setSpacing(3)
        for (ad, mid) in [("SABİTLEME", 0), ("LOITER", 5), ("OTOMATİK", 3), ("KILAVUZ", 4)]:
            b = QPushButton(ad)
            b.setMaximumHeight(32)
            b.clicked.connect(lambda _, m=mid: self._mod_tikla(m))
            mod_lay.addWidget(b)
        lay.addWidget(mod_grp, 4)

        # Diğer (Ev + Terrain/ADSB)
        diger_grp = QGroupBox("Diğer")
        diger_lay = QHBoxLayout(diger_grp)
        diger_lay.setContentsMargins(4, 4, 4, 4)
        diger_lay.setSpacing(6)
        ev_btn = QPushButton("Ev Yap")
        ev_btn.setMaximumHeight(32)
        ev_btn.clicked.connect(self._ev_yap_tikla)
        diger_lay.addWidget(ev_btn)
        self._terrain_yukseklik_lbl = QLabel("Arazi: —")
        self._terrain_yukseklik_lbl.setFont(QFont("Courier New", 9))
        self._adsb_sayac_lbl = QLabel("ADSB: 0")
        self._adsb_sayac_lbl.setFont(QFont("Courier New", 9))
        diger_lay.addWidget(self._terrain_yukseklik_lbl)
        diger_lay.addWidget(self._adsb_sayac_lbl)
        lay.addWidget(diger_grp, 2)

        return w

    def _tile_serit(self) -> QWidget:
        """Zone 4 — 8 telemetri tile'ı tek yatay satır (max 84px)."""
        w = QWidget()
        w.setStyleSheet("background:#0d1117;")
        w.setMaximumHeight(84)
        lay = QHBoxLayout(w)
        lay.setSpacing(2)
        lay.setContentsMargins(2, 2, 2, 2)

        _TILES = [
            ("İrtifa",    "m",   "#4dd0e1", "_irtifa_lbl"),
            ("Hız",       "m/s", "#a5d6a7", "_hiz_lbl"),
            ("Dikey Hız", "m/s", "#fff176", "_dikey_lbl"),
            ("Mesafe",    "m",   "#ce93d8", "_uzaklik_lbl"),
            ("Roll",      "°",   "#80cbc4", "_roll_lbl"),
            ("Pitch",     "°",   "#f48fb1", "_pitch_lbl"),
            ("Yaw",       "°",   "#80deea", "_yaw_lbl"),
            ("Bat Volt",  "V",   "#ffb74d", "_bat_volt_tile_lbl"),
        ]

        for (ad, birim, renk, attr) in _TILES:
            tile = QWidget()
            tile.setStyleSheet(
                "QWidget { background:#111827; border:1px solid #1a2535; border-radius:3px; }"
            )
            tlay = QVBoxLayout(tile)
            tlay.setContentsMargins(5, 3, 5, 3)
            tlay.setSpacing(0)
            ad_lbl = QLabel(f"{ad}\n({birim})")
            ad_lbl.setStyleSheet("color:#3a5060; font-size:9px; background:transparent; border:none;")
            ad_lbl.setAlignment(Qt.AlignCenter)
            val_lbl = QLabel("—")
            val_lbl.setStyleSheet(
                f"color:{renk}; font-size:22px; font-weight:bold; "
                "background:transparent; border:none; letter-spacing:-1px;"
            )
            val_lbl.setAlignment(Qt.AlignCenter)
            tlay.addWidget(ad_lbl)
            tlay.addWidget(val_lbl)
            lay.addWidget(tile, 1)
            setattr(self, attr, val_lbl)

        return w

    def _imu_esc_sekme(self) -> "QTabWidget":
        """Zone 5 — IMU ve ESC panellerini daraltılmış QTabWidget içinde göster."""
        from PyQt5.QtWidgets import QTabWidget as _QTW
        tabs = _QTW()
        tabs.setMaximumHeight(130)
        tabs.setMinimumHeight(80)
        tabs.addTab(self._imu_paneli(), "IMU Sıcaklıkları")
        tabs.addTab(self._esc_paneli(), "ESC / Motor")
        return tabs

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

        self._param_yedekle_btn = QPushButton("💾 Yedekle")
        self._param_yedekle_btn.setToolTip("İndirilen parametreleri JSON dosyasına kaydet")
        self._param_yedekle_btn.clicked.connect(self._param_yedekle_tikla)
        araci.addWidget(self._param_yedekle_btn)

        self._param_geri_yukle_btn = QPushButton("📂 Geri Yükle")
        self._param_geri_yukle_btn.setToolTip("JSON yedekten parametreleri drone'a gönder")
        self._param_geri_yukle_btn.clicked.connect(self._param_geri_yukle_tikla)
        araci.addWidget(self._param_geri_yukle_btn)

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

        self._param_satir_index: dict[str, int] = {}
        self._degistirilen_parametreler: dict[str, float] = {}
        self._param_ui_hazir = True
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
        self._harita_hazir = False
        def _harita_yuklendi(ok):
            self._harita_hazir = True
            self._harita_terrain_sinir_goster()   # startup'ta NPZ varsa mavi kutu çiz
        self._harita.loadFinished.connect(_harita_yuklendi)
        self._harita.setHtml(HARITA_HTML)
        duz.addWidget(self._harita)

        # ── Görev özet satırı ─────────────────────────────────────────────────
        _ozet_satir = QHBoxLayout()
        _ozet_satir.setContentsMargins(4, 2, 4, 2)
        _ozet_satir.setSpacing(0)
        self._wp_wp_sayisi  = QLabel("WP: 0")
        self._wp_mesafe_lbl = QLabel("Toplam: — m")
        self._wp_sure_lbl   = QLabel("Süre: — dk")
        _lbl_stil = "color:#7eb8e0; font-size:12px; padding:2px 10px;"
        for _lbl in (self._wp_wp_sayisi, self._wp_mesafe_lbl, self._wp_sure_lbl):
            _lbl.setStyleSheet(_lbl_stil)
        _ozet_satir.addWidget(self._wp_wp_sayisi)
        _ozet_satir.addWidget(self._wp_mesafe_lbl)
        _ozet_satir.addWidget(self._wp_sure_lbl)
        _ozet_satir.addStretch()
        duz.addLayout(_ozet_satir)

        # ── Ayarlar çubuğu (Mission Planner tarzı) ────────────────────────────
        _ayar_satir = QHBoxLayout()
        _ayar_satir.setContentsMargins(4, 2, 4, 2)
        _ayar_satir.setSpacing(6)

        _ayar_satir.addWidget(QLabel("Varsayılan İrtifa:"))
        self._wp_def_alt = QSpinBox()
        self._wp_def_alt.setRange(5, 500)
        self._wp_def_alt.setValue(50)
        self._wp_def_alt.setSuffix(" m")
        self._wp_def_alt.setFixedWidth(80)
        self._wp_def_alt.setToolTip("Yeni waypoint'lerin varsayılan irtifası")
        self._wp_def_alt.setStyleSheet(
            "QSpinBox { background:#1a2a3a; color:#ddd; border:1px solid #2a4060;"
            " border-radius:3px; padding:1px 4px; }"
        )
        self._wp_def_alt.valueChanged.connect(
            lambda v: self._js(f"wpDefAltGuncelle({v});")
        )
        _ayar_satir.addWidget(self._wp_def_alt)

        _ayar_satir.addWidget(QLabel("WP Yarıçapı:"))
        self._wp_radius = QSpinBox()
        self._wp_radius.setRange(1, 200)
        self._wp_radius.setValue(10)
        self._wp_radius.setSuffix(" m")
        self._wp_radius.setFixedWidth(75)
        self._wp_radius.setToolTip("Waypoint kabul yarıçapı (MAVLink param 1)")
        self._wp_radius.setStyleSheet(
            "QSpinBox { background:#1a2a3a; color:#ddd; border:1px solid #2a4060;"
            " border-radius:3px; padding:1px 4px; }"
        )
        _ayar_satir.addWidget(self._wp_radius)

        _ayar_satir.addSpacing(8)

        _load_btn = QPushButton("WP Yükle")
        _load_btn.setFixedHeight(24)
        _load_btn.setToolTip(".waypoints dosyasından WP listesini yükle")
        _load_btn.clicked.connect(self._wp_dosya_yukle)
        _ayar_satir.addWidget(_load_btn)

        _save_btn = QPushButton("WP Kaydet")
        _save_btn.setFixedHeight(24)
        _save_btn.setToolTip("WP listesini .waypoints formatında kaydet")
        _save_btn.clicked.connect(self._wp_dosya_kaydet)
        _ayar_satir.addWidget(_save_btn)

        _ayar_satir.addSpacing(8)

        self._wp_home_lbl = QLabel("Ev: —")
        self._wp_home_lbl.setStyleSheet("color:#7eb8e0; font-size:11px;")
        self._wp_home_lbl.setToolTip("Drone ev konumu (GPS fix alındığında güncellenir)")
        _ayar_satir.addWidget(self._wp_home_lbl)

        _ayar_satir.addStretch()
        duz.addLayout(_ayar_satir)

        # ── Waypoint tablosu (haritanın altında) ──────────────────────────────
        # Sütunlar: # | Komut | Enlem | Boylam | İrtifa | Mesafe | AZ | ↑↓
        self._wp_tablo = QTableWidget(0, 8)
        self._wp_tablo.setHorizontalHeaderLabels(
            ["#", "Komut", "Enlem", "Boylam", "İrtifa (m)", "Mesafe (m)", "AZ (°)", ""]
        )
        _hh = self._wp_tablo.horizontalHeader()
        _hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        _hh.setSectionResizeMode(2, QHeaderView.Stretch)   # Enlem — genişle
        _hh.setSectionResizeMode(3, QHeaderView.Stretch)   # Boylam — genişle
        _hh.setSectionResizeMode(7, QHeaderView.Fixed)
        self._wp_tablo.setColumnWidth(7, 56)               # ↑↓ buton sütunu
        self._wp_tablo.setMaximumHeight(165)
        self._wp_tablo.setMinimumHeight(80)
        self._wp_tablo.setEditTriggers(QAbstractItemView.DoubleClicked)
        self._wp_tablo.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._wp_tablo.setAlternatingRowColors(True)
        self._wp_tablo.setStyleSheet(
            "QTableWidget { background:#1a1a2a; color:#ddd; font-size:12px; }"
            "QHeaderView::section { background:#2a2a3a; color:#aaa; padding:3px; }"
            "QTableWidget::item:selected { background:#2a3a5a; }"
        )
        self._wp_tablo.itemChanged.connect(self._wp_tablo_degisti)
        duz.addWidget(self._wp_tablo)

        # ── İrtifa profil grafiği ──────────────────────────────────────────────
        try:
            import pyqtgraph as pg
            pg.setConfigOptions(antialias=True, background='#1a2a3a', foreground='#7eb8e0')
            self._irtifa_grafik = pg.PlotWidget()
            self._irtifa_grafik.setMaximumHeight(90)
            self._irtifa_grafik.setMinimumHeight(60)
            self._irtifa_grafik.setLabel('left', 'İrt (m)', color='#7eb8e0', size='10pt')
            self._irtifa_grafik.setLabel('bottom', 'Mesafe (m)', color='#7eb8e0', size='10pt')
            self._irtifa_grafik.showGrid(x=True, y=True, alpha=0.25)
            self._irtifa_grafik.getPlotItem().getAxis('left').setTextPen('#7eb8e0')
            self._irtifa_grafik.getPlotItem().getAxis('bottom').setTextPen('#7eb8e0')
            self._irtifa_grafik_cizgi = self._irtifa_grafik.plot(
                pen=pg.mkPen('#ffeb3b', width=2),
                symbol='o', symbolBrush='#ffeb3b', symbolPen=None, symbolSize=7
            )
            # Zemin profili çizgisi (kahverengi, dolgu)
            self._irtifa_terrain_cizgi = pg.PlotCurveItem(
                pen=pg.mkPen('#8b4513', width=1.5),
                fillLevel=0,
                brush=pg.mkBrush(139, 69, 19, 80)
            )
            self._irtifa_grafik.addItem(self._irtifa_terrain_cizgi)
            duz.addWidget(self._irtifa_grafik)
        except Exception:
            self._irtifa_grafik = None
            self._irtifa_grafik_cizgi = None
            self._irtifa_terrain_cizgi = None

        self._terrain_profil_thread: "TerrainProfilThread | None" = None
        return w

    # ── Yardımcılar ──────────────────────────────────────────────────────────

    def _sekme_degisti(self, index: int):
        if index == self._param_tab_index and not self._param_tab_hazir:
            QTimer.singleShot(0, self._param_tab_yukle)
            return
        if HARITA_MEVCUT and index == self._harita_tab_index and not self._harita_tab_hazir:
            # Sekme tam görünür olduktan sonra WebEngine oluştur (100ms = Qt paint turu)
            QTimer.singleShot(100, self._harita_tab_yukle)
            return
        if HARITA_MEVCUT and hasattr(self, '_harita') and index == self._harita_tab_index:
            QTimer.singleShot(100, self._harita_boyut_duzelt)
            QTimer.singleShot(400, self._harita_boyut_duzelt)

    def _param_tab_yukle(self):
        if self._param_tab_hazir:
            return
        self._param_tab_hazir = True
        w = self._parametre_sekme()
        self._param_stack.addWidget(w)      # index 1 = gerçek param ekranı
        self._param_stack.setCurrentIndex(1)
        if self._param_cache:
            QTimer.singleShot(150, self._param_cache_doldur)

    def _param_cache_doldur(self):
        """Parametre önbelleğini tabloya yükler (singleShot ile ertelenmiş)."""
        if not hasattr(self, "_param_tablo"):
            return
        self._param_tablo.setSortingEnabled(False)
        for ad, deger in self._param_cache.items():
            self._param_guncelle(ad, deger, 0, 0)
        self._param_tablo.setSortingEnabled(True)

    def _mini_harita_yukle(self):
        """Uçuş sekmesi göründükten ~150ms sonra mini-haritayı oluşturur."""
        if not HARITA_MEVCUT or getattr(self, "_mini_harita_tab_hazir", False):
            return
        self._mini_harita_tab_hazir = True
        self._mini_harita_view = QWebEngineView()
        self._mini_harita_view.setMinimumSize(200, 200)
        sayfa = MiniHaritaSayfa(self._mini_harita_view)
        self._mini_harita_view.setPage(sayfa)

        def _yukle_tamamlandi(ok):
            self._mini_harita_hazir = True
            QTimer.singleShot(350, self._mini_harita_boyut_duzelt)
            QTimer.singleShot(800, self._mini_harita_boyut_duzelt)

        self._mini_harita_view.loadFinished.connect(_yukle_tamamlandi)
        self._mini_harita_view.setHtml(MINI_HARITA_HTML)
        self._mini_harita_stack.addWidget(self._mini_harita_view)   # index 1
        self._mini_harita_stack.setCurrentIndex(1)

    def _mini_harita_boyut_duzelt(self):
        """Leaflet invalidateSize — widget boyutlandıktan sonra."""
        if not getattr(self, "_mini_harita_hazir", False):
            QTimer.singleShot(400, self._mini_harita_boyut_duzelt)
            return
        if not hasattr(self, "_mini_harita_view"):
            return
        h = self._mini_harita_view.height()
        w = self._mini_harita_view.width()
        if h <= 10 or w <= 10:
            QTimer.singleShot(300, self._mini_harita_boyut_duzelt)
            return
        self._mini_js("boyutDuzelt();")

    def _harita_tab_yukle(self):
        if self._harita_tab_hazir:
            return
        self._harita_tab_hazir = True
        # WebEngine artık geçerli HWND var (show() sonrası çağrılıyor)
        w = self._harita_sekme()
        self._harita_stack.addWidget(w)      # index 1 = gerçek harita
        self._harita_stack.setCurrentIndex(1)
        # Leaflet boyutunu harita görünür olduktan sonra düzelt
        QTimer.singleShot(300, self._harita_boyut_duzelt)
        QTimer.singleShot(800, self._harita_boyut_duzelt)

    def _harita_boyut_duzelt(self):
        if not hasattr(self, '_harita'):
            return
        if not getattr(self, '_harita_hazir', False):
            # Sayfa henüz yüklenmedi — 500 ms sonra tekrar dene
            QTimer.singleShot(500, self._harita_boyut_duzelt)
            return
        h = self._harita.height()
        w = self._harita.width()
        if h <= 10 or w <= 10:
            # Widget henüz boyutlanmamış — tekrar dene
            QTimer.singleShot(300, self._harita_boyut_duzelt)
            return
        js = (
            f"if(typeof map!=='undefined'){{"
            f"var m=document.getElementById('map');"
            f"if(m){{m.style.width='{w}px';m.style.height='{h}px';}}"
            f"map.invalidateSize(true);}}"
        )
        self._js(js)

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
        self._ucus_kaydedici.baslat()
        self._log_timer.start()
        self._mesaj_ekle(6, f"Log: {self._logger.csv_yolu()}")
        # GCS Failsafe — kuyruk thread-safe olduğu için doğrudan çağrılabilir
        self._gcs_failsafe_ayarla()

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
        self._ucus_kaydedici.durdur()
        self._rapor_olustur_arka_plan()

    def _rapor_olustur_arka_plan(self):
        """Bağlantı kesilince arka planda HTML rapor üretir, bitince mesaj loguna yazar."""
        try:
            yol = self._ucus_kaydedici.html_rapor_olustur()
            if yol:
                self._mesaj_ekle(4, f"📊 Uçuş raporu hazır: {os.path.basename(yol)}")
                self._son_rapor_yolu = yol
        except Exception as e:
            self._mesaj_ekle(3, f"Rapor oluşturulamadı: {e}")

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
        _b = "border-radius:3px; padding:2px 8px; font-size:10px;"
        if arm:
            self._arm_lbl.setText("● ARMED")
            self._arm_lbl.setStyleSheet(
                f"color:#f44336; background:#2a0a0a; border:1px solid #6a1a1a; font-weight:bold; {_b}"
            )
        else:
            self._arm_lbl.setText("DISARM")
            self._arm_lbl.setStyleSheet(
                f"color:#666; background:#111; border:1px solid #2a2a2a; {_b}"
            )
        # RTL modu yeni başladıysa izleyiciyi başlat
        if mod_id == 6 and self._son_mod_id != 6:
            self._rtl_izleyici.baslat(self._guncel_eve_uzaklik)
            self._mesaj_ekle(4, "RTL başlatıldı — ilerleme izleniyor.")
        elif mod_id != 6:
            self._rtl_izleyici.durdur()
        # Mod değişiminde sesli uyarı
        if mod_id != self._son_mod_id:
            mod_adi = UÇUŞ_MODLARI.get(mod_id, f"Mod {mod_id}")
            self._sesli_uyan(f"Mod {mod_adi}")
        self._son_mod_id = mod_id

    def _batarya_guncelle(self, volt: float, amper: float, yuzde: int):
        self._guncel_batarya_yuzde = yuzde
        if hasattr(self, '_bat_volt_tile_lbl') and self._bat_volt_tile_lbl:
            self._bat_volt_tile_lbl.setText(f"{volt:.2f}")
        self._batarya_bar.guncelle(volt, amper, yuzde)
        if volt > 0 and amper > 0.5 and yuzde > 0:
            sure_dk = (volt * yuzde / 100.0) / amper * 60
            self._batarya_detay.setText(
                f"{volt:.2f}V  {amper:.2f}A  Tahmini süre: {sure_dk:.0f} dk"
            )
        else:
            yuzde_str = f"{yuzde}%" if yuzde >= 0 else "?%"
            self._batarya_detay.setText(f"{volt:.2f}V  {amper:.2f}A  {yuzde_str}  Tahmini süre: --")
        self._log_satiri.update({"bat_volt": volt, "bat_amper": amper, "bat_yuzde": yuzde})
        # Sesli batarya uyarısı (her seviye bir kez)
        if yuzde > 0:
            if yuzde <= 8 and self._son_bat_uyari != 8:
                self._son_bat_uyari = 8
                self._sesli_uyan("Batarya kritik, acil inis yapın")
            elif yuzde <= 15 and self._son_bat_uyari not in (8, 15):
                self._son_bat_uyari = 15
                self._sesli_uyan("Batarya kritik")
            elif yuzde <= 25 and self._son_bat_uyari not in (8, 15, 25):
                self._son_bat_uyari = 25
                self._sesli_uyan("Batarya düşük")

    def _vfr_guncelle(self, irtifa: float, hiz: float, dikey: float, uzaklik: float):
        self._guncel_irtifa      = irtifa
        self._guncel_eve_uzaklik = uzaklik
        self._irtifa_lbl.setText(f"{irtifa:.2f}")
        self._hiz_lbl.setText(f"{hiz:.2f}")
        self._dikey_lbl.setText(f"{dikey:+.2f}")
        self._uzaklik_lbl.setText(f"{uzaklik:.0f}")
        self._log_satiri.update({"irtifa": irtifa, "hiz": hiz, "dikey_hiz": dikey, "eve_uzaklik": uzaklik})
        self._rtl_izleyici.guncelle(
            uzaklik,
            getattr(self, "_guncel_batarya_yuzde", 100),
            self._log_satiri.get("ruzgar_ms", 0.0),   # zaten m/s
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
        # Harita JS güncellemesi — doğrudan değil, 500 ms timer buffer'ına yaz
        self._harita_bekleyen_lat = lat
        self._harita_bekleyen_lon = lon
        # Mini-harita (uçuş sekmesi) buffer
        self._mini_harita_bekleyen_lat = lat
        self._mini_harita_bekleyen_lon = lon
        self._guncel_gps_fix = fix
        self._log_satiri.update({"gps_fix": fix, "gps_uydu": uydu, "lat": lat, "lon": lon})

        # Ev konumu etiketi — ilk 3D fix'te göster
        if fix >= 3 and lat != 0.0 and hasattr(self, '_wp_home_lbl'):
            if self._wp_home_lbl.text() == "Ev: —":
                self._wp_home_lbl.setText(f"Ev: {lat:.5f}, {lon:.5f}")

        # İlk 3D fix'te terrain hazırlığı — fence/önceki alan sınırına göre akıllı karar
        if (fix >= 3
                and not self._alan_hazirlik_yapildi
                and self._alan_karar is None
                and lat != 0.0):
            self._alan_hazirlik_yapildi = True
            if self._alan_bounds:
                lat_min, lat_max, lon_min, lon_max = self._alan_bounds
                if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
                    # GPS mevcut terrain alanı içinde — NPZ'yi yeniden yüklemeyi dene
                    _npz = os.path.join(os.path.dirname(__file__), "alan_verisi.npz")
                    if not os.path.isfile(_npz):
                        _npz = "alan_verisi.npz"
                    if os.path.isfile(_npz):
                        try:
                            from alan_inis_karar import AlanInisKarar
                            self._alan_karar = AlanInisKarar(_npz)
                            self._mesaj_ekle(4, "✓ Mevcut terrain verisi yüklendi — "
                                               "gerçek zamanlı iniş kontrolü aktif.")
                        except Exception as _re:
                            self._mesaj_ekle(3, f"Terrain yeniden yükleme hatası: {_re}")
                else:
                    # GPS bilinen terrain dışında — yeni GPS alanı için indir
                    self._mesaj_ekle(6,
                        f"GPS mevcut terrain sınırı dışında "
                        f"({lat:.4f}, {lon:.4f}) — yeni alan indiriliyor…")
                    self._alan_thread_baslat(
                        lat - 0.05, lat + 0.05, lon - 0.05, lon + 0.05,
                        kaynak=f"GPS ({lat:.4f}, {lon:.4f})"
                    )
            else:
                # Hiç terrain yok — GPS etrafında ±0.05° indir
                self._alan_hazirligini_baslat(lat, lon)

        # Alan iniş kararı — 5 sn debounce (10Hz'de sürekli NumPy lookup önlenir)
        if self._alan_karar is not None and lat != 0.0:
            _simdi = time.monotonic()
            if _simdi - self._alan_karar_son_sorgu >= 5.0:
                self._alan_karar_son_sorgu = _simdi
                try:
                    ruz_ms  = self._ruz_zemin_ms   # Hellmann güç yasasıyla zemin tahmini
                    ruz_yon = self._log_satiri.get("ruzgar_yon", 0.0)
                    karar = self._alan_karar.inis_karari(
                        lat, lon, self._guncel_lidar_m,
                        ruzgar_ms=ruz_ms, ruzgar_yonu=ruz_yon,
                    )
                    if not karar.inebilir:
                        if _simdi - self._alan_karar_son_uyari >= 5.0:
                            self._alan_karar_son_uyari = _simdi
                            self._mesaj_ekle(3, f"Alan: {karar.neden}")
                except Exception:
                    pass   # Koordinat sınır dışı vb. — sessiz geç

    # ── Merkezi JS kuyruğu ───────────────────────────────────────────────────

    def _js(self, script: str):
        """Tüm harita JS çağrıları buradan geçer — asla doğrudan runJavaScript çağırma."""
        if HARITA_MEVCUT and getattr(self, "_harita_hazir", False):
            self._js_kuyruk.append(script)

    def _js_temizle(self):
        """100 ms'de bir kuyruktaki tüm JS'i TEK bir runJavaScript çağrısıyla çalıştırır."""
        if not self._js_kuyruk:
            return
        if not HARITA_MEVCUT or not getattr(self, "_harita_hazir", False):
            self._js_kuyruk.clear()
            return
        if not hasattr(self, "_harita"):
            self._js_kuyruk.clear()
            return
        # Tüm parçaları birleştir → tek IPC mesajı → re-entrancy riski yok
        kod = "\n".join(self._js_kuyruk)
        self._js_kuyruk.clear()
        try:
            self._harita.page().runJavaScript(kod)
        except Exception:
            pass

    # ── Mini-harita JS altyapısı ──────────────────────────────────────────────

    def _mini_js(self, script: str):
        """Mini-harita JS kuyruğuna ekle."""
        if HARITA_MEVCUT and getattr(self, "_mini_harita_hazir", False):
            self._mini_js_kuyruk.append(script)

    def _mini_js_temizle(self):
        """Timer tick'inde mini-harita JS kuyruğunu flush eder."""
        if not self._mini_js_kuyruk:
            return
        if not HARITA_MEVCUT or not getattr(self, "_mini_harita_hazir", False):
            self._mini_js_kuyruk.clear()
            return
        if not hasattr(self, "_mini_harita_view"):
            self._mini_js_kuyruk.clear()
            return
        kod = "\n".join(self._mini_js_kuyruk)
        self._mini_js_kuyruk.clear()
        try:
            self._mini_harita_view.page().runJavaScript(kod)
        except Exception:
            pass

    def _mini_harita_js_guncelle(self):
        """Timer tick'inde mini-harita GPS buffer'ını kuyruğa ekler."""
        lat = self._mini_harita_bekleyen_lat
        lon = self._mini_harita_bekleyen_lon
        if lat is None:
            return
        self._mini_harita_bekleyen_lat = None
        if lat == 0.0 and lon == 0.0:
            return
        alt = self._guncel_irtifa
        yaw = self._log_satiri.get("yaw", 0.0)
        self._mini_js(f"droneGuncelle({lat},{lon},{alt},{yaw});")

    def _harita_js_guncelle(self):
        """100 ms timer'ından GPS buffer'ını kuyruğa ekler."""
        lat = self._harita_bekleyen_lat
        lon = self._harita_bekleyen_lon
        if lat is None:
            return
        self._harita_bekleyen_lat = None
        # lat=0/lon=0 → GPS fix yok — haritayı (0,0)'a taşıma
        if lat == 0.0 and lon == 0.0:
            return
        alt = self._guncel_irtifa
        self._js(f"droneyiGuncelle({lat},{lon},{alt});")
        self._js(f"konumuGuncelle('Konum: {lat:.5f}, {lon:.5f}  |  Irtifa: {alt:.1f} m');")

    def _harita_terrain_sinir_goster(self):
        """Bilinen terrain alanını haritada mavi kesik dikdörtgen olarak çizer."""
        if not self._alan_bounds:
            return
        lat_min, lat_max, lon_min, lon_max = self._alan_bounds
        self._js(f"terrainSinirGoster({lat_min},{lon_min},{lat_max},{lon_max});")

    def _alan_hazirligini_baslat(self, lat: float, lon: float, r: float = 0.05):
        """GPS fix alındığında GPS merkezi etrafında ±r° kare alan hazırlar."""
        self._alan_thread_baslat(
            lat - r, lat + r, lon - r, lon + r,
            kaynak=f"GPS ({lat:.4f}, {lon:.4f})"
        )

    def _alan_thread_baslat(self, lat_min: float, lat_max: float,
                            lon_min: float, lon_max: float, kaynak: str = ""):
        """Verilen bounding box için AlanHazirlikThread başlatır."""
        if self._alan_hazirlik_thread and self._alan_hazirlik_thread.isRunning():
            self._mesaj_ekle(3, "Terrain: hazırlık zaten devam ediyor, bekleyin.")
            return
        self._mesaj_ekle(6, f"Terrain: alan hazırlanıyor {kaynak} "
                            f"({lat_min:.3f}–{lat_max:.3f}, "
                            f"{lon_min:.3f}–{lon_max:.3f})…")
        t = AlanHazirlikThread(lat_min, lat_max, lon_min, lon_max)
        t.ilerleme.connect(lambda m: self._mesaj_ekle(6, m))
        t.ilerleme.connect(lambda m: self._js(f"durumGoster({json.dumps(m)});"))
        t.tamamlandi.connect(self._alan_hazirlik_tamamlandi)
        t.hata.connect(lambda e: self._mesaj_ekle(3, e))
        t.hata.connect(lambda e: self._js(f"durumGoster({json.dumps('⚠ Terrain hatası: ' + e)});"))
        self._alan_hazirlik_thread = t
        t.start()
        self._js("durumGoster('⏳ Terrain indiriliyor… (2-5 dk sürebilir, lütfen bekleyin)');")


    def _alan_hazirlik_tamamlandi(self, npz_yolu: str):
        """AlanHazirlikThread tamamlandığında AlanInisKarar'ı yükler ve haritada gösterir."""
        try:
            import numpy as _np
            _data = _np.load(npz_yolu, allow_pickle=True)
            _lat_min = _lat_max = _lon_min = _lon_max = None
            if "bounds" in _data:
                _b = _data["bounds"]   # [lon_min, lat_min, lon_max, lat_max]
                _lon_min, _lat_min = float(_b[0]), float(_b[1])
                _lon_max, _lat_max = float(_b[2]), float(_b[3])
                self._alan_bounds = (_lat_min, _lat_max, _lon_min, _lon_max)
                self._harita_terrain_sinir_goster()
            from alan_inis_karar import AlanInisKarar
            self._alan_karar = AlanInisKarar(npz_yolu)
            self._mesaj_ekle(4, "✓ Terrain hazır — gerçek zamanlı iniş kontrolü aktif.")

            # NPZ'deki güvenli noktaları haritada göster
            if "noktalar_json" in _data:
                try:
                    _noktalar_str = str(_data["noktalar_json"][0])
                    _lat_a  = str(_lat_min)  if _lat_min  is not None else "null"
                    _lat_b  = str(_lat_max)  if _lat_max  is not None else "null"
                    _lon_a  = str(_lon_min)  if _lon_min  is not None else "null"
                    _lon_b  = str(_lon_max)  if _lon_max  is not None else "null"
                    self._js(
                        f"alanNoktalarGoster("
                        f"{json.dumps(_noktalar_str)}, "
                        f"{_lat_a}, {_lat_b}, {_lon_a}, {_lon_b});"
                    )
                except Exception as _ve:
                    self._mesaj_ekle(3, f"Nokta görselleştirme hatası: {_ve}")
                    self._js("durumGoster('✓ Terrain hazır — nokta gösterimi için "
                             "\\\"Güvenli İniş Analizi\\\" butonuna basın.');")
            else:
                self._js("durumGoster('✓ Terrain hazır — "
                         "\\\"Güvenli İniş Analizi\\\" butonuna basın.');")
        except Exception as exc:
            self._mesaj_ekle(3, f"Alan karar yükleme hatası: {exc}")
            self._js(f"durumGoster({json.dumps('⚠ Terrain yükleme hatası: ' + str(exc))});")

    def _tutum_guncelle(self, roll: float, pitch: float, yaw: float):
        self._yapay_ufuk.guncelle(roll, pitch)
        self._roll_lbl.setText(f"{roll:.2f}")
        self._pitch_lbl.setText(f"{pitch:.2f}")
        self._yaw_lbl.setText(f"{yaw:.2f}")
        self._log_satiri.update({"roll": roll, "pitch": pitch, "yaw": yaw})

    def _ruzgar_guncelle(self, hiz: float, yon: float):
        """
        MAVLink WIND msg.speed (m/s, drone irtifasında) işlenir.
        1. EMA filtresi — anlık gust'lardan yanlış alarm önler (α=0.25)
        2. Hellmann Güç Yasası — irtifa rüzgarını zemin seviyesine (2 m) indirger
        3. 60 saniyelik trend penceresi — rüzgar artıyor mu azalıyor mu?
        4. Bekleme önerisi — eşiğe yakınsa mesaj üret
        5. Eşik kontrolleri — zemin tahmini kullanılır (irtifa değil!)
        """
        import time as _time

        # ── 0. Kalite kapıları — Cube Orange EKF gürültüsünü engeller ─────────

        # Kapı A: EKF tutum + yatay hız kilitli değilse rüzgar tahmini güvenilmez
        if not self._ekf_ruzgar_gecerli:
            self._ruz_panel_guncelle(hiz, yon)              # Panel'i yine de göster
            self._log_satiri.update({"ruzgar_ms": hiz, "ruzgar_yon": yon})
            return  # Gradient / gust / trend hesaplama

        # Kapı B: IMU klipleme varsa titreşim çok yüksek → EKF wind verisi bozuk
        if self._guncel_vib_klip > 0:
            self._ruz_panel_guncelle(hiz, yon)
            self._log_satiri.update({"ruzgar_ms": hiz, "ruzgar_yon": yon})
            return

        # Kapı C: 2 m/s altı tamamen EKF gürültü tabanı
        if hiz < self._ruz_min_gecerli_ms:
            self._ruz_zemin_ms = 0.0
            self._ruz_trend_ms_per_s = 0.0
            self._ruz_panel_guncelle(hiz, yon)
            self._log_satiri.update({"ruzgar_ms": hiz, "ruzgar_yon": yon})
            self._ruzgar_zemin_lbl.setText("Zemin: <2 m/s (gürültü)")
            return

        # ── 1. Panel + ham log ────────────────────────────────────────────────
        self._ruz_panel_guncelle(hiz, yon)
        self._log_satiri.update({"ruzgar_ms": hiz, "ruzgar_yon": yon})

        # ── 2. EMA filtresi ────────────────────────────────────────────────────
        self._ruz_ema = 0.25 * hiz + 0.75 * self._ruz_ema
        hiz_f = self._ruz_ema   # filtrelenmiş irtifa rüzgarı (m/s)

        # ── 3. Hellmann Güç Yasası: irtifa → zemin ────────────────────────────
        # v_zemin = v_irtifa × (h_zemin / h_irtifa) ^ α
        irtifa = max(getattr(self, "_guncel_irtifa", 10.0), self._ruz_zemin_ref_m + 0.1)
        self._ruz_zemin_ms = hiz_f * (self._ruz_zemin_ref_m / irtifa) ** self._ruz_hellmann

        # ── 4. Trend penceresi (60 sn kayan) ──────────────────────────────────
        self._ruz_gecmis.append((_time.monotonic(), hiz_f))
        self._ruz_trend_ms_per_s = self._ruzgar_trend_hesapla()

        # ── 5. Log güncelle (zemin + trend) ───────────────────────────────────
        self._log_satiri.update({
            "ruzgar_zemin_ms": round(self._ruz_zemin_ms, 2),
            "ruzgar_trend":    round(self._ruz_trend_ms_per_s, 4),
        })

        # ── 6. UI: zemin etiketi ───────────────────────────────────────────────
        trend_ok = ("↑" if self._ruz_trend_ms_per_s >  0.03 else
                    "↓" if self._ruz_trend_ms_per_s < -0.03 else "→")
        self._ruzgar_zemin_lbl.setText(
            f"Zemin: {self._ruz_zemin_ms * 3.6:.0f} km/h {trend_ok}"
        )

        # ── 7. Sürekli gust dedektörü ─────────────────────────────────────────
        self._gust_dedekt(hiz, hiz_f, _time.monotonic())

        # ── 8. Bekleme önerisi ─────────────────────────────────────────────────
        self._bekleme_onerisi_guncelle(hiz_f)

        # ── 9. Eşik kontrolleri — zemin tahmini kullanılır ────────────────────
        z = self._ruz_zemin_ms   # zemin rüzgarı (m/s)

        if z >= self._ruz_kritik_ms and not getattr(self, "_ruzgar_kritik_gonderildi", False):
            self._ruzgar_kritik_gonderildi = True
            self._mesaj_ekle(2,
                f"KRİTİK RÜZGAR! İrtifa: {hiz_f*3.6:.0f} km/h → "
                f"Zemin: {z*3.6:.0f} km/h — güvenli iniş analizi başlatılıyor.")
            if getattr(self, "_en_yakin_guvenli_nokta", None):
                self._guvenli_inise_git(onay_sor=False)   # Kritik → onaysız
            else:
                self._ruzgar_acil_inis_bekliyor = True
                self._guvenli_inis_baslat()
        elif z >= self._ruz_tehlikeli_ms and not getattr(self, "_ruzgar_tehlikeli_gonderildi", False):
            self._ruzgar_tehlikeli_gonderildi = True
            self._mesaj_ekle(3,
                f"TEHLİKELİ RÜZGAR! İrtifa: {hiz_f*3.6:.0f} km/h → "
                f"Zemin: {z*3.6:.0f} km/h — eve dönüş başlatılıyor.")
            self._mavlink.mod_degistir(6)   # RTL

        # Histerezis: zemin rüzgarı %85'in altına düşünce bayrakları sıfırla
        if z < self._ruz_tehlikeli_ms * 0.85:
            self._ruzgar_tehlikeli_gonderildi = False
            self._ruzgar_kritik_gonderildi   = False

    def _ruz_panel_guncelle(self, hiz_ms: float, yon: float):
        """Rüzgar panelindeki etiketleri (hız, seviye, yön) günceller."""
        if not hasattr(self, '_ruz_hiz_lbl') or self._ruz_hiz_lbl is None:
            return
        hiz_kmh = hiz_ms * 3.6
        # Renk + seviye metni
        if hiz_kmh < 20:
            renk, seviye = "#4caf50", "NORMAL"
        elif hiz_kmh < 40:
            renk, seviye = "#ffc107", "DİKKAT"
        elif hiz_kmh < 60:
            renk, seviye = "#ff9800", "TEHLİKELİ"
        else:
            renk, seviye = "#f44336", "KRİTİK"
        self._ruz_seviye_lbl.setText(f"● {seviye}")
        self._ruz_seviye_lbl.setStyleSheet(
            f"color:{renk}; font-weight:bold; font-size:12px;"
        )
        self._ruz_hiz_lbl.setText(f"{hiz_ms:.1f}  m/s")
        self._ruz_hiz_lbl.setStyleSheet(
            f"color:{renk}; font-size:16px; font-weight:bold;"
        )
        # Yön metni (sekiz yön)
        _yonler = ["K", "KD", "D", "GD", "G", "GB", "B", "KB"]
        _yon_idx = int((yon + 22.5) / 45) % 8
        self._ruz_yon_lbl.setText(f"Yön: {yon:.0f}°  {_yonler[_yon_idx]}")

    def _ruzgar_trend_hesapla(self) -> float:
        """
        60 saniyelik pencerede en küçük kareler doğrusal regresyon ile trend hesaplar.
        Döndürür: m/s/saniye (+ artıyor, - azalıyor, 0 = yetersiz veri)
        """
        if len(self._ruz_gecmis) < 6:
            return 0.0
        veriler = list(self._ruz_gecmis)
        t0  = veriler[0][0]
        n   = len(veriler)
        ts  = [v[0] - t0 for v in veriler]
        vs  = [v[1]       for v in veriler]
        t_ort = sum(ts) / n
        v_ort = sum(vs) / n
        pay   = sum((ts[i] - t_ort) * (vs[i] - v_ort) for i in range(n))
        payda = sum((ts[i] - t_ort) ** 2               for i in range(n))
        return pay / payda if payda > 0 else 0.0

    def _gust_dedekt(self, hiz_ham: float, hiz_f: float, simdi: float):
        """
        Ham hız EMA'nın gust_esik_ms m/s üstünde gust_min_sure_s saniyeden
        uzun kaldığında alarm üretir.

        Mantık:
          1 saniye → drone ataleti absorbe eder, alarm yok
          3+ saniye → motorlar sürekli düzeltme yapar, batarya + kararlılık riski
          Gust geçince (ham < EMA + esik * 0.5) → durum sıfırlanır
        """
        delta = hiz_ham - hiz_f   # ham - EMA: pozitifse anlık yükseliş

        # Vibrasyon yüksekse gust eşiğini dinamik olarak artır
        # (15-30 m/s²: orta titreşim → 1.5× eşik; >30: yüksek → 2× eşik)
        vib = self._guncel_vibrasyon_mss
        if vib > 30.0:
            gust_esik_aktif = self._gust_esik_ms * 2.0
        elif vib > 15.0:
            gust_esik_aktif = self._gust_esik_ms * 1.5
        else:
            gust_esik_aktif = self._gust_esik_ms

        if delta > gust_esik_aktif:
            # Gust BAŞLADI (ilk kez)
            if self._gust_baslangic_t is None:
                self._gust_baslangic_t = simdi
                self._gust_alarm_verildi = False

        # Gust takibi: başladıktan sonra ham hız EMA'nın altına düşene kadar sürdür.
        # "EMA güst'a yaklaşıyor" durumunu gust sonu olarak SAYMA —
        # aksi hâlde EMA yaklaşma süresi alarm eşiğini geçemez.
        if self._gust_baslangic_t is not None:
            sure = simdi - self._gust_baslangic_t

            if sure >= self._gust_min_sure_s and not self._gust_alarm_verildi:
                self._gust_alarm_verildi = True
                # ── İrtifa tavsiyesi: hangi yükseklikte rüzgar kabul edilebilir? ──
                irtifa_tavsiye = self._guvenli_irtifa_hesapla(hiz_ham)
                if irtifa_tavsiye is not None:
                    guncel_irtifa = getattr(self, "_guncel_irtifa", 0.0)
                    self._mesaj_ekle(3,
                        f"⚡ Sürekli gust {sure:.0f} sn: {hiz_ham*3.6:.0f} km/h "
                        f"(EMA: {hiz_f*3.6:.0f} km/h) — motorlar zorlanıyor. "
                        f"{guncel_irtifa:.0f}m'den {irtifa_tavsiye:.0f}m'ye alçal: "
                        f"rüzgar ~{self._ruz_tehlikeli_ms*3.6:.0f} km/h eşiğine düşer."
                    )
                else:
                    self._mesaj_ekle(3,
                        f"⚡ Sürekli gust {sure:.0f} sn: {hiz_ham*3.6:.0f} km/h "
                        f"(EMA: {hiz_f*3.6:.0f} km/h) — motorlar zorlanıyor, iniş düşün."
                    )

            # Gust bitti: ham hız EMA'nın altına düştüğünde sıfırla
            if hiz_ham < hiz_f:
                self._gust_baslangic_t = None
                self._gust_alarm_verildi = False

    def _guvenli_irtifa_hesapla(self, hiz_ham: float) -> "float | None":
        """
        Hellmann'ı tersine çevirir: rüzgarın tehlikeli eşiğin altına düşeceği
        minimum irtifayı hesaplar.

          v_esik = hiz_ham × (h_hedef / h_irtifa) ^ α
          h_hedef = h_irtifa × (v_esik / hiz_ham) ^ (1/α)

        Hesaplanan irtifa mevcut irtifadan yüksekse (yukarı çıkılacak) ya da
        çok alçaksa (zemin_ref + 5m altı) None döner.
        """
        esik  = self._ruz_tehlikeli_ms
        alpha = self._ruz_hellmann
        h_mev = max(getattr(self, "_guncel_irtifa", 0.0), self._ruz_zemin_ref_m + 0.1)

        if hiz_ham <= esik or alpha <= 0:
            return None   # Zaten güvenli

        try:
            h_hedef = h_mev * (esik / hiz_ham) ** (1.0 / alpha)
        except (ValueError, ZeroDivisionError):
            return None

        min_guvenli = self._ruz_zemin_ref_m + 5.0  # en az 7m yükseklikte kal
        if h_hedef >= h_mev:
            return None   # Yukarı çıkmak gerekiyor — anlamsız
        if h_hedef < min_guvenli:
            return None   # Çok alçak — güvensiz

        return round(h_hedef, 1)

    def _bekleme_onerisi_guncelle(self, hiz_f: float):
        """
        Rüzgar tehlikeli eşiğe yakınsa ve belirgin bir trend varsa,
        operatöre bekleme veya uyarı mesajı üretir.
        Mesajlar spam önlemi için 30 sn'de bir tetiklenir.
        """
        import time as _time
        _simdi = _time.monotonic()
        _son   = getattr(self, "_bekleme_son_mesaj_t", 0.0)
        if _simdi - _son < 30.0:
            return
        tehlikeli = self._ruz_tehlikeli_ms
        trend     = self._ruz_trend_ms_per_s

        # Tehlikeli eşiğin %80-100 aralığında VE azalıyorsa → pencere açılıyor
        if tehlikeli * 0.80 <= hiz_f < tehlikeli and trend < -0.05:
            kalan = max((hiz_f - tehlikeli * 0.70) / abs(trend), 0)
            self._mesaj_ekle(6,
                f"💨 Rüzgar azalıyor ({hiz_f*3.6:.0f}→{tehlikeli*0.70*3.6:.0f} km/h) "
                f"— tahminen {kalan:.0f} sn sonra güvenli pencere açılabilir."
            )
            self._bekleme_son_mesaj_t = _simdi

        # Güvenli aralıkta ama hızla artıyorsa → yaklaşan tehlike uyarısı
        elif hiz_f < tehlikeli * 0.80 and trend > 0.08:
            sure = (tehlikeli - hiz_f) / trend
            if sure < 120:
                self._mesaj_ekle(5,
                    f"⚠ Rüzgar artıyor ({hiz_f*3.6:.0f} km/h ↑) "
                    f"— {sure:.0f} sn içinde tehlikeli eşiğe ulaşabilir, iniş planla."
                )
                self._bekleme_son_mesaj_t = _simdi

    def _lidar_guncelle(self, mesafe_m: float):
        """DISTANCE_SENSOR mesajından gelen yüksekliği saklar."""
        self._guncel_lidar_m = mesafe_m
        self._log_satiri["lidar_m"] = mesafe_m

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
        """Her saniye mevcut telemetri satırını CSV'ye yazar + uçuş kaydediciye besler."""
        if self._log_satiri:
            self._logger.kaydet_satir(dict(self._log_satiri))
            # Alan adı dönüşümü: _log_satiri CSV anahtarları → UcusKaydedici anahtarları
            s = self._log_satiri
            self._ucus_kaydedici.veri_ekle({
                "irtifa":        s.get("irtifa", 0.0),
                "hiz":           s.get("hiz", 0.0),
                "dikey_hiz":     s.get("dikey_hiz", 0.0),
                "lat":           s.get("lat", 0.0),
                "lon":           s.get("lon", 0.0),
                "batarya_v":     s.get("bat_volt", 0.0),
                "batarya_a":     s.get("bat_amper", 0.0),
                "batarya_yuzde": s.get("bat_yuzde", -1),
                "ruzgar_ms":     s.get("ruzgar_ms", 0.0),
                "imu0_c":        s.get("imu0_c", 0.0),
                "imu1_c":        s.get("imu1_c", 0.0),
                "imu2_c":        s.get("imu2_c", 0.0),
                "gps_fix":       s.get("gps_fix", 0),
                "gps_uydu":      s.get("gps_uydu", 0),
                "ekf_hata":      s.get("ekf_hata", 0.0),
                "mod_id":        s.get("mod_id", 0),
            })

    def _ekf_guncelle(self, bayraklar: int, hata: float):
        self._guncel_ekf_hata = hata
        self._ekf_bayraklar   = bayraklar
        # Bit 0 (tutum) + Bit 1 (yatay hız) her ikisi de set ise rüzgar tahmini güvenilir
        self._ekf_ruzgar_gecerli = bool(bayraklar & 0x0001) and bool(bayraklar & 0x0002)
        _b = "border-radius:3px; padding:2px 8px; font-size:10px;"
        if bayraklar & 0x01F:
            self._ekf_lbl.setText(f"EKF: OK ({hata:.2f})")
            self._ekf_lbl.setStyleSheet(
                f"color:#4caf50; background:#0a1e0a; border:1px solid #1a5a1a; {_b}"
            )
        else:
            self._ekf_lbl.setText("EKF: HATA")
            self._ekf_lbl.setStyleSheet(
                f"color:#f44336; background:#1e0a0a; border:1px solid #5a1a1a; font-weight:bold; {_b}"
            )
        self._log_satiri.update({"ekf_bayrak": bayraklar, "ekf_hata": hata})

    def _vibrasyon_guncelle(self, vib_mss: float, klipping: int):
        """VIBRATION mesajından titreşim seviyesini saklar.
        Sürekli yüksek vibrasyonda EK3_WIND_P_NSE ayar önerisi üretir."""
        self._guncel_vibrasyon_mss = vib_mss
        self._guncel_vib_klip      = klipping

        # ── EK3_WIND_P_NSE akıllı uyarı ─────────────────────────────────────
        # Vibrasyon > 30 m/s² → EKF rüzgar tahmini güvenilmez.
        # ArduPilot EK3_WIND_P_NSE (varsayılan 0.20) artırılırsa EKF daha
        # hızlı uyum sağlar; ancak çok yükselirse gürültülü tahmin olur.
        if vib_mss > 30.0:
            self._ek3_yuksek_vib_sayac += 1
        else:
            self._ek3_yuksek_vib_sayac = max(0, self._ek3_yuksek_vib_sayac - 1)

        # 20 arka arkaya yüksek okuma (~10 sn) → bir kez öner
        if self._ek3_yuksek_vib_sayac >= 20 and not self._ek3_uyari_verildi:
            self._ek3_uyari_verildi = True
            mevcut = self._param_cache.get("EK3_WIND_P_NSE", None)
            if mevcut is not None:
                if mevcut < 0.35:
                    self._mesaj_ekle(3,
                        f"⚠ Vibrasyon yüksek ({vib_mss:.0f} m/s²) — "
                        f"EK3_WIND_P_NSE şu an {mevcut:.2f}. "
                        f"0.40 yapılması rüzgar EKF kalitesini artırır "
                        f"(Parametreler → EK3_WIND_P_NSE)."
                    )
                # else: zaten yeterince yüksek, uyarma
            else:
                self._mesaj_ekle(3,
                    f"⚠ Vibrasyon yüksek ({vib_mss:.0f} m/s²) — "
                    f"EK3_WIND_P_NSE parametresini 0.40'a artırmayı dene "
                    f"(rüzgar EKF uyum hızı)."
                )

        # Vibrasyon normale döndüyse uyarı bayrağını sıfırla (yeni yüksek için tekrar uyarsın)
        if vib_mss < 15.0:
            self._ek3_uyari_verildi  = False
            self._ek3_yuksek_vib_sayac = 0

    # ── Parametre sinyal alıcıları ────────────────────────────────────────────

    def _param_guncelle(self, ad: str, deger: float, alinan: int, toplam: int):
        self._param_cache[ad] = deger   # yedekleme için cache
        if not getattr(self, "_param_ui_hazir", False):
            return
        if toplam > 0:
            self._param_progress.setMaximum(toplam)
            self._param_progress.setValue(alinan)
            self._param_progress.setFormat(f"{alinan} / {toplam} parametre")

        # Tabloya ekle/guncelle (satir indeksini O(1) tut)
        satir = self._param_satir_index.get(ad)
        if satir is not None:
            val_item = self._param_tablo.item(satir, 1)
            if val_item:
                val_item.setText(f"{deger:.6g}")
            return

        satir = self._param_tablo.rowCount()
        self._param_tablo.insertRow(satir)
        ad_item  = QTableWidgetItem(ad)
        val_item = QTableWidgetItem(f"{deger:.6g}")
        val_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._param_tablo.setItem(satir, 0, ad_item)
        self._param_tablo.setItem(satir, 1, val_item)
        self._param_tablo.setItem(satir, 2, QTableWidgetItem(""))
        self._param_satir_index[ad] = satir

    def _param_tamam(self):
        if not getattr(self, "_param_ui_hazir", False):
            return
        self._param_tablo.setSortingEnabled(True)
        self._param_progress.hide()
        sayi = self._param_tablo.rowCount()
        self._param_bilgi.setText(f"{sayi} parametre indirildi. Düzenlemek için satıra çift tıkla.")
        self._mesaj_ekle(6, f"{sayi} parametre indirildi.")

    def _param_filtrele(self, metin: str):
        if not getattr(self, "_param_ui_hazir", False):
            return
        metin = metin.lower()
        for r in range(self._param_tablo.rowCount()):
            item = self._param_tablo.item(r, 0)
            if item:
                self._param_tablo.setRowHidden(r, metin not in item.text().lower())

    def _param_satir_duzenle(self, index):
        if not getattr(self, "_param_ui_hazir", False):
            return
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

    def _rapor_tikla(self):
        """📊 Rapor butonuna basılınca: önce mevcut veriyle rapor üret, tarayıcıda aç."""
        import webbrowser
        # Uçuş devam ediyorsa anlık rapor üret (durdurma)
        yol = self._son_rapor_yolu
        if not yol or not os.path.isfile(yol):
            try:
                yol = self._ucus_kaydedici.html_rapor_olustur()
                if yol:
                    self._son_rapor_yolu = yol
            except Exception as e:
                QMessageBox.warning(self, "Rapor Hatası", f"Rapor oluşturulamadı:\n{e}")
                return
        if yol and os.path.isfile(yol):
            self._mesaj_ekle(4, f"📊 Rapor açılıyor: {os.path.basename(yol)}")
            webbrowser.open(f"file:///{yol.replace(os.sep, '/')}")
        else:
            QMessageBox.information(self, "Rapor", "Henüz yeterli uçuş verisi yok.\nDrone'u bağla ve biraz uçur.")

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
        self._js(f"evNoktasiGuncelle({self._guncel_lat}, {self._guncel_lon});")
        self._mesaj_ekle(6, f"Ev noktası güncellendi: {self._guncel_lat:.5f}, {self._guncel_lon:.5f}")

    def _param_indir_tikla(self):
        if not self._bagli:
            QMessageBox.warning(self, "Bağlantı Yok", "Önce SITL/drone'a bağlanın.")
            return
        if not self._param_tab_hazir:
            self._param_tab_yukle()   # sekme henüz açılmamışsa önce oluştur
        self._param_tablo.setRowCount(0)
        self._param_satir_index.clear()
        self._param_tablo.setSortingEnabled(False)
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

    def _param_yedekle_tikla(self):
        """İndirilen parametreleri JSON dosyasına kaydeder."""
        if not self._param_cache:
            QMessageBox.warning(
                self, "Parametre Yok",
                "Önce 'Parametreleri İndir' ile parametreleri indirin.",
            )
            return

        import datetime
        varsayilan = f"param_yedek_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        dosya, _ = QFileDialog.getSaveFileName(
            self, "Parametre Yedeği Kaydet", varsayilan,
            "JSON Dosyası (*.json);;Tüm Dosyalar (*)"
        )
        if not dosya:
            return

        import json as _json
        cikti = {
            "_meta": {
                "tarih":   datetime.datetime.now().isoformat(timespec="seconds"),
                "baglanti": self._mavlink.baglanti_dizesi,
                "toplam":  len(self._param_cache),
            },
            "parametreler": self._param_cache,
        }
        try:
            with open(dosya, "w", encoding="utf-8") as f:
                _json.dump(cikti, f, indent=2, ensure_ascii=False)
            self._mesaj_ekle(4, f"✓ {len(self._param_cache)} parametre yedeklendi → {os.path.basename(dosya)}")
        except Exception as e:
            QMessageBox.critical(self, "Kayıt Hatası", str(e))

    def _param_geri_yukle_tikla(self):
        """JSON yedekten parametreleri drone'a gönderir."""
        if not self._bagli:
            QMessageBox.warning(self, "Bağlantı Yok", "Önce drone'a bağlanın.")
            return

        dosya, _ = QFileDialog.getOpenFileName(
            self, "Parametre Yedeği Aç", "",
            "JSON Dosyası (*.json);;Tüm Dosyalar (*)"
        )
        if not dosya:
            return

        import json as _json
        try:
            with open(dosya, encoding="utf-8") as f:
                veri = _json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "Okuma Hatası", str(e))
            return

        parametreler: dict = veri.get("parametreler", veri)
        meta = veri.get("_meta", {})
        tarih = meta.get("tarih", "?")

        yanit = QMessageBox.question(
            self, "Parametreleri Geri Yükle",
            f"{os.path.basename(dosya)}\n"
            f"Tarih: {tarih}\n"
            f"{len(parametreler)} parametre drone'a gönderilsin mi?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if yanit != QMessageBox.Yes:
            return

        self._mesaj_ekle(6, f"Parametre geri yükleme başlıyor ({len(parametreler)} parametre)…")
        gonderilen = 0
        for ad, deger in parametreler.items():
            self._mavlink.parametre_ayarla(ad, float(deger))
            gonderilen += 1

        self._mesaj_ekle(4, f"✓ {gonderilen} parametre gönderildi (yeniden başlatma gerekebilir).")

    def _harita_yol_temizle(self):
        self._js("ucusYolunuTemizle();")

    # ── Waypoint Görev Planlama ───────────────────────────────────────────────

    _WP_KOMUTLAR = ["NAV_WAYPOINT", "TAKEOFF", "LAND", "LOITER_TURNS",
                    "LOITER_TIME", "LOITER_UNLIMITED", "RTL", "DELAY"]
    _WP_KOMUT_KODLARI = {
        "NAV_WAYPOINT":       16,
        "TAKEOFF":            22,
        "LAND":               21,
        "LOITER_TURNS":       18,
        "LOITER_TIME":        19,
        "LOITER_UNLIMITED":   17,
        "RTL":                20,
        "DELAY":              93,
    }

    def _wp_tablo_yenile(self):
        """Python waypoint listesinden Qt tablosunu yeniden çizer."""
        import math as _math
        if not hasattr(self, '_wp_tablo'):
            return
        self._wp_tablo.blockSignals(True)
        self._wp_tablo.setRowCount(0)

        # Mesafe ve azimut ön-hesaplama
        mesafeler = [0.0]
        azimutlar = [0.0]
        for i in range(1, len(self._wp_listesi)):
            w0, w1 = self._wp_listesi[i - 1], self._wp_listesi[i]
            dlat = (w1['lat'] - w0['lat']) * 111000.0
            dlon = (w1['lon'] - w0['lon']) * 111000.0 * _math.cos(_math.radians(w0['lat']))
            seg = _math.hypot(dlat, dlon)
            mesafeler.append(seg)
            az = (_math.degrees(_math.atan2(dlon, dlat))) % 360.0
            azimutlar.append(az)

        _btn_stil = (
            "QPushButton { background:#1e2e3e; color:#9ab; border:1px solid #2a4060;"
            " border-radius:2px; font-size:12px; padding:0; }"
            "QPushButton:hover { background:#2a4060; }"
        )

        for i, wp in enumerate(self._wp_listesi):
            self._wp_tablo.insertRow(i)

            # Sütun 0 — sıra no
            no = QTableWidgetItem(str(i + 1))
            no.setFlags(no.flags() & ~Qt.ItemIsEditable)
            no.setTextAlignment(Qt.AlignCenter)

            # Sütun 2,3 — lat/lon (salt okunur)
            lat = QTableWidgetItem(f"{wp['lat']:.6f}")
            lat.setFlags(lat.flags() & ~Qt.ItemIsEditable)
            lon = QTableWidgetItem(f"{wp['lon']:.6f}")
            lon.setFlags(lon.flags() & ~Qt.ItemIsEditable)

            # Sütun 4 — irtifa (düzenlenebilir)
            alt = QTableWidgetItem(str(int(wp.get('alt', 50))))

            # Sütun 5 — mesafe (salt okunur)
            mes_str = f"{mesafeler[i]:.0f}" if i > 0 else "—"
            mes_item = QTableWidgetItem(mes_str)
            mes_item.setFlags(mes_item.flags() & ~Qt.ItemIsEditable)
            mes_item.setTextAlignment(Qt.AlignCenter)

            # Sütun 6 — azimut (salt okunur)
            az_str = f"{azimutlar[i]:.0f}" if i > 0 else "—"
            az_item = QTableWidgetItem(az_str)
            az_item.setFlags(az_item.flags() & ~Qt.ItemIsEditable)
            az_item.setTextAlignment(Qt.AlignCenter)

            self._wp_tablo.setItem(i, 0, no)
            self._wp_tablo.setItem(i, 2, lat)
            self._wp_tablo.setItem(i, 3, lon)
            self._wp_tablo.setItem(i, 4, alt)
            self._wp_tablo.setItem(i, 5, mes_item)
            self._wp_tablo.setItem(i, 6, az_item)

            # Sütun 1 — komut tipi (QComboBox)
            combo = QComboBox()
            combo.addItems(self._WP_KOMUTLAR)
            combo.setCurrentText(wp.get("komut", "NAV_WAYPOINT"))
            combo.setStyleSheet("background:#1a2a3a; color:#ddd; font-size:11px;")
            combo.currentTextChanged.connect(lambda t, idx=i: self._wp_komut_degisti(idx, t))
            self._wp_tablo.setCellWidget(i, 1, combo)

            # Sütun 7 — Yukarı / Aşağı butonları
            _btn_w = QWidget()
            _btn_lay = QHBoxLayout(_btn_w)
            _btn_lay.setContentsMargins(1, 1, 1, 1)
            _btn_lay.setSpacing(2)
            _up = QPushButton("↑")
            _up.setFixedSize(24, 22)
            _up.setStyleSheet(_btn_stil)
            _up.setEnabled(i > 0)
            _up.clicked.connect(lambda _, idx=i: self._wp_yukari(idx))
            _dn = QPushButton("↓")
            _dn.setFixedSize(24, 22)
            _dn.setStyleSheet(_btn_stil)
            _dn.setEnabled(i < len(self._wp_listesi) - 1)
            _dn.clicked.connect(lambda _, idx=i: self._wp_asagi(idx))
            _btn_lay.addWidget(_up)
            _btn_lay.addWidget(_dn)
            self._wp_tablo.setCellWidget(i, 7, _btn_w)

        self._wp_tablo.blockSignals(False)
        self._wp_profil_guncelle()

    def _wp_tablo_degisti(self, item):
        """Kullanıcı tabloda irtifayı çift tıklayıp değiştirince haritayı güncelle."""
        if item.column() != 4:   # Sütun 4 = İrtifa
            return
        idx = item.row()
        try:
            alt = max(5, int(item.text()))
            if idx < len(self._wp_listesi):
                self._wp_listesi[idx]['alt'] = alt
                self._js(f"wpIrtifaGuncelle({idx}, {alt});")
                self._wp_profil_guncelle()
        except (ValueError, IndexError):
            pass

    def _wp_komut_degisti(self, idx: int, komut: str):
        """WP tablosundaki komut tipi dropdown değişince listeyi güncelle."""
        if idx < len(self._wp_listesi):
            self._wp_listesi[idx]['komut'] = komut

    def _wp_yukari(self, idx: int):
        """Waypoint'i listede bir üste taşır."""
        if idx <= 0 or idx >= len(self._wp_listesi):
            return
        self._wp_listesi[idx - 1], self._wp_listesi[idx] = \
            self._wp_listesi[idx], self._wp_listesi[idx - 1]
        self._wp_tablo_yenile()
        self._wp_haritadan_yenile()

    def _wp_asagi(self, idx: int):
        """Waypoint'i listede bir alta taşır."""
        if idx < 0 or idx >= len(self._wp_listesi) - 1:
            return
        self._wp_listesi[idx], self._wp_listesi[idx + 1] = \
            self._wp_listesi[idx + 1], self._wp_listesi[idx]
        self._wp_tablo_yenile()
        self._wp_haritadan_yenile()

    def _wp_haritadan_yenile(self):
        """WP listesini JS haritasına yeniden gönderir (sıra değişiminden sonra)."""
        import json as _json
        self._js(f"wpListeYukle({_json.dumps(self._wp_listesi)});")

    def _wp_dosya_yukle(self):
        """QGC/Mission Planner .waypoints dosyasından WP listesini yükler."""
        yol, _ = QFileDialog.getOpenFileName(
            self, "Waypoint Dosyası Aç",
            "", "Waypoint Dosyaları (*.waypoints *.txt);;Tüm Dosyalar (*)"
        )
        if not yol:
            return
        try:
            yeni = []
            with open(yol, encoding="utf-8", errors="replace") as f:
                for satir in f:
                    satir = satir.strip()
                    if not satir or satir.startswith("QGC WPL") or satir.startswith("#"):
                        continue
                    parcalar = satir.split("\t")
                    if len(parcalar) < 12:
                        continue
                    try:
                        # Format: index current frame command p1 p2 p3 p4 lat lon alt autocont
                        cmd_id  = int(parcalar[3])
                        lat_f   = float(parcalar[8])
                        lon_f   = float(parcalar[9])
                        alt_f   = float(parcalar[10])
                        # Komut kodu → isim
                        _ters = {v: k for k, v in self._WP_KOMUT_KODLARI.items()}
                        komut = _ters.get(cmd_id, "NAV_WAYPOINT")
                        yeni.append({"lat": lat_f, "lon": lon_f, "alt": alt_f, "komut": komut})
                    except (ValueError, IndexError):
                        continue
            if not yeni:
                self._mesaj_ekle(3, "Dosyada geçerli waypoint bulunamadı.")
                return
            self._wp_listesi = yeni
            self._wp_tablo_yenile()
            self._wp_haritadan_yenile()
            self._mesaj_ekle(4, f"{len(yeni)} waypoint dosyadan yüklendi: {yol}")
        except Exception as exc:
            self._mesaj_ekle(3, f"WP dosya yükleme hatası: {exc}")

    def _wp_dosya_kaydet(self):
        """WP listesini QGC/Mission Planner .waypoints formatında kaydeder."""
        if not self._wp_listesi:
            self._mesaj_ekle(3, "Kaydedilecek waypoint yok.")
            return
        yol, _ = QFileDialog.getSaveFileName(
            self, "Waypoint Dosyası Kaydet",
            "gorev.waypoints", "Waypoint Dosyaları (*.waypoints);;Tüm Dosyalar (*)"
        )
        if not yol:
            return
        try:
            satirlar = ["QGC WPL 110"]
            # index | current | frame | command | p1 | p2 | p3 | p4 | lat | lon | alt | autocontinue
            for i, wp in enumerate(self._wp_listesi):
                cmd_id = self._WP_KOMUT_KODLARI.get(wp.get("komut", "NAV_WAYPOINT"), 16)
                current = 1 if i == 0 else 0
                satirlar.append(
                    f"{i}\t{current}\t3\t{cmd_id}\t0\t0\t0\t0"
                    f"\t{wp['lat']:.8f}\t{wp['lon']:.8f}\t{wp.get('alt', 50):.1f}\t1"
                )
            with open(yol, "w", encoding="utf-8") as f:
                f.write("\n".join(satirlar) + "\n")
            self._mesaj_ekle(4, f"{len(self._wp_listesi)} waypoint kaydedildi: {yol}")
        except Exception as exc:
            self._mesaj_ekle(3, f"WP dosya kaydetme hatası: {exc}")

    def _sesli_uyan(self, metin: str):
        """Arka planda TTS ile sesli uyarı verir (Windows SAPI / espeak)."""
        if not self._tts_aktif or self._tts_motor is None:
            return
        import threading
        def _konus():
            try:
                self._tts_motor.say(metin)
                self._tts_motor.runAndWait()
            except Exception:
                pass
        threading.Thread(target=_konus, daemon=True).start()

    def _wp_profil_guncelle(self):
        """WP listesinden irtifa profil grafiğini günceller (mesafe vs irtifa)."""
        import math as _math
        # Özet etiketlerini sıfırla
        _no_wp = len(self._wp_listesi)
        if hasattr(self, '_wp_wp_sayisi'):
            self._wp_wp_sayisi.setText(f"WP: {_no_wp}")
        if not hasattr(self, '_irtifa_grafik') or self._irtifa_grafik is None:
            return
        if not self._wp_listesi:
            self._irtifa_grafik_cizgi.setData([], [])
            if hasattr(self, '_irtifa_terrain_cizgi') and self._irtifa_terrain_cizgi:
                self._irtifa_terrain_cizgi.setData([], [])
            if hasattr(self, '_wp_mesafe_lbl'):
                self._wp_mesafe_lbl.setText("Toplam: — m")
                self._wp_sure_lbl.setText("Süre: — dk")
            return
        mesafeler = [0.0]
        for i in range(1, len(self._wp_listesi)):
            w0, w1 = self._wp_listesi[i - 1], self._wp_listesi[i]
            dlat = (w1['lat'] - w0['lat']) * 111000
            dlon = (w1['lon'] - w0['lon']) * 111000 * _math.cos(_math.radians(w0['lat']))
            mesafeler.append(mesafeler[-1] + _math.hypot(dlat, dlon))
        altlar = [wp.get('alt', 50) for wp in self._wp_listesi]
        self._irtifa_grafik_cizgi.setData(mesafeler, altlar)

        # Görev özet etiketlerini güncelle
        toplam_m = mesafeler[-1] if mesafeler else 0.0
        hiz_ms = float(_cfg.al("hiz_kisitlama.normal_cms", 1000)) / 100.0
        sure_s = toplam_m / hiz_ms if hiz_ms > 0 else 0
        if hasattr(self, '_wp_mesafe_lbl'):
            self._wp_mesafe_lbl.setText(f"Toplam: {toplam_m:.0f} m")
            self._wp_sure_lbl.setText(f"Süre: ~{sure_s / 60:.1f} dk")

        # Terrain profil thread'ini başlat (SRTM arka planda)
        if hasattr(self, '_terrain_profil_thread') and self._terrain_profil_thread \
                and self._terrain_profil_thread.isRunning():
            return   # Önceki sorgu hâlâ devam ediyor
        self._terrain_profil_thread = TerrainProfilThread(self._wp_listesi, mesafeler)
        self._terrain_profil_thread.tamamlandi.connect(self._terrain_profil_geldi)
        self._terrain_profil_thread.start()

    def _terrain_profil_geldi(self, mes: list, alt: list):
        """TerrainProfilThread sinyalini alır, terrain çizgisini günceller."""
        if hasattr(self, '_irtifa_terrain_cizgi') and self._irtifa_terrain_cizgi:
            self._irtifa_terrain_cizgi.setData(mes, alt)

    def _wp_yukle_baslat(self):
        """Waypoint listesini MAVLink MISSION protokolüyle drone'a yükler."""
        if not self._bagli:
            self._mesaj_ekle(3, "Bağlantı yok — önce drone'a bağlan.")
            return
        if not self._wp_listesi:
            self._mesaj_ekle(3, "Yüklenecek waypoint yok — haritaya tıklayarak ekle.")
            return
        self._mesaj_ekle(6, f"{len(self._wp_listesi)} waypoint drone'a yükleniyor…")
        self._mavlink.mission_yukle(self._wp_listesi)

    def _wp_oku_baslat(self):
        """Drone'daki waypoint listesini okur ve haritada gösterir."""
        if not self._bagli:
            self._mesaj_ekle(3, "Bağlantı yok — önce drone'a bağlan.")
            return
        self._mesaj_ekle(6, "Drone'daki waypointler okunuyor…")
        self._mavlink.mission_oku()

    def _wp_mission_yuklendi(self, basarili: bool, mesaj: str):
        """MAVLink MISSION upload sonucu."""
        if basarili:
            self._mesaj_ekle(4, f"✓ {mesaj}")
            # Başarılı yükleme → OTOMATİK moda geç
            self._mavlink.mod_degistir(3)
            self._mesaj_ekle(4, "OTOMATİK mod — görev başladı.")
            self._sesli_uyan("Görev yüklendi, otomatik mod başladı")
        else:
            self._mesaj_ekle(2, f"Waypoint yükleme hatası: {mesaj}")
            self._sesli_uyan("Görev yükleme başarısız")

    def _wp_mission_alindi(self, wp_listesi: list):
        """Drone'dan okunan waypoint listesi — haritaya aktar."""
        self._wp_listesi = wp_listesi
        self._wp_tablo_yenile()
        self._js(f"wpListeYukle({json.dumps(json.dumps(wp_listesi, ensure_ascii=False))});")
        self._mesaj_ekle(4, f"✓ {len(wp_listesi)} waypoint drone'dan okundu.")

    def _guvenli_noktalar_temizle(self):
        self._js("guvenliNoktalariTemizle(); durumGoster('');")


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

        self._js("document.getElementById('analizBtn').disabled=true;"
                 "durumGoster('Arazi verisi indiriliyor, analiz yapılıyor… (ilk kez ~15 sn)');")

        ruz_ms  = self._ruz_zemin_ms                       # Hellmann güç yasasıyla zemin tahmini
        ruz_yon = self._log_satiri.get("ruzgar_yon", 0.0)
        self._terrain_thread = TerrainAnalizThread(
            self._guncel_lat, self._guncel_lon, bat,
            ruzgar_ms=ruz_ms, ruzgar_yonu_derece=ruz_yon,
        )
        self._terrain_thread.tamamlandi.connect(self._guvenli_inis_tamamlandi)
        self._terrain_thread.hata.connect(self._guvenli_inis_hata)
        self._terrain_thread.start()

    def _guvenli_inis_tamamlandi(self, sonuc):
        self._js("document.getElementById('analizBtn').disabled=false;")
        self._son_analiz_sonucu = sonuc
        if not sonuc.basarili:
            self._js(f"durumGoster({json.dumps('Hata: ' + sonuc.hata)});")
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

        noktalar_json = json.dumps(json.dumps(noktalar))
        self._js(
            f"guvenliNoktalariGoster("
            f"JSON.parse({noktalar_json}), "
            f"{sonuc.yaricap_m:.0f}, "
            f"{sonuc.merkez_lat}, "
            f"{sonuc.merkez_lon});"
        )
        if sonuc.en_yakin_guvenli:
            g = sonuc.en_yakin_guvenli
            self._en_yakin_guvenli_nokta = (g.lat, g.lon)
            self._js(f"enYakinNoktayiKaydet({g.lat}, {g.lon});")

        ozet = sonuc.ozet()
        durum = f"Güvenli: {len(sonuc.guvenli_noktalar)} nokta  |  Riskli: {len(sonuc.riskli_noktalar)} nokta  |  {ozet}"
        self._js(f"durumGoster({json.dumps(durum)});")
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
        # Hedefe git — LIDAR tarama için en az 5m AGL
        irtifa = max(getattr(self, "_guncel_irtifa", 10.0), 5.0)
        self._mavlink.komut_gonder(
            _mu.mavlink.MAV_CMD_DO_REPOSITION,
            -1, 0, 0, 0, lat, lon, irtifa
        )
        # Tarama durumunu sıfırla
        self._inis_hedef  = (lat, lon)
        self._inis_lidar  = {}
        self._inis_denedi = {(round(lat, 5), round(lon, 5))}
        self._mesaj_ekle(6, f"Hedef: {lat:.5f}, {lon:.5f} — LIDAR tarama başlıyor (~14 sn)…")
        self._js("durumGoster('🔍 Hedefe gidiliyor — iniş öncesi LIDAR zemin taraması…');")
        # 8 sn sonra merkez ölçüm başlat (drone varış süresi)
        QTimer.singleShot(8000, self._dogrulama_merkez_olcum)

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
        self._js("document.getElementById('analizBtn').disabled=false;"
                 f"durumGoster({json.dumps('Analiz hatası: ' + mesaj)});")
        self._mesaj_ekle(3, f"Arazi analiz hatası: {mesaj}")

    # ── LIDAR Hover Tarama — Zemin Doğrulama ─────────────────────────────────

    def _inis_hedef_git(self, lat: float, lon: float, alt: float):
        """Drone'u belirtilen konuma GUIDED modda yönlendirir."""
        from pymavlink import mavutil as _mu
        self._mavlink.komut_gonder(
            _mu.mavlink.MAV_CMD_DO_REPOSITION,
            -1, 0, 0, 0, lat, lon, alt
        )

    def _dogrulama_merkez_olcum(self):
        """Adım 1: Merkez noktada LIDAR ölçümü al."""
        h = self._guncel_lidar_m
        if h is None:
            # LIDAR yok — eski davranış: direkt in
            self._mesaj_ekle(5, "LIDAR verisi yok — doğrulama atlandı, direkt iniş.")
            self._js("durumGoster('⚠ LIDAR yok — zemin doğrulaması atlandı, iniş başlıyor…');")
            self._inis_komutu_gonder()
            return
        self._inis_lidar["merkez"] = h
        lat, lon = self._inis_hedef
        irt = max(getattr(self, "_guncel_irtifa", 5.0), 5.0)
        # Kuzey +1 m: 1° lat ≈ 111 000 m → 1 m ≈ 0.000009°
        self._inis_hedef_git(lat + 9e-6, lon, irt)
        self._mesaj_ekle(6, f"LIDAR merkez: {h:.2f} m — kuzey ölçümüne gidiliyor…")
        QTimer.singleShot(3000, self._dogrulama_kuzey_olcum)

    def _dogrulama_kuzey_olcum(self):
        """Adım 2: Kuzey noktasında LIDAR ölçümü al, Doğuya yönel."""
        h = self._guncel_lidar_m
        if h is not None:
            self._inis_lidar["kuzey"] = h
        lat, lon = self._inis_hedef
        irt = max(getattr(self, "_guncel_irtifa", 5.0), 5.0)
        # Doğu +1 m: 1° lon ≈ 111 000 × cos(lat) m
        lon_offset = 9e-6 / math.cos(math.radians(lat))
        self._inis_hedef_git(lat, lon + lon_offset, irt)
        self._mesaj_ekle(6, f"LIDAR kuzey: {h:.2f if h else '?'} m — doğu ölçümüne gidiliyor…")
        QTimer.singleShot(3000, self._dogrulama_dogu_olcum)

    def _dogrulama_dogu_olcum(self):
        """Adım 3: Doğu noktasında LIDAR ölçümü al, hesapla."""
        h = self._guncel_lidar_m
        if h is not None:
            self._inis_lidar["dogu"] = h
        self._dogrulama_hesapla()

    def _dogrulama_hesapla(self):
        """Adım 4: 3 ölçümden gerçek zemin eğimini hesapla, karar ver."""
        lat, lon = self._inis_hedef
        irt = max(getattr(self, "_guncel_irtifa", 5.0), 5.0)
        ok = self._inis_lidar
        h0 = ok.get("merkez", 5.0)

        # Yeterli ölçüm yoksa doğrulama atla
        if len(ok) < 2:
            self._mesaj_ekle(5, "LIDAR okuması yetersiz — direkt iniş başlıyor.")
            self._inis_hedef_git(lat, lon, irt)
            QTimer.singleShot(2000, self._inis_komutu_gonder)
            return

        # Eğim hesabı: arctan(yükseklik_farkı / 1m yatay mesafe)
        egim_ns = math.degrees(math.atan(abs(h0 - ok.get("kuzey", h0)) / 1.0))
        egim_ew = math.degrees(math.atan(abs(h0 - ok.get("dogu",  h0)) / 1.0))
        gercek_egim = math.sqrt(egim_ns ** 2 + egim_ew ** 2)

        self._mesaj_ekle(6,
            f"LIDAR tarama sonucu: K/G={egim_ns:.1f}°  D/B={egim_ew:.1f}°  "
            f"→ toplam {gercek_egim:.1f}°"
        )

        # Hedefe geri dön, karar ver
        self._inis_hedef_git(lat, lon, irt)

        if gercek_egim <= 5.0:
            msg = f"✓ Zemin onaylandı — eğim {gercek_egim:.1f}°, iniş başlıyor."
            self._mesaj_ekle(4, msg)
            self._js(f"durumGoster({json.dumps(msg)});")
            QTimer.singleShot(2000, self._inis_komutu_gonder)
        elif gercek_egim <= 15.0:
            msg = f"⚠ Zemin eğimi {gercek_egim:.1f}° — riskli ama kabul edilebilir, iniş başlıyor."
            self._mesaj_ekle(3, msg)
            self._js(f"durumGoster({json.dumps(msg)});")
            QTimer.singleShot(2000, self._inis_komutu_gonder)
        else:
            msg = f"✗ Zemin eğimi {gercek_egim:.1f}° > 15° — bu nokta tehlikeli! Sıradaki deneniyor…"
            self._mesaj_ekle(2, msg)
            self._js(f"durumGoster({json.dumps(msg)});")
            self._inis_bir_sonraki_dene()

    def _inis_bir_sonraki_dene(self):
        """LIDAR taramayı geçemeyen nokta iptal — listeden sıradaki adayı dene."""
        son_analiz = getattr(self, "_son_analiz_sonucu", None)
        if son_analiz:
            adaylar = list(son_analiz.guvenli_noktalar) + list(son_analiz.riskli_noktalar)
            for n in adaylar:
                anahtar = (round(n.lat, 5), round(n.lon, 5))
                if anahtar not in self._inis_denedi:
                    self._inis_denedi.add(anahtar)
                    self._en_yakin_guvenli_nokta = (n.lat, n.lon)
                    self._mesaj_ekle(6,
                        f"Yeni hedef deneniyor: {n.lat:.5f}, {n.lon:.5f} "
                        f"(eğim {n.egim_derece:.1f}°)"
                    )
                    self._guvenli_inise_git(onay_sor=False)
                    return
        # Hiç aday kalmadı
        self._mesaj_ekle(2,
            "Tüm güvenli noktalar LIDAR tarafından reddedildi — operatör müdahalesi gerekli."
        )
        self._js("durumGoster("
                 "'✗ Hiçbir güvenli nokta zemin testini geçemedi — operatör müdahale etmeli!');")

    # ── Rally Point yükleme (Katman 2) ───────────────────────────────────────

    def _rally_yukle_baslat(self):
        """
        Terrain analizinden çıkan en iyi 5 noktayı ArduPilot'a
        Rally Point olarak yükler.  Ayrı bir QThread'de çalışır.
        """
        if not self._bagli:
            QMessageBox.warning(self, "Bağlantı Yok", "Önce drone'a bağlanın.")
            return

        npz = os.path.join(os.path.dirname(__file__), "alan_verisi.npz")
        if not os.path.isfile(npz):
            npz = "alan_verisi.npz"
        if not os.path.isfile(npz):
            QMessageBox.warning(
                self, "Dosya Yok",
                "alan_verisi.npz bulunamadı.\n"
                "Önce 'ucus_alani_hazirla.py' ile alanı hazırlayın.",
            )
            return

        dize = self._mavlink.baglanti_dizesi
        self._mesaj_ekle(6, f"Rally Point yükleme başlıyor ({dize})…")

        self._rally_thread = _RallyYuklemeThread(npz, dize, self._guncel_lat, self._guncel_lon)
        self._rally_thread.tamamlandi.connect(self._rally_yukle_tamamlandi)
        self._rally_thread.hata.connect(lambda m: self._mesaj_ekle(3, f"Rally hata: {m}"))
        self._rally_thread.start()

    def _rally_yukle_tamamlandi(self, basarili: bool, n: int):
        if basarili:
            self._mesaj_ekle(4, f"✓ {n} Rally Point ArduPilot'a yüklendi (Katman 2 aktif).")
        else:
            self._mesaj_ekle(3, f"✗ Rally Point yüklenemedi — log'u kontrol edin.")

    # ── GCS Failsafe ─────────────────────────────────────────────────────────

    def _gcs_failsafe_ayarla(self):
        """
        Bağlantı kurulunca çağrılır.
        FS_GCS_ENABLE=1 + FS_GCS_TIMEOUT → bağlantı kesilince RTL tetiklenir.
        parametre_ayarla artık thread-safe kuyruk üzerinden çalışır.
        """
        if not self._bagli:
            return
        timeout = int(_cfg.al("gcs_failsafe.timeout_s", 10))
        self._mavlink.parametre_ayarla("FS_GCS_ENABLE",  1.0)
        self._mavlink.parametre_ayarla("FS_GCS_TIMEOUT", float(timeout))
        self._mesaj_ekle(6, f"GCS Failsafe aktif — timeout={timeout}s (bağlantı kopunca RTL).")

    # ── ADSB çakışma uyarısı ──────────────────────────────────────────────────

    def _adsb_guncelle(self, icao: int, lat: float, lon: float,
                       alt: float, heading: float, callsign: str):
        """ADSB_VEHICLE — yakın hava aracı tespiti ve uyarı."""
        import math
        simdi = time.monotonic()
        self._adsb_araclar[icao] = {
            "lat": lat, "lon": lon, "alt": alt,
            "hdg": heading, "callsign": callsign, "t": simdi,
        }

        # 30sn görmeyenleri temizle
        eskiler = [k for k, v in self._adsb_araclar.items()
                   if simdi - v["t"] > 30.0]
        for k in eskiler:
            del self._adsb_araclar[k]
            self._adsb_son_uyari.pop(k, None)

        # Sayaç etiketi güncelle
        if hasattr(self, "_adsb_sayac_lbl"):
            n = len(self._adsb_araclar)
            renk = "#f44336" if n > 0 else "#4caf50"
            self._adsb_sayac_lbl.setText(f"ADSB: {n} araç")
            self._adsb_sayac_lbl.setStyleSheet(f"color:{renk};")

        # Mesafe hesapla (Haversine)
        if self._guncel_lat == 0.0 and self._guncel_lon == 0.0:
            return
        R = 6371000.0
        f1, f2 = math.radians(self._guncel_lat), math.radians(lat)
        df = math.radians(lat - self._guncel_lat)
        dl = math.radians(lon  - self._guncel_lon)
        a  = math.sin(df/2)**2 + math.cos(f1)*math.cos(f2)*math.sin(dl/2)**2
        mesafe_m = R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

        # Uyarı eşiği ve debounce (30sn)
        if mesafe_m < self._adsb_uyari_esik_m:
            son = self._adsb_son_uyari.get(icao, 0.0)
            if simdi - son >= 30.0:
                self._adsb_son_uyari[icao] = simdi
                cs = callsign if callsign else f"ICAO:{icao:06X}"
                self._mesaj_ekle(2,
                    f"⚠ ADSB UYARI: {cs}  {mesafe_m:.0f}m  "
                    f"alt={alt:.0f}m  hdg={heading:.0f}°")
                QApplication.beep()

        # Haritada göster
        cs_js = json.dumps(callsign.strip() if callsign else f"{icao:06X}")
        self._js(f"adsbGuncelle({icao},{lat},{lon},{alt:.0f},{heading:.0f},{cs_js});")

    # ── ESC telemetrisi ───────────────────────────────────────────────────────

    def _esc_guncelle(self, motorlar: list):
        """ESC_TELEMETRY — motor RPM, sıcaklık, voltaj etiketlerini günceller."""
        for m in motorlar:
            idx = m["motor"]
            if idx >= len(self._esc_lbls):
                continue
            lbls = self._esc_lbls[idx]
            rpm  = m["rpm"]
            tmp  = m["sicaklik"]
            vlt  = m["volt"]

            lbls["rpm"].setText(f"{rpm:5d}")

            # Sıcaklık renk kodu: normal < 60°C, dikkat 60-80°C, kritik 80°C+
            if tmp >= 80.0:
                renk = "#f44336"
                self._mesaj_ekle(3, f"ESC M{idx+1} AŞIRI SICAK: {tmp:.0f}°C!")
            elif tmp >= 60.0:
                renk = "#ffc107"
            else:
                renk = "#4caf50"
            lbls["sicaklik"].setText(f"{tmp:.0f}°C")
            lbls["sicaklik"].setStyleSheet(f"color:{renk};")
            lbls["volt"].setText(f"{vlt:.1f}V")

    # ── Terrain raporu ────────────────────────────────────────────────────────

    def _terrain_rapor_guncelle(self, yukseklik: float, bekleyen: int, yuklenen: int):
        """TERRAIN_REPORT — terrain follow yüksekliğini durum çubuğuna yazar."""
        if self._terrain_yukseklik_lbl is not None:
            self._terrain_yukseklik_lbl.setText(
                f"Arazi: {yukseklik:.1f}m  ▼{bekleyen}bkl ✓{yuklenen}yük"
            )

    # ── AC_Fence yükleme ──────────────────────────────────────────────────────

    def _fence_yukle_baslat(self):
        """
        alan_verisi.npz'deki bounding box'tan AC_Fence polygon oluşturur ve
        ArduPilot'a yükler.  Ayrı bir QThread'de çalışır.
        FENCE_ENABLE=1, FENCE_ACTION=1 (RTL) otomatik set edilir.
        """
        if not self._bagli:
            QMessageBox.warning(self, "Bağlantı Yok", "Önce drone'a bağlanın.")
            return

        npz = os.path.join(os.path.dirname(__file__), "alan_verisi.npz")
        if not os.path.isfile(npz):
            npz = "alan_verisi.npz"
        if not os.path.isfile(npz):
            QMessageBox.warning(
                self, "Dosya Yok",
                "alan_verisi.npz bulunamadı.\n"
                "Önce 'ucus_alani_hazirla.py' ile alanı hazırlayın.",
            )
            return

        alt_max      = float(_cfg.al("fence.alt_max", 120.0))
        fence_action = int(_cfg.al("fence.action", 1))
        dize         = self._mavlink.baglanti_dizesi
        self._mesaj_ekle(6, f"AC_Fence yükleme başlıyor ({dize}, "
                            f"alt_max={alt_max}m, eylem={fence_action})…")

        self._fence_thread = _FenceYuklemeThread(
            npz, dize, alt_max=alt_max, fence_action=fence_action
        )
        self._fence_thread.tamamlandi.connect(self._fence_yukle_tamamlandi)
        self._fence_thread.hata.connect(
            lambda m: self._mesaj_ekle(3, f"Fence hata: {m}")
        )
        self._fence_thread.start()

    def _fence_yukle_tamamlandi(self, basarili: bool):
        if basarili:
            self._mesaj_ekle(4, "✓ AC_Fence ArduPilot'a yüklendi — FENCE_ENABLE=1 (RTL aktif).")
            # NPZ'den bounds oku ve terrain karar yükle (fence = terrain alanıdır)
            _npz = os.path.join(os.path.dirname(__file__), "alan_verisi.npz")
            if not os.path.isfile(_npz):
                _npz = "alan_verisi.npz"
            if os.path.isfile(_npz):
                try:
                    import numpy as _np
                    _data = _np.load(_npz)
                    if "bounds" in _data:
                        _b = _data["bounds"]
                        self._alan_bounds = (float(_b[1]), float(_b[3]),
                                             float(_b[0]), float(_b[2]))
                        self._harita_terrain_sinir_goster()
                    if self._alan_karar is None:
                        from alan_inis_karar import AlanInisKarar
                        self._alan_karar = AlanInisKarar(_npz)
                        self._alan_hazirlik_yapildi = True
                        self._mesaj_ekle(6, "Terrain iniş kararı fence alanından yüklendi.")
                except Exception:
                    pass
            self._js("document.getElementById('fenceBtn').style.background='#1a4a1a';"
                     "document.getElementById('fenceBtn').style.borderColor='#3a9a3a';")
        else:
            self._mesaj_ekle(3, "✗ AC_Fence yüklenemedi — log'u kontrol edin.")

    # ── Genel ────────────────────────────────────────────────────────────────

    def _durum_guncelle(self, metin: str, renk: str):
        self._durum_bar.showMessage(metin)
        self._durum_bar.setStyleSheet(
            f"QStatusBar {{ background-color: #0a1520; color: {renk}; }}"
        )
        if hasattr(self, '_durum_led'):
            self._durum_led.setStyleSheet(f"color:{renk}; padding:0 2px;")
        if hasattr(self, '_durum_led'):
            self._durum_led.setStyleSheet(f"color:{renk}; padding:0 2px;")

    def showEvent(self, event):
        super().showEvent(event)

    def closeEvent(self, event):
        # Timer'ları durdur
        self._hb_timer.stop()
        self._log_timer.stop()
        self._js_timer.stop()
        self._js_kuyruk.clear()
        self._mini_js_kuyruk.clear()
        # Arka plan thread'lerini durdur (beklemez — sadece sinyaller kesilir)
        for t in (self._alan_hazirlik_thread, self._terrain_thread,
                  self._rally_thread, self._fence_thread):
            if t is not None and t.isRunning():
                t.terminate()
        self._mavlink.durdur()
        super().closeEvent(event)


# ── Açılış Ekranı ─────────────────────────────────────────────────────────────

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

        # Ortalama ekrana yerleştir
        ekran = QApplication.primaryScreen().geometry()
        self.move(
            ekran.center().x() - self.width()  // 2,
            ekran.center().y() - self.height() // 2,
        )

        # Arka plan
        self.setStyleSheet("background-color: #0d1117;")

        ana = QVBoxLayout(self)
        ana.setContentsMargins(56, 40, 56, 36)
        ana.setSpacing(0)

        # ── Üst: logo + başlık ───────────────────────────────────────────────
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

        # ── Orta: özellik listesi — her özellik ayrı satırda, wordwrap açık ──
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

        # ── Alt: progress bar + durum ────────────────────────────────────────
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
        from PyQt5.QtGui import QPainter, QPen
        super().paintEvent(event)
        p = QPainter(self)
        p.setPen(QPen(QColor("#21262d"), 1))
        p.drawRect(0, 0, self.width() - 1, self.height() - 1)


# ── Giriş noktası ─────────────────────────────────────────────────────────────

def main():
    # AA_ShareOpenGLContexts → WebEngine'in OpenGL context'ini uygulama ile paylaşır.
    # QApplication() ÖNCESINDE set edilmesi zorunludur; aksi hâlde Chromium renderer çöküyor.
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    app.setApplicationName("Türkçe GCS – Doğuş ÜNİ LÖP")

    # Açılış ekranı
    splash = SplashEkrani()

    def _splash_bitti():
        pencere = AnaPencere()
        pencere.show()
        splash.close()

    splash.tamamlandi.connect(_splash_bitti)
    splash.goster_ve_yukle()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
