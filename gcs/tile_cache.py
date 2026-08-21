"""
Tile Cache Proxy Sunucusu
Leaflet tile isteklerini diskten serve eder; yoksa indirir ve kaydeder.
Cache konum: ~/.dogus-gcs/tilecache/
"""

import os
import threading
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from PyQt5.QtCore import QThread

CACHE_DIR = os.path.expanduser("~/.dogus-gcs/tilecache")

# Tile sağlayıcıları — aynı HARITA_HTML'deki isimlerle eşleşmeli
SAGLAYICILAR = {
    "uydu":  {
        "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "uzanti": "jpg",
        "basliklar": {"Referer": "https://www.arcgis.com/"},
    },
    "hibrit": {
        "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "uzanti": "jpg",
        "basliklar": {"Referer": "https://www.arcgis.com/"},
    },
    "sokak": {
        "url": "https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
        "uzanti": "png",
        "basliklar": {},
    },
    "topo": {
        "url": "https://a.tile.opentopomap.org/{z}/{x}/{y}.png",
        "uzanti": "png",
        "basliklar": {},
    },
    "gece": {
        "url": "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
        "uzanti": "png",
        "basliklar": {},
    },
}

ICERIK_TIPLERI = {"jpg": "image/jpeg", "png": "image/png"}

_BOSTA_TILE = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
    b'\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00'
    b'\x00\x0cIDATx\x9cc\x10\x10\x10\x00\x00\x00\x04\x00\x01'
    b'\xf3\xc4b\x14\x00\x00\x00\x00IEND\xaeB`\x82'
)


class _TileHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # HTTP request logları bastırıldı

    _STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
    _harita_html_fn = None  # gcs_main tarafından set edilir

    def do_GET(self):
        path = self.path.split("?")[0].strip("/")

        # Ana harita HTML — /harita.html
        if path == "harita.html":
            # Dinamik olarak oluşturulmuş HTML'i döndür
            if _TileHandler._harita_html_fn is not None:
                html_bytes = _TileHandler._harita_html_fn().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html_bytes)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(html_bytes)
            else:
                self._404()
            return

        # Statik dosyalar: /leaflet.js, /leaflet.css
        if path in ("leaflet.js", "leaflet.css"):
            dosya = os.path.join(self._STATIC_DIR, path)
            if os.path.isfile(dosya):
                tip = "application/javascript" if path.endswith(".js") else "text/css"
                with open(dosya, "rb") as f:
                    veri = f.read()
                self.send_response(200)
                self.send_header("Content-Type", tip)
                self.send_header("Content-Length", str(len(veri)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(veri)
                return
            self._404()
            return

        # URL: /saglayici/z/x/y
        parcalar = path.split("/")
        if len(parcalar) != 4:
            self._404()
            return

        saglayici, z, x, y = parcalar
        cfg = SAGLAYICILAR.get(saglayici)
        if not cfg:
            self._404()
            return

        uzanti = cfg["uzanti"]
        cache_dosya = os.path.join(CACHE_DIR, saglayici, z, x, f"{y}.{uzanti}")

        # Diskten serve et
        if os.path.isfile(cache_dosya):
            with open(cache_dosya, "rb") as f:
                veri = f.read()
            self._tamam(veri, uzanti)
            return

        # İndir ve kaydet
        gercek_url = cfg["url"].format(z=z, x=x, y=y)
        try:
            r = requests.get(gercek_url, headers=cfg["basliklar"], timeout=8)
            if r.status_code == 200:
                os.makedirs(os.path.dirname(cache_dosya), exist_ok=True)
                with open(cache_dosya, "wb") as f:
                    f.write(r.content)
                self._tamam(r.content, uzanti)
            else:
                self._bosta()
        except Exception:
            self._bosta()

    def _tamam(self, veri: bytes, uzanti: str):
        self.send_response(200)
        self.send_header("Content-Type", ICERIK_TIPLERI.get(uzanti, "image/png"))
        self.send_header("Content-Length", str(len(veri)))
        self.send_header("Cache-Control", "max-age=86400")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(veri)

    def _bosta(self):
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(_BOSTA_TILE)))
        self.end_headers()
        self.wfile.write(_BOSTA_TILE)

    def _404(self):
        self.send_response(404)
        self.end_headers()


class TileCacheSunucusu(QThread):
    PORT = 17180

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sunucu = None

    def run(self):
        os.makedirs(CACHE_DIR, exist_ok=True)
        self._sunucu = HTTPServer(("127.0.0.1", self.PORT), _TileHandler)
        self._sunucu.serve_forever()

    def durdur(self):
        if self._sunucu:
            threading.Thread(target=self._sunucu.shutdown, daemon=True).start()

    @classmethod
    def tile_url(cls, saglayici: str) -> str:
        """Leaflet tile URL şablonu — proxy üzerinden."""
        return f"http://127.0.0.1:{cls.PORT}/{saglayici}/{{z}}/{{x}}/{{y}}"

    @classmethod
    def cache_boyutu_mb(cls) -> float:
        """Cache klasörünün toplam boyutu (MB)."""
        toplam = 0
        for kok, _, dosyalar in os.walk(CACHE_DIR):
            for d in dosyalar:
                try:
                    toplam += os.path.getsize(os.path.join(kok, d))
                except OSError:
                    pass
        return toplam / (1024 * 1024)
