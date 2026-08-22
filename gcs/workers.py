import os

from PyQt5.QtCore import QThread, pyqtSignal as Signal


class _RallyYuklemeThread(QThread):
    """En iyi N rally noktasını arka planda ArduPilot'a yükler."""
    tamamlandi = Signal(bool, int)   # (basarili, nokta_sayisi)
    hata       = Signal(str)

    def __init__(self, npz_dosya: str, baglanti_dizesi: str,
                 merkez_lat: float = 0.0, merkez_lon: float = 0.0, n: int = 5,
                 conn=None):
        super().__init__()
        self.npz     = npz_dosya
        self.dize    = baglanti_dizesi
        self.m_lat   = merkez_lat
        self.m_lon   = merkez_lon
        self.n       = n
        self.conn    = conn   # varsa GCS'nin zaten açık MAVLink bağlantısı
        self._durdur_istendi = False

    def durdur(self):
        """Nazikçe durdurma iste. Devam eden tek bloklamalı çağrı (ağ/IO)
        anında kesilmez, ama tamamlanınca sonuç sinyali emit edilmez —
        bağlantı koptuktan sonra UI'a geç kalmış bir güncelleme gitmez."""
        self._durdur_istendi = True
        self.wait(2000)

    def run(self):
        try:
            from rally_yukle import en_iyi_noktalar, rally_yukle
            noktalar = en_iyi_noktalar(
                self.npz, n=self.n,
                merkez_lat=self.m_lat if self.m_lat != 0.0 else None,
                merkez_lon=self.m_lon if self.m_lon != 0.0 else None,
            )
            basarili = rally_yukle(noktalar, baglanti_dizesi=self.dize, conn=self.conn)
            if self._durdur_istendi:
                return
            self.tamamlandi.emit(basarili, len(noktalar))
        except Exception as e:
            if not self._durdur_istendi:
                self.hata.emit(str(e))


class _FenceYuklemeThread(QThread):
    """alan_verisi.npz bounds'ından AC_Fence polygon arka planda yükler."""
    tamamlandi = Signal(bool)   # basarili
    hata       = Signal(str)

    def __init__(self, npz_dosya: str, baglanti_dizesi: str,
                 alt_max: float = 120.0, fence_action: int = 1, conn=None):
        super().__init__()
        self.npz          = npz_dosya
        self.dize         = baglanti_dizesi
        self.alt_max      = alt_max
        self.fence_action = fence_action
        self.conn         = conn   # varsa GCS'nin zaten açık MAVLink bağlantısı
        self._durdur_istendi = False

    def durdur(self):
        self._durdur_istendi = True
        self.wait(2000)

    def run(self):
        try:
            from fence_yukle import fence_yukle_npz
            basarili = fence_yukle_npz(
                self.npz, self.dize,
                alt_max=self.alt_max,
                fence_action=self.fence_action,
                conn=self.conn,
            )
            if self._durdur_istendi:
                return
            self.tamamlandi.emit(basarili)
        except Exception as e:
            if not self._durdur_istendi:
                self.hata.emit(str(e))


class TerrainAnalizThread(QThread):
    tamamlandi = Signal(object)   # AnalizSonucu
    hata       = Signal(str)

    def __init__(self, lat, lon, batarya_yuzde,
                 ruzgar_ms: float = 0.0, ruzgar_yonu_derece: float = 0.0,
                 min_hucre_volt: float = 0.0):
        super().__init__()
        self.lat = lat
        self.lon = lon
        self.batarya_yuzde = batarya_yuzde
        self.ruzgar_ms = ruzgar_ms
        self.ruzgar_yonu_derece = ruzgar_yonu_derece
        self.min_hucre_volt = min_hucre_volt
        self._durdur_istendi = False

    def durdur(self):
        self._durdur_istendi = True
        self.wait(2000)

    def run(self):
        try:
            from terrain_analiz import GuvenliInisAnalizci   # srtm yükü burada — bg thread
            analizci = GuvenliInisAnalizci()
            sonuc = analizci.analiz_et(
                self.lat, self.lon, self.batarya_yuzde,
                ruzgar_ms=self.ruzgar_ms,
                ruzgar_yonu_derece=self.ruzgar_yonu_derece,
                min_hucre_volt=self.min_hucre_volt,
            )
            if self._durdur_istendi:
                return
            self.tamamlandi.emit(sonuc)
        except Exception as e:
            if not self._durdur_istendi:
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
        self._durdur_istendi = False

    def durdur(self):
        self._durdur_istendi = True
        self.wait(2000)

    def run(self):
        try:
            import srtm as _srtm
            veri = _srtm.get_data()
            t_mes: list = []
            t_alt: list = []
            n = len(self._wp)
            for i in range(n):
                if self._durdur_istendi:
                    return
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
            if self._durdur_istendi:
                return
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
        self._durdur_istendi = False

    def durdur(self):
        self._durdur_istendi = True
        self.wait(2000)

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
            if self._durdur_istendi:
                return

            self.ilerleme.emit("Terrain: DEM okunuyor…")
            dem, transform, bounds = dem_oku(tif_yolu)
            if self._durdur_istendi:
                return

            self.ilerleme.emit("Terrain: Eğim hesaplanıyor…")
            egim = egim_hesapla(dem)
            if self._durdur_istendi:
                return

            self.ilerleme.emit("Terrain: Güvenli noktalar belirleniyor…")
            noktalar = guvenli_noktalari_bul(egim, transform)
            if self._durdur_istendi:
                return

            # kaydet() doğru NPZ formatını (noktalar_json 1-elemanlı dizi) üretir
            cikti = os.path.join(os.path.dirname(__file__), "alan_verisi.npz")
            kaydet(egim, dem, transform, bounds, noktalar, cikti=cikti)

            # Geçici TIF temizle
            try:
                os.remove(tif_yolu)
            except OSError:
                pass
            if self._durdur_istendi:
                return
            self.tamamlandi.emit(cikti)
        except Exception as exc:
            if not self._durdur_istendi:
                self.hata.emit(f"Terrain hazırlık hatası: {exc}")
