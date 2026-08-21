import time
from collections import deque

import config_yukleyici as _cfg


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
