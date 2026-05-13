"""
alan_inis_karar.py
Doğuş Üniversitesi LÖP — Uçuş Anı İniş Karar Modülü

GPS koordinatı + LIDAR mesafesi gelir → inecek mi kararı verir.

Veri akışı:
    MAVLink GLOBAL_POSITION_INT → lat, lon
    MAVLink DISTANCE_SENSOR     → lidar_m
    → AlanInisKarar.inis_karari(lat, lon, lidar_m)
    → InisKarari(inebilir=True/False, neden=...)
"""

import json
import math
import numpy as np
from dataclasses import dataclass
from typing import Optional

try:
    from rasterio.transform import Affine
    RASTERIO_MEVCUT = True
except ImportError:
    RASTERIO_MEVCUT = False

try:
    import config_yukleyici as _cfg
    _MAX_MESAFE_M = float(_cfg.al("alan_inis.max_mesafe_m", 3000))
    _W_MESAFE = float(_cfg.al("alan_inis.mesafe_agirlik", 0.45))
    _W_EGIM = float(_cfg.al("alan_inis.egim_agirlik", 0.35))
    _W_RUZGAR = float(_cfg.al("alan_inis.ruzgar_agirlik", 0.20))
except Exception:
    _MAX_MESAFE_M = 3000.0
    _W_MESAFE = 0.45
    _W_EGIM = 0.35
    _W_RUZGAR = 0.20

GUVENLI_EGIM  = 5.0   # derece
RISKLI_EGIM   = 15.0  # derece
LIDAR_MIN_M   = 0.3   # zemine bu kadar yaklaşınca dur
LIDAR_INIS_M  = 2.0   # bu mesafede iniş onayı al


def _normalize_weights() -> tuple[float, float, float]:
    toplam = _W_MESAFE + _W_EGIM + _W_RUZGAR
    if toplam <= 0:
        return 0.45, 0.35, 0.20
    return _W_MESAFE / toplam, _W_EGIM / toplam, _W_RUZGAR / toplam


@dataclass
class InisKarari:
    inebilir:       bool
    neden:          str
    egim_derece:    float        = 0.0
    lidar_m:        Optional[float] = None
    en_yakin_nokta: Optional[dict]  = None  # önceden belirlenmiş en yakın güvenli nokta
    mesafe_m:       float        = 0.0      # o noktaya uzaklık


class AlanInisKarar:
    """
    __init__: alan_verisi.npz yüklenir (bir kez).
    inis_karari(): her karar anında çağrılır, anında cevap verir.
    en_iyi_nokta(): rüzgar + mesafe + eğim skoruyla en uygun noktayı seçer.
    """

    def __init__(self, npz_dosya: str):
        self._egim:      np.ndarray = None
        self._transform             = None
        self._noktalar:  list       = []
        self._w_mesafe, self._w_egim, self._w_ruzgar = _normalize_weights()
        self._yukle(npz_dosya)

    def _yukle(self, dosya: str):
        data = np.load(dosya, allow_pickle=True)
        self._egim = data["egim"]
        t = data["transform"]
        if RASTERIO_MEVCUT:
            self._transform = Affine(t[0], t[1], t[2], t[3], t[4], t[5])
        else:
            self._transform = t
        self._noktalar = json.loads(str(data["noktalar_json"][0]))
        guvenli = sum(1 for n in self._noktalar if n["durum"] == "GUVENLI")
        print(f"Alan yüklendi: {self._egim.shape} grid | "
              f"{len(self._noktalar)} nokta ({guvenli} güvenli)")

    # ── Eğim lookup ───────────────────────────────────────────────────────────

    def egim_sor(self, lat: float, lon: float) -> Optional[float]:
        """GPS koordinatından anlık eğim — hesaplama yok, sadece dizi indexi."""
        if self._egim is None:
            return None
        try:
            if RASTERIO_MEVCUT:
                col, row = ~self._transform * (lon, lat)
            else:
                t = self._transform
                col = (lon - t[2]) / t[0]
                row = (lat - t[5]) / t[4]
            row, col = int(row), int(col)
            if 0 <= row < self._egim.shape[0] and 0 <= col < self._egim.shape[1]:
                return float(self._egim[row, col])
        except Exception:
            pass
        return None

    # ── En yakın güvenli nokta ────────────────────────────────────────────────

    def en_yakin_guvenli(self, lat: float, lon: float) -> Optional[dict]:
        guvenli = [n for n in self._noktalar if n["durum"] == "GUVENLI"]
        if not guvenli:
            return None
        nokta = min(guvenli, key=lambda n: self._haversine(lat, lon, n["lat"], n["lon"]))
        nokta = dict(nokta)
        nokta["mesafe_m"] = self._haversine(lat, lon, nokta["lat"], nokta["lon"])
        return nokta

    def en_iyi_nokta(
        self,
        lat: float,
        lon: float,
        ruzgar_ms: float = 0.0,
        ruzgar_yonu: float = 0.0,
    ) -> Optional[dict]:
        guvenli = [n for n in self._noktalar if n.get("durum") == "GUVENLI"]
        riskli = [n for n in self._noktalar if n.get("durum") == "RISKLI"]
        adaylar = guvenli or riskli
        if not adaylar:
            return None

        secilebilir = []
        for n in adaylar:
            mesafe = self._haversine(lat, lon, n["lat"], n["lon"])
            if _MAX_MESAFE_M > 0 and mesafe > _MAX_MESAFE_M:
                continue
            ruzgar_s = self._ruzgar_skoru(lat, lon, n["lat"], n["lon"], ruzgar_ms, ruzgar_yonu)
            egim_s = max(0.0, 1.0 - (n.get("egim", 0.0) / RISKLI_EGIM))
            mesafe_s = 1.0 if _MAX_MESAFE_M <= 0 else max(0.0, 1.0 - mesafe / _MAX_MESAFE_M)
            skor = (
                self._w_mesafe * mesafe_s +
                self._w_egim * egim_s +
                self._w_ruzgar * ruzgar_s
            )
            secilebilir.append((skor, mesafe, n))

        if not secilebilir:
            return None

        skor, mesafe, nokta = max(secilebilir, key=lambda x: x[0])
        nokta = dict(nokta)
        nokta["mesafe_m"] = mesafe
        nokta["skor"] = skor
        return nokta

    # ── Ana karar metodu ──────────────────────────────────────────────────────

    def inis_karari(
        self,
        lat:     float,
        lon:     float,
        lidar_m: float = None,   # DISTANCE_SENSOR mesajından gelir
        ruzgar_ms: float = 0.0,
        ruzgar_yonu: float = 0.0,
    ) -> InisKarari:

        # 1. GPS koordinatından eğim sorgula
        egim = self.egim_sor(lat, lon)
        if egim is None:
            return InisKarari(False, "Koordinat alan dışında", egim_derece=0.0)

        if egim > RISKLI_EGIM:
            return InisKarari(False, f"Eğim çok yüksek: {egim:.1f}°", egim_derece=egim)

        # 2. LIDAR mesafe kontrolü
        if lidar_m is not None:
            if lidar_m < LIDAR_MIN_M:
                return InisKarari(
                    False, f"LIDAR: zemine çok yakın ({lidar_m:.2f}m)",
                    egim_derece=egim, lidar_m=lidar_m
                )

        # 3. En iyi önceden belirlenmiş noktayı bul (rüzgar dahil)
        yakin = self.en_iyi_nokta(lat, lon, ruzgar_ms=ruzgar_ms, ruzgar_yonu=ruzgar_yonu)

        # 4. Karar
        neden = (f"Güvenli — eğim {egim:.1f}°" if egim <= GUVENLI_EGIM
                 else f"Riskli ama kabul edilebilir — eğim {egim:.1f}°")

        return InisKarari(
            inebilir       = True,
            neden          = neden,
            egim_derece    = egim,
            lidar_m        = lidar_m,
            en_yakin_nokta = yakin,
            mesafe_m       = yakin["mesafe_m"] if yakin else 0.0,
        )

    @staticmethod
    def _haversine(lat1, lon1, lat2, lon2) -> float:
        R = 6371000
        f1, f2 = math.radians(lat1), math.radians(lat2)
        df = math.radians(lat2 - lat1)
        dl = math.radians(lon2 - lon1)
        a  = math.sin(df/2)**2 + math.cos(f1)*math.cos(f2)*math.sin(dl/2)**2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

    @staticmethod
    def _ruzgar_skoru(
        merkez_lat: float,
        merkez_lon: float,
        lat: float,
        lon: float,
        ruzgar_ms: float,
        ruzgar_yonu: float,
    ) -> float:
        if ruzgar_ms < 1.0:
            return 1.0
        d_lon = (lon - merkez_lon) * math.cos(math.radians(merkez_lat))
        d_lat = lat - merkez_lat
        nokta_acisi = math.degrees(math.atan2(d_lon, d_lat)) % 360
        gole_yonu = (ruzgar_yonu + 180) % 360
        fark = abs(nokta_acisi - gole_yonu)
        if fark > 180:
            fark = 360 - fark
        hizalama = (math.cos(math.radians(fark)) + 1) / 2
        etki = min(ruzgar_ms / 15.0, 1.0)
        return 1.0 - etki * (1.0 - hizalama)


# ── Test ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    npz = sys.argv[1] if len(sys.argv) > 1 else "alan_verisi.npz"
    lat = float(sys.argv[2]) if len(sys.argv) > 2 else 40.95
    lon = float(sys.argv[3]) if len(sys.argv) > 3 else 28.85
    lidar = float(sys.argv[4]) if len(sys.argv) > 4 else None

    karar = AlanInisKarar(npz)
    sonuc = karar.inis_karari(lat, lon, lidar_m=lidar)

    print(f"\nKonum : {lat:.5f}, {lon:.5f}")
    print(f"Eğim  : {sonuc.egim_derece:.1f}°")
    print(f"LIDAR : {sonuc.lidar_m}m")
    print(f"Karar : {'İNEBİLİR' if sonuc.inebilir else 'İNEMEZ'} — {sonuc.neden}")
    if sonuc.en_yakin_nokta:
        n = sonuc.en_yakin_nokta
        print(f"En yakın güvenli nokta: {n['id']} — {n['mesafe_m']:.0f}m uzakta")
