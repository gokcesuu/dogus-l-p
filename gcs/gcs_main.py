"""
Doğuş Üniversitesi LÖP – Türkçe Yer İstasyonu (GCS)
Çalıştırmak için: python gcs_main.py
SITL bağlantısı: tcp:127.0.0.1:5762
"""

import os
import sys
import time
import threading

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
    QFileDialog, QStackedWidget, QComboBox, QSpinBox, QToolButton, QScrollArea,
)
from PyQt5.QtCore import Qt, QDateTime, QTimer, QThread, QSize, pyqtSignal as Signal
from PyQt5.QtGui import QFont, QColor, QIcon, QPixmap, QPainter, QPen, QBrush

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
    import importlib.util as _ilu
    TERRAIN_MEVCUT = _ilu.find_spec("terrain_analiz") is not None
except Exception:
    TERRAIN_MEVCUT = False

from gcs_logger import GCSLogger
from tile_cache import TileCacheSunucusu


def _harita_html_olustur() -> str:
    import os
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    try:
        css_icerik = open(os.path.join(static_dir, "leaflet.css"), encoding="utf-8").read()
        js_icerik  = open(os.path.join(static_dir, "leaflet.js"),  encoding="utf-8").read()
    except OSError:
        return HARITA_HTML  # statik dosya yoksa CDN'e geri dön
    return HARITA_HTML.replace(
        '<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>',
        f'<style>\n{css_icerik}\n</style>'
    ).replace(
        '<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>',
        f'<script>\n{js_icerik}\n</script>'
    )
from ucus_raporu import UcusKaydedici
import config_yukleyici as _cfg


from rtl_monitor import RtlIzleyici
from splash_screen import SplashEkrani
from analytics import AnalyticsCollector, extract_csv_row_to_dict
from analytics_widget import AnalyticsPanel
from ui_theme import (
    ACİL_STILI, BAĞLAN_STILI, KOYU_TEMA, UYARI_STILI,
    KOKPIT_ZEMIN, KOKPIT_PANEL, KOKPIT_KENAR, KOKPIT_VURGU, KOKPIT_VURGU2,
    KOKPIT_ACIL, KOKPIT_ACIL2, KOKPIT_BASARI,
    ACİL_STİLİ_KOKPIT, BAĞLAN_STİLİ_KOKPIT,
)

# ── Harita HTML (Leaflet.js) ──────────────────────────────────────────────────

HARITA_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<link rel="preconnect" href="https://fonts.gstatic.com">
<link href="https://fonts.googleapis.com/css2?family=Barlow:wght@400;500;600&family=Barlow+Condensed:wght@500;600;700&display=swap" rel="stylesheet">
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { width: 100%; height: 100%; overflow: hidden; background: #16222e; font-family: 'Barlow Condensed', 'Barlow', sans-serif; }
  #map { position: absolute; top: 0; left: 0; right: 0; bottom: 0; }
  #toolbar {
    position: absolute; top: 0; left: 0; right: 0; z-index: 1000;
    background: rgba(22,34,46,0.94);
    display: flex; align-items: center; gap: 4px;
    padding: 4px 6px; border-bottom: 1px solid rgba(148,188,227,0.22); height: 36px;
  }
  #toolbar button, .grp-btn {
    background: #1d2d3d; color: #bdd8f2; border: 1px solid rgba(148,188,227,0.28);
    border-radius: 4px; padding: 3px 10px; cursor: pointer; font-size: 12px; height: 28px;
    font-family: 'Barlow Condensed', sans-serif; font-weight: 600; letter-spacing: 0.02em;
  }
  #toolbar button:hover, .grp-btn:hover { background: rgba(148,188,227,0.16); }
  #toolbar button.green { background: #94bce3; color: #12202c; border-color: #94bce3; }
  #toolbar button.red   { background: #8f3b34; border-color: #c25b52; }
  #toolbar button:disabled { opacity: 0.4; cursor: default; }
  #konum { margin-left: auto; color: #7e9cb8; font-size: 11px; white-space: nowrap; }
  /* Dropdown grupları */
  .grp { position: relative; display: inline-block; }
  .grp-menu {
    display: none; position: absolute; top: 30px; left: 0; z-index: 2000;
    background: #1d2d3d; border: 1px solid rgba(148,188,227,0.22); border-radius: 4px;
    min-width: 160px; padding: 4px 0; box-shadow: 0 4px 12px rgba(0,0,0,0.6);
  }
  .grp:hover .grp-menu { display: block; }
  .grp-menu button {
    display: block; width: 100%; text-align: left;
    background: none; border: none; color: #bdd8f2;
    padding: 6px 14px; cursor: pointer; font-size: 12px; border-radius: 0;
    font-family: 'Barlow Condensed', sans-serif;
  }
  .grp-menu button:hover { background: rgba(148,188,227,0.14); }
  .grp-menu hr { border: none; border-top: 1px solid rgba(148,188,227,0.22); margin: 3px 0; }
  #durum {
    position: absolute; bottom: 8px; left: 50%; transform: translateX(-50%);
    z-index: 1000; background: rgba(22,34,46,0.92);
    color: #bdd8f2; font-size: 15px; padding: 7px 18px;
    border-radius: 4px; border: 1px solid rgba(148,188,227,0.28);
    display: none; white-space: nowrap;
    font-family: 'Barlow', sans-serif;
  }
  @keyframes inisHedefNabiz {
    0%   { transform: scale(0.7); opacity: 0.9; }
    70%  { transform: scale(2.2); opacity: 0; }
    100% { transform: scale(2.2); opacity: 0; }
  }
  .inis-hedef-nabiz {
    width: 22px; height: 22px; border-radius: 50%;
    background: rgba(0, 230, 118, 0.55);
    animation: inisHedefNabiz 1.4s ease-out infinite;
  }
</style>
</head>
<body>
<div id="map"></div>
<div id="toolbar">
  <!-- Katman seçici -->
  <select id="katmanSecici" onchange="katmanDegistir(this.value)"
    style="background:#1a2a3a;color:#7eb8e0;border:1px solid #2a4060;
           border-radius:3px;padding:2px 6px;font-size:11px;height:28px;cursor:pointer;">
    <option value="uydu">&#128752; Uydu</option>
    <option value="hibrit">&#127758; Hibrit</option>
    <option value="sokak">&#128506; Sokak</option>
    <option value="topo">&#9968; Kontur</option>
    <option value="gece">&#127761; Gece</option>
  </select>

  <!-- Drone odakla + yol temizle — sık kullanılan, doğrudan -->
  <button onclick="window.location.href='gcs://drone-git'">&#127988; Drone</button>
  <button onclick="window.location.href='gcs://ucus-yolu-temizle'">Yol Sil</button>

  <!-- WP grubu -->
  <div class="grp">
    <button class="grp-btn">&#128205; WP &#9662;</button>
    <div class="grp-menu">
      <button id="wpBtn" onclick="wpToggle()">&#9998; WP Ekle (haritadan)</button>
      <button id="gridBtn" onclick="gridToggle()">&#128196; Grid Tara</button>
      <button onclick="window.location.href='gcs://wp-yukle'">&#9654; Gorevi Yukle</button>
      <button onclick="window.location.href='gcs://wp-oku'">&#11015; Drone'dan Oku</button>
      <button onclick="wpTemizle();window.location.href='gcs://wp-temizle'">&#128465; WP Temizle</button>
    </div>
  </div>

  <!-- Fence grubu -->
  <div class="grp">
    <button class="grp-btn">&#128274; Fence &#9662;</button>
    <div class="grp-menu">
      <button id="fenceEditBtn" onclick="fenceToggle()">&#128312; Fence Ciz</button>
      <button onclick="fenceBitir()">&#10003; Fence Bitir</button>
      <button id="fenceBtn" onclick="window.location.href='gcs://fence-yukle'">&#128274; Fence Yukle</button>
      <button onclick="window.location.href='gcs://fence-polygon-yukle'">&#9989; Polygon Yukle</button>
      <button onclick="fenceTemizle()">&#128465; Fence Sil</button>
    </div>
  </div>

  <!-- Analiz grubu -->
  <div class="grp">
    <button class="grp-btn">&#128269; Analiz &#9662;</button>
    <div class="grp-menu">
      <button id="analizBtn" onclick="window.location.href='gcs://guvenli-inis-baslat'">&#9989; Guvenli Inis Analizi</button>
      <button onclick="window.location.href='gcs://analiz-temizle'">Analizi Temizle</button>
      <button id="inisBtn" disabled onclick="window.location.href='gcs://guvenli-inise-git'">&#128680; Guvenli Inise Git</button>
      <hr/>
      <button id="rallyBtn" onclick="window.location.href='gcs://rally-yukle'">&#128225; Rally Yukle</button>
      <button id="cizBtn" onclick="cizimBaslat()">&#9999; Alan Ciz</button>
      <button id="alanHazirlaBtn" onclick="window.location.href='gcs://alan-hazirla'">&#128205; Alani Yenile</button>
    </div>
  </div>

  <span id="konum" style="margin-left:auto;color:#7eb8e0;font-size:11px;white-space:nowrap;">--</span>
</div>
<div id="durum"></div>
<script>
var map = L.map('map', {zoomControl: true}).setView([40.9923, 29.1244], 13);
var _ERR_TILE = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';
var _ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services/';
// Sadece URL konfigürasyonları — L.tileLayer() seçilince oluşturulur (hafıza tasarrufu)
var _TILE_URL = {
  uydu:   {url: _ESRI + 'World_Imagery/MapServer/tile/{z}/{y}/{x}',           attr:'© Esri',    zoom:19},
  hibrit: {url: _ESRI + 'World_Imagery/MapServer/tile/{z}/{y}/{x}',           attr:'© Esri',    zoom:19, yerAdi:true, yol:true},
  sokak:  {url: 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', attr:'© CartoDB', zoom:19},
  topo:   {url: 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',           attr:'© OpenTopoMap',  zoom:17},
  gece:   {url: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', attr:'© CartoDB', zoom:19}
};
var _YERADI_URL = _ESRI + 'Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}';
var _YOL_URL = _ESRI + 'Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}';
var _aktifKatman = null;
var _yerAdiKatman = null;
var _yolKatman = null;

function katmanDegistir(isim) {
  // Eskiyi kaldır ve bellekten temizle
  if (_aktifKatman) { map.removeLayer(_aktifKatman); _aktifKatman = null; }
  if (_yerAdiKatman) { map.removeLayer(_yerAdiKatman); _yerAdiKatman = null; }
  if (_yolKatman) { map.removeLayer(_yolKatman); _yolKatman = null; }
  // Sadece seçilen katmanı oluştur
  var cfg = _TILE_URL[isim] || _TILE_URL.uydu;
  _aktifKatman = L.tileLayer(cfg.url, {attribution:cfg.attr, maxZoom:cfg.zoom, errorTileUrl:_ERR_TILE}).addTo(map);
  if (cfg.yol) {
    // Hibrit: uydu görüntüsü + yol/cadde çizgileri — Uydu'dan görsel olarak
    // net ayrışsın diye (eskiden sadece yer adı etiketi vardı, fark azdı)
    _yolKatman = L.tileLayer(_YOL_URL, {attribution:'', maxZoom:19, opacity:0.9, errorTileUrl:_ERR_TILE}).addTo(map);
  }
  if (cfg.yerAdi) {
    _yerAdiKatman = L.tileLayer(_YERADI_URL, {attribution:'', maxZoom:19, opacity:0.85, errorTileUrl:_ERR_TILE}).addTo(map);
  }
  var sel = document.getElementById('katmanSecici');
  if (sel) sel.value = isim;
}
katmanDegistir('uydu');   // başlangıçta sadece uydu yükle

// ── Harita boş alan sağ tık menüsü ──────────────────────────────────────────
var _sagTikPopup = null;
function _sagTikMenuKapat() {
  if (_sagTikPopup) { map.closePopup(_sagTikPopup); _sagTikPopup = null; }
}
map.on('contextmenu', function(e) {
  _sagTikMenuKapat();
  var lat = e.latlng.lat.toFixed(7);
  var lon = e.latlng.lng.toFixed(7);
  var icerik =
    '<div style="background:#0d1b2a;border:1px solid #2a4060;border-radius:4px;'
    + 'padding:4px 0;min-width:160px;font-size:12px;font-family:sans-serif;">'
    + '<div style="padding:3px 10px;color:#7eb8e0;font-size:10px;border-bottom:1px solid #2a4060;">'
    + lat + ', ' + lon + '</div>'
    + '<div style="cursor:pointer;padding:6px 12px;color:#80cbc4;"'
    + ' onmouseover="this.style.background=\\'#1a3050\\'" onmouseout="this.style.background=\\'\\'"'
    + ' onclick="_sagTikMenuKapat();window.location.href=\\'gcs://guided-git?lat=' + lat + '&lon=' + lon + '\\'">&#128681; Buraya git (GUIDED)</div>'
    + '<div style="cursor:pointer;padding:6px 12px;color:#a5d6a7;"'
    + ' onmouseover="this.style.background=\\'#1a3050\\'" onmouseout="this.style.background=\\'\\'"'
    + ' onclick="_sagTikMenuKapat();window.location.href=\\'gcs://wp-ekle-koordinat?lat=' + lat + '&lon=' + lon + '\\'">&#128205; WP Ekle</div>'
    + '</div>';
  _sagTikPopup = L.popup({closeButton:false, offset:[0,0], className:'sagTikPopup'})
    .setLatLng(e.latlng).setContent(icerik).openOn(map);
});
map.on('click', function() { _sagTikMenuKapat(); });

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
  if (typeof inisReddedilenKatman !== 'undefined') { inisReddedilenKatman.clearLayers(); }
  if (typeof lidarTaramaKatman !== 'undefined') { lidarTaramaKatman.clearLayers(); }
  if (typeof inisHedefTemizle === 'function') { inisHedefTemizle(); }
}

// ── LIDAR hover tarama görselleştirmesi ──────────────────────────────────────
var lidarTaramaKatman    = L.layerGroup().addTo(map);   // canlı tarama noktaları (her denemede silinir)
var inisReddedilenKatman = L.layerGroup().addTo(map);   // reddedilen noktalar (geçmiş — kalıcı)
var inisHedefMarker      = null;   // aktif hedefteki nabız animasyonu

function lidarTaramaGoster(lat, lon, etiket, yukseklikStr) {
  L.circleMarker([lat, lon], {
    radius: 6, color: '#29b6f6', fillColor: '#29b6f6',
    fillOpacity: 0.85, weight: 2,
  }).bindTooltip(
    '<b>LIDAR — ' + etiket + '</b><br>Mesafe: ' + yukseklikStr + ' m',
    {permanent: false, direction: 'top'}
  ).addTo(lidarTaramaKatman);
}

function lidarTaramaTemizle() {
  lidarTaramaKatman.clearLayers();
}

function inisNoktasiReddet(lat, lon, egimStr) {
  L.circle([lat, lon], {
    radius: 45, color: '#ef5350', fillColor: '#ef5350',
    fillOpacity: 0.45, weight: 2, dashArray: '4,3',
  }).bindTooltip(
    '<b>✗ Reddedildi</b><br>LIDAR eğimi: ' + egimStr + '°',
    {sticky: true}
  ).addTo(inisReddedilenKatman);
}

function inisHedefGoster(lat, lon) {
  inisHedefTemizle();
  inisHedefMarker = L.marker([lat, lon], {
    icon: L.divIcon({
      html: '<div class="inis-hedef-nabiz"></div>',
      iconSize: [22, 22], iconAnchor: [11, 11], className: '',
    }),
    zIndexOffset: 1000,
  }).addTo(map);
}

function inisHedefTemizle() {
  if (inisHedefMarker) { map.removeLayer(inisHedefMarker); inisHedefMarker = null; }
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

// Dışarıdan (sağ tık menüsü veya Python) WP eklemek için
function wpEkle(lat, lon, alt) {
  var wp = {lat: lat, lon: lon, alt: alt || _wpDefAlt, komut: 'NAV_WAYPOINT'};
  wpListesi.push(wp);
  _wpMarkerEkle(wpListesi.length - 1);
  _wpYoluGuncelle();
  _wpTabloGonder();
  durumGoster('WP ' + wpListesi.length + ' eklendi — ' + lat.toFixed(5) + ', ' + lon.toFixed(5));
}

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
      + ' onmouseover="this.style.background=\\'#2a1a1a\\'" onmouseout="this.style.background=\\'\\'"'
      + ' onclick="_wpCtxKapat();wpSil(' + idx + ')">Sil</div>'
      + '<div class="wp-ctx-item" style="cursor:pointer;padding:4px 12px;color:#80cbc4;"'
      + ' onmouseover="this.style.background=\\'#1a2a2a\\'" onmouseout="this.style.background=\\'\\'"'
      + ' onclick="_wpCtxKapat();wpKomutDegistir(' + idx + ',\\'LOITER_UNLIMITED\\')">Loiter Yap</div>'
      + '<div class="wp-ctx-item" style="cursor:pointer;padding:4px 12px;color:#a5d6a7;"'
      + ' onmouseover="this.style.background=\\'#1a2a1a\\'" onmouseout="this.style.background=\\'\\'"'
      + ' onclick="_wpCtxKapat();wpKomutDegistir(' + idx + ',\\'TAKEOFF\\')">Takeoff Yap</div>'
      + '<div class="wp-ctx-item" style="cursor:pointer;padding:4px 12px;color:#ffcc80;"'
      + ' onmouseover="this.style.background=\\'#2a2a1a\\'" onmouseout="this.style.background=\\'\\'"'
      + ' onclick="_wpCtxKapat();wpKomutDegistir(' + idx + ',\\'LAND\\')">Land Yap</div>'
      + '<div class="wp-ctx-item" style="cursor:pointer;padding:4px 12px;color:#90caf9;"'
      + ' onmouseover="this.style.background=\\'#1a1a2a\\'" onmouseout="this.style.background=\\'\\'"'
      + ' onclick="_wpCtxKapat();wpKomutDegistir(' + idx + ',\\'DO_LAND_START\\')">İniş Başlangıcı Yap</div>'
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

function wpAktifVurgula(idx) {
  /* Drone'un aktif WP'sini yeşil, diğerlerini sarı göster. */
  wpMarkerlar.forEach(function(m, i) {
    var aktif = (i === idx);
    m.setIcon(L.divIcon({
      html: '<div style="background:' + (aktif ? '#00e676' : '#ffeb3b')
          + ';color:#000;border-radius:50%;width:22px;height:22px;'
          + 'display:flex;align-items:center;justify-content:center;'
          + 'font-size:11px;font-weight:bold;border:2px solid '
          + (aktif ? '#00c853' : '#f57f17') + ';">' + (i+1) + '</div>',
      iconSize: [22,22], iconAnchor: [11,11], className: ''
    }));
    if (aktif && m.getTooltip()) m.openTooltip();
  });
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
  durumGoster(liste.length + ' waypoint drone\\'dan yüklendi');
}

// ── Geofence Polygon Editörü ────────────────────────────────────────────────
var fenceModAktif  = false;
var fenceNoktalar  = [];   // [[lat,lon], ...]
var fenceMarkerlar = [];
var fencePolygon   = null;

function fenceEditModAc() {
  fenceModAktif = true;
  map.getContainer().style.cursor = 'crosshair';
  document.getElementById('fenceEditBtn').style.borderColor = '#e040fb';
  document.getElementById('fenceEditBtn').style.background  = '#2a003a';
  durumGoster('🔷 Fence modu: Haritaya tıklayarak köşe ekleyin, bitirmek için "Fence Bitir"e basın');
}
function fenceEditModKapat() {
  fenceModAktif = false;
  map.getContainer().style.cursor = '';
  document.getElementById('fenceEditBtn').style.borderColor = '#6a3a9a';
  document.getElementById('fenceEditBtn').style.background  = '#2a1a4a';
}
function fenceToggle() {
  if (fenceModAktif) { fenceEditModKapat(); } else { fenceEditModAc(); }
}
function fenceBitir() {
  fenceEditModKapat();
  if (fenceNoktalar.length < 3) {
    durumGoster('⚠ En az 3 köşe gerekli!');
    return;
  }
  // Kapat (ilk noktayı sona ekle)
  _fencePolygonGuncelle();
  window.location.href = 'gcs://fence-cizildi?data=' + encodeURIComponent(JSON.stringify(fenceNoktalar));
  durumGoster('🔷 Fence polygon gönderildi (' + fenceNoktalar.length + ' köşe) — Fence Yükle ile drone\\'a gönderin');
}
function fenceTemizle() {
  fenceMarkerlar.forEach(function(m) { map.removeLayer(m); });
  fenceNoktalar = []; fenceMarkerlar = [];
  if (fencePolygon) { map.removeLayer(fencePolygon); fencePolygon = null; }
  fenceEditModKapat();
  durumGoster('Fence temizlendi');
}
function _fenceNoktaEkle(lat, lon) {
  var idx = fenceNoktalar.length;
  fenceNoktalar.push([lat, lon]);
  var ikon = L.divIcon({
    html: '<div style="background:#e040fb;color:#fff;border-radius:50%;width:18px;height:18px;'
        + 'display:flex;align-items:center;justify-content:center;font-size:10px;'
        + 'font-weight:bold;border:2px solid #aa00ff;">' + (idx+1) + '</div>',
    iconSize: [18,18], iconAnchor: [9,9], className: ''
  });
  var m = L.marker([lat, lon], {icon: ikon, draggable: true}).addTo(map);
  m.bindTooltip('Fence ' + (idx+1) + '<br>' + lat.toFixed(5) + ', ' + lon.toFixed(5) + '<br><i>Sağ tık → sil</i>', {sticky:true});
  m.on('drag', function(ev) {
    fenceNoktalar[idx] = [ev.latlng.lat, ev.latlng.lng];
    _fencePolygonGuncelle();
  });
  m.on('contextmenu', function() {
    map.removeLayer(m);
    fenceNoktalar.splice(idx, 1);
    fenceMarkerlar.splice(idx, 1);
    _fencePolygonGuncelle();
  });
  fenceMarkerlar.push(m);
  _fencePolygonGuncelle();
}
function _fencePolygonGuncelle() {
  if (fencePolygon) map.removeLayer(fencePolygon);
  if (fenceNoktalar.length < 2) { fencePolygon = null; return; }
  fencePolygon = L.polygon(fenceNoktalar, {
    color: '#e040fb', weight: 2, fillOpacity: 0.08
  }).addTo(map);
}

// Harita click handler — fence modunda tıklama
(function() {
  var _origClick = map._events && map._events.click;
})();
map.on('click', function(e) {
  if (fenceModAktif) {
    _fenceNoktaEkle(e.latlng.lat, e.latlng.lng);
  }
});

// Python → JS: fence noktalarını haritaya yükle (drone'dan okunan)
function fenceListeGoster(noktalarJsonStr) {
  fenceTemizle();
  var liste = JSON.parse(noktalarJsonStr);
  liste.forEach(function(n) { _fenceNoktaEkle(n[0], n[1]); });
  if (liste.length > 0) {
    map.fitBounds(fencePolygon ? fencePolygon.getBounds() : map.getBounds(), {padding:[30,30]});
  }
  durumGoster('Fence: ' + liste.length + ' köşe yüklendi');
}

// Grid Generator — paralel çizgi WP üretici
var gridPolygon   = null;
var gridNoktalar  = [];
var gridModAktif  = false;
var gridBaslangic = null;
var gridGeciciRect= null;

function gridModAc() {
  gridModAktif = true;
  map.getContainer().style.cursor = 'crosshair';
  document.getElementById('gridBtn').style.borderColor = '#00bcd4';
  document.getElementById('gridBtn').style.background  = '#002a30';
  durumGoster('📐 Grid modu: Sol tıkla-sürükle alanı çiz, bırakınca grid WP\\'leri oluşturulur');
}
function gridModKapat() {
  gridModAktif = false;
  map.getContainer().style.cursor = '';
  var btn = document.getElementById('gridBtn');
  if (btn) { btn.style.borderColor = '#2a6060'; btn.style.background = '#1a3050'; }
}
function gridToggle() {
  if (gridModAktif) { gridModKapat(); } else { gridModAc(); }
}

map.on('mousedown', function(e) {
  if (!gridModAktif) return;
  L.DomEvent.stop(e);
  gridBaslangic = e.latlng;
  if (gridGeciciRect) { map.removeLayer(gridGeciciRect); gridGeciciRect = null; }
});
map.on('mousemove', function(e) {
  if (!gridModAktif || !gridBaslangic) return;
  var b = L.latLngBounds(gridBaslangic, e.latlng);
  if (gridGeciciRect) { gridGeciciRect.setBounds(b); }
  else { gridGeciciRect = L.rectangle(b, {color:'#00bcd4', weight:2, fillOpacity:0.06}).addTo(map); }
});
map.on('mouseup', function(e) {
  if (!gridModAktif || !gridBaslangic) return;
  var b   = L.latLngBounds(gridBaslangic, e.latlng);
  var sw  = b.getSouthWest(), ne = b.getNorthEast();
  gridBaslangic = null;
  gridModKapat();
  if (gridGeciciRect) { map.removeLayer(gridGeciciRect); gridGeciciRect = null; }
  window.location.href = 'gcs://grid-uret?lat1=' + sw.lat + '&lon1=' + sw.lng
      + '&lat2=' + ne.lat + '&lon2=' + ne.lng;
});
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
<link rel="preconnect" href="https://fonts.gstatic.com">
<link href="https://fonts.googleapis.com/css2?family=Barlow:wght@400;500;600&family=Barlow+Condensed:wght@500;600;700&display=swap" rel="stylesheet">
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
    <option value="topo">Kontur</option>
    <option value="gece">Gece</option>
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
  uydu:  {url: _ESRI + 'World_Imagery/MapServer/tile/{z}/{y}/{x}',                           attr:'Esri',    zoom:19},
  sokak: {url: 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png',   attr:'CartoDB', zoom:19},
  topo:  {url: 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',                           attr:'OpenTopoMap', zoom:17},
  gece:  {url: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',              attr:'CartoDB', zoom:19}
};
var map = L.map('map', {zoomControl:true, attributionControl:false, preferCanvas:true})
           .setView([40.9923, 29.1244], 13);
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


if HARITA_MEVCUT:
    from map_bridge import HaritaSayfa, MiniHaritaSayfa
else:
    HaritaSayfa = MiniHaritaSayfa = None

from workers import (
    _FenceYuklemeThread,
    _RallyYuklemeThread,
    AlanHazirlikThread,
    TerrainAnalizThread,
    TerrainProfilThread,
)


# ── Ana Pencere ───────────────────────────────────────────────────────────────

class AnaPencere(QMainWindow):
    _BADGE = "border-radius:3px; padding:2px 8px; font-size:10px;"

    @staticmethod
    def _rozet_html(etiket: str, deger: str, renk: str = "#bdd8f2") -> str:
        """Tasarımdaki 'küçük etiket üstte / kalın değer altta' rozet biçimi."""
        return (
            f'<div style="line-height:1.2">'
            f'<span style="font-size:9px;letter-spacing:0.1em;color:#7e9cb8;">{etiket}</span><br>'
            f'<b style="font-size:13px;letter-spacing:0.04em;color:{renk};">{deger}</b>'
            f'</div>'
        )

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Doğuş ÜNİ – Türkçe Yer İstasyonu v0.2")
        self.resize(1366, 800)
        self.setMinimumSize(900, 600)
        self.setStyleSheet(KOYU_TEMA)

        # Tile cache proxy sunucusunu başlat
        from tile_cache import _TileHandler
        _TileHandler._harita_html_fn = _harita_html_olustur
        self._tile_sunucu = TileCacheSunucusu()
        self._tile_sunucu.start()

        self._mavlink = MAVLinkBaglantisi()
        self._sinyalleri_bagla()
        self._ui_olustur()

        # Heartbeat izleme timer'ı (2 sn'de bir) — worker (MAVLink) thread'inin
        # canlılığını izler.
        self._hb_timer = QTimer()
        self._hb_timer.setInterval(2000)
        self._hb_timer.timeout.connect(self._heartbeat_kontrol)

        # UI thread nabzı — ayrı, Qt event loop'undan bağımsız bir watchdog
        # thread'i bu sayacın ilerleyip ilerlemediğini kontrol eder. Worker
        # heartbeat'inden (_hb_timer/_heartbeat_kontrol, MAVLink thread'ini
        # izler) BİLİNÇLİ olarak ayrı: UI thread donarsa Qt sinyalleri de
        # tetiklenmeyebileceğinden, gözlemci Qt'ye bağımlı olmayan plain bir
        # thread olmalı.
        self._ui_nabiz = 0
        self._ui_nabiz_timer = QTimer()
        self._ui_nabiz_timer.setInterval(500)
        self._ui_nabiz_timer.timeout.connect(self._ui_nabiz_artir)
        self._ui_nabiz_timer.start()
        self._ui_watchdog_baslat()

        # Harita JS kuyruğu — tüm runJavaScript çağrıları buradan geçer,
        # asla sinyal/event handler içinden doğrudan çağrılmaz (re-entrancy crash önlemi)
        self._harita_bekleyen_lat: "float | None" = None
        self._harita_bekleyen_lon: "float | None" = None
        self._js_kuyruk: list = []          # bekleyen JS parçacıkları
        self._js_timer = QTimer()
        self._js_timer.setInterval(200)     # 5 Hz — harita akıcı, renderer daha rahat
        # HUD etiketleri (VFR vb.) için rate-limit kuyruğu — sık gelen
        # MAVLink mesajlarında (örn. VFR_HUD 10Hz) her seferinde setText
        # yerine son değer burada tutulur, aynı 5Hz timer'da tek seferde
        # boyanır (drop-oldest: aradaki eski örnekler otomatik atlanır).
        self._hud_kuyruk: dict = {}
        self._js_timer.timeout.connect(self._hud_flush)
        # Önce GPS buffer'ını kuyruğa ekle, sonra kuyruğu tek çağrıyla flush et
        self._js_timer.timeout.connect(self._harita_js_guncelle)
        self._js_timer.timeout.connect(self._js_temizle)
        self._js_timer.start()
        # Eski isim → yeni isim takma adı (eski referanslar bozulmasın)
        self._harita_js_timer = self._js_timer

        self._guncel_irtifa = 0.0
        self._guncel_lat = 0.0
        self._guncel_lon = 0.0
        self._ev_lat = 0.0
        self._logger = GCSLogger()
        self._ucus_kaydedici = UcusKaydedici()   # uçuş sonrası HTML rapor için
        self._son_rapor_yolu      = ""      # son üretilen HTML rapor yolu
        self._onceki_arm_durumu   = False   # bir önceki heartbeat'teki ARM durumu
        self._ucus_yapildi        = False   # bu bağlantıda en az bir kez ARM oldu mu
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
        self._ruz_ema_alpha    = float(_cfg.al("ruzgar.ema_alpha", 0.25))  # filtre katsayısı

        # Rüzgar gradient modeli (Hellmann Güç Yasası)
        self._ruz_hellmann       = float(_cfg.al("ruzgar.hellmann_alpha", 0.14))
        self._ruz_zemin_ref_m    = float(_cfg.al("ruzgar.zemin_ref_m",   2.0))
        self._ruz_trend_pencere  = int(_cfg.al("ruzgar.trend_pencere_sn", 60))
        self._ruz_zemin_ms       = 0.0   # Hellmann ile tahmin edilen zemin rüzgarı (m/s)
        self._ruz_trend_ms_per_s = 0.0   # Trend: m/s/saniye (+ artıyor, - azalıyor)
        # Gust irtifa yönetimi
        self._ruz_irtifa_ayarli  = False  # Şu an gust nedeniyle irtifa düşürüldü mü
        self._ruz_irtifa_onceki  = 0.0    # Gust öncesi irtifa — geri çıkmak için
        self._arm_durumu         = False  # Son heartbeat'ten ARM durumu
        # Sürekli yüksek rüzgar irtifa yönetimi (gust değil, EMA yüksek)
        self._ruz_surekli_ayarli      = False   # EMA nedeniyle irtifa düşürüldü mü
        self._ruz_surekli_irt_onceki  = 0.0     # Önceki irtifa
        self._ruz_surekli_son_t       = 0.0     # Son kontrol zamanı
        # Trend bazlı irtifa yönetimi
        self._ruz_trend_irtifa_verildi = False   # Trend uyarısı sonrası irtifa komutu verildi mi
        # Hız kısıtlaması
        self._ruz_hiz_kisitlandi      = False    # Rüzgar nedeniyle hız düşürüldü mü
        self._ruz_hiz_onceki          = 0.0      # Önceki hız (m/s)
        self._ruz_trend_esik     = float(_cfg.al("ruzgar.trend_esik", 0.03))  # ↑↓→ gösterge eşiği
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
        self._ekf_ruzgar_gecerli  = False   # EKF_STATUS_REPORT bayrak 0+1+2 (tutum+yatay+dikey hız)
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
        self._fence_noktalar: list = []        # haritadan çizilen fence polygon [[lat,lon], ...]
        self._alan_hazirlik_yapildi = False   # ilk GPS fix'te bir kez tetikle
        self._wp_listesi: list = []            # waypoint görev listesi [{lat,lon,alt}, ...]
        # RC / Fence / WP aktif takip
        self._rc_failsafe_aktif = False
        self._fence_ihlal_son   = 0
        self._aktif_wp_seq      = 0
        self._adsb_tts_son: dict = {}          # {icao: monotonic_zaman} — TTS spam önleme
        # Batarya hücre takibi
        self._min_hucre_volt    = 0.0          # BATTERY_STATUS'tan, 0=bilinmiyor
        self._alan_bounds: "tuple | None" = None  # (lat_min, lat_max, lon_min, lon_max)
        self._alan_karar_yukleniyor = False   # arka plan okuma sürerken yazma/yeniden-indirme tetiklenmesin
         
        # Analytics Collector (real-time metrics)
        _hucre_sayisi = int(_cfg.al("batarya.hucre_sayisi", 4))
        _nominal_v = float(_cfg.al("batarya.hucre_sayisi", 4)) * 4.2  # nom = 4.2V/hücre
        self._analytics = AnalyticsCollector(battery_nominal_v=_nominal_v, cell_count=_hucre_sayisi)
        self._analytics_panel: "AnalyticsPanel | None" = None
         
        _npz = os.path.join(os.path.dirname(__file__), "alan_verisi.npz")
        if not os.path.isfile(_npz):
            _npz = "alan_verisi.npz"       # çalışma dizininde ara
        if os.path.isfile(_npz):
            # np.load + AlanInisKarar ağır olabilir — main thread'i bloklamasın,
            # arka planda yüklenip sonuç QTimer.singleShot(0, ...) ile UI'a aktarılır.
            self._alan_karar_yukleniyor = True
            import threading as _threading_init
            _threading_init.Thread(
                target=self._alan_karar_arka_planda_yukle, args=(_npz,), daemon=True
            ).start()

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
        m.vfr_guncellendi.connect(self._gauge_vfr_guncelle)
        m.batarya_guncellendi.connect(self._gauge_bat_guncelle)
        m.gps_guncellendi.connect(self._gauge_gps_guncelle)
        m.gps_guncellendi.connect(self._gps_guncelle)
        m.gps_guncellendi.connect(self._prearm_gps_guncelle)
        m.tutum_guncellendi.connect(self._tutum_guncelle)
        m.ruzgar_guncellendi.connect(self._ruzgar_guncelle)
        m.lidar_guncellendi.connect(self._lidar_guncelle)
        m.imu_sicakligi.connect(self._imu_guncelle)
        m.imu_sicakligi.connect(self._prearm_imu_guncelle)
        m.durum_mesaji.connect(self._mesaj_ekle)
        m.durum_mesaji.connect(self._prearm_mesaj_isle)
        m.ekf_durumu.connect(self._ekf_guncelle)
        m.ekf_durumu.connect(self._prearm_ekf_guncelle)
        m.batarya_guncellendi.connect(self._prearm_batarya_guncelle)
        m.rc_guncellendi.connect(self._prearm_rc_guncelle)
        m.kalp_atisi.connect(self._prearm_arm_guncelle)
        m.vibrasyon_guncellendi.connect(self._vibrasyon_guncelle)
        m.parametre_guncellendi.connect(self._param_guncelle)
        m.parametre_tamamlandi.connect(self._param_tamam)
        m.adsb_guncellendi.connect(self._adsb_guncelle)
        m.esc_guncellendi.connect(self._esc_guncelle)
        m.terrain_rapor.connect(self._terrain_rapor_guncelle)
        m.mission_yuklendi.connect(self._wp_mission_yuklendi)
        m.mission_alindi.connect(self._wp_mission_alindi)
        m.mission_wp_degisti.connect(self._mission_wp_degisti)
        m.komut_onaylandi.connect(self._komut_onaylandi)
        m.rc_guncellendi.connect(self._rc_guncellendi)
        m.fence_ihlal.connect(self._fence_ihlal_handler)
        m.ev_noktasi_guncellendi.connect(self._ev_noktasi_guncelle)
        m.batarya_hucre_guncellendi.connect(self._batarya_hucre_guncelle)
        m.servo_doyum_guncellendi.connect(self._servo_doyum_guncelle)

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

        # ── Kalıcı acil şerit — 1B tasarımı: HER ekranda görünür, sekmeye
        # gömülü değil (bkz. READMEe.md). _kontrol_serit() acil/mod/diğer
        # butonlarını içeriyor, davranışı değişmedi — sadece yeri değişti.
        ana.addWidget(self._kontrol_serit())

        # ── Gövde: sol dikey ray (96px) + sağ içerik stack'i ──────────────────
        govde = QHBoxLayout()
        govde.setSpacing(0)
        govde.setContentsMargins(0, 0, 0, 0)

        self._icerik_stack = QStackedWidget()

        UCUS_IDX, PARAM_IDX, PREARM_IDX, LOG_IDX, ANALYTICS_IDX = 0, 1, 2, 3, 4
        self._param_tab_index = PARAM_IDX
        self._harita_tab_index = UCUS_IDX   # harita artık Uçuş ekranının parçası
        self._analytics_tab_index = ANALYTICS_IDX

        self._icerik_stack.addWidget(self._ana_sekme())          # 0: UÇUŞ

        self._param_tab_hazir = False
        self._param_stack = QStackedWidget()
        _pk = QLabel("Parametreler yükleniyor…")
        _pk.setAlignment(Qt.AlignCenter)
        self._param_stack.addWidget(_pk)                          # index 0 = placeholder
        self._icerik_stack.addWidget(self._param_stack)           # 1: PARAM

        self._icerik_stack.addWidget(self._prearm_sekme())        # 2: PRE-ARM
        self._icerik_stack.addWidget(self._log_sekme())           # 3: LOG
         
        # Analytics sekmesi
        self._analytics_panel = AnalyticsPanel()
        self._icerik_stack.addWidget(self._analytics_panel)       # 4: ANALYTICS

        govde.addWidget(self._nav_ray_olustur(), 0)
        govde.addWidget(self._icerik_stack, 1)
        ana.addLayout(govde)

        self._durum_bar = QStatusBar()
        self.setStatusBar(self._durum_bar)

    # ── Dikey ray (1B navigasyonu) ─────────────────────────────────────────────

    @staticmethod
    def _rail_ikon_ciz(sekil: str, renk: str) -> QIcon:
        """
        Rail öğeleri için basit, vektörel çizilmiş ikon (gerçek SVG/Lucide seti
        yerine QPainter ile 20x20 px çizim — spesifikasyondaki sade geometrik
        işaretlerle aynı ruhta: çember/kare/çizgi/yarım çember).
        """
        pix = QPixmap(20, 20)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing, True)
        kalem = QPen(QColor(renk))
        kalem.setWidthF(1.6)
        p.setPen(kalem)
        p.setBrush(Qt.NoBrush)

        if sekil == "cember":       # UÇUŞ
            p.drawEllipse(3, 3, 14, 14)
        elif sekil == "kare":       # PARAM
            p.drawRect(4, 4, 12, 12)
        elif sekil == "cizgiler":   # PRE-ARM
            p.drawLine(4, 7, 16, 7)
            p.drawLine(4, 13, 16, 13)
        elif sekil == "yarim":      # LOG
            p.setBrush(QBrush(QColor(renk)))
            p.drawPie(3, 3, 14, 14, 0, 180 * 16)
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(3, 3, 14, 14)
        elif sekil == "acik_cember":  # RAPOR
            p.drawArc(3, 3, 14, 14, 30 * 16, 300 * 16)

        p.end()
        return QIcon(pix)

    def _nav_ray_olustur(self) -> QWidget:
        """
        96px genişlikte dikey ikon rayı — eski yatay QTabWidget'ın yerini alır.
        RAPOR öğesi bir sayfa değil, doğrudan _rapor_tikla() eylemini tetikler
        (uçuş raporu hâlâ tarayıcıda HTML olarak açılıyor — bu turun kapsamı
        dışında, bkz. plan).
        """
        ray = QWidget()
        ray.setFixedWidth(96)
        ray.setStyleSheet(f"background:{KOKPIT_ZEMIN}; border-right:1px solid {KOKPIT_KENAR};")
        lay = QVBoxLayout(ray)
        lay.setContentsMargins(0, 10, 0, 10)
        lay.setSpacing(2)

        self._ray_dugmeleri: dict[int, QToolButton] = {}
        oge_stili_pasif = (
            "QToolButton { background:transparent; color:#9ebbd8; border:none; "
            "border-left:2px solid transparent; font-family:'Barlow Condensed',sans-serif; "
            "font-weight:600; font-size:10px; padding:12px 0; }"
            "QToolButton:hover { background:rgba(148,188,227,0.06); }"
        )
        oge_stili_aktif = (
            "QToolButton { background:rgba(148,188,227,0.1); color:#e7e7ea; "
            "border:none; border-left:2px solid #94bce3; "
            "font-family:'Barlow Condensed',sans-serif; font-weight:700; font-size:10px; "
            " padding:12px 0; }"
        )
        self._ray_stil_pasif = oge_stili_pasif
        self._ray_stil_aktif = oge_stili_aktif

        def _rail_dugmesi(etiket: str, sekil: str) -> QToolButton:
            b = QToolButton()
            b.setText(etiket)
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setIconSize(QSize(18, 18))
            b.setIcon(self._rail_ikon_ciz(sekil, "#9ebbd8"))
            b.setMinimumHeight(74)
            b.setAutoRaise(True)
            return b

        _OGELER = ((0, "UÇUŞ", "cember"), (1, "PARAM", "kare"),
                   (2, "PRE-ARM", "cizgiler"), (3, "LOG", "yarim"), (4, "ANALYTİCS", "daire"))
        for idx, etiket, sekil in _OGELER:
            b = _rail_dugmesi(etiket, sekil)
            if idx == 0:
                b.setIcon(self._rail_ikon_ciz(sekil, "#e7e7ea"))
            b.setStyleSheet(oge_stili_aktif if idx == 0 else oge_stili_pasif)
            b.clicked.connect(lambda _, i=idx: self._rail_sayfa_degistir(i))
            lay.addWidget(b)
            self._ray_dugmeleri[idx] = b

        lay.addStretch()

        rapor_btn = _rail_dugmesi("RAPOR", "acik_cember")
        rapor_btn.setStyleSheet(oge_stili_pasif)
        rapor_btn.clicked.connect(self._rapor_tikla)
        lay.addWidget(rapor_btn)

        return ray

    def _rail_sayfa_degistir(self, index: int):
        """Ray'e tıklanınca çağrılır — eski _sekme_degisti'nin (QTabWidget
        currentChanged) yerini alır, aynı lazy-load mantığını korur."""
        for i, btn in self._ray_dugmeleri.items():
            btn.setStyleSheet(self._ray_stil_aktif if i == index else self._ray_stil_pasif)
        self._icerik_stack.setCurrentIndex(index)
        self._sekme_degisti(index)

    # ── Bağlantı çubuğu ──────────────────────────────────────────────────────

    def _baglanti_cubugu(self) -> QWidget:
        _BADGE = (
            "border-radius:3px; padding:2px 8px; font-size:10px;"
        )
        bar = QWidget()
        bar.setFixedHeight(58)
        bar.setStyleSheet(
            "QWidget#baglantiBar { background:#0a1520; border-bottom:1px solid #1a3a5a; }"
            "QLabel { background:transparent; }"
        )
        bar.setObjectName("baglantiBar")
        duz = QHBoxLayout(bar)
        duz.setContentsMargins(10, 8, 10, 8)
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
            f"QLineEdit {{ background:{KOKPIT_ZEMIN}; color:{KOKPIT_VURGU2}; "
            f"border:1px solid {KOKPIT_KENAR}; border-radius:4px; "
            "padding:2px 8px; font-family:'Courier New'; font-size:12px; }"
            f"QLineEdit:focus {{ border-color:{KOKPIT_VURGU}; }}"
        )
        duz.addWidget(self._baglanti_giris)

        # ── Bağlan butonu ─────────────────────────────────────────────────────
        self._baglan_btn = QPushButton("BAĞLAN")
        self._baglan_btn.setFixedSize(100, 30)
        self._baglan_btn.setStyleSheet(
            f"QPushButton {{ background:{KOKPIT_VURGU}; color:#12202c; "
            "border:none; border-radius:4px; "
            "font-weight:bold; font-size:11px; }"
            f"QPushButton:hover {{ background:{KOKPIT_VURGU2}; }}"
            "QPushButton:pressed { background:#7ea6c9; }"
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
        self._rapor_btn = QPushButton("RAPOR")
        self._rapor_btn.setFixedSize(74, 30)
        self._rapor_btn.setToolTip("Son uçuş için HTML rapor oluştur ve tarayıcıda aç")
        self._rapor_btn.setStyleSheet(
            "QPushButton { background:#1a2a3a; color:#7eb8e0; border:1px solid #2a4060; "
            "border-radius:4px; font-size:11px; padding:0 6px; }"
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
        self._mod_lbl = QLabel(self._rozet_html("MOD", "—"))
        self._mod_lbl.setStyleSheet(
            f"background:transparent; border:1px solid {KOKPIT_KENAR}; padding:3px 14px;"
        )
        self._mod_lbl.setFixedHeight(42)
        self._mod_lbl.setAlignment(Qt.AlignCenter)
        duz.addWidget(self._mod_lbl)

        # ── ARM rozeti ────────────────────────────────────────────────────────
        self._arm_lbl = QLabel(self._rozet_html("DURUM", "DISARM", "#7e9cb8"))
        self._arm_lbl.setStyleSheet(
            f"background:transparent; border:1px solid {KOKPIT_KENAR}; padding:3px 14px;"
        )
        self._arm_lbl.setFixedHeight(42)
        self._arm_lbl.setAlignment(Qt.AlignCenter)
        duz.addWidget(self._arm_lbl)

        # ── EKF rozeti ────────────────────────────────────────────────────────
        self._ekf_lbl = QLabel(self._rozet_html("EKF", "—", "#7e9cb8"))
        self._ekf_lbl.setStyleSheet(
            f"background:transparent; border:1px solid {KOKPIT_KENAR}; padding:3px 14px;"
        )
        self._ekf_lbl.setFixedHeight(42)
        self._ekf_lbl.setAlignment(Qt.AlignCenter)
        duz.addWidget(self._ekf_lbl)

        # ── RC sinyal rozeti ──────────────────────────────────────────────────
        self._rc_lbl = QLabel(self._rozet_html("RC", "—", "#7e9cb8"))
        self._rc_lbl.setStyleSheet(
            f"background:transparent; border:1px solid {KOKPIT_KENAR}; padding:3px 14px;"
        )
        self._rc_lbl.setFixedHeight(42)
        self._rc_lbl.setAlignment(Qt.AlignCenter)
        duz.addWidget(self._rc_lbl)

        # ── GPS rozeti (1B tasarımı — MOD/DURUM/EKF/RC/GPS/SÜRE) ──────────────
        self._gps_badge_lbl = QLabel(self._rozet_html("GPS", "—", "#7e9cb8"))
        self._gps_badge_lbl.setStyleSheet(
            f"background:transparent; border:1px solid {KOKPIT_KENAR}; padding:3px 14px;"
        )
        self._gps_badge_lbl.setFixedHeight(42)
        self._gps_badge_lbl.setAlignment(Qt.AlignCenter)
        duz.addWidget(self._gps_badge_lbl)

        # ── SÜRE rozeti — bağlantı kurulduğundan bu yana geçen süre ───────────
        self._sure_lbl = QLabel(self._rozet_html("SÜRE", "—", "#7e9cb8"))
        self._sure_lbl.setStyleSheet(
            f"background:transparent; border:1px solid {KOKPIT_KENAR}; padding:3px 14px;"
        )
        self._sure_lbl.setFixedHeight(42)
        self._sure_lbl.setAlignment(Qt.AlignCenter)
        duz.addWidget(self._sure_lbl)
        self._baglanti_zamani: "float | None" = None
        self._sure_timer = QTimer()
        self._sure_timer.setInterval(1000)
        self._sure_timer.timeout.connect(self._sure_guncelle)

        return bar

    def _sure_guncelle(self):
        if self._baglanti_zamani is None:
            return
        gecen = int(time.time() - self._baglanti_zamani)
        saat, kalan = divmod(gecen, 3600)
        dakika, saniye = divmod(kalan, 60)
        metin = f"{saat:02d}:{dakika:02d}:{saniye:02d}"
        self._sure_lbl.setText(self._rozet_html("SÜRE", metin, "#bdd8f2"))

    # ── Uçuş sekmesi ─────────────────────────────────────────────────────────

    def _ana_sekme(self) -> QWidget:
        """1B düzeni — Uçuş ekranı: sol enstrüman kolonu (%55) + sağ birleşik
        harita/görev paneli (%45). Eskiden sağda ayrı bir "mini-harita" vardı
        ve tam harita+görev tablosu ayrı bir sekmedeydi; 1B'de tek harita var,
        doğrudan burada gösteriliyor (bkz. READMEe.md, 1B bölümü).
        """
        w = QWidget()
        main_row = QHBoxLayout(w)
        main_row.setSpacing(3)
        main_row.setContentsMargins(4, 4, 4, 4)

        # ── Sol kolon ─────────────────────────────────────────────────────────
        # Kart sayısı arttıkça (yapay ufuk + 6 kart + alt sekmeler) dar
        # ekranlarda taşma riski var — kaydırılabilir alana sarıldı.
        sol_w = QWidget()
        sol = QVBoxLayout(sol_w)
        sol.setSpacing(6)
        sol.setContentsMargins(0, 0, 6, 0)

        # HUD — ekranın çoğunu kullanır, stretch=1 ile esnek büyür
        hud_grp = QGroupBox("Yapay Ufuk")
        hud_grp.setMinimumHeight(260)
        hud_lay = QVBoxLayout(hud_grp)
        hud_lay.setContentsMargins(4, 4, 4, 4)
        self._yapay_ufuk = YapayUfukWidget()
        hud_lay.addWidget(self._yapay_ufuk)
        sol.addWidget(hud_grp)

        # 1B kart dizisi: 2x2 tile + Batarya + Rüzgar&Arazi + Sistem Mesajları
        sol.addWidget(self._tile_2x2_kart())
        sol.addWidget(self._batarya_karti())
        sol.addWidget(self._ruzgar_arazi_karti())
        sol.addWidget(self._mesaj_logu_paneli())

        # IMU/ESC ve Grafik — artık kalıcı kartlar (eskiden alt-sekme içindeydi)
        sol.addWidget(self._imu_esc_karti())
        sol.addWidget(self._grafik_karti())

        # Alt sekmeler — Değerler (Roll/Pitch/Yaw/Bat) / Göstergeler
        sol.addWidget(self._alt_sekmeler())

        kaydirma = QScrollArea()
        kaydirma.setWidgetResizable(True)
        kaydirma.setFrameShape(QScrollArea.NoFrame)
        kaydirma.setStyleSheet(f"QScrollArea {{ background:transparent; border:none; }}")
        kaydirma.setWidget(sol_w)
        main_row.addWidget(kaydirma, 55)

        # ── Sağ kolon: birleşik harita + görev tablosu (tam yükseklik) ────────
        # HWND kısıtı (Chromium, show() öncesi geçerli pencere handle bulamıyor)
        # nedeniyle gerçek QWebEngineView burada değil, showEvent'ten sonra
        # _harita_tab_yukle() içinde oluşturulur — placeholder şimdilik konur.
        if HARITA_MEVCUT:
            self._harita_tab_hazir = False
            self._harita_stack = QStackedWidget()
            _yk = QLabel("Harita yükleniyor…")
            _yk.setAlignment(Qt.AlignCenter)
            _yk.setStyleSheet(f"color:{KOKPIT_VURGU2}; background:{KOKPIT_ZEMIN}; font-size:12px;")
            self._harita_stack.addWidget(_yk)      # index 0 = placeholder
            main_row.addWidget(self._harita_stack, 45)
        else:
            self._harita_tab_hazir = True
            eksik = QLabel("Harita için: pip install PyQtWebEngine")
            eksik.setAlignment(Qt.AlignCenter)
            main_row.addWidget(eksik, 45)

        return w

    def _kart(self, baslik: str) -> tuple:
        """1B kart deseni: kokpit bordürlü, başlıklı dikey kutu. (frame, içerik_layout) döner."""
        cerceve = QWidget()
        cerceve.setStyleSheet(
            f"background:rgba(17,28,38,0.6); border:1px solid {KOKPIT_KENAR};"
        )
        dis = QVBoxLayout(cerceve)
        dis.setContentsMargins(11, 8, 11, 10)
        dis.setSpacing(6)
        if baslik:
            b = QLabel(baslik)
            b.setStyleSheet(
                "color:#9ebbd8; font-size:10px; font-weight:700; "
                "font-family:'Barlow Condensed',sans-serif; "
                "background:transparent; border:none;"
            )
            dis.addWidget(b)
        return cerceve, dis

    def _tile_2x2_kart(self) -> QWidget:
        """1B: İrtifa/Hız/Dikey/Eve — 2×2 ızgara (spec: tabular-nums, 40px değer)."""
        w = QWidget()
        grid = QGridLayout(w)
        grid.setSpacing(8)
        grid.setContentsMargins(0, 0, 0, 0)

        _TILES = [
            ("İRTİFA (m)",  "#bdd8f2", "_irtifa_lbl"),
            ("HIZ (m/s)",   "#e7e7ea", "_hiz_lbl"),
            ("DİKEY (m/s)", "#e7e7ea", "_dikey_lbl"),
            ("EVE (m)",     "#e7e7ea", "_uzaklik_lbl"),
        ]
        for i, (ad, renk, attr) in enumerate(_TILES):
            tile = QWidget()
            tile.setStyleSheet(
                f"background:rgba(17,28,38,0.6); border:1px solid {KOKPIT_KENAR};"
            )
            tlay = QVBoxLayout(tile)
            tlay.setContentsMargins(8, 6, 8, 6)
            tlay.setSpacing(0)
            ad_lbl = QLabel(ad)
            ad_lbl.setStyleSheet(
                "color:#627d98; font-size:10px; font-weight:600; "
                "background:transparent; border:none; "
                "font-family:'Barlow Condensed',sans-serif;"
            )
            val_lbl = QLabel("—")
            val_lbl.setStyleSheet(
                f"color:{renk}; font-size:28px; font-weight:700; background:transparent; "
                "border:none; font-family:'Barlow Condensed',sans-serif;"
            )
            tlay.addWidget(ad_lbl)
            tlay.addWidget(val_lbl)
            grid.addWidget(tile, i // 2, i % 2)
            setattr(self, attr, val_lbl)
        return w

    def _batarya_karti(self) -> QWidget:
        """1B: Batarya kartı — bar + volt/amper/yüzde detayı."""
        cerceve, dis = self._kart("BATARYA")
        self._batarya_bar = BataryaBar()
        self._batarya_bar.setFixedHeight(16)
        dis.addWidget(self._batarya_bar)
        self._batarya_detay = QLabel("—V  —A  —%")
        self._batarya_detay.setStyleSheet(
            "color:#e7e7ea; font-size:15px; font-weight:600; background:transparent; border:none; "
            "font-family:'Barlow Condensed',sans-serif;"
        )
        dis.addWidget(self._batarya_detay)
        return cerceve

    def _ruzgar_arazi_karti(self) -> QWidget:
        """1B: Rüzgar & Arazi kartı — rüzgar hız/yön/seviye + GPS özeti (tucked)."""
        cerceve, dis = self._kart("RÜZGAR &amp; ARAZİ")
        satir = QHBoxLayout()
        satir.setSpacing(10)
        self._ruzgar           = None
        self._ruz_seviye_lbl   = QLabel("—")
        self._ruz_hiz_lbl      = QLabel("— km/h")
        self._ruz_yon_lbl      = QLabel("—°")
        self._ruzgar_zemin_lbl = QLabel("Zemin: —")
        for _l in (self._ruz_seviye_lbl, self._ruz_hiz_lbl,
                   self._ruz_yon_lbl, self._ruzgar_zemin_lbl):
            _l.setStyleSheet(
                "color:#9ebbd8; font-size:12px; background:transparent; border:none;"
            )
            satir.addWidget(_l)
        satir.addStretch()
        dis.addLayout(satir)

        # GPS özeti — GPS'in ana gösterimi artık üst bar rozeti; burada sadece
        # koordinat/uydu detayı tutuluyor (attr'lar korunur, _gps_guncelle bozulmaz).
        gps_satir = QHBoxLayout()
        gps_satir.setSpacing(10)
        self._gps_fix_lbl   = QLabel("Fix: —")
        self._gps_uydu_lbl  = QLabel("Uydu: —")
        self._gps_konum_lbl = QLabel("—, —")
        for _l in (self._gps_fix_lbl, self._gps_uydu_lbl, self._gps_konum_lbl):
            _l.setStyleSheet(
                "color:#627d98; font-size:11px; background:transparent; border:none;"
            )
            gps_satir.addWidget(_l)
        gps_satir.addStretch()
        dis.addLayout(gps_satir)
        return cerceve

    def _alt_sekmeler(self) -> QTabWidget:
        """Alt sekmeli panel: Değerler / Göstergeler.

        IMU/ESC ve Grafik artık ayrı kalıcı kartlar (bkz. _ana_sekme,
        _imu_esc_karti, _grafik_karti) — sekme içine gömülü değiller.
        """
        tabs = QTabWidget()
        tabs.setMinimumHeight(210)
        tabs.setMaximumHeight(340)
        tabs.setStyleSheet(
            "QTabWidget::pane { border:1px solid #1a2a3a; background:#0d1b2a; }"
            "QTabBar::tab { background:#0a1520; color:#7eb8e0; padding:4px 11px;"
            "  font-size:11px; border:1px solid #1a2a3a; border-bottom:none;"
            "  margin-right:1px; }"
            "QTabBar::tab:selected { background:#0d1b2a; color:#58a6ff;"
            "  border-bottom:2px solid #58a6ff; }"
            "QTabBar::tab:hover { background:#1a2a3a; }"
        )
        tabs.addTab(self._tile_serit(),          "Değerler")
        tabs.addTab(self._gauge_sekme(),         "Göstergeler")
        return tabs

    def _imu_esc_karti(self) -> QWidget:
        """IMU sıcaklıkları + ESC/Motor panellerini yan yana kart olarak gösterir."""
        cerceve, dis = self._kart("IMU / ESC")
        yatay = QHBoxLayout()
        yatay.setSpacing(8)
        yatay.addWidget(self._imu_paneli())
        yatay.addWidget(self._esc_paneli())
        dis.addLayout(yatay)
        return cerceve

    def _grafik_karti(self) -> QWidget:
        """Uçuş grafiğini (pyqtgraph) kart görünümüne sarar."""
        cerceve, dis = self._kart("UÇUŞ GRAFİĞİ")
        dis.addWidget(self._ucus_grafik_widget())
        return cerceve

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
                "background:transparent; border:none;"
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
        """Kalıcı acil şerit — 1B tasarımı: her ekranda görünür (bkz. _ui_olustur)."""
        w = QWidget()
        w.setMinimumHeight(78)
        w.setMaximumHeight(96)
        lay = QHBoxLayout(w)
        lay.setSpacing(4)
        lay.setContentsMargins(2, 2, 2, 2)

        # Acil komutlar
        acil_grp = QGroupBox("Acil")
        acil_lay = QHBoxLayout(acil_grp)
        acil_lay.setContentsMargins(4, 4, 4, 4)
        acil_lay.setSpacing(3)
        for (ad, slot, kirmizi) in [
            ("EV'E DÖN (RTL)", self._rtl_tikla,       True),
            ("ACİL İNİŞ",      self._inis_tikla,       True),
            ("HOVERING",       self._hovering_tikla,  False),
            ("DEVAM ET",       self._devam_tikla,     False),
            ("🪂 PARAŞÜT",     self._parasut_tikla,   True),
        ]:
            b = QPushButton(ad)
            b.setMaximumHeight(36)
            if kirmizi:
                b.setStyleSheet(ACİL_STİLİ_KOKPIT)
            b.clicked.connect(slot)
            acil_lay.addWidget(b)
        lay.addWidget(acil_grp, 4)

        # Mod seçici
        mod_grp = QGroupBox("Mod")
        mod_lay = QHBoxLayout(mod_grp)
        mod_lay.setContentsMargins(4, 4, 4, 4)
        mod_lay.setSpacing(3)
        self._mod_btn_map = {}
        for (ad, mid) in [("SABİTLEME", 0), ("LOITER", 5), ("FREN", 12), ("OTOMATİK", 3), ("KILAVUZ", 4), ("SMART RTL", 22)]:
            b = QPushButton(ad)
            b.setMaximumHeight(36)
            b.clicked.connect(lambda _, m=mid: self._mod_tikla(m))
            mod_lay.addWidget(b)
            self._mod_btn_map[mid] = b
        lay.addWidget(mod_grp, 4)

        # Diğer (Ev + Kalibrasyon + Terrain/ADSB)
        diger_grp = QGroupBox("Diğer")
        diger_lay = QHBoxLayout(diger_grp)
        diger_lay.setContentsMargins(4, 4, 4, 4)
        diger_lay.setSpacing(6)
        ev_btn = QPushButton("Ev Yap")
        ev_btn.setMaximumHeight(36)
        ev_btn.clicked.connect(self._ev_yap_tikla)
        diger_lay.addWidget(ev_btn)
        kal_btn = QPushButton("🔧 Kalibrasyon")
        kal_btn.setMaximumHeight(36)
        kal_btn.setToolTip("Gyro + Manyetometre + İvmeölçer kalibrasyonu (PREFLIGHT_CALIBRATION)")
        kal_btn.clicked.connect(self._kalibrasyon_tikla)
        diger_lay.addWidget(kal_btn)
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

        # İrtifa/Hız/Dikey/Eve artık _tile_2x2_kart()'ta (1B sol kolon kartı).
        _TILES = [
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
                "background:transparent; border:none;"
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
        tabs.setMaximumHeight(180)
        tabs.setMinimumHeight(120)
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

    def _gauge_sekme(self) -> QWidget:
        """4 büyük gösterge: İrtifa, Hız, Batarya, GPS."""
        w = QWidget()
        grid = QGridLayout(w)
        grid.setSpacing(6)
        grid.setContentsMargins(6, 6, 6, 6)

        def _gauge(baslik: str, renk: str) -> tuple:
            kutu = QGroupBox(baslik)
            kutu.setMinimumHeight(95)
            kutu.setStyleSheet(
                f"QGroupBox {{ border:1px solid {renk}44; border-radius:6px; "
                f"color:{renk}; font-size:9pt; font-weight:bold; "
                f"margin-top:8px; padding-top:4px; }}"
                f"QGroupBox::title {{ subcontrol-origin:margin; left:8px; }}"
            )
            ic = QVBoxLayout(kutu)
            ic.setContentsMargins(4, 4, 4, 4)
            deger = QLabel("--")
            deger.setAlignment(Qt.AlignCenter)
            deger.setStyleSheet(
                f"color:{renk}; font-size:22pt; font-weight:bold; background:transparent;")
            alt = QLabel("")
            alt.setAlignment(Qt.AlignCenter)
            alt.setStyleSheet("color:#7eb8e0; font-size:9pt; background:transparent;")
            ic.addWidget(deger)
            ic.addWidget(alt)
            return kutu, deger, alt

        g_irt, self._g_irtifa_deger, self._g_irtifa_alt   = _gauge("İrtifa (m)",   "#64b5f6")
        g_hiz, self._g_hiz_deger,    self._g_hiz_alt      = _gauge("Hız (m/s)",    "#81c784")
        g_bat, self._g_bat_deger,    self._g_bat_alt       = _gauge("Batarya",      "#ffb74d")
        g_gps, self._g_gps_deger,    self._g_gps_alt       = _gauge("GPS",          "#ce93d8")

        grid.addWidget(g_irt, 0, 0)
        grid.addWidget(g_hiz, 0, 1)
        grid.addWidget(g_bat, 1, 0)
        grid.addWidget(g_gps, 1, 1)
        return w

    def _gauge_vfr_guncelle(self, irtifa: float, hiz: float, dikey: float, uzaklik: float):
        self._g_irtifa_deger.setText(f"{irtifa:.1f}")
        self._g_irtifa_alt.setText(f"Dikey: {dikey:+.1f} m/s")
        self._g_hiz_deger.setText(f"{hiz:.1f}")
        self._g_hiz_alt.setText(f"Eve: {uzaklik:.0f} m")

    def _gauge_bat_guncelle(self, volt: float, amper: float, yuzde: int):
        self._g_bat_deger.setText(f"{volt:.1f}V")
        txt = f"{amper:.1f}A"
        if yuzde >= 0:
            txt += f"  %{yuzde}"
        self._g_bat_alt.setText(txt)

    def _gauge_gps_guncelle(self, fix: int, uydu: int, lat: float, lon: float):
        fix_ad = {0:"YOK", 1:"YOK", 2:"2D", 3:"3D", 4:"DGPS", 5:"RTK Float", 6:"RTK Fix"}
        self._g_gps_deger.setText(fix_ad.get(fix, str(fix)))
        self._g_gps_alt.setText(f"{uydu} uydu")

    def _prearm_sekme(self) -> QWidget:
        """Uçuş öncesi kontrol listesi — MAVLink verilerine göre otomatik güncellenir.

        1B/1E: sol kolon (kontrol satırları + ArduPilot mesajları) + sağ 430px
        kolon (ARM DURUMU — gerçek ARM/DISARM butonu, GÜVENLİK KATMANLARI,
        KALİBRASYON). Eskiden bu ekran sadece durum GÖSTERİYORDU, ARM etmenin
        kendisi için bir yol yoktu — artık gerçek MAV_CMD_COMPONENT_ARM_DISARM
        (400) komutu buradan gönderiliyor.
        """
        disari = QHBoxLayout()
        disari.setSpacing(10)
        disari.setContentsMargins(6, 6, 6, 6)
        w = QWidget()
        w.setLayout(disari)

        sol_w = QWidget()
        ana = QVBoxLayout(sol_w)
        ana.setSpacing(4)
        ana.setContentsMargins(0, 0, 0, 0)
        disari.addWidget(sol_w, 1)

        baslik = QLabel("UÇUŞ ÖNCESİ KONTROLLER")
        baslik.setStyleSheet(
            "color:#e7e7ea; font-size:16px; font-weight:700; "
            "font-family:'Barlow Condensed',sans-serif;"
        )
        ana.addWidget(baslik)

        izgara = QVBoxLayout()
        izgara.setSpacing(6)

        def _satir(ad: str, satir: int):
            cerceve = QWidget()
            cerceve.setObjectName("prearmSatir")
            cerceve.setStyleSheet(
                f"QWidget#prearmSatir {{ background:{KOKPIT_PANEL}; "
                f"border:1px solid {KOKPIT_KENAR}; padding:2px; }}"
            )
            clay = QHBoxLayout(cerceve)
            clay.setContentsMargins(14, 10, 14, 10)
            etiket = QLabel(ad)
            etiket.setStyleSheet(
                "color:#9ebbd8; font-size:12px; font-family:'Barlow Condensed',sans-serif; "
                "font-weight:600;"
            )
            clay.addWidget(etiket)
            clay.addStretch()
            durum = QLabel("—")
            durum.setStyleSheet("color:#7e9cb8; font-size:11px; font-weight:700;")
            clay.addWidget(durum)
            durum._prearm_cerceve = cerceve   # _prearm_renk kenarlığı da güncelleyebilsin
            izgara.addWidget(cerceve)
            return durum

        self._prearm_gps     = _satir("GPS Fix",              0)
        self._prearm_ekf     = _satir("EKF Durumu",           1)
        self._prearm_batarya = _satir("Batarya",              2)
        self._prearm_hucre   = _satir("Batarya Hücre (min)",  3)
        self._prearm_rc      = _satir("RC / RSSI",            4)
        self._prearm_imu     = _satir("IMU1 Sıcaklığı",       5)
        self._prearm_imu2    = _satir("IMU2 Sıcaklığı",       6)
        self._prearm_vib     = _satir("Titreşim",             7)
        self._prearm_genel   = _satir("Genel Durum",          8)

        ana.addLayout(izgara)

        # ArduPilot'tan gelen pre-arm mesajları
        ara = QLabel("ARDUPILOT MESAJLARI")
        ara.setStyleSheet(
            "color:#9ebbd8; font-size:10px; font-weight:700; margin-top:4px; "
            "font-family:'Barlow Condensed',sans-serif;"
        )
        ana.addWidget(ara)
        self._prearm_mesajlar = QTextEdit()
        self._prearm_mesajlar.setReadOnly(True)
        self._prearm_mesajlar.setMinimumHeight(200)
        self._prearm_mesajlar.setFont(QFont("Courier New", 9))
        self._prearm_mesajlar.setStyleSheet(
            f"background:{KOKPIT_ZEMIN}; color:#c8d8e8; border:1px solid {KOKPIT_KENAR};"
        )
        # Sabit yükseklik yerine artık kalan boş alanı doldurur (stretch=1) —
        # eskiden altta büyük bir boş alan kalıyordu.
        ana.addWidget(self._prearm_mesajlar, 1)

        # ── Sağ kolon (430px) — ARM DURUMU / GÜVENLİK KATMANLARI / KALİBRASYON ──
        sag_w = QWidget()
        sag_w.setFixedWidth(430)
        sag = QVBoxLayout(sag_w)
        sag.setSpacing(10)
        sag.setContentsMargins(0, 0, 0, 0)

        arm_cerceve, arm_lay = self._kart("ARM DURUMU")
        self._prearm_arm_baslik = QLabel("DISARM")
        self._prearm_arm_baslik.setAlignment(Qt.AlignCenter)
        self._prearm_arm_baslik.setStyleSheet(
            "color:#d9a24a; font-size:40px; font-weight:700; background:transparent; "
            "border:none; font-family:'Barlow Condensed',sans-serif;"
        )
        arm_lay.addWidget(self._prearm_arm_baslik)
        self._prearm_arm_btn = QPushButton("MOTORLARI ARM ET")
        self._prearm_arm_btn.setFixedHeight(52)
        self._prearm_arm_btn.setStyleSheet(
            BAĞLAN_STİLİ_KOKPIT.replace("font-weight: bold;", "font-weight:700; font-size:13px; "
            "font-family:'Barlow Condensed',sans-serif;")
        )
        self._prearm_arm_btn.clicked.connect(self._arm_disarm_tikla)
        arm_lay.addWidget(self._prearm_arm_btn)
        sag.addWidget(arm_cerceve)

        guv_cerceve, guv_lay = self._kart("GÜVENLİK KATMANLARI")
        for satir in (
            "K1 — GPS: 3D fix + yeterli uydu sayısı",
            "K2 — EKF: sensör füzyonu sağlıklı",
            "K3 — Batarya: güvenli voltaj/yüzde",
            "K4 — RC: sinyal var, failsafe yok",
            "K5 — IMU: sıcaklık normal aralıkta",
        ):
            l = QLabel(satir)
            l.setStyleSheet(
                "color:#9ebbd8; font-size:12px; background:transparent; border:none; padding:2px 0;"
            )
            guv_lay.addWidget(l)
        sag.addWidget(guv_cerceve)

        kal_cerceve, kal_lay = self._kart("KALİBRASYON")
        kal_row = QHBoxLayout()
        kal_row.setSpacing(6)
        for ad, tur in (("GYRO", 1), ("MAG", 2), ("ACCEL", 5)):
            b = QPushButton(ad)
            b.setFixedHeight(38)
            b.clicked.connect(lambda _, t=tur: self._hizli_kalibrasyon(t))
            kal_row.addWidget(b)
        kal_lay.addLayout(kal_row)

        _sihirbaz_btn = QPushButton("🔧 Kalibrasyon Sihirbazını Aç")
        _sihirbaz_btn.setFixedHeight(32)
        _sihirbaz_btn.setToolTip("Adım adım rehberli kalibrasyon (Gyro → Accel → Mag)")
        _sihirbaz_btn.clicked.connect(self._kalibrasyon_sihirbazi_ac)
        kal_lay.addWidget(_sihirbaz_btn)

        sag.addWidget(kal_cerceve)

        sag.addStretch()
        disari.addWidget(sag_w)

        return w

    def _arm_disarm_tikla(self):
        """MAV_CMD_COMPONENT_ARM_DISARM (400) — gerçek arm/disarm komutu."""
        if not self._komut_izinli_mi():
            return
        if getattr(self, "_arm_durumu", False):
            self._mavlink.komut_gonder(400, 0, 0, 0, 0, 0, 0, 0)
            self._mesaj_ekle(6, "DISARM komutu gönderildi.")
        else:
            cevap = QMessageBox.question(
                self, "ARM ONAYI",
                "Motorlar ARM edilecek!\n\nPervaneler dönmeye başlayabilir.\n\nEmin misiniz?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if cevap == QMessageBox.Yes:
                self._mavlink.komut_gonder(400, 1, 0, 0, 0, 0, 0, 0)
                self._mesaj_ekle(3, "ARM komutu gönderildi.")

    def _kalibrasyon_sihirbazi_ac(self):
        """Adım adım rehberli kalibrasyon dialogunu açar."""
        if not self._komut_izinli_mi():
            return
        from kalibrasyon_sihirbazi import KalibrasyonSihirbazi
        dlg = KalibrasyonSihirbazi(self)
        dlg.exec_()

    def _hizli_kalibrasyon(self, tur: int):
        """Pre-Arm ekranındaki tek-tık kalibrasyon butonları (Gyro/Mag/Accel)."""
        if not self._komut_izinli_mi():
            return
        p1 = 1 if tur == 1 else 0
        p2 = 1 if tur == 2 else 0
        p5 = 1 if tur == 5 else 0
        self._mavlink.komut_gonder(241, p1, p2, 0, 0, p5, 0, 0)
        adlar = {1: "Gyro", 2: "Manyetometre", 5: "İvmeölçer"}
        self._mesaj_ekle(4, f"🔧 {adlar[tur]} kalibrasyonu başlatıldı.")

    def _prearm_renk(self, durum_lbl: QLabel, metin: str, ok: bool):
        renk = "#a8cf94" if ok else "#e0c07a"
        durum_lbl.setText(metin)
        durum_lbl.setStyleSheet(
            f"color:{renk}; font-size:11px; font-weight:700; "
            f"font-family:'Barlow Condensed',sans-serif;"
        )
        cerceve = getattr(durum_lbl, "_prearm_cerceve", None)
        if cerceve is not None:
            kenar = "rgba(143,191,122,0.4)" if ok else "rgba(217,162,74,0.5)"
            zemin = KOKPIT_PANEL if ok else "rgba(217,162,74,0.08)"
            cerceve.setStyleSheet(
                f"QWidget#prearmSatir {{ background:{zemin}; border:1px solid {kenar}; padding:2px; }}"
            )

    def _prearm_gps_guncelle(self, fix: int, uydu: int, lat: float, lon: float):
        ok = fix >= 3 and uydu >= 6
        self._prearm_renk(self._prearm_gps,
                          f"Fix {fix} / {uydu} uydu", ok)

    def _prearm_ekf_guncelle(self, bayraklar: int, hata: float):
        ok = (bayraklar & 0x01F) == 0x01F and hata < 0.5
        self._prearm_renk(self._prearm_ekf,
                          f"Bayrak {bayraklar:#06x} / Hata {hata:.2f}", ok)

    def _prearm_batarya_guncelle(self, volt: float, amper: float, yuzde: int):
        ok = volt > 14.0 and (yuzde < 0 or yuzde > 20)
        gosterge = f"{volt:.1f}V"
        if yuzde >= 0:
            gosterge += f" / %{yuzde}"
        self._prearm_renk(self._prearm_batarya, gosterge, ok)

    def _prearm_rc_guncelle(self, rssi: int, failsafe: bool):
        ok = rssi > 50 and not failsafe
        self._prearm_renk(self._prearm_rc,
                          f"RSSI {rssi}" + (" ⚠ Failsafe" if failsafe else ""), ok)

    def _prearm_imu_guncelle(self, imu_no: int, sicaklik: float):
        # Donanımda 2 IMU var (ICM-42688-P + BMI088, bkz. hwdef.dat) — ikisi
        # de ayrı ayrı izleniyor, tek IMU'nun aşırı ısınması/soğuması artık
        # gözden kaçmıyor.
        ok = 30 <= sicaklik <= 65
        if imu_no == 0:
            self._prearm_renk(self._prearm_imu, f"IMU1: {sicaklik:.1f}°C", ok)
        elif imu_no == 1:
            self._prearm_renk(self._prearm_imu2, f"IMU2: {sicaklik:.1f}°C", ok)

    def _prearm_arm_guncelle(self, mod_id: int, arm: bool):
        if arm:
            self._prearm_renk(self._prearm_genel, "ARMED ✓", True)
        else:
            self._prearm_renk(self._prearm_genel, "DISARMED", False)
        self._prearm_arm_karti_guncelle(arm)

    def _prearm_arm_karti_guncelle(self, arm: bool):
        """Pre-Arm sağ kolonundaki ARM DURUMU kartını (başlık + buton) günceller."""
        if not hasattr(self, "_prearm_arm_baslik"):
            return
        if arm:
            self._prearm_arm_baslik.setText("ARMED")
            self._prearm_arm_baslik.setStyleSheet(
                "color:#8fbf7a; font-size:40px; font-weight:700; background:transparent; "
                "border:none; font-family:'Barlow Condensed',sans-serif;"
            )
            self._prearm_arm_btn.setText("MOTORLARI DISARM ET")
        else:
            self._prearm_arm_baslik.setText("DISARM")
            self._prearm_arm_baslik.setStyleSheet(
                "color:#d9a24a; font-size:40px; font-weight:700; background:transparent; "
                "border:none; font-family:'Barlow Condensed',sans-serif;"
            )
            self._prearm_arm_btn.setText("MOTORLARI ARM ET")

    def _prearm_mesaj_isle(self, severity: int, metin: str):
        # severity 0-3 arası kritik/hata — pre-arm hataları genellikle buradan gelir
        if "PreArm" in metin or "EKF" in metin or severity <= 3:
            renk = "#f44336" if severity <= 3 else "#ffb300"
            self._prearm_mesajlar.append(
                f'<span style="color:{renk}">[{severity}] {metin}</span>')
        # Genel durumu arm durumuna göre güncelle
        if "Arming" in metin or "Armed" in metin:
            self._prearm_renk(self._prearm_genel, "ARMED ✓", True)
            self._prearm_arm_karti_guncelle(True)
        elif "Disarmed" in metin:
            self._prearm_renk(self._prearm_genel, "DISARMED", False)
            self._prearm_arm_karti_guncelle(False)

    # ── Parametre sekmesi ─────────────────────────────────────────────────────

    def _parametre_sekme(self) -> QWidget:
        w   = QWidget()
        duz = QVBoxLayout(w)
        duz.setSpacing(6)

        # Araç çubuğu
        araci = QHBoxLayout()

        self._param_indir_btn = QPushButton("PARAMETRELERİ İNDİR")
        self._param_indir_btn.setStyleSheet(BAĞLAN_STİLİ_KOKPIT)
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

        self._param_karsilastir_btn = QPushButton("🔍 Karşılaştır")
        self._param_karsilastir_btn.setToolTip("Mevcut parametreleri bir JSON yedekle karşılaştır")
        self._param_karsilastir_btn.clicked.connect(self._param_karsilastir_tikla)
        araci.addWidget(self._param_karsilastir_btn)

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
        self._param_tablo.itemChanged.connect(self._param_tablo_degisti)
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

    # ── Uçuş Logu İndirme Sekmesi ─────────────────────────────────────────────

    def _log_sekme(self) -> QWidget:
        """Log listesi + indirme arayüzü."""
        w = QWidget()
        duz = QVBoxLayout(w)
        duz.setContentsMargins(6, 6, 6, 6)
        duz.setSpacing(6)

        # Araç çubuğu
        araci = QHBoxLayout()
        self._log_listele_btn = QPushButton("LOG LİSTESİNİ AL")
        self._log_listele_btn.setStyleSheet(BAĞLAN_STİLİ_KOKPIT)
        self._log_listele_btn.clicked.connect(self._log_listele_tikla)
        araci.addWidget(self._log_listele_btn)

        self._log_indir_btn = QPushButton("SEÇİLİ LOGU İNDİR")
        self._log_indir_btn.clicked.connect(self._log_indir_tikla)
        araci.addWidget(self._log_indir_btn)

        self._log_ac_btn = QPushButton("KAYDEDİLEN LOGU AÇ")
        self._log_ac_btn.clicked.connect(self._log_ac_tikla)
        araci.addWidget(self._log_ac_btn)

        araci.addStretch()
        self._log_durum_lbl = QLabel("Drone'a bağlanın ve log listesini alın.")
        self._log_durum_lbl.setStyleSheet("color:#7e9cb8; font-size:11px;")
        araci.addWidget(self._log_durum_lbl)
        duz.addLayout(araci)

        # İlerleme çubuğu
        self._log_progress = QProgressBar()
        self._log_progress.setMaximumHeight(14)
        self._log_progress.setValue(0)
        self._log_progress.hide()
        duz.addWidget(self._log_progress)

        # ── Uçuş Kaydı Oynatma (CSV telemetri playback) ──────────────────
        self._log_oynatici = None
        oynat_cerceve, oynat_lay = self._kart("UÇUŞ KAYDI OYNATMA (CSV)")
        oynat_satir = QHBoxLayout()
        oynat_satir.setSpacing(6)

        self._oynat_sec_btn = QPushButton("CSV Seç")
        self._oynat_sec_btn.setFixedHeight(26)
        self._oynat_sec_btn.setToolTip("telemetri_*.csv dosyası seçip geçmiş uçuşu oynat")
        self._oynat_sec_btn.clicked.connect(self._oynatma_dosya_sec)
        oynat_satir.addWidget(self._oynat_sec_btn)

        self._oynat_play_btn = QPushButton("▶ Oynat")
        self._oynat_play_btn.setFixedHeight(26)
        self._oynat_play_btn.setEnabled(False)
        self._oynat_play_btn.clicked.connect(self._oynatma_baslat_duraklat)
        oynat_satir.addWidget(self._oynat_play_btn)

        self._oynat_durdur_btn = QPushButton("■ Durdur")
        self._oynat_durdur_btn.setFixedHeight(26)
        self._oynat_durdur_btn.setEnabled(False)
        self._oynat_durdur_btn.clicked.connect(self._oynatma_durdur)
        oynat_satir.addWidget(self._oynat_durdur_btn)

        oynat_satir.addWidget(QLabel("Hız:"))
        self._oynat_hiz_combo = QComboBox()
        self._oynat_hiz_combo.addItems(["1x", "2x", "5x"])
        self._oynat_hiz_combo.setFixedWidth(60)
        oynat_satir.addWidget(self._oynat_hiz_combo)

        oynat_satir.addStretch()
        self._oynat_durum_lbl = QLabel("Oynatma için CSV seçin.")
        self._oynat_durum_lbl.setStyleSheet("color:#7e9cb8; font-size:11px;")
        oynat_satir.addWidget(self._oynat_durum_lbl)
        oynat_lay.addLayout(oynat_satir)

        self._oynat_progress = QProgressBar()
        self._oynat_progress.setMaximumHeight(12)
        self._oynat_progress.setValue(0)
        oynat_lay.addWidget(self._oynat_progress)
        duz.addWidget(oynat_cerceve)

        # Log tablosu
        self._log_tablo = QTableWidget(0, 3)
        self._log_tablo.setHorizontalHeaderLabels(["Log ID", "Boyut", "Tarih (UTC)"])
        self._log_tablo.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._log_tablo.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._log_tablo.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._log_tablo.setAlternatingRowColors(True)
        self._log_tablo.setStyleSheet(
            f"QTableWidget {{ background:{KOKPIT_ZEMIN}; color:#bdd8f2; gridline-color:{KOKPIT_PANEL}; "
            "font-family:'Barlow',sans-serif; }"
            f"QHeaderView::section {{ background:{KOKPIT_PANEL}; color:#7e9cb8; padding:4px; "
            "font-family:'Barlow Condensed',sans-serif; font-weight:600; }"
            f"QTableWidget::item:alternate {{ background:#111c26; }}"
            "QTableWidget::item:selected { background:rgba(148,188,227,0.18); }"
        )
        duz.addWidget(self._log_tablo)

        # Sinyal bağlantıları
        m = self._mavlink
        m.log_listesi_alindi.connect(self._log_listesi_goster)
        m.log_ilerleme.connect(self._log_ilerleme_goster)
        m.log_tamamlandi.connect(self._log_indir_tamamlandi)
        m.log_hata.connect(lambda e: self._mesaj_ekle(3, f"Log hatası: {e}"))

        self._son_log_yolu: str = ""
        return w

    def _log_listele_tikla(self):
        if not self._bagli:
            QMessageBox.warning(self, "Bağlantı Yok", "Önce drone'a bağlanın.")
            return
        self._log_durum_lbl.setText("Log listesi alınıyor…")
        self._mavlink.log_listesi_iste()

    def _log_listesi_goster(self, loglar: list):
        self._log_tablo.setRowCount(0)
        for lg in loglar:
            r = self._log_tablo.rowCount()
            self._log_tablo.insertRow(r)
            self._log_tablo.setItem(r, 0, QTableWidgetItem(str(lg["id"])))
            boyut_kb = lg["size"] / 1024.0
            boyut_str = f"{boyut_kb:.0f} KB" if boyut_kb < 1024 else f"{boyut_kb/1024:.1f} MB"
            self._log_tablo.setItem(r, 1, QTableWidgetItem(boyut_str))
            import datetime
            t = lg.get("time_utc", 0)
            tarih = datetime.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d %H:%M") if t else "—"
            self._log_tablo.setItem(r, 2, QTableWidgetItem(tarih))
        self._log_durum_lbl.setText(f"{len(loglar)} log bulundu.")
        self._mesaj_ekle(6, f"Log listesi: {len(loglar)} log.")

    def _log_indir_tikla(self):
        if not self._bagli:
            QMessageBox.warning(self, "Bağlantı Yok", "Önce drone'a bağlanın.")
            return
        secili = self._log_tablo.selectedItems()
        if not secili:
            QMessageBox.warning(self, "Seçim Yok", "İndirilecek bir log satırı seçin.")
            return
        satir = self._log_tablo.currentRow()
        log_id = int(self._log_tablo.item(satir, 0).text())
        import datetime
        varsayilan = f"log_{log_id}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.BIN"
        dosya, _ = QFileDialog.getSaveFileName(
            self, "Log Kaydet", varsayilan,
            "BIN Logu (*.BIN);;Tüm Dosyalar (*)"
        )
        if not dosya:
            return
        self._log_progress.show()
        self._log_progress.setValue(0)
        self._log_durum_lbl.setText(f"Log {log_id} indiriliyor…")
        self._mavlink.log_indir(log_id, dosya)

    def _log_ilerleme_goster(self, alinan: int, toplam: int):
        if toplam > 0:
            self._log_progress.setValue(int(alinan * 100 / toplam))
            self._log_durum_lbl.setText(f"İndiriliyor: {alinan//1024} / {toplam//1024} KB")

    def _log_indir_tamamlandi(self, yol: str):
        self._log_progress.hide()
        self._log_progress.setValue(0)
        self._son_log_yolu = yol
        self._log_durum_lbl.setText(f"✓ İndirildi: {os.path.basename(yol)}")
        self._mesaj_ekle(4, f"✓ Log indirildi → {yol}")
        QMessageBox.information(self, "Log İndirildi",
            f"Log başarıyla kaydedildi:\n{yol}\n\nMission Planner veya PyFlightLog ile açabilirsiniz.")

    def _log_ac_tikla(self):
        """Son indirilen log dosyasını OS'un varsayılan uygulamasıyla aç."""
        if not self._son_log_yolu or not os.path.isfile(self._son_log_yolu):
            dosya, _ = QFileDialog.getOpenFileName(
                self, "Log Dosyası Aç", "",
                "BIN Logu (*.BIN);;Tüm Dosyalar (*)"
            )
            if not dosya:
                return
            self._son_log_yolu = dosya
        import subprocess
        try:
            os.startfile(self._son_log_yolu)   # Windows
        except AttributeError:
            subprocess.Popen(["xdg-open", self._son_log_yolu])  # Linux

    def _oynatma_dosya_sec(self):
        """Oynatılacak telemetri CSV dosyasını seçtirir ve LogOynatici oluşturur."""
        if self._bagli:
            QMessageBox.warning(
                self, "Bağlantı Aktif",
                "Oynatma, canlı MAVLink verisiyle karışmaması için yalnızca "
                "bağlantı yokken kullanılabilir. Önce bağlantıyı kesin."
            )
            return
        yol, _ = QFileDialog.getOpenFileName(
            self, "Telemetri CSV Seç", "", "CSV Dosyası (*.csv);;Tüm Dosyalar (*)"
        )
        if not yol:
            return
        try:
            from log_playback import LogOynatici
            self._log_oynatici = LogOynatici(self, yol)
        except Exception as exc:
            QMessageBox.critical(self, "CSV Okuma Hatası", str(exc))
            return
        if self._log_oynatici.satir_sayisi() == 0:
            self._mesaj_ekle(3, "CSV dosyasında satır bulunamadı.")
            self._log_oynatici = None
            return
        self._log_oynatici.ilerleme.connect(self._oynatma_ilerleme)
        self._log_oynatici.bitti.connect(self._oynatma_bitti)
        self._oynat_progress.setMaximum(self._log_oynatici.satir_sayisi())
        self._oynat_progress.setValue(0)
        self._oynat_play_btn.setEnabled(True)
        self._oynat_play_btn.setText("▶ Oynat")
        self._oynat_durdur_btn.setEnabled(True)
        self._oynat_durum_lbl.setText(
            f"{self._log_oynatici.satir_sayisi()} satır yüklendi: {os.path.basename(yol)}"
        )
        self._mesaj_ekle(6, f"Kayıt oynatma için hazır: {os.path.basename(yol)}")

    def _oynatma_baslat_duraklat(self):
        if self._log_oynatici is None:
            return
        if self._log_oynatici.calisiyor_mu():
            self._log_oynatici.duraklat()
            self._oynat_play_btn.setText("▶ Oynat")
            self._oynatma_bant_goster(False)
        else:
            hiz = float(self._oynat_hiz_combo.currentText().rstrip("x"))
            self._log_oynatici.baslat(hiz)
            self._oynat_play_btn.setText("⏸ Duraklat")
            self._oynatma_bant_goster(True)

    def _oynatma_durdur(self):
        if self._log_oynatici is None:
            return
        self._log_oynatici.durdur()
        self._oynat_play_btn.setText("▶ Oynat")
        self._oynat_progress.setValue(0)
        self._oynatma_bant_goster(False)

    def _oynatma_ilerleme(self, mevcut: int, toplam: int):
        self._oynat_progress.setMaximum(max(1, toplam))
        self._oynat_progress.setValue(mevcut)
        self._oynat_durum_lbl.setText(f"Oynatılıyor: {mevcut} / {toplam}")

    def _oynatma_bitti(self):
        self._oynat_play_btn.setText("▶ Oynat")
        self._oynat_durum_lbl.setText("Oynatma tamamlandı.")
        self._oynatma_bant_goster(False)
        self._mesaj_ekle(6, "Kayıt oynatma tamamlandı.")

    def _oynatma_bant_goster(self, goster: bool):
        """Oynatma sırasında gerçek veriyle karışmasın diye uyarı bandı gösterir."""
        if goster:
            self._uyari_bant.setText("⏵ KAYIT OYNATILIYOR — GERÇEK VERİ DEĞİL")
            self._uyari_bant.show()
        elif self._log_oynatici is None or not self._log_oynatici.calisiyor_mu():
            if not self._bagli:
                self._uyari_bant.hide()

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
            self._harita_hazir = ok
            if ok:
                self._harita_terrain_sinir_goster()
        self._harita.loadFinished.connect(_harita_yuklendi)
        self._harita.setHtml(_harita_html_olustur())
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

        _wp_git_btn = QPushButton("▶ Seçili WP'ye Git")
        _wp_git_btn.setFixedHeight(22)
        _wp_git_btn.setToolTip("Uçuş sırasında seçili waypoint'e atla (MISSION_SET_CURRENT)")
        _wp_git_btn.setStyleSheet(
            "QPushButton { background:rgba(143,191,122,0.12); color:#a8cf94; border:1px solid rgba(143,191,122,0.4);"
            " border-radius:3px; font-size:11px; padding:0 6px; }"
            "QPushButton:hover { background:rgba(143,191,122,0.2); }"
        )
        _wp_git_btn.clicked.connect(self._wp_git_tikla)
        _ozet_satir.addWidget(_wp_git_btn)

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
            f"QSpinBox {{ background:{KOKPIT_PANEL}; color:#bdd8f2; border:1px solid {KOKPIT_KENAR};"
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
            f"QSpinBox {{ background:{KOKPIT_PANEL}; color:#bdd8f2; border:1px solid {KOKPIT_KENAR};"
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

        _plan_load_btn = QPushButton("Plan Aç (.plan)")
        _plan_load_btn.setFixedHeight(24)
        _plan_load_btn.setToolTip("QGroundControl .plan (JSON) dosyasından WP listesini yükle")
        _plan_load_btn.clicked.connect(self._wp_plan_yukle)
        _ayar_satir.addWidget(_plan_load_btn)

        _plan_save_btn = QPushButton("Plan Kaydet (.plan)")
        _plan_save_btn.setFixedHeight(24)
        _plan_save_btn.setToolTip("WP listesini QGroundControl .plan (JSON) formatında kaydet")
        _plan_save_btn.clicked.connect(self._wp_plan_kaydet)
        _ayar_satir.addWidget(_plan_save_btn)

        _ayar_satir.addSpacing(8)

        _fence_import_btn = QPushButton("Fence İçe Aktar")
        _fence_import_btn.setFixedHeight(24)
        _fence_import_btn.setToolTip("SHP veya KML dosyasından geofence polygon'u içe aktar")
        _fence_import_btn.clicked.connect(self._fence_dosyadan_yukle)
        _ayar_satir.addWidget(_fence_import_btn)

        _ayar_satir.addSpacing(8)

        self._wp_home_lbl = QLabel("Ev: —")
        self._wp_home_lbl.setStyleSheet("color:#7eb8e0; font-size:11px;")
        self._wp_home_lbl.setToolTip("Drone ev konumu (GPS fix alındığında güncellenir)")
        _ayar_satir.addWidget(self._wp_home_lbl)

        _ayar_satir.addStretch()
        duz.addLayout(_ayar_satir)

        # ── Waypoint tablosu (haritanın altında) ──────────────────────────────
        # Sütunlar: # | Komut | P1 | Enlem | Boylam | İrtifa | Mesafe | AZ | ↑↓
        self._wp_tablo = QTableWidget(0, 11)
        self._wp_tablo.setHorizontalHeaderLabels(
            ["#", "Komut", "P1", "P2", "P3", "Enlem", "Boylam", "İrtifa (m)", "Mesafe (m)", "AZ (°)", ""]
        )
        # Sütun dizini: #=0, Komut=1, P1=2, P2=3, P3=4, Enlem=5, Boylam=6, İrtifa=7, Mesafe=8, AZ=9, btn=10
        _hh = self._wp_tablo.horizontalHeader()
        _hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        _hh.setSectionResizeMode(5, QHeaderView.Stretch)   # Enlem — genişle
        _hh.setSectionResizeMode(6, QHeaderView.Stretch)   # Boylam — genişle
        _hh.setSectionResizeMode(2, QHeaderView.Fixed)
        _hh.setSectionResizeMode(3, QHeaderView.Fixed)
        _hh.setSectionResizeMode(4, QHeaderView.Fixed)
        _hh.setSectionResizeMode(10, QHeaderView.Fixed)
        self._wp_tablo.setColumnWidth(2, 48)               # P1 sütunu
        self._wp_tablo.setColumnWidth(3, 48)               # P2 sütunu
        self._wp_tablo.setColumnWidth(4, 48)               # P3 sütunu
        self._wp_tablo.setColumnWidth(10, 56)              # ↑↓ buton sütunu
        self._wp_tablo.setMaximumHeight(238)
        self._wp_tablo.setMinimumHeight(120)
        self._wp_tablo.setEditTriggers(QAbstractItemView.DoubleClicked)
        self._wp_tablo.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._wp_tablo.setAlternatingRowColors(True)
        self._wp_tablo.setStyleSheet(
            f"QTableWidget {{ background:{KOKPIT_ZEMIN}; color:#bdd8f2; font-size:12px; "
            "font-family:'Barlow',sans-serif; gridline-color:rgba(148,188,227,0.08); }"
            f"QHeaderView::section {{ background:{KOKPIT_PANEL}; color:#627d98; padding:6px 4px; "
            "font-family:'Barlow Condensed',sans-serif; font-weight:600; font-size:11px; "
            "border:none; }"
            "QTableWidget::item:alternate { background:rgba(17,28,38,0.5); }"
            "QTableWidget::item:selected { background:rgba(148,188,227,0.14); }"
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
        self._js_timer.setInterval(200)    # bağlı iken harita 5 Hz akıcı güncellensin
        self._hb_timer.start()
        self._logger.baslat()
        self._ucus_kaydedici.baslat()
        self._log_timer.start()
        self._mesaj_ekle(6, f"Log: {self._logger.csv_yolu()}")
        self._baglanti_zamani = time.time()
        self._sure_timer.start()
        # GCS Failsafe — kuyruk thread-safe olduğu için doğrudan çağrılabilir
        self._gcs_failsafe_ayarla()

    def _baglanti_temizligi_yap(self):
        """
        Bağlantı koptuğunda (otomatik ya da manuel KES) yapılması gereken TEK
        ortak temizlik. Eskiden _kes_tikla ve _baglanti_kesildi farklı şeyler
        yapıyordu (manuel KES'te logger/timer hiç durdurulmuyordu) — artık
        ikisi de bunu çağırır, tutarlı ve güvenli kapanış garanti edilir.

        Arka plan thread'leri artık sert `.terminate()` ile değil, her
        thread'in kendi `durdur()` metoduyla (bkz. workers.py) nazikçe
        durdurulur — bu, devam eden bir işlemin tamamlanınca artık kopmuş
        bağlantıya/kapanmış GCS'e sinyal göndermesini de engeller.
        """
        self._log_timer.stop()
        self._logger.durdur()
        self._ucus_kaydedici.durdur()
        
        # Analytics'i finalize et (uçuş sonu hesapları yap) ve panel'i güncelle
        self._analytics.finalize()
        if self._analytics_panel:
            self._analytics_panel.update_metrics(self._analytics.get_metrics())
        # Yeni uçuş için sıfırla
        self._analytics.reset()
        if self._analytics_panel:
            self._analytics_panel.reset()
        
        self._js_timer.setInterval(1000)   # bağlı değilken harita güncellemesi gereksiz — yavaşlat
        self._sure_timer.stop()
        self._baglanti_zamani = None
        for _ad in ("_alan_hazirlik_thread", "_terrain_thread",
                    "_rally_thread", "_fence_thread", "_terrain_profil_thread"):
            t = getattr(self, _ad, None)
            if t is not None and t.isRunning():
                t.durdur()

    def _baglanti_kesildi(self):
        self._bagli = False
        self._durum_guncelle("Bağlantı kesildi – yeniden deneniyor…", "#f44336")
        self._baglan_btn.setEnabled(True)
        self._kes_btn.setEnabled(False)
        self._mesaj_ekle(4, "Bağlantı kesildi.")
        self._uyari_bant.show()
        QApplication.beep()
        self._baglanti_temizligi_yap()
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

    def _inis_sonrasi_rapor(self):
        """
        DISARM algılandıktan 5 sn sonra çağrılır.
        HTML raporu arka plan thread'inde üretir, bitince:
          - Mesaj loguna "📊 Rapor hazır" yazar
          - Tarayıcıda otomatik açar
          - Son_rapor_yolu günceller
        """
        import threading as _thr
        import webbrowser as _wb

        def _uret():
            try:
                yol = self._ucus_kaydedici.html_rapor_olustur()
                if not yol:
                    return
                self._son_rapor_yolu = yol
                # Qt sinyalini ana thread'e gönder — lambda QTimer trick
                QTimer.singleShot(0, lambda: (
                    self._mesaj_ekle(4,
                        f"📊 Uçuş raporu hazır: {os.path.basename(yol)} — tarayıcıda açılıyor."),
                    _wb.open(f"file:///{yol.replace(os.sep, '/')}")
                ))
            except Exception as exc:
                QTimer.singleShot(0, lambda: self._mesaj_ekle(3, f"İniş raporu hatası: {exc}"))

        _thr.Thread(target=_uret, daemon=True).start()

    def _hata(self, mesaj: str):
        self._mesaj_ekle(3, mesaj)

    def _ui_nabiz_artir(self):
        """500ms'de bir çağrılır — UI event loop'unun canlı olduğunun kanıtı."""
        self._ui_nabiz += 1

    def _ui_watchdog_baslat(self):
        """
        Qt event loop'undan bağımsız, plain bir thread — _ui_nabiz sayacı
        beklenen hızda ilerlemiyorsa UI thread'in donduğunu/deadlock'ta
        olduğunu tespit eder. UI gerçekten donmuşsa Qt sinyalleri de
        tetiklenmeyebilir, bu yüzden bu thread Qt'ye hiç dokunmadan
        doğrudan diske log yazar — dürüst sınır: donmuş bir ekranı o an
        "DONDU" yazısıyla güncelleyemez (donmuş event loop repaint
        yapamaz), amaç teşhis/kayıt, canlı kurtarma değil.
        """
        log_yolu = os.path.join(os.path.expanduser("~"), ".dogus-gcs", "ui_watchdog.log")
        os.makedirs(os.path.dirname(log_yolu), exist_ok=True)

        def _izle():
            son_nabiz = -1
            son_degisim = time.time()
            donuk_bildirildi = False
            while True:
                time.sleep(2.0)
                simdiki = self._ui_nabiz
                simdi = time.time()
                if simdiki != son_nabiz:
                    son_nabiz = simdiki
                    son_degisim = simdi
                    donuk_bildirildi = False
                    continue
                sure = simdi - son_degisim
                if sure > 3.0 and not donuk_bildirildi:
                    donuk_bildirildi = True
                    try:
                        with open(log_yolu, "a", encoding="utf-8") as f:
                            f.write(
                                f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
                                f"UI THREAD DONMUŞ OLABİLİR — {sure:.1f}sn'dir nabız ilerlemiyor\n"
                            )
                    except OSError:
                        pass

        threading.Thread(target=_izle, daemon=True, name="ui-watchdog").start()

    def _heartbeat_kontrol(self):
        if not self._bagli:
            return
        gecen = time.time() - self._mavlink.son_heartbeat_zamani
        # Esik 4sn: drone'un kendi FS_GCS_TIMEOUT'undan (varsayilan 10sn,
        # bkz. _gcs_failsafe_ayarla) daha erken uyarir — operator, drone
        # kendi basina RTL yapmadan once haberdar olur.
        if gecen > 4:
            self._uyari_bant.setText("BAĞLANTI YANIT VERMİYOR")
            self._uyari_bant.show()
            QApplication.beep()
            # Worker yanit vermiyorsa harita/HUD'u da yavaslat — eski veriyi
            # "canliymis gibi" gostermeyi birak (_baglanti_kesildi ile ayni
            # yavaslatma, ama bagilanti henuz tam kopmadan).
            if self._js_timer.interval() < 1000:
                self._js_timer.setInterval(1000)
        else:
            self._uyari_bant.setText("BAĞLANTI KESİLDİ")
            self._uyari_bant.hide()
            if self._js_timer.interval() != 200:
                self._js_timer.setInterval(200)

        # Kategori bazlı bayat veri kontrolü — genel heartbeat taze olsa
        # bile GPS/batarya sensörü ayrı ayrı susmuş olabilir (bkz.
        # mavlink_handler.py: _son_veri_zamani / son_veri_zamanlari).
        zamanlar = self._mavlink.son_veri_zamanlari
        simdi = time.time()

        gps_zaman = zamanlar.get("gps")
        gps_bayat = gps_zaman is not None and (simdi - gps_zaman) > 3.0
        if gps_bayat != getattr(self, "_gps_bayat_son", False):
            if gps_bayat:
                self._gps_fix_lbl.setStyleSheet("color:#5a6a7a; font-style:italic; font-size:11px;")
            else:
                # Debounce önbelleğini sıfırla — bir sonraki gerçek GPS
                # mesajı rengi baştan doğru uygulasın (_gps_guncelle).
                self._gps_fix_renk_son = None
            self._gps_bayat_son = gps_bayat

        bat_zaman = zamanlar.get("batarya")
        bat_bayat = bat_zaman is not None and (simdi - bat_zaman) > 5.0
        if bat_bayat != getattr(self, "_bat_bayat_son", False):
            if bat_bayat:
                self._batarya_detay.setStyleSheet("color:#5a6a7a; font-style:italic; font-size:11px;")
            else:
                self._batarya_detay.setStyleSheet("color:#ffb74d; font-size:11px;")
            self._bat_bayat_son = bat_bayat

    def _hb_guncelle(self, mod_id: int, arm: bool):
        self._arm_durumu = arm
        self._log_satiri["mod_id"] = mod_id
        self._mod_lbl.setText(self._rozet_html(
            "MOD", UÇUŞ_MODLARI.get(mod_id, f"MOD-{mod_id}"), "#bdd8f2"
        ))
        if hasattr(self, "_mod_btn_map"):
            for _mid, _btn in self._mod_btn_map.items():
                if _mid == mod_id:
                    _btn.setStyleSheet(
                        "QPushButton { background:#94bce3; color:#12202c; "
                        "border:1px solid #94bce3; font-weight:bold; }"
                    )
                else:
                    _btn.setStyleSheet("")
        _onceki_arm = getattr(self, "_onceki_arm_durumu", False)
        if arm:
            self._arm_lbl.setText(self._rozet_html("DURUM", "ARMED", "#a8cf94"))
            self._arm_lbl.setStyleSheet(
                "background:rgba(143,191,122,0.12); "
                "border:1px solid rgba(143,191,122,0.45); padding:1px 12px;"
            )
            self._ucus_yapildi = True   # Bu bağlantıda en az bir kez ARM oldu
        else:
            self._arm_lbl.setText(self._rozet_html("DURUM", "DISARM", "#7e9cb8"))
            self._arm_lbl.setStyleSheet(
                f"background:transparent; border:1px solid {KOKPIT_KENAR}; padding:1px 12px;"
            )
            # ARMED → DISARM geçişi: drone indi, otomatik rapor üret
            if _onceki_arm and getattr(self, "_ucus_yapildi", False):
                self._ucus_yapildi = False   # Bir sonraki ARM için sıfırla
                self._mesaj_ekle(4, "✅ İniş algılandı — uçuş raporu 5 sn içinde hazırlanıyor…")
                QTimer.singleShot(5000, self._inis_sonrasi_rapor)
        self._onceki_arm_durumu = arm
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
        # Hücre bilgisi varsa ekle
        _hucre_str = ""
        if self._min_hucre_volt > 0:
            _hucre_str = f"  |  min hücre: {self._min_hucre_volt:.3f}V"
        if volt > 0 and amper > 0.5 and yuzde > 0:
            sure_dk = (volt * yuzde / 100.0) / amper * 60
            self._batarya_detay.setText(
                f"{volt:.2f}V  {amper:.2f}A  Tahmini süre: {sure_dk:.0f} dk{_hucre_str}"
            )
        else:
            yuzde_str = f"{yuzde}%" if yuzde >= 0 else "?%"
            self._batarya_detay.setText(
                f"{volt:.2f}V  {amper:.2f}A  {yuzde_str}  Tahmini süre: --{_hucre_str}"
            )
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

    def _hud_flush(self):
        """_hud_kuyruk'ta bekleyen en-son değerleri ekrana yazar (5Hz, _js_timer)."""
        if "vfr" in self._hud_kuyruk:
            irtifa, hiz, dikey, uzaklik = self._hud_kuyruk.pop("vfr")
            self._irtifa_lbl.setText(f"{irtifa:.2f}")
            self._hiz_lbl.setText(f"{hiz:.2f}")
            self._dikey_lbl.setText(f"{dikey:+.2f}")
            self._uzaklik_lbl.setText(f"{uzaklik:.0f}")

    def _vfr_guncelle(self, irtifa: float, hiz: float, dikey: float, uzaklik: float):
        # NOT: state güncelleme, loglama ve RTL izleyici HER mesajda (10Hz)
        # senkron çalışır — sadece asagıdaki setText çağrıları (saf ekran
        # boyaması) _hud_kuyruk üzerinden 5Hz'e (_js_timer) düşürülür.
        self._guncel_irtifa      = irtifa
        self._guncel_eve_uzaklik = uzaklik
        self._hud_kuyruk["vfr"] = (irtifa, hiz, dikey, uzaklik)
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
        if hasattr(self, "_gps_badge_lbl"):
            _badge_renk = "#a8cf94" if fix >= 3 else ("#e0c07a" if fix == 2 else "#c98b85")
            self._gps_badge_lbl.setText(self._rozet_html("GPS", f"{fix_str} · {uydu}", _badge_renk))
        self._gps_fix_lbl.setText(f"Fix: {fix_str}")
        if fix_renk != getattr(self, "_gps_fix_renk_son", None):
            self._gps_fix_renk_son = fix_renk
            self._gps_fix_lbl.setStyleSheet(f"color: {fix_renk}; font-weight: bold;")
        self._gps_uydu_lbl.setText(f"Uydu: {uydu}")
        uydu_renk = "#f44336" if uydu < 6 else ("#ffc107" if uydu < 8 else "#4caf50")
        if uydu_renk != getattr(self, "_gps_uydu_renk_son", None):
            self._gps_uydu_renk_son = uydu_renk
            self._gps_uydu_lbl.setStyleSheet(f"color: {uydu_renk};")
        self._gps_konum_lbl.setText(f"{lat:.5f}, {lon:.5f}")
        # Harita JS güncellemesi — doğrudan değil, 500 ms timer buffer'ına yaz
        self._harita_bekleyen_lat = lat
        self._harita_bekleyen_lon = lon
        self._guncel_gps_fix = fix
        self._log_satiri.update({"gps_fix": fix, "gps_uydu": uydu, "lat": lat, "lon": lon})

        # Ev konumu etiketi — ilk 3D fix'te göster
        if fix >= 3 and lat != 0.0 and hasattr(self, '_wp_home_lbl'):
            if self._wp_home_lbl.text() == "Ev: —":
                self._wp_home_lbl.setText(f"Ev: {lat:.5f}, {lon:.5f}")

        # İlk 3D fix'te terrain hazırlığı — fence/önceki alan sınırına göre akıllı karar
        # _alan_karar_yukleniyor: başlangıçtaki arka plan NPZ okuması hâlâ sürüyorsa
        # burada YENİ bir indirme/yazma başlatma — aynı dosyada okuma/yazma çakışır
        # (AlanHazirlikThread aynı alan_verisi.npz'ye yazıyor). Okuma bitince bir
        # sonraki GPS güncellemesinde bu blok normal akışıyla tekrar denenir.
        if (fix >= 3
                and not self._alan_hazirlik_yapildi
                and not self._alan_karar_yukleniyor
                and self._alan_karar is None
                and lat != 0.0):
            self._alan_hazirlik_yapildi = True
            if self._alan_bounds:
                lat_min, lat_max, lon_min, lon_max = self._alan_bounds
                if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
                    # GPS mevcut terrain alanı içinde — NPZ'yi arka planda yeniden yükle
                    _npz = os.path.join(os.path.dirname(__file__), "alan_verisi.npz")
                    if not os.path.isfile(_npz):
                        _npz = "alan_verisi.npz"
                    if os.path.isfile(_npz):
                        self._alan_karar_yukleniyor = True
                        import threading as _threading_gps
                        _threading_gps.Thread(
                            target=self._alan_karar_arka_planda_yukle, args=(_npz,), daemon=True
                        ).start()
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


    def _alan_karar_arka_planda_yukle(self, npz_yolu: str):
        """
        Başlangıçta bulunan alan_verisi.npz için np.load + AlanInisKarar.
        Worker thread'de çalışır — Qt nesnelerine sadece QTimer.singleShot(0, ...)
        üzerinden, main thread'e dönerek dokunulur.
        """
        try:
            import numpy as _np_bg
            from alan_inis_karar import AlanInisKarar
            _data = _np_bg.load(npz_yolu)
            bounds = None
            if "bounds" in _data:
                _b = _data["bounds"]   # [lon_min, lat_min, lon_max, lat_max]
                bounds = (float(_b[1]), float(_b[3]), float(_b[0]), float(_b[2]))
            karar = AlanInisKarar(npz_yolu)

            def _uygula():
                self._alan_bounds = bounds
                self._alan_karar = karar
                self._alan_karar_yukleniyor = False
                self._mesaj_ekle(6, f"Alan veri dosyası yüklendi: {os.path.basename(npz_yolu)}")
            QTimer.singleShot(0, _uygula)
        except Exception as _e:
            _hata_msg = f"Alan verisi yüklenemedi: {_e}"
            def _hata_uygula():
                self._alan_karar_yukleniyor = False
                self._mesaj_ekle(3, _hata_msg)
            QTimer.singleShot(0, _hata_uygula)

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
        α = self._ruz_ema_alpha
        self._ruz_ema = α * hiz + (1.0 - α) * self._ruz_ema
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
        _te = self._ruz_trend_esik
        trend_ok = ("↑" if self._ruz_trend_ms_per_s >  _te else
                    "↓" if self._ruz_trend_ms_per_s < -_te else "→")
        self._ruzgar_zemin_lbl.setText(
            f"Zemin: {self._ruz_zemin_ms * 3.6:.0f} km/h {trend_ok}"
        )

        # ── 7. Sürekli gust dedektörü ─────────────────────────────────────────
        self._gust_dedekt(hiz, hiz_f, _time.monotonic())

        # ── 8. Bekleme önerisi ─────────────────────────────────────────────────
        self._bekleme_onerisi_guncelle(hiz_f)

        # ── 8b. Sürekli yüksek rüzgar irtifa yönetimi ─────────────────────────
        # Gust dedektörü anlık spike'ları yakalar; bu blok EMA'nın kendisi
        # dikkat eşiğinin üstünde kaldığı durumu yönetir.
        self._surekli_ruzgar_irtifa_kontrol(hiz_f, _time.monotonic())

        # ── 8c. Trend bazlı önleyici irtifa düşürme ────────────────────────────
        self._trend_irtifa_kontrol(hiz_f, _time.monotonic())

        # ── 8d. Hız kısıtlaması ────────────────────────────────────────────────
        self._ruzgar_hiz_kontrol(hiz_f)

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
        # Renk eşikleri config'den türetilir (m/s → km/h)
        _dik_kmh = float(_cfg.al("ruzgar.dikkat_ms",    5.5)) * 3.6   # ~19.8 km/h
        _teh_kmh = self._ruz_tehlikeli_ms * 3.6                        # ~40 km/h
        _krt_kmh = self._ruz_kritik_ms    * 3.6                        # ~60 km/h
        if hiz_kmh < _dik_kmh:
            renk, seviye = "#4caf50", "NORMAL"
        elif hiz_kmh < _teh_kmh:
            renk, seviye = "#ffc107", "DİKKAT"
        elif hiz_kmh < _krt_kmh:
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
                guncel_irtifa  = getattr(self, "_guncel_irtifa", 0.0)
                if irtifa_tavsiye is not None:
                    # Mesajı her zaman yaz
                    self._mesaj_ekle(3,
                        f"⚡ Sürekli gust {sure:.0f} sn: {hiz_ham*3.6:.0f} km/h "
                        f"(EMA: {hiz_f*3.6:.0f} km/h) — motorlar zorlanıyor. "
                        f"{guncel_irtifa:.0f}m → {irtifa_tavsiye:.0f}m'ye alçalınıyor "
                        f"(Hellmann: rüzgar ~{self._ruz_tehlikeli_ms*3.6:.0f} km/h'e düşer)."
                    )
                    # Otonom irtifa düşürme:
                    # Sadece armed + havada (>8m) + GUIDED/AUTO/RTL modunda
                    # ve daha önce gust için irtifa ayarlanmadıysa
                    _irtifa_modu = self._son_mod_id in (3, 4, 6)  # AUTO/GUIDED/RTL
                    if (self._arm_durumu
                            and guncel_irtifa > 8.0
                            and _irtifa_modu
                            and not self._ruz_irtifa_ayarli):
                        self._ruz_irtifa_ayarli = True
                        self._ruz_irtifa_onceki = guncel_irtifa
                        self._mavlink.irtifa_degistir(irtifa_tavsiye)
                        self._mesaj_ekle(2,
                            f"⬇ OTOMATİK: irtifa {guncel_irtifa:.0f}m → {irtifa_tavsiye:.0f}m "
                            f"(gust koruması aktif).")
                        self._js(f"durumGoster('⬇ Gust: irtifa {guncel_irtifa:.0f}m → {irtifa_tavsiye:.0f}m');")
                else:
                    self._mesaj_ekle(3,
                        f"⚡ Sürekli gust {sure:.0f} sn: {hiz_ham*3.6:.0f} km/h "
                        f"(EMA: {hiz_f*3.6:.0f} km/h) — motorlar zorlanıyor, iniş düşün."
                    )

            # Gust bitti: ham hız EMA'nın altına düştüğünde sıfırla
            if hiz_ham < hiz_f:
                self._gust_baslangic_t = None
                self._gust_alarm_verildi = False
                # Gust için düşürülen irtifayı geri al
                if self._ruz_irtifa_ayarli:
                    self._ruz_irtifa_ayarli = False
                    onceki = self._ruz_irtifa_onceki
                    self._mavlink.irtifa_degistir(onceki)
                    self._mesaj_ekle(6,
                        f"⬆ Gust geçti: irtifa {onceki:.0f}m'ye geri alınıyor.")
                    self._js(f"durumGoster('⬆ Gust bitti: irtifa {onceki:.0f}m');")

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

    # ── Rüzgar irtifa / hız yönetimi yardımcıları ────────────────────────────

    def _ruz_irtifa_uygun_mu(self) -> bool:
        """Otonom irtifa/hız değişikliği için ortak ön koşulları kontrol eder."""
        return (self._arm_durumu
                and getattr(self, "_guncel_irtifa", 0.0) > 8.0
                and self._son_mod_id in (3, 4, 6))   # AUTO / GUIDED / RTL

    def _surekli_ruzgar_irtifa_kontrol(self, hiz_f: float, simdi: float):
        """
        EMA'nın kendisi dikkat eşiğini aşıp aşmadığını 30 sn'de bir kontrol eder.
        Gust değil, sürekli yüksek rüzgar durumu: irtifayı Hellmann hedefine indir.
        Rüzgar yatıştığında eski irtifaya geri çık.
        """
        _dikkat = float(_cfg.al("ruzgar.dikkat_ms", 5.5))

        # Sürekli yüksek → irtifa düşür
        if (hiz_f >= _dikkat
                and not self._ruz_surekli_ayarli
                and not self._ruz_irtifa_ayarli):  # gust zaten ayarladıysa dokunma
            if simdi - self._ruz_surekli_son_t < 30.0:
                return   # 30 sn bekle — tek seferlik değişikliğe yakınsın
            self._ruz_surekli_son_t = simdi
            irtifa_tavsiye = self._guvenli_irtifa_hesapla(hiz_f)
            if irtifa_tavsiye is None:
                return
            if not self._ruz_irtifa_uygun_mu():
                return
            guncel = self._guncel_irtifa
            self._ruz_surekli_ayarli     = True
            self._ruz_surekli_irt_onceki = guncel
            self._mavlink.irtifa_degistir(irtifa_tavsiye)
            self._mesaj_ekle(3,
                f"🌬 Sürekli yüksek rüzgar (EMA {hiz_f*3.6:.0f} km/h) — "
                f"irtifa {guncel:.0f}m → {irtifa_tavsiye:.0f}m (Hellmann koruma).")
            self._js(f"durumGoster('🌬 Rüzgar: irtifa {guncel:.0f}m → {irtifa_tavsiye:.0f}m');")

        # Rüzgar yatıştı → geri çık
        elif hiz_f < _dikkat * 0.80 and self._ruz_surekli_ayarli:
            self._ruz_surekli_ayarli = False
            onceki = self._ruz_surekli_irt_onceki
            if self._ruz_irtifa_uygun_mu() and onceki > 0:
                self._mavlink.irtifa_degistir(onceki)
                self._mesaj_ekle(6,
                    f"⬆ Rüzgar normale döndü ({hiz_f*3.6:.0f} km/h): "
                    f"irtifa {onceki:.0f}m'ye geri alınıyor.")
                self._js(f"durumGoster('⬆ Rüzgar normale döndü: irtifa {onceki:.0f}m');")

    def _trend_irtifa_kontrol(self, hiz_f: float, simdi: float):
        """
        Trend hızla artıyorsa (>0.08 m/s²) ve tehlikeli eşiğe 90 sn içinde
        ulaşılacaksa, eşiğe çarpmadan ÖNCE irtifayı düşür.
        """
        trend     = self._ruz_trend_ms_per_s
        tehlikeli = self._ruz_tehlikeli_ms

        if self._ruz_trend_irtifa_verildi:
            # Trend tersine döndüyse bayrağı sıfırla
            if trend < 0.03:
                self._ruz_trend_irtifa_verildi = False
            return

        if trend < 0.08:
            return   # Yavaş artış — müdahale gerekmez

        # Tehlikeli eşiğe ulaşma süresi
        kalan_sure = (tehlikeli - hiz_f) / trend if trend > 0 else 9999
        if kalan_sure > 90 or kalan_sure <= 0:
            return   # Yeterli süre var veya zaten aşıldı

        irtifa_tavsiye = self._guvenli_irtifa_hesapla(tehlikeli * 1.05)  # biraz üstü için hesapla
        if irtifa_tavsiye is None or not self._ruz_irtifa_uygun_mu():
            return
        if self._ruz_irtifa_ayarli or self._ruz_surekli_ayarli:
            return   # Başka bir koruma zaten aktif

        self._ruz_trend_irtifa_verildi = True
        guncel = self._guncel_irtifa
        self._ruz_surekli_ayarli     = True
        self._ruz_surekli_irt_onceki = guncel
        self._mavlink.irtifa_degistir(irtifa_tavsiye)
        self._mesaj_ekle(3,
            f"📈 Rüzgar artıyor — {kalan_sure:.0f} sn içinde tehlikeli eşiğe ulaşacak! "
            f"Önleyici: irtifa {guncel:.0f}m → {irtifa_tavsiye:.0f}m.")
        self._js(f"durumGoster('📈 Rüzgar artış trendi: irtifa {guncel:.0f}m → {irtifa_tavsiye:.0f}m');")

    def _ruzgar_hiz_kontrol(self, hiz_f: float):
        """
        Rüzgar dikkat eşiğini aştığında uçuş hızını kısıtlar (MAV_CMD_DO_CHANGE_SPEED).
        Normale dönünce config'deki normal_cms değerine geri alır.
        """
        _dikkat   = float(_cfg.al("ruzgar.dikkat_ms", 5.5))
        _normal_ms = float(_cfg.al("hiz_kisitlama.normal_cms", 1000)) / 100.0   # cm/s → m/s

        if hiz_f >= _dikkat and not self._ruz_hiz_kisitlandi:
            if not self._ruz_irtifa_uygun_mu():
                return
            # Hızı rüzgar hızıyla ters orantılı kısıtla: rüzgar arttıkça hız düşer
            # Formül: v_hedef = normal × (dikkat / hiz_f) — ama en az 2 m/s
            v_hedef = max(_normal_ms * (_dikkat / hiz_f), 2.0)
            v_hedef = round(v_hedef, 1)
            self._ruz_hiz_kisitlandi = True
            self._ruz_hiz_onceki     = _normal_ms
            self._mavlink.hiz_kisitla(v_hedef)
            self._mesaj_ekle(5,
                f"🐢 Rüzgar nedeniyle hız kısıtlandı: {_normal_ms:.0f} → {v_hedef:.0f} m/s.")

        elif hiz_f < _dikkat * 0.80 and self._ruz_hiz_kisitlandi:
            self._ruz_hiz_kisitlandi = False
            onceki = self._ruz_hiz_onceki
            if onceki > 0 and self._ruz_irtifa_uygun_mu():
                self._mavlink.hiz_kisitla(onceki)
                self._mesaj_ekle(6,
                    f"🐇 Rüzgar azaldı: hız kısıtlaması kaldırıldı ({onceki:.0f} m/s).")

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

        # ── Akıllı uyarı yönlendirmesi ──────────────────────────────────────
        # critical (0-1): sesli uyarı + status bar'da görünür kalıcı uyarı
        # warning/info (2-7): sadece renkli log (mevcut davranış, değişmedi)
        if severity <= 1:
            simdi = time.monotonic()
            if simdi - getattr(self, "_son_kritik_uyari_zamani", 0.0) > 8.0:
                self._son_kritik_uyari_zamani = simdi
                self._sesli_uyan(metin)
                if hasattr(self, "_durum_bar"):
                    self._durum_bar.showMessage(f"⚠ KRİTİK: {metin}", 6000)

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
            
            # Analytics collector'ı update et
            timestamp_s = s.get("timestamp_s", 0.0)
            analytics_dict = {
                "timestamp_s": timestamp_s,
                "lat": s.get("lat"),
                "lon": s.get("lon"),
                "alt_agl_m": s.get("irtifa"),
                "climb_rate_ms": s.get("dikey_hiz"),
                "speed_ms": s.get("hiz"),
                "battery_volt": s.get("bat_volt"),
                "battery_percent": s.get("bat_yuzde"),
                "battery_current_a": s.get("bat_amper"),
                "wind_speed_ms": s.get("ruzgar_ms"),
                "imu0_temp": s.get("imu0_c"),
                "imu1_temp": s.get("imu1_c"),
                "imu2_temp": s.get("imu2_c"),
                "gps_fix": s.get("gps_fix"),
                "mode": s.get("mod_adi"),
                "ekf_error": bool(s.get("ekf_hata", 0.0) > 0.8),
                "rc_lost": False,  # RC status MAVLink handler'ından gelir
                "vibration": s.get("vibrasyon", 0.0),
            }
            self._analytics.update_from_dict(analytics_dict, timestamp_s)
            if self._analytics_panel:
                self._analytics_panel.update_metrics(self._analytics.get_metrics())

    def _ekf_guncelle(self, bayraklar: int, hata: float):
        self._guncel_ekf_hata = hata
        self._ekf_bayraklar   = bayraklar
        # Bit 0 (tutum) + Bit 1 (yatay hız) + Bit 2 (dikey hız) — üçü kilitli ise güvenilir
        self._ekf_ruzgar_gecerli = (
            bool(bayraklar & 0x0001) and   # tutum kilidi
            bool(bayraklar & 0x0002) and   # yatay hız kilidi
            bool(bayraklar & 0x0004)       # dikey hız kilidi (yüksek irtifada kritik)
        )
        if bayraklar & 0x01F:
            self._ekf_lbl.setText(self._rozet_html("EKF", f"İYİ {hata:.2f}", "#a8cf94"))
            self._ekf_lbl.setStyleSheet(
                "background:rgba(143,191,122,0.12); "
                "border:1px solid rgba(143,191,122,0.45); padding:1px 12px;"
            )
        else:
            self._ekf_lbl.setText(self._rozet_html("EKF", "HATA", "#c98b85"))
            self._ekf_lbl.setStyleSheet(
                "background:rgba(194,91,82,0.12); "
                "border:1px solid rgba(194,91,82,0.5); padding:1px 12px;"
            )
        self._log_satiri.update({"ekf_bayrak": bayraklar, "ekf_hata": hata})

    def _vibrasyon_guncelle(self, vib_mss: float, klipping: int):
        """VIBRATION mesajından titreşim seviyesini saklar.
        Sürekli yüksek vibrasyonda EK3_WIND_P_NSE ayar önerisi üretir."""
        self._guncel_vibrasyon_mss = vib_mss
        self._guncel_vib_klip      = klipping
        if hasattr(self, "_prearm_vib"):
            ok = vib_mss < 30.0 and klipping == 0
            self._prearm_renk(self._prearm_vib, f"{vib_mss:.1f} m/s² · klip {klipping}", ok)

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
        """Çift tıklayınca sadece 'Yeni Değer' sütununu (2) düzenleme moduna al.

        Gerçek değer yakalama işi burada YAPILMAZ — editItem() sadece
        düzenleme kutusunu açar, kullanıcı henüz bir şey yazmamış olur.
        Kullanıcı Enter'a basıp düzenlemeyi bitirdiğinde asıl yakalama
        _param_tablo_degisti (itemChanged sinyali) içinde olur.
        """
        if not getattr(self, "_param_ui_hazir", False):
            return
        satir = index.row()
        if not self._param_tablo.item(satir, 0):
            return
        self._param_tablo.setEditTriggers(QAbstractItemView.DoubleClicked)
        self._param_tablo.editItem(self._param_tablo.item(satir, 2))
        self._param_tablo.setEditTriggers(QAbstractItemView.NoEditTriggers)

    def _param_tablo_degisti(self, item):
        """'Yeni Değer' sütunu düzenlemesi TAMAMLANINCA (Enter/odak kaybı) çağrılır."""
        if not getattr(self, "_param_ui_hazir", False):
            return
        if item.column() != 2:
            return
        satir = item.row()
        ad_item = self._param_tablo.item(satir, 0)
        if not ad_item or not item.text():
            return
        ad = ad_item.text()
        try:
            yeni_deger = float(item.text())
        except ValueError:
            return
        self._degistirilen_parametreler[ad] = yeni_deger
        item.setForeground(QColor("#ffc107"))
        self._param_bilgi.setText(f"{len(self._degistirilen_parametreler)} parametre değiştirildi (uygulanmadı).")

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
        self._baglanti_temizligi_yap()
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

    def _komut_izinli_mi(self) -> bool:
        """
        Riskli/etkili komutlardan (RTL, iniş, mod değiştirme, kalibrasyon,
        paraşüt vb.) önce çağrılır. Bağlantı yoksa veya worker heartbeat
        bayatsa (bkz. _heartbeat_kontrol, 4sn eşiği) komutu engeller ve
        kullanıcıya GERÇEK durumu bildirir — eskiden bağlantı kesikken bile
        bu butonlara tıklanabiliyordu ve "komut gönderildi" mesajı
        gösteriliyordu, oysa alt katman komutu sessizce yutuyordu.
        """
        if not self._bagli:
            self._mesaj_ekle(2, "Komut gönderilmedi — bağlantı yok.")
            return False
        if time.time() - self._mavlink.son_heartbeat_zamani > 4.0:
            self._mesaj_ekle(2, "Komut gönderilmedi — bağlantı yanıt vermiyor.")
            return False
        return True

    def _rtl_tikla(self):
        if not self._komut_izinli_mi():
            return
        self._mavlink.mod_degistir(6)
        self._mesaj_ekle(3, "EV'E DÖN (RTL) komutu gönderildi.")

    def _hovering_tikla(self):
        if not self._komut_izinli_mi():
            return
        self._mavlink.mod_degistir(5)
        self._mesaj_ekle(6, "HOVERING (LOITER) komutu gönderildi.")

    def _inis_tikla(self):
        if not self._komut_izinli_mi():
            return
        self._mavlink.mod_degistir(9)
        self._mesaj_ekle(3, "ACİL İNİŞ komutu gönderildi.")

    def _devam_tikla(self):
        if not self._komut_izinli_mi():
            return
        self._mavlink.mod_degistir(3)
        self._mesaj_ekle(6, "DEVAM ET (AUTO) komutu gönderildi.")

    def _mod_tikla(self, mod_id: int):
        if not self._komut_izinli_mi():
            return
        self._mavlink.mod_degistir(mod_id)
        self._mesaj_ekle(6, f"Mod: {UÇUŞ_MODLARI.get(mod_id, mod_id)}")

    def _ev_yap_tikla(self):
        if not self._komut_izinli_mi():
            return
        self._mavlink.ev_noktasi_sifirla()
        self._js(f"evNoktasiGuncelle({self._guncel_lat}, {self._guncel_lon});")
        self._mesaj_ekle(6, f"Ev noktası güncellendi: {self._guncel_lat:.5f}, {self._guncel_lon:.5f}")

    def _kalibrasyon_tikla(self):
        """MAV_CMD_PREFLIGHT_CALIBRATION (241) — gyro/manyetometre/ivmeölçer kalibrasyonu."""
        if not self._komut_izinli_mi():
            return
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QCheckBox, QDialogButtonBox
        dlg = QDialog(self)
        dlg.setWindowTitle("🔧 Kalibrasyon Seçimi")
        dlg.setMinimumWidth(280)
        lay = QVBoxLayout(dlg)
        lay.addWidget(__import__('PyQt5.QtWidgets', fromlist=['QLabel']).QLabel(
            "<b>Kalibrasyon tiplerini seçin:</b><br>"
            "<small>(Drone yerde, motorlar kapalı olmalı)</small>"
        ))
        gyro_cb  = QCheckBox("Gyro kalibrasyonu    (param1=1)")
        mag_cb   = QCheckBox("Manyetometre         (param2=1)")
        accel_cb = QCheckBox("İvmeölçer            (param5=1)")
        baro_cb  = QCheckBox("Barometri sıfırlama  (param3=1)")
        gyro_cb.setChecked(True)
        for cb in (gyro_cb, mag_cb, accel_cb, baro_cb):
            lay.addWidget(cb)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec_() != QDialog.Accepted:
            return
        p1 = 1 if gyro_cb.isChecked()  else 0
        p2 = 1 if mag_cb.isChecked()   else 0
        p3 = 1 if baro_cb.isChecked()  else 0
        p5 = 1 if accel_cb.isChecked() else 0
        if not any([p1, p2, p3, p5]):
            self._mesaj_ekle(3, "Kalibrasyon: hiçbir tip seçilmedi.")
            return
        # MAV_CMD_PREFLIGHT_CALIBRATION = 241
        # p1=gyro, p2=mag, p3=pressure, p4=rc, p5=accel, p6=compmot, p7=airspeed
        self._mavlink.komut_gonder(241, p1, p2, p3, 0, p5, 0, 0)
        tipler = []
        if p1: tipler.append("Gyro")
        if p2: tipler.append("Manyetometre")
        if p3: tipler.append("Barometri")
        if p5: tipler.append("İvmeölçer")
        self._mesaj_ekle(4, f"🔧 Kalibrasyon başlatıldı: {', '.join(tipler)} — STATUSTEXT mesajlarını takip edin.")

    def _parasut_tikla(self):
        """DO_PARACHUTE (208) — paraşütü tetikler. Onay gerektirir."""
        if not self._komut_izinli_mi():
            return
        cevap = QMessageBox.question(
            self, "⚠ PARAŞÜT ONAYI",
            "Paraşüt fırlatılacak!\n\nDrone düşecek ve kurtarılamayabilir.\n\nEmin misiniz?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if cevap == QMessageBox.Yes:
            # MAV_CMD_DO_PARACHUTE = 208, param1=2 (fırlat/tetikle)
            self._mavlink.komut_gonder(208, 2)
            self._mesaj_ekle(2, "🪂 PARAŞÜT TETİKLENDİ — MAV_CMD_DO_PARACHUTE gönderildi.")
            self._sesli_uyan("Paraşüt tetiklendi")

    def _wp_git_tikla(self):
        """Seçili WP satırına MISSION_SET_CURRENT komutu gönderir."""
        if not hasattr(self, '_wp_tablo'):
            return
        satirlar = self._wp_tablo.selectionModel().selectedRows()
        if not satirlar:
            self._mesaj_ekle(3, "Önce tabloda bir waypoint satırı seç.")
            return
        seq = satirlar[0].row() + 1   # seq 1-tabanlı (0 = ev noktası)
        self._mavlink.mission_wp_atla(seq)
        self._mesaj_ekle(6, f"WP {seq} aktif yapılıyor (MISSION_SET_CURRENT)…")
        self._sesli_uyan(f"Waypoint {seq} seçildi")

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

    def _param_karsilastir_tikla(self):
        """Mevcut param_cache ile bir JSON yedek dosyasını karşılaştırır, farkları listeler."""
        if not self._param_cache:
            QMessageBox.warning(self, "Parametre Yok",
                "Önce 'Parametreleri İndir' ile parametreleri indirin.")
            return

        dosya, _ = QFileDialog.getOpenFileName(
            self, "Karşılaştırılacak Parametre Yedeği", "",
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

        yedek: dict = veri.get("parametreler", veri)
        # Karşılaştırma
        farklar = []
        for ad, yedek_val in yedek.items():
            if ad in self._param_cache:
                guncel_val = self._param_cache[ad]
                try:
                    if abs(float(guncel_val) - float(yedek_val)) > 1e-6:
                        farklar.append((ad, float(yedek_val), float(guncel_val)))
                except (TypeError, ValueError):
                    pass
        sadece_yedekte = [ad for ad in yedek if ad not in self._param_cache]
        sadece_guncelde = [ad for ad in self._param_cache if ad not in yedek]

        # Sonuç dialogu
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QDialogButtonBox
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Parametre Karşılaştırması — {os.path.basename(dosya)}")
        dlg.resize(700, 500)
        lay = QVBoxLayout(dlg)
        txt = QTextEdit()
        txt.setReadOnly(True)
        txt.setFont(QFont("Courier New", 9))

        satirlar = []
        satirlar.append(f"=== Parametre Karşılaştırması ===")
        satirlar.append(f"Yedek: {os.path.basename(dosya)}")
        satirlar.append(f"Farklı değer: {len(farklar)} | Sadece yedekte: {len(sadece_yedekte)} | Sadece mevcut: {len(sadece_guncelde)}")
        satirlar.append("")

        if farklar:
            satirlar.append("── FARKLI DEĞERLER ──────────────────────────────────")
            satirlar.append(f"{'Parametre':<35} {'Yedek':>12} {'Mevcut':>12}")
            satirlar.append("-" * 62)
            for ad, yv, gv in sorted(farklar):
                satirlar.append(f"{ad:<35} {yv:>12.4f} {gv:>12.4f}")

        if sadece_yedekte:
            satirlar.append("")
            satirlar.append(f"── SADECE YEDEKTE ({len(sadece_yedekte)}) ────────────────────")
            for ad in sorted(sadece_yedekte)[:30]:
                satirlar.append(f"  {ad}")
            if len(sadece_yedekte) > 30:
                satirlar.append(f"  ... ve {len(sadece_yedekte)-30} tane daha")

        if sadece_guncelde:
            satirlar.append("")
            satirlar.append(f"── SADECE MEVCUT DRONE'DA ({len(sadece_guncelde)}) ───────────────")
            for ad in sorted(sadece_guncelde)[:30]:
                satirlar.append(f"  {ad}")
            if len(sadece_guncelde) > 30:
                satirlar.append(f"  ... ve {len(sadece_guncelde)-30} tane daha")

        if not farklar and not sadece_yedekte and not sadece_guncelde:
            satirlar.append("✓ Parametreler birebir aynı!")

        txt.setPlainText("\n".join(satirlar))
        lay.addWidget(txt)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        dlg.exec_()
        self._mesaj_ekle(6, f"Karşılaştırma: {len(farklar)} fark, {len(sadece_yedekte)} eksik, {len(sadece_guncelde)} fazla.")

    def _harita_yol_temizle(self):
        self._js("ucusYolunuTemizle();")

    # ── Waypoint Görev Planlama ───────────────────────────────────────────────

    _WP_KOMUTLAR = ["NAV_WAYPOINT", "TAKEOFF", "LAND", "LOITER_TURNS",
                    "LOITER_TIME", "LOITER_UNLIMITED", "RTL", "DELAY",
                    "DO_LAND_START", "DO_JUMP", "DO_CHANGE_SPEED",
                    "DO_DIGICAM_CONTROL", "DO_SET_CAM_TRIGG_DIST"]
    _WP_KOMUT_KODLARI = {
        "NAV_WAYPOINT":          16,
        "TAKEOFF":               22,
        "LAND":                  21,
        "LOITER_TURNS":          18,
        "LOITER_TIME":           19,
        "LOITER_UNLIMITED":      17,
        "RTL":                   20,
        "DELAY":                 93,
        "DO_LAND_START":        189,   # RTL/failsafe burada başlayan iniş yaklaşmasına atlar
        "DO_JUMP":              177,   # P1=hedef WP seq, P2=tekrar sayısı (-1=sonsuz)
        "DO_CHANGE_SPEED":      178,   # P1=hız tipi (0=hava,1=zemin), P2=hız (m/s)
        "DO_DIGICAM_CONTROL":   203,   # P1=oturum (1=aç), P5=fotoğraf çek (1)
        "DO_SET_CAM_TRIGG_DIST":206,   # P1=tetikleme mesafesi (m), 0=durdur
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

            # Sütun 2,3,4 — P1/P2/P3 parametreleri (düzenlenebilir)
            # Yeni sütun dizini: #=0, Komut=1, P1=2, P2=3, P3=4, Enlem=5, Boylam=6, İrtifa=7, Mesafe=8, AZ=9, btn=10
            komut_adi = wp.get("komut", "NAV_WAYPOINT")
            _p_ipucu = {
                # {komut: (p1, p2, p3)}
                "NAV_WAYPOINT":         ("Kabul yarıçapı (m)", "Geçiş (sn)", "—"),
                "TAKEOFF":              ("Min pitch (°)", "—", "—"),
                "LAND":                 ("Abort irtifa (m)", "—", "—"),
                "LOITER_TURNS":         ("Tur sayısı", "Yarıçap (m, 0=wp)", "—"),
                "LOITER_TIME":          ("Bekleme (sn)", "Yarıçap (m)", "—"),
                "LOITER_UNLIMITED":     ("Yarıçap (m)", "—", "—"),
                "DELAY":                ("Gecikme (sn)", "—", "—"),
                "DO_LAND_START":        ("—", "—", "—"),
                "DO_JUMP":              ("Hedef WP no", "Tekrar sayısı", "—"),
                "DO_CHANGE_SPEED":      ("Hız tipi (0=hava,1=yer)", "Hız (m/s)", "İvme (m/s²,-1=yok)"),
                "DO_DIGICAM_CONTROL":   ("Oturum (1=aç)", "—", "—"),
                "DO_SET_CAM_TRIGG_DIST":("Tetik mes. (m)", "—", "—"),
            }
            p1_val = wp.get("p1", 0)
            p2_val = wp.get("p2", 0)
            p3_val = wp.get("p3", 0)
            ipucu = _p_ipucu.get(komut_adi, ("Parametre 1", "Parametre 2", "Parametre 3"))

            def _pitem(val, tip_str):
                _it = QTableWidgetItem(str(int(val)) if val == int(val) else f"{val:.1f}")
                _it.setToolTip(tip_str)
                _it.setTextAlignment(Qt.AlignCenter)
                return _it

            p1_item = _pitem(p1_val, ipucu[0])
            p2_item = _pitem(p2_val, ipucu[1])
            p3_item = _pitem(p3_val, ipucu[2])

            # Sütun 5,6 — lat/lon (salt okunur)
            lat = QTableWidgetItem(f"{wp['lat']:.6f}")
            lat.setFlags(lat.flags() & ~Qt.ItemIsEditable)
            lon = QTableWidgetItem(f"{wp['lon']:.6f}")
            lon.setFlags(lon.flags() & ~Qt.ItemIsEditable)

            # Sütun 7 — irtifa (düzenlenebilir)
            alt = QTableWidgetItem(str(int(wp.get('alt', 50))))

            # Sütun 8 — mesafe (salt okunur)
            mes_str = f"{mesafeler[i]:.0f}" if i > 0 else "—"
            mes_item = QTableWidgetItem(mes_str)
            mes_item.setFlags(mes_item.flags() & ~Qt.ItemIsEditable)
            mes_item.setTextAlignment(Qt.AlignCenter)

            # Sütun 9 — azimut (salt okunur)
            az_str = f"{azimutlar[i]:.0f}" if i > 0 else "—"
            az_item = QTableWidgetItem(az_str)
            az_item.setFlags(az_item.flags() & ~Qt.ItemIsEditable)
            az_item.setTextAlignment(Qt.AlignCenter)

            self._wp_tablo.setItem(i, 0, no)
            self._wp_tablo.setItem(i, 2, p1_item)
            self._wp_tablo.setItem(i, 3, p2_item)
            self._wp_tablo.setItem(i, 4, p3_item)
            self._wp_tablo.setItem(i, 5, lat)
            self._wp_tablo.setItem(i, 6, lon)
            self._wp_tablo.setItem(i, 7, alt)
            self._wp_tablo.setItem(i, 8, mes_item)
            self._wp_tablo.setItem(i, 9, az_item)

            # Sütun 1 — komut tipi (QComboBox)
            combo = QComboBox()
            combo.addItems(self._WP_KOMUTLAR)
            combo.setCurrentText(komut_adi)
            combo.setStyleSheet("background:#1a2a3a; color:#ddd; font-size:11px;")
            combo.currentTextChanged.connect(lambda t, idx=i: self._wp_komut_degisti(idx, t))
            self._wp_tablo.setCellWidget(i, 1, combo)

            # Sütun 10 — Yukarı / Aşağı butonları
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
            self._wp_tablo.setCellWidget(i, 10, _btn_w)

        self._wp_tablo.blockSignals(False)
        self._wp_profil_guncelle()

    def _wp_tablo_degisti(self, item):
        """Kullanıcı tabloda irtifa veya P1/P2/P3 değerini değiştirince listeyi güncelle."""
        # Sütun dizini: #=0, Komut=1, P1=2, P2=3, P3=4, Enlem=5, Boylam=6, İrtifa=7, Mesafe=8, AZ=9, btn=10
        col = item.column()
        idx = item.row()
        if idx >= len(self._wp_listesi):
            return
        try:
            if col == 7:   # İrtifa
                alt = max(5, int(item.text()))
                self._wp_listesi[idx]['alt'] = alt
                self._js(f"wpIrtifaGuncelle({idx}, {alt});")
                self._wp_profil_guncelle()
            elif col == 2:  # P1 parametresi
                self._wp_listesi[idx]['p1'] = float(item.text())
            elif col == 3:  # P2 parametresi
                self._wp_listesi[idx]['p2'] = float(item.text())
            elif col == 4:  # P3 parametresi
                self._wp_listesi[idx]['p3'] = float(item.text())
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
                        p1_f    = float(parcalar[4])
                        lat_f   = float(parcalar[8])
                        lon_f   = float(parcalar[9])
                        alt_f   = float(parcalar[10])
                        # Komut kodu → isim
                        _ters = {v: k for k, v in self._WP_KOMUT_KODLARI.items()}
                        komut = _ters.get(cmd_id, "NAV_WAYPOINT")
                        yeni.append({"lat": lat_f, "lon": lon_f, "alt": alt_f,
                                     "komut": komut, "p1": p1_f})
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
                p1_val  = wp.get("p1", 0)
                satirlar.append(
                    f"{i}\t{current}\t3\t{cmd_id}\t{p1_val:.1f}\t0\t0\t0"
                    f"\t{wp['lat']:.8f}\t{wp['lon']:.8f}\t{wp.get('alt', 50):.1f}\t1"
                )
            with open(yol, "w", encoding="utf-8") as f:
                f.write("\n".join(satirlar) + "\n")
            self._mesaj_ekle(4, f"{len(self._wp_listesi)} waypoint kaydedildi: {yol}")
        except Exception as exc:
            self._mesaj_ekle(3, f"WP dosya kaydetme hatası: {exc}")

    def _wp_plan_yukle(self):
        """QGroundControl .plan (JSON) formatından WP listesini yükler."""
        yol, _ = QFileDialog.getOpenFileName(
            self, "QGC Plan Aç", "", "QGC Plan (*.plan);;Tüm Dosyalar (*)"
        )
        if not yol:
            return
        try:
            import json as _json
            with open(yol, encoding="utf-8") as f:
                data = _json.load(f)
            items = data.get("mission", {}).get("items", [])
            _ters = {v: k for k, v in self._WP_KOMUT_KODLARI.items()}
            yeni = []
            for it in items:
                if it.get("type") != "SimpleItem":
                    continue  # ComplexItem (survey vb.) bu turda desteklenmiyor
                params = it.get("params") or [0, 0, 0, 0, 0, 0, 0]
                while len(params) < 7:
                    params.append(0)
                komut = _ters.get(it.get("command", 16), "NAV_WAYPOINT")
                lat = params[4]
                lon = params[5]
                alt = params[6] if params[6] not in (None, 0) else it.get("Altitude", 50)
                if lat in (None, 0) and lon in (None, 0):
                    continue
                yeni.append({"lat": float(lat), "lon": float(lon),
                             "alt": float(alt or 50), "komut": komut,
                             "p1": float(params[0] or 0)})
            if not yeni:
                self._mesaj_ekle(3, "Plan dosyasında geçerli (SimpleItem) waypoint bulunamadı.")
                return
            self._wp_listesi = yeni
            self._wp_tablo_yenile()
            self._wp_haritadan_yenile()
            self._mesaj_ekle(4, f"{len(yeni)} waypoint QGC .plan dosyasından yüklendi: {yol}")
        except Exception as exc:
            self._mesaj_ekle(3, f"Plan yükleme hatası: {exc}")

    def _wp_plan_kaydet(self):
        """WP listesini QGroundControl .plan (JSON) formatında kaydeder."""
        if not self._wp_listesi:
            self._mesaj_ekle(3, "Kaydedilecek waypoint yok.")
            return
        yol, _ = QFileDialog.getSaveFileName(
            self, "QGC Plan Kaydet", "gorev.plan", "QGC Plan (*.plan);;Tüm Dosyalar (*)"
        )
        if not yol:
            return
        try:
            items = []
            for i, wp in enumerate(self._wp_listesi):
                cmd_id = self._WP_KOMUT_KODLARI.get(wp.get("komut", "NAV_WAYPOINT"), 16)
                items.append({
                    "AMSLAltAboveTerrain": None, "Altitude": wp.get("alt", 50), "AltitudeMode": 1,
                    "autoContinue": True, "command": cmd_id, "doJumpId": i + 1, "frame": 3,
                    "params": [wp.get("p1", 0), 0, 0, None, wp["lat"], wp["lon"], wp.get("alt", 50)],
                    "type": "SimpleItem",
                })
            plan = {
                "fileType": "Plan", "version": 1, "groundStation": "Dogus LOP GCS",
                "mission": {
                    "cruiseSpeed": 15, "firmwareType": 12, "hoverSpeed": 5,
                    "items": items,
                    "plannedHomePosition": [self._wp_listesi[0]["lat"], self._wp_listesi[0]["lon"], 0],
                    "vehicleType": 2, "version": 2,
                },
                "geoFence": {"circles": [], "polygons": [], "version": 2},
                "rallyPoints": {"points": [], "version": 2},
            }
            import json as _json
            with open(yol, "w", encoding="utf-8") as f:
                _json.dump(plan, f, indent=2)
            self._mesaj_ekle(4, f"{len(items)} waypoint QGC .plan olarak kaydedildi: {yol}")
        except Exception as exc:
            self._mesaj_ekle(3, f"Plan kaydetme hatası: {exc}")

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

    # ── Yeni MAVLink mesaj handler'ları ──────────────────────────────────────

    def _mission_wp_degisti(self, seq: int):
        """MISSION_CURRENT: drone'un aktif waypoint'ini vurgula."""
        self._aktif_wp_seq = seq
        # WP tablosunda satırı yeşil vurgula
        self._wp_tablo.blockSignals(True)
        for r in range(self._wp_tablo.rowCount()):
            aktif = (r == seq - 1)
            renk = QColor(148, 188, 227, 24) if aktif else QColor(KOKPIT_ZEMIN)
            for c in range(self._wp_tablo.columnCount()):
                itm = self._wp_tablo.item(r, c)
                if itm:
                    itm.setBackground(renk)
        self._wp_tablo.blockSignals(False)
        # Haritada marker vurgula
        self._js(f"wpAktifVurgula({seq - 1});")

    _MAV_RESULT_TR = {
        0: "✓ OK", 1: "⚠ Desteklenmiyor", 2: "✗ Reddedildi",
        3: "✗ Başarısız",  4: "⏳ Devam ediyor", 5: "✗ İptal edildi",
    }

    def _komut_onaylandi(self, komut_id: int, sonuc: int):
        """COMMAND_ACK: komutun sonucunu logla (OK ise sessiz)."""
        if sonuc == 0:
            return   # başarılı — loga spam yapma
        aciklama = self._MAV_RESULT_TR.get(sonuc, f"sonuc={sonuc}")
        self._mesaj_ekle(2, f"Komut {komut_id}: {aciklama}")

    def _rc_guncellendi(self, rssi: int, failsafe: bool):
        """RC_CHANNELS: sinyal gücü ve failsafe durumu."""
        if failsafe and not self._rc_failsafe_aktif:
            self._rc_failsafe_aktif = True
            # _mesaj_ekle(severity<=1) artık otomatik sesli uyarı veriyor
            self._mesaj_ekle(1, "⚠ RC SİNYAL KAYBI — failsafe aktif!")
        elif not failsafe and self._rc_failsafe_aktif:
            self._rc_failsafe_aktif = False
            self._mesaj_ekle(4, "RC sinyali geri geldi.")
        # Badge güncelle
        if rssi == 255 or rssi == 0:
            self._rc_lbl.setText(self._rozet_html("RC", "—", "#7e9cb8"))
            self._rc_lbl.setStyleSheet(
                f"background:transparent; border:1px solid {KOKPIT_KENAR}; padding:1px 12px;"
            )
        else:
            guc = int(rssi / 254 * 100)
            if guc > 60:
                renk, kenar, zemin = "#a8cf94", "rgba(143,191,122,0.45)", "rgba(143,191,122,0.12)"
            elif guc > 25:
                renk, kenar, zemin = "#e0c07a", "rgba(224,192,122,0.45)", "rgba(224,192,122,0.12)"
            else:
                renk, kenar, zemin = "#c98b85", "rgba(194,91,82,0.5)", "rgba(194,91,82,0.12)"
            self._rc_lbl.setText(self._rozet_html("RC", f"%{guc}", renk))
            self._rc_lbl.setStyleSheet(
                f"background:{zemin}; border:1px solid {kenar}; padding:1px 12px;"
            )

    _FENCE_TUR_TR = {
        1: "Yükseklik ihlali",
        2: "Çevre (daire) ihlali",
        3: "Poligon ihlali",
        4: "Çoklu ihlal",
    }

    def _fence_ihlal_handler(self, durum: int):
        """FENCE_STATUS: geofence ihlali bildirimi."""
        if durum == 0:
            if self._fence_ihlal_son != 0:
                self._fence_ihlal_son = 0
                self._mesaj_ekle(5, "Geofence: sınır içi — ihlal sona erdi.")
            return
        if durum == self._fence_ihlal_son:
            return   # aynı ihlali tekrar loglama
        self._fence_ihlal_son = durum
        tur = self._FENCE_TUR_TR.get(durum, f"bilinmeyen durum={durum}")
        # _mesaj_ekle(severity<=1) artık otomatik sesli uyarı veriyor
        self._mesaj_ekle(1, f"🚧 GEOFENCE İHLALİ: {tur}!")
        self._js(f"durumGoster('🚧 GEOFENCE İHLALİ: {tur}!');")

    def _ev_noktasi_guncelle(self, lat: float, lon: float, alt: float):
        """HOME_POSITION: drone'un resmi ev noktasını UI'a yansıt."""
        self._ev_lat = lat
        self._ev_lon = lon
        # WP özet satırındaki Ev etiketi
        if hasattr(self, '_wp_home_lbl'):
            self._wp_home_lbl.setText(f"Ev: {lat:.5f}, {lon:.5f}")
        # Harita marker (evNoktasiGuncelle JS fonksiyonu zaten mevcut)
        self._js(f"evNoktasiGuncelle({lat}, {lon});")
        self._mesaj_ekle(6, f"Ev noktası güncellendi (HOME_POSITION): {lat:.5f}, {lon:.5f}")

    def _batarya_hucre_guncelle(self, min_volt: float, hucre_sayisi: int):
        """BATTERY_STATUS: hücre başına minimum voltaj — kritik hücre uyarısı."""
        self._min_hucre_volt = min_volt
        kritik = float(_cfg.al("batarya.hucre_kritik_volt", 3.3))
        if hasattr(self, "_prearm_hucre") and min_volt > 0:
            self._prearm_renk(self._prearm_hucre, f"{min_volt:.3f}V ({hucre_sayisi}S)", min_volt >= kritik)
        if min_volt < kritik and min_volt > 0:
            self._mesaj_ekle(1,
                f"⚠ KRİTİK HÜCRE: {min_volt:.3f}V "
                f"({hucre_sayisi}S — eşik: {kritik:.2f}V)")

    def _servo_doyum_guncelle(self, servo_bilgi: list):
        """SERVO_OUTPUT_RAW: ≥1950µs doyum tespiti → uyarı (30 sn debounce)."""
        simdi = time.monotonic()
        for s in servo_bilgi:
            if not s["doyum"]:
                continue
            k = s["kanal"]
            son = getattr(self, f"_servo_doyum_son_{k}", 0.0)
            if simdi - son >= 30.0:
                setattr(self, f"_servo_doyum_son_{k}", simdi)
                self._mesaj_ekle(3,
                    f"⚠ Motor/Servo {k} doyum: {s['pwm']}µs — "
                    "bu eksen tam güçte, manevra kapasitesi kalmayabilir!")

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
            min_hucre_volt=getattr(self, "_min_hucre_volt", 0.0),
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

        if sonuc.voltaj_sapma_faktoru < 1.0:
            self._mesaj_ekle(3,
                f"⚠ Hücre voltajı bildirilen bataryaya göre düşük "
                f"(min {self._min_hucre_volt:.2f}V) — uçuş yarıçapı ek güvenlik "
                f"payıyla %{(1.0 - sonuc.voltaj_sapma_faktoru) * 100:.0f} kısıtlandı.")

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
        self._mesaj_ekle(6, f"Hedef: {lat:.5f}, {lon:.5f} — LIDAR tarama başlıyor (~22 sn)…")
        self._js("durumGoster('🔍 Hedefe gidiliyor — iniş öncesi LIDAR zemin taraması…');")
        self._js(f"lidarTaramaTemizle(); inisHedefGoster({lat}, {lon});")
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
        self._js("inisHedefTemizle();")

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
        self._js(f"lidarTaramaGoster({lat}, {lon}, 'Merkez', {h:.2f});")
        # Kuzey +1 m: 1° lat ≈ 111 000 m → 1 m ≈ 0.000009°
        self._inis_hedef_git(lat + 9e-6, lon, irt)
        self._mesaj_ekle(6, f"LIDAR merkez: {h:.2f} m — kuzey ölçümüne gidiliyor…")
        QTimer.singleShot(3000, self._dogrulama_kuzey_olcum)

    def _dogrulama_kuzey_olcum(self):
        """Adım 2: Kuzey noktasında LIDAR ölçümü al, Güneye yönel."""
        h = self._guncel_lidar_m
        lat, lon = self._inis_hedef
        irt = max(getattr(self, "_guncel_irtifa", 5.0), 5.0)
        if h is not None:
            self._inis_lidar["kuzey"] = h
            self._js(f"lidarTaramaGoster({lat + 9e-6}, {lon}, 'Kuzey', {h:.2f});")
        self._inis_hedef_git(lat - 9e-6, lon, irt)
        _h_str = f"{h:.2f}" if h is not None else "?"
        self._mesaj_ekle(6, f"LIDAR kuzey: {_h_str} m — güney ölçümüne gidiliyor…")
        QTimer.singleShot(3000, self._dogrulama_guney_olcum)

    def _dogrulama_guney_olcum(self):
        """Adım 3: Güney noktasında LIDAR ölçümü al, Doğuya yönel."""
        h = self._guncel_lidar_m
        lat, lon = self._inis_hedef
        irt = max(getattr(self, "_guncel_irtifa", 5.0), 5.0)
        if h is not None:
            self._inis_lidar["guney"] = h
            self._js(f"lidarTaramaGoster({lat - 9e-6}, {lon}, 'Güney', {h:.2f});")
        # Doğu +1 m: 1° lon ≈ 111 000 × cos(lat) m
        lon_offset = 9e-6 / math.cos(math.radians(lat))
        self._inis_hedef_git(lat, lon + lon_offset, irt)
        _h_str = f"{h:.2f}" if h is not None else "?"
        self._mesaj_ekle(6, f"LIDAR güney: {_h_str} m — doğu ölçümüne gidiliyor…")
        QTimer.singleShot(3000, self._dogrulama_dogu_olcum)

    def _dogrulama_dogu_olcum(self):
        """Adım 4: Doğu noktasında LIDAR ölçümü al, Batıya yönel."""
        h = self._guncel_lidar_m
        lat, lon = self._inis_hedef
        irt = max(getattr(self, "_guncel_irtifa", 5.0), 5.0)
        lon_offset = 9e-6 / math.cos(math.radians(lat))
        if h is not None:
            self._inis_lidar["dogu"] = h
            self._js(f"lidarTaramaGoster({lat}, {lon + lon_offset}, 'Doğu', {h:.2f});")
        self._inis_hedef_git(lat, lon - lon_offset, irt)
        _h_str = f"{h:.2f}" if h is not None else "?"
        self._mesaj_ekle(6, f"LIDAR doğu: {_h_str} m — batı ölçümüne gidiliyor…")
        QTimer.singleShot(3000, self._dogrulama_bati_olcum)

    def _dogrulama_bati_olcum(self):
        """Adım 5: Batı noktasında LIDAR ölçümü al, hesapla."""
        h = self._guncel_lidar_m
        if h is not None:
            self._inis_lidar["bati"] = h
            lat, lon = self._inis_hedef
            lon_offset = 9e-6 / math.cos(math.radians(lat))
            self._js(f"lidarTaramaGoster({lat}, {lon - lon_offset}, 'Batı', {h:.2f});")
        self._dogrulama_hesapla()

    def _dogrulama_hesapla(self):
        """Adım 6: 5 ölçümden (haç deseni) gerçek zemin eğimini hesapla, karar ver."""
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

        # N-S ve E-W eğim bileşenleri: karşılıklı çift varsa merkezi fark
        # (asimetrik eğimi de doğru yakalar — örn. sadece güneye eğimli zemin),
        # sadece bir taraf ölçülebildiyse tek taraflı fark (eski davranış, fallback).
        if "kuzey" in ok and "guney" in ok:
            dz_ns = (ok["kuzey"] - ok["guney"]) / 2.0
        elif "kuzey" in ok:
            dz_ns = ok["kuzey"] - h0
        elif "guney" in ok:
            dz_ns = h0 - ok["guney"]
        else:
            dz_ns = 0.0

        if "dogu" in ok and "bati" in ok:
            dz_ew = (ok["dogu"] - ok["bati"]) / 2.0
        elif "dogu" in ok:
            dz_ew = ok["dogu"] - h0
        elif "bati" in ok:
            dz_ew = h0 - ok["bati"]
        else:
            dz_ew = 0.0

        egim_ns = math.degrees(math.atan(abs(dz_ns)))
        egim_ew = math.degrees(math.atan(abs(dz_ew)))
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
            self._js(f"inisHedefTemizle(); inisNoktasiReddet({lat}, {lon}, {gercek_egim:.1f});")
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

        self._rally_thread = _RallyYuklemeThread(
            npz, dize, self._guncel_lat, self._guncel_lon,
            conn=getattr(self._mavlink, "_baglanti", None),
        )
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
                # Sesli uyarı — aynı ICAO için 60sn debounce (ayrı sayaç)
                _tts_son = self._adsb_tts_son.get(icao, 0.0)
                if simdi - _tts_son >= 60.0:
                    self._adsb_tts_son[icao] = simdi
                    _cs_sesli = callsign.strip() if callsign.strip() else "bilinmeyen araç"
                    self._sesli_uyan(f"Yakın hava aracı uyarısı: {_cs_sesli}")

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

    def _fence_dosyadan_yukle(self):
        """
        SHP/KML dosyasından geofence polygon'u içe aktarır. Haritada elle
        çizmenin (fenceBitir -> gcs://fence-cizildi) ALTERNATİFİ — aynı
        _fence_noktalar değişkenini doldurur, JS tarafında zaten var olan
        `fenceListeGoster` fonksiyonunu (drone'dan okunan fence'i haritada
        göstermek için yazılmıştı) yeniden kullanır — yeni bir JS fonksiyonu
        yazmaya gerek yok.
        """
        yol, _ = QFileDialog.getOpenFileName(
            self, "Fence Dosyası Seç", "", "Fence Dosyaları (*.shp *.kml)"
        )
        if not yol:
            return
        try:
            from geo_import import dosyadan_oku
            noktalar = dosyadan_oku(yol)
        except Exception as e:
            self._mesaj_ekle(3, f"Fence içe aktarma hatası: {e}")
            return

        self._fence_noktalar = noktalar
        import json as _json
        json_str = _json.dumps(_json.dumps(noktalar))  # JS string literal olarak güvenli kaçış
        self._js(f"fenceListeGoster({json_str});")
        self._mesaj_ekle(
            6,
            f"📥 Fence içe aktarıldı: {len(noktalar)} köşe "
            f"({os.path.basename(yol)}) — 'Fence Yükle' ile drone'a gönderin."
        )

    def _fence_polygon_yukle(self):
        """
        Haritada çizilen fence polygon (_fence_noktalar) → MAVLink FENCE_POINT
        protokolüyle ArduPilot'a yükle.
        """
        if not self._bagli:
            QMessageBox.warning(self, "Bağlantı Yok", "Önce drone'a bağlanın.")
            return
        if len(self._fence_noktalar) < 3:
            QMessageBox.warning(self, "Yetersiz Nokta",
                "En az 3 köşe noktası gerekli.\n'Fence Çiz' ile haritada polygon çizin.")
            return
        alt_max  = float(_cfg.al("fence.alt_max", 120.0))
        eylem    = int(_cfg.al("fence.action", 1))
        # FENCE_ENABLE=1, FENCE_ACTION=eylem, FENCE_TYPE=2 (polygon)
        self._mavlink.parametre_ayarla("FENCE_ENABLE", 1)
        self._mavlink.parametre_ayarla("FENCE_ACTION", eylem)
        self._mavlink.parametre_ayarla("FENCE_TYPE",   2)
        self._mavlink.parametre_ayarla("FENCE_MAXALT", alt_max)
        # FENCE_TOTAL = nokta sayısı + 1 (kapanış noktası)
        n = len(self._fence_noktalar)
        self._mavlink.parametre_ayarla("FENCE_TOTAL", float(n + 1))
        # Her noktayı FENCE_POINT mesajıyla gönder
        import threading
        def _gonder():
            try:
                mav = self._mavlink._baglanti.mav
                ts  = self._mavlink._baglanti.target_system
                tc  = self._mavlink._baglanti.target_component
                for idx, (lat, lon) in enumerate(self._fence_noktalar):
                    mav.fence_point_send(ts, tc, idx, n + 1, float(lat), float(lon))
                    import time as _t; _t.sleep(0.05)
                # Kapanış noktası = ilk nokta
                mav.fence_point_send(ts, tc, n, n + 1,
                                     float(self._fence_noktalar[0][0]),
                                     float(self._fence_noktalar[0][1]))
                self._mesaj_ekle(4,
                    f"✓ Fence polygon yüklendi: {n} köşe, alt_max={alt_max}m, eylem={eylem}")
                self._js("document.getElementById('fenceEditBtn').style.background='#1a4a1a';"
                         "document.getElementById('fenceEditBtn').style.borderColor='#3a9a3a';")
            except Exception as _e:
                self._mesaj_ekle(3, f"Fence polygon yükleme hatası: {_e}")
        threading.Thread(target=_gonder, daemon=True).start()

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
            npz, dize, alt_max=alt_max, fence_action=fence_action,
            conn=getattr(self._mavlink, "_baglanti", None),
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
                    # AlanInisKarar kurulumu ağır (~2sn) — başka bir okuma zaten
                    # sürüyorsa veya zaten yüklüyse tekrar tetiklemeyelim.
                    if self._alan_karar is None and not self._alan_karar_yukleniyor:
                        self._alan_karar_yukleniyor = True
                        self._alan_hazirlik_yapildi = True
                        import threading as _threading_fence
                        _threading_fence.Thread(
                            target=self._alan_karar_arka_planda_yukle, args=(_npz,), daemon=True
                        ).start()
                except Exception:
                    pass
            self._js("document.getElementById('fenceBtn').style.background='#1a4a1a';"
                     "document.getElementById('fenceBtn').style.borderColor='#3a9a3a';")
        else:
            self._mesaj_ekle(3, "✗ AC_Fence yüklenemedi — log'u kontrol edin.")

    def _grid_ayar_ve_uret(self, lat_min, lat_max, lon_min, lon_max):
        """Grid ayarları dialogu göster → onaylanınca _grid_uret() çağır."""
        from PyQt5.QtWidgets import (QDialog, QFormLayout, QDoubleSpinBox,
                                     QSpinBox, QComboBox, QDialogButtonBox, QLabel)
        dlg = QDialog(self)
        dlg.setWindowTitle("📐 Grid Survey Ayarları")
        dlg.setMinimumWidth(300)
        form = QFormLayout(dlg)

        aralik_sb = QDoubleSpinBox()
        aralik_sb.setRange(10, 500)
        aralik_sb.setValue(60.0)
        aralik_sb.setSuffix(" m")
        aralik_sb.setToolTip("Paralel çizgiler arası mesafe")
        form.addRow("Çizgi Aralığı:", aralik_sb)

        irtifa_sb = QDoubleSpinBox()
        irtifa_sb.setRange(10, 500)
        irtifa_sb.setValue(50.0)
        irtifa_sb.setSuffix(" m AGL")
        irtifa_sb.setToolTip("Waypoint irtifası (zemin üstü)")
        form.addRow("Uçuş İrtifası:", irtifa_sb)

        yon_combo = QComboBox()
        yon_combo.addItems(["Yatay (E→W şeritler)", "Dikey (N→S şeritler)"])
        form.addRow("Tarama Yönü:", yon_combo)

        import math as _m
        lat_ort = (lat_min + lat_max) / 2.0
        alan_m2 = (abs(lat_max - lat_min) * 111000) * (abs(lon_max - lon_min) * 111000 * _m.cos(_m.radians(lat_ort)))
        form.addRow("", QLabel(f"<small>Alan: ~{alan_m2/1e6:.2f} km²</small>"))

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)

        if dlg.exec_() != QDialog.Accepted:
            return
        self._grid_uret(lat_min, lat_max, lon_min, lon_max,
                        aralik_m=aralik_sb.value(),
                        irtifa=irtifa_sb.value(),
                        dikey=(yon_combo.currentIndex() == 1))

    def _grid_uret(self, lat_min: float, lat_max: float,
                   lon_min: float, lon_max: float,
                   aralik_m: float = 60.0, irtifa: float = 50.0,
                   dikey: bool = False):
        """
        Bounding box içinde paralel çizgi survey görevi üretir.
        aralik_m: çizgiler arası mesafe (m)
        irtifa:   WP irtifası (m, AGL)
        Oluşturulan WP'ler self._wp_listesi'ne eklenir + haritaya gönderilir.
        """
        import math as _math

        # Metre/derece dönüşümü (yaklaşık)
        lat_ort = (lat_min + lat_max) / 2.0
        m_per_lat = 111_000.0
        m_per_lon = 111_000.0 * _math.cos(_math.radians(lat_ort))

        # Önce mevcut WP listesini temizle
        self._wp_listesi = []
        sayac = 0

        def _wp(lat_, lon_):
            return {"lat": lat_, "lon": lon_, "alt": irtifa,
                    "komut": "NAV_WAYPOINT", "p1": 0, "p2": 0, "p3": 0}

        if not dikey:
            # Yatay şeritler: K→G ilerleme, ping-pong B↔D
            lat_aralik = aralik_m / m_per_lat
            lat = lat_max
            sol_dan = True
            while lat >= lat_min:
                if sol_dan:
                    self._wp_listesi += [_wp(lat, lon_min), _wp(lat, lon_max)]
                else:
                    self._wp_listesi += [_wp(lat, lon_max), _wp(lat, lon_min)]
                sol_dan = not sol_dan
                lat -= lat_aralik
                sayac += 1
                if sayac > 200: break
        else:
            # Dikey şeritler: B→D ilerleme, ping-pong K↔G
            lon_aralik = aralik_m / m_per_lon
            lon = lon_min
            kuzeyden = True
            while lon <= lon_max:
                if kuzeyden:
                    self._wp_listesi += [_wp(lat_max, lon), _wp(lat_min, lon)]
                else:
                    self._wp_listesi += [_wp(lat_min, lon), _wp(lat_max, lon)]
                kuzeyden = not kuzeyden
                lon += lon_aralik
                sayac += 1
                if sayac > 200: break

        self._wp_tablo_yenile()

        # Haritaya gönder
        import json as _json
        self._js(f"wpListeYukle({_json.dumps(self._wp_listesi)});")
        self._mesaj_ekle(4,
            f"📐 Grid görevi: {len(self._wp_listesi)} WP, "
            f"{sayac} şerit, {aralik_m:.0f}m aralık, {irtifa:.0f}m irtifa — "
            "Görevi Yükle ile drone'a gönderin.")

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
        # 1B düzeninde harita, Uçuş ekranının sağ paneli — pencere gösterildikten
        # 1500ms sonra (Chromium'un geçerli HWND'ye ihtiyacı olduğu için) yüklenir.
        if HARITA_MEVCUT and not self._harita_tab_hazir:
            QTimer.singleShot(1500, self._harita_tab_yukle)

    def resizeEvent(self, event):
        """
        Pencere yeniden boyutlanınca (maximize, sürükle-büyüt vb.) haritanın
        iç #map div'i eski (küçük) boyutta kalmasın diye yeniden senkronlanır.
        Eskiden bu sadece harita ilk yüklenirken 300/800ms'de bir kez
        yapılıyordu — pencere sonradan büyürse harita küçük kalıyordu.
        """
        super().resizeEvent(event)
        if HARITA_MEVCUT and getattr(self, "_harita_hazir", False):
            self._harita_boyut_duzelt()

    def closeEvent(self, event):
        # Timer'ları durdur
        self._hb_timer.stop()
        self._log_timer.stop()
        self._js_timer.stop()
        self._sure_timer.stop()
        self._js_kuyruk.clear()
        # Arka plan thread'lerini nazikçe durdur (artık sert .terminate() değil)
        self._baglanti_temizligi_yap()
        self._mavlink.durdur()
        if hasattr(self, '_tile_sunucu'):
            self._tile_sunucu.durdur()
        super().closeEvent(event)


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
