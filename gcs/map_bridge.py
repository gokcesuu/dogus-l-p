import json
import urllib.parse as _up

try:
    from PyQt5.QtCore import QUrlQuery
    from PyQt5.QtWebEngineWidgets import QWebEnginePage
    HARITA_MEVCUT = True
except ImportError:
    HARITA_MEVCUT = False
    QUrlQuery = None
    QWebEnginePage = object


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
                    from PyQt5.QtCore import QTimer
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
                            self._gcs._alan_karar = None
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
                    try:
                        raw = QUrlQuery(url).queryItemValue('data')
                        self._gcs._wp_listesi = json.loads(_up.unquote(raw))
                        from PyQt5.QtCore import QTimer
                        QTimer.singleShot(0, self._gcs._wp_tablo_yenile)
                    except Exception:
                        pass
                elif eylem == 'wp-yukle':
                    _defer(self._gcs._wp_yukle_baslat)
                elif eylem == 'wp-oku':
                    _defer(self._gcs._wp_oku_baslat)
                elif eylem == 'wp-temizle':
                    self._gcs._wp_listesi = []
                    from PyQt5.QtCore import QTimer
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
                elif eylem == 'fence-polygon-yukle':
                    _defer(self._gcs._fence_polygon_yukle)
                elif eylem == 'fence-cizildi':
                    try:
                        raw = QUrlQuery(url).queryItemValue('data')
                        noktalar = json.loads(_up.unquote(raw))
                        self._gcs._fence_noktalar = noktalar
                        self._gcs._mesaj_ekle(6,
                            f"🔷 Fence polygon hazır: {len(noktalar)} köşe — "
                            "'Fence Yükle' ile drone'a gönderin.")
                    except Exception as _fe:
                        self._gcs._mesaj_ekle(3, f"Fence çizimi: veri okunamadı ({_fe}).")
                elif eylem == 'guided-git':
                    def _guided_git():
                        try:
                            q = QUrlQuery(url)
                            lat = float(q.queryItemValue('lat'))
                            lon = float(q.queryItemValue('lon'))
                            alt = float(self._gcs._guncel_irtifa or 30.0)
                            self._gcs._mavlink.guided_git(lat, lon, max(alt, 10.0))
                            self._gcs._mesaj_ekle(6, f"GUIDED → {lat:.5f}, {lon:.5f} @ {max(alt,10):.0f}m")
                        except Exception as _ge:
                            self._gcs._mesaj_ekle(3, f"Guided git hatası: {_ge}")
                    _defer(_guided_git)
                elif eylem == 'wp-ekle-koordinat':
                    def _wp_ekle_koordinat():
                        try:
                            q = QUrlQuery(url)
                            lat = float(q.queryItemValue('lat'))
                            lon = float(q.queryItemValue('lon'))
                            alt = 50.0
                            self._gcs._wp_listesi.append({'lat': lat, 'lon': lon, 'alt': alt, 'komut': 'NAV_WAYPOINT'})
                            self._gcs._wp_tablo_yenile()
                            js = f"wpEkle({lat}, {lon}, {alt});"
                            self._gcs._js(js)
                        except Exception as _we:
                            self._gcs._mesaj_ekle(3, f"WP ekle hatası: {_we}")
                    _defer(_wp_ekle_koordinat)
                elif eylem == 'grid-uret':
                    def _grid_uret():
                        try:
                            q = QUrlQuery(url)
                            lat1 = float(q.queryItemValue('lat1'))
                            lon1 = float(q.queryItemValue('lon1'))
                            lat2 = float(q.queryItemValue('lat2'))
                            lon2 = float(q.queryItemValue('lon2'))
                            self._gcs._grid_ayar_ve_uret(
                                min(lat1, lat2), max(lat1, lat2),
                                min(lon1, lon2), max(lon1, lon2)
                            )
                        except Exception as _ge:
                            self._gcs._mesaj_ekle(3, f"Grid hatası: {_ge}")
                    _defer(_grid_uret)
                return False
            return super().acceptNavigationRequest(url, nav_type, is_main_frame)


    class MiniHaritaSayfa(QWebEnginePage):
        """Mini-harita için minimal sayfa — hiçbir gcs:// URL'sini işlemez."""
        def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
            if 'Failed to load' not in message and 'net::ERR' not in message:
                pass

        def acceptNavigationRequest(self, url, nav_type, is_main_frame):
            if url.scheme() == 'gcs':
                return False
            return super().acceptNavigationRequest(url, nav_type, is_main_frame)
else:
    class HaritaSayfa(object):
        def __init__(self, *args, **kwargs):
            pass

        def javaScriptConsoleMessage(self, *args, **kwargs):
            pass

        def acceptNavigationRequest(self, *args, **kwargs):
            return False

    class MiniHaritaSayfa(HaritaSayfa):
        pass

__all__ = ["HaritaSayfa", "MiniHaritaSayfa", "HARITA_MEVCUT"]
