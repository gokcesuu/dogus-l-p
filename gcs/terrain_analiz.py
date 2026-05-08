"""
terrain_analiz.py  —  v2
Doğuş Üniversitesi LÖP – Çok Katmanlı Güvenli İniş Analizi

Katmanlar:
  1. SRTM 30m eğim  — Horn yöntemi (3×3 ızgara)
  2. İniş ayak izi  — merkez + 4 kardinal noktada max eğim
  3. OSM engel maskesi — bina / orman / su (overpy + Overpass API)
  4. Rüzgar yönü skoru — leeward taraf tercih edilir
  5. Bileşik skor ile sıralama

Windows uyumlu — srtm.py kullanır (make gerektirmez).
OSM katmanı overpy gerektirrir; kurulu değilse sessizce atlanır.
"""

import math
from dataclasses import dataclass, field
from typing import Optional

import srtm

try:
    import overpy as _overpy
    OVERPY_MEVCUT = True
except ImportError:
    OVERPY_MEVCUT = False

try:
    import config_yukleyici as _cfg
    ANALIZ_ADIM_M      = float(_cfg.al("terrain.analiz_adim_m",       150))
    HORN_OFSET_M       = float(_cfg.al("terrain.horn_ofset_m",          30))
    RISKLI_EGIM_DERECE = float(_cfg.al("terrain.max_egim_derece",      15.0))
    AYAK_IZI_M         = float(_cfg.al("terrain.ayak_izi_yaricap_m",   30.0))
    RUZGAR_AGIRLIGI    = float(_cfg.al("terrain.ruzgar_skor_agirligi",  0.10))
    OSM_ZAMAN_ASIMI    = int(_cfg.al("terrain.osm_zaman_asimi",           10))
except Exception:
    ANALIZ_ADIM_M      = 150
    HORN_OFSET_M       = 30
    RISKLI_EGIM_DERECE = 15.0
    AYAK_IZI_M         = 30.0
    RUZGAR_AGIRLIGI    = 0.10
    OSM_ZAMAN_ASIMI    = 10

GUVENLI_EGIM_DERECE   = 5.0
WHM_PER_KM            = 10.0
BATARYA_KAPASİTESİ_WH = 44.4
M_PER_DEG_LAT         = 111320.0

# Bileşik skor ağırlıkları (toplam 1.0)
_W_EGIM   = 0.45
_W_ALAN   = 0.25
_W_OSM    = 0.15
_W_RUZGAR = 0.10
_W_MESAFE = 0.05


# ── Veri yapıları ─────────────────────────────────────────────────────────────

@dataclass
class InisNoktasi:
    lat: float
    lon: float
    yukseklik_m: float
    egim_derece: float
    mesafe_m: float
    guvenlik: str              # "GUVENLI" | "RISKLI" | "TEHLIKELI"
    alan_max_egim: float = 0.0 # Ayak izi içindeki max eğim
    osm_engel: bool = False    # OSM engel maskesi içinde
    ruzgar_skoru: float = 1.0  # 0=kötü, 1=ideal
    genel_skor: float = 0.0    # Bileşik skor (yüksek=iyi)

    def __str__(self):
        osm = " [OSM-ENGEL]" if self.osm_engel else ""
        return (
            f"{self.lat:.5f}, {self.lon:.5f} | "
            f"Yükseklik: {self.yukseklik_m:.0f}m | "
            f"Eğim: {self.egim_derece:.1f}° | AlanMax: {self.alan_max_egim:.1f}° | "
            f"Mesafe: {self.mesafe_m:.0f}m | Skor: {self.genel_skor:.2f} | "
            f"{self.guvenlik}{osm}"
        )


@dataclass
class AnalizSonucu:
    merkez_lat: float
    merkez_lon: float
    yaricap_m: float
    en_yakin_guvenli: Optional[InisNoktasi]
    guvenli_noktalar: list = field(default_factory=list)
    riskli_noktalar:  list = field(default_factory=list)
    hata: Optional[str] = None
    osm_aktif: bool = False
    ruzgar_skoru_aktif: bool = False

    @property
    def basarili(self) -> bool:
        return self.hata is None

    def ozet(self) -> str:
        if self.hata:
            return f"HATA: {self.hata}"
        katmanlar = []
        if self.osm_aktif:
            katmanlar.append("OSM")
        if self.ruzgar_skoru_aktif:
            katmanlar.append("Rüzgar")
        katman_str = f" [{'+'.join(katmanlar)}]" if katmanlar else ""
        if not self.en_yakin_guvenli:
            return (
                f"Yarıçap {self.yaricap_m:.0f}m içinde güvenli iniş noktası bulunamadı! "
                f"({len(self.riskli_noktalar)} riskli nokta var){katman_str}"
            )
        g = self.en_yakin_guvenli
        return (
            f"En yakın güvenli iniş: {g.lat:.5f}, {g.lon:.5f} | "
            f"{g.mesafe_m:.0f}m uzakta | Eğim: {g.egim_derece:.1f}° | "
            f"Skor: {g.genel_skor:.2f}{katman_str}"
        )


# ── OSM Engel Katmanı ─────────────────────────────────────────────────────────

class OsmEngelKatmani:
    """Overpass API ile bina, orman, su gibi iniş yasak alanlarını çeker."""

    _OVERPASS_FILTRELER = [
        '"building"',
        '"landuse"="forest"',
        '"natural"="wood"',
        '"natural"="water"',
        '"waterway"~"river|canal|stream"',
        '"landuse"="residential"',
        '"landuse"="industrial"',
        '"aeroway"',
    ]

    def __init__(self):
        self._poligonlar: list = []
        self._aktif = False

    def sorgula(self, min_lat: float, min_lon: float,
                max_lat: float, max_lon: float) -> bool:
        if not OVERPY_MEVCUT:
            return False
        try:
            api = _overpy.Overpass()
            filtreler = "\n  ".join(
                f"way[{f}]({min_lat:.6f},{min_lon:.6f},{max_lat:.6f},{max_lon:.6f});"
                for f in self._OVERPASS_FILTRELER
            )
            sorgu = (
                f"[out:json][timeout:{OSM_ZAMAN_ASIMI}];\n"
                f"(\n  {filtreler}\n);\n"
                f"out body;\n>;\nout skel qt;\n"
            )
            sonuc = api.query(sorgu)
            node_map = {n.id: (float(n.lat), float(n.lon)) for n in sonuc.nodes}
            self._poligonlar = []
            for way in sonuc.ways:
                pts = [node_map[nid] for nid in way._node_ids if nid in node_map]
                if len(pts) >= 3:
                    self._poligonlar.append(pts)
            self._aktif = True
            return True
        except Exception:
            self._aktif = False
            return False

    def engel_mi(self, lat: float, lon: float) -> bool:
        if not self._aktif:
            return False
        return any(self._icinde_mi(lat, lon, p) for p in self._poligonlar)

    @staticmethod
    def _icinde_mi(lat: float, lon: float, poly: list) -> bool:
        """Ray casting — nokta poligon içinde mi?"""
        n = len(poly)
        icinde = False
        j = n - 1
        for i in range(n):
            yi, xi = poly[i]
            yj, xj = poly[j]
            if ((yi > lat) != (yj > lat)) and (
                lon < (xj - xi) * (lat - yi) / (yj - yi) + xi
            ):
                icinde = not icinde
            j = i
        return icinde


# ── Ana Sınıf ─────────────────────────────────────────────────────────────────

class GuvenliInisAnalizci:
    """
    GPS konumu ve batarya seviyesine göre çok katmanlı güvenli iniş analizi.

    Katman 1: SRTM eğim (her zaman aktif)
    Katman 2: Ayak izi alan kontrolü (her zaman aktif)
    Katman 3: OSM engel maskesi (overpy kuruluysa)
    Katman 4: Rüzgar yönü skoru (ruzgar_ms > 1 m/s ise)
    """

    def __init__(self):
        self._srtm = srtm.get_data()

    # ── Genel API ────────────────────────────────────────────────────────────

    def analiz_et(
        self,
        lat: float,
        lon: float,
        batarya_yuzde: int = 30,
        hiz_ms: float = 10.0,
        batarya_wh: float = BATARYA_KAPASİTESİ_WH,
        ruzgar_ms: float = 0.0,
        ruzgar_yonu_derece: float = 0.0,
    ) -> AnalizSonucu:
        yaricap_m = self._ucucabilir_yaricap(batarya_yuzde, hiz_ms, batarya_wh)
        try:
            return self._cok_katmanli_analiz(
                lat, lon, yaricap_m, ruzgar_ms, ruzgar_yonu_derece
            )
        except Exception as e:
            return AnalizSonucu(
                merkez_lat=lat, merkez_lon=lon,
                yaricap_m=yaricap_m,
                en_yakin_guvenli=None,
                hata=f"Analiz hatası: {e}",
            )

    def tek_nokta_egimi(self, lat: float, lon: float) -> Optional[float]:
        return self._hesapla_egim(lat, lon)

    # ── Uçuş yarıçapı ─────────────────────────────────────────────────────

    @staticmethod
    def _ucucabilir_yaricap(batarya_yuzde: int, hiz_ms: float,
                             batarya_wh: float) -> float:
        kalan_wh = batarya_wh * (batarya_yuzde / 100.0) * 0.5
        return (kalan_wh / WHM_PER_KM) * 1000

    # ── Çok katmanlı analiz ───────────────────────────────────────────────

    def _cok_katmanli_analiz(
        self,
        merkez_lat: float,
        merkez_lon: float,
        yaricap_m: float,
        ruzgar_ms: float,
        ruzgar_yonu: float,
    ) -> AnalizSonucu:

        # OSM bounding box sorgusu (bir kez)
        osm = OsmEngelKatmani()
        m_per_deg_lon = M_PER_DEG_LAT * math.cos(math.radians(merkez_lat))
        delta_lat = yaricap_m / M_PER_DEG_LAT
        delta_lon = yaricap_m / m_per_deg_lon
        osm_aktif = osm.sorgula(
            merkez_lat - delta_lat, merkez_lon - delta_lon,
            merkez_lat + delta_lat, merkez_lon + delta_lon,
        )

        ruzgar_aktif = ruzgar_ms >= 1.0

        guvenli: list[InisNoktasi] = []
        riskli:  list[InisNoktasi] = []

        adim_deg_lat = ANALIZ_ADIM_M / M_PER_DEG_LAT
        adim_deg_lon = ANALIZ_ADIM_M / m_per_deg_lon
        yaricap_deg_lat = yaricap_m / M_PER_DEG_LAT
        yaricap_deg_lon = yaricap_m / m_per_deg_lon

        lat = merkez_lat - yaricap_deg_lat
        while lat <= merkez_lat + yaricap_deg_lat:
            lon = merkez_lon - yaricap_deg_lon
            while lon <= merkez_lon + yaricap_deg_lon:

                mesafe = self._haversine(merkez_lat, merkez_lon, lat, lon)
                if mesafe <= yaricap_m:
                    egim = self._hesapla_egim(lat, lon)
                    if egim is not None and egim <= RISKLI_EGIM_DERECE:
                        yukseklik = float(self._srtm.get_elevation(lat, lon) or 0.0)

                        # Katman 2: ayak izi alan kontrolü
                        alan_max = self._alan_max_egim(lat, lon, yukseklik)

                        # Katman 3: OSM engel
                        engel = osm.engel_mi(lat, lon)

                        # Katman 4: rüzgar skoru
                        r_skor = self._ruzgar_skoru(
                            lat, lon, merkez_lat, merkez_lon,
                            ruzgar_ms, ruzgar_yonu
                        ) if ruzgar_aktif else 1.0

                        # Bileşik skor
                        skor = self._genel_skor(
                            egim, alan_max, engel, r_skor, mesafe, yaricap_m
                        )

                        nokta = InisNoktasi(
                            lat=lat, lon=lon,
                            yukseklik_m=yukseklik,
                            egim_derece=egim,
                            mesafe_m=mesafe,
                            guvenlik=self._guvenlik_sinifi(egim),
                            alan_max_egim=alan_max,
                            osm_engel=engel,
                            ruzgar_skoru=r_skor,
                            genel_skor=skor,
                        )

                        if egim <= GUVENLI_EGIM_DERECE and not engel:
                            guvenli.append(nokta)
                        elif not engel:
                            riskli.append(nokta)

                lon += adim_deg_lon
            lat += adim_deg_lat

        # Bileşik skora göre sırala (yüksek skor önce)
        guvenli.sort(key=lambda p: p.genel_skor, reverse=True)
        riskli.sort(key=lambda p: p.genel_skor, reverse=True)

        return AnalizSonucu(
            merkez_lat=merkez_lat,
            merkez_lon=merkez_lon,
            yaricap_m=yaricap_m,
            en_yakin_guvenli=guvenli[0] if guvenli else None,
            guvenli_noktalar=guvenli[:20],
            riskli_noktalar=riskli[:20],
            osm_aktif=osm_aktif,
            ruzgar_skoru_aktif=ruzgar_aktif,
        )

    # ── Katman 1: Horn eğim hesabı ────────────────────────────────────────

    def _hesapla_egim(self, lat: float, lon: float) -> Optional[float]:
        m_per_deg_lon = M_PER_DEG_LAT * math.cos(math.radians(lat))
        dlat = HORN_OFSET_M / M_PER_DEG_LAT
        dlon = HORN_OFSET_M / m_per_deg_lon

        coords = [
            (lat - dlat, lon - dlon), (lat - dlat, lon), (lat - dlat, lon + dlon),
            (lat,        lon - dlon), (lat,        lon), (lat,        lon + dlon),
            (lat + dlat, lon - dlon), (lat + dlat, lon), (lat + dlat, lon + dlon),
        ]
        elev = []
        for la, lo in coords:
            h = self._srtm.get_elevation(la, lo)
            if h is None:
                return None
            elev.append(float(h))

        dz_dx = (
            (elev[2] + 2*elev[5] + elev[8]) -
            (elev[0] + 2*elev[3] + elev[6])
        ) / (8 * HORN_OFSET_M)

        dz_dy = (
            (elev[6] + 2*elev[7] + elev[8]) -
            (elev[0] + 2*elev[1] + elev[2])
        ) / (8 * HORN_OFSET_M)

        return math.degrees(math.atan(math.sqrt(dz_dx**2 + dz_dy**2)))

    # ── Katman 2: Ayak izi alan kontrolü ─────────────────────────────────

    def _alan_max_egim(self, lat: float, lon: float,
                        merkez_elev: float) -> float:
        """
        4 kardinal noktada merkez yüksekliğiyle slope hesaplar.
        Max değeri döndürür → tüm ayak izi düzlüğünü temsil eder.
        """
        m_per_deg_lon = M_PER_DEG_LAT * math.cos(math.radians(lat))
        dlat = AYAK_IZI_M / M_PER_DEG_LAT
        dlon = AYAK_IZI_M / m_per_deg_lon

        noktalar = [
            (lat + dlat, lon),
            (lat - dlat, lon),
            (lat, lon + dlon),
            (lat, lon - dlon),
        ]
        max_egim = 0.0
        for la, lo in noktalar:
            h = self._srtm.get_elevation(la, lo)
            if h is not None:
                dh = abs(float(h) - merkez_elev)
                egim = math.degrees(math.atan(dh / AYAK_IZI_M))
                max_egim = max(max_egim, egim)
        return max_egim

    # ── Katman 4: Rüzgar yönü skoru ──────────────────────────────────────

    @staticmethod
    def _ruzgar_skoru(
        lat: float, lon: float,
        merkez_lat: float, merkez_lon: float,
        ruzgar_ms: float, ruzgar_yonu: float,
    ) -> float:
        """
        Leeward (rüzgar gölgesi) tarafı tercih eder.
        skor ∈ [0.25, 1.0]; zayıf rüzgarda 1.0'a yaklaşır.
        """
        if ruzgar_ms < 1.0:
            return 1.0
        d_lon = (lon - merkez_lon) * math.cos(math.radians(merkez_lat))
        d_lat = lat - merkez_lat
        nokta_acisi = math.degrees(math.atan2(d_lon, d_lat)) % 360
        # Rüzgar gölgesi = rüzgar geliş yönü + 180°
        gole_yonu = (ruzgar_yonu + 180) % 360
        fark = abs(nokta_acisi - gole_yonu)
        if fark > 180:
            fark = 360 - fark
        hizalama = (math.cos(math.radians(fark)) + 1) / 2   # [0, 1]
        etki = min(ruzgar_ms / 15.0, 1.0)
        return 1.0 - etki * (1.0 - hizalama)

    # ── Bileşik skor ─────────────────────────────────────────────────────

    @staticmethod
    def _genel_skor(
        egim: float,
        alan_max_egim: float,
        osm_engel: bool,
        ruzgar_skoru: float,
        mesafe_m: float,
        yaricap_m: float,
    ) -> float:
        if osm_engel:
            return 0.0
        egim_s   = max(0.0, 1.0 - egim / GUVENLI_EGIM_DERECE)
        alan_s   = max(0.0, 1.0 - alan_max_egim / RISKLI_EGIM_DERECE)
        mesafe_s = max(0.0, 1.0 - mesafe_m / yaricap_m) if yaricap_m > 0 else 1.0
        return (
            _W_EGIM   * egim_s   +
            _W_ALAN   * alan_s   +
            _W_OSM    * 1.0      +
            _W_RUZGAR * ruzgar_skoru +
            _W_MESAFE * mesafe_s
        )

    # ── Yardımcılar ───────────────────────────────────────────────────────

    @staticmethod
    def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        R = 6371000
        f1, f2 = math.radians(lat1), math.radians(lat2)
        df = math.radians(lat2 - lat1)
        dl = math.radians(lon2 - lon1)
        a  = math.sin(df/2)**2 + math.cos(f1)*math.cos(f2)*math.sin(dl/2)**2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    @staticmethod
    def _guvenlik_sinifi(egim: float) -> str:
        if egim <= GUVENLI_EGIM_DERECE:
            return "GUVENLI"
        elif egim <= RISKLI_EGIM_DERECE:
            return "RISKLI"
        return "TEHLIKELI"


# ── Komut satırı testi ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    print("=" * 60)
    print("Doğuş ÜNİ LÖP – Çok Katmanlı Güvenli İniş Analizi v2")
    print("=" * 60)

    lat  = float(sys.argv[1]) if len(sys.argv) > 1 else -35.363262
    lon  = float(sys.argv[2]) if len(sys.argv) > 2 else 149.165237
    bat  = int(sys.argv[3])   if len(sys.argv) > 3 else 30
    ruz  = float(sys.argv[4]) if len(sys.argv) > 4 else 0.0
    yon  = float(sys.argv[5]) if len(sys.argv) > 5 else 0.0

    print(f"\nKonum    : {lat:.5f}, {lon:.5f}")
    print(f"Batarya  : %{bat}")
    print(f"Rüzgar   : {ruz:.1f} m/s @ {yon:.0f}°")
    print(f"OSM      : {'overpy kurulu' if OVERPY_MEVCUT else 'overpy YOK (pip install overpy)'}")
    print("\nSRTM verisi indiriliyor (ilk kez ~10 saniye sürebilir)…\n")

    analizci = GuvenliInisAnalizci()
    sonuc    = analizci.analiz_et(lat, lon, batarya_yuzde=bat,
                                  ruzgar_ms=ruz, ruzgar_yonu_derece=yon)

    print(f"Uçuş yarıçapı : {sonuc.yaricap_m:.0f} m")
    print(f"OSM aktif     : {sonuc.osm_aktif}")
    print(f"Rüzgar skoru  : {sonuc.ruzgar_skoru_aktif}")
    print(f"Güvenli nokta : {len(sonuc.guvenli_noktalar)}")
    print(f"Riskli nokta  : {len(sonuc.riskli_noktalar)}")
    print()
    print("SONUÇ:", sonuc.ozet())

    if sonuc.guvenli_noktalar:
        print("\nİlk 5 güvenli iniş noktası (skora göre sıralı):")
        for i, n in enumerate(sonuc.guvenli_noktalar[:5], 1):
            print(f"  {i}. {n}")
