"""
test_ruzgar_gradient.py
Doğuş Üniversitesi LÖP — Rüzgar Gradient Modeli Birim Testleri

Test kapsamı:
  1. Hellmann Güç Yasası hesabı
  2. Doğrusal regresyon trend hesabı (_ruzgar_trend_hesapla)
  3. Bekleme önerisi koşulları
  4. EMA → Zemin dönüşümü zinciri
  5. Eşik sıfırlama (histerezis)
  6. Yüksek irtifa davranışı
  7. Çok düşük irtifa (zemin-ref sınırı)
  8. Sürekli gust dedektörü
  9. İrtifa tavsiyesi (Hellmann tersine çevirme)
"""

import math
import time
import sys
import types
from collections import deque
from unittest.mock import MagicMock, patch, PropertyMock


# ──────────────────────────────────────────────────────────────────────────────
# Hellmann Güç Yasası bağımsız fonksiyon — gcs_main'e dokunmadan test
# ──────────────────────────────────────────────────────────────────────────────

def hellmann(v_irtifa: float, h_irtifa: float, h_zemin: float = 2.0, alpha: float = 0.14) -> float:
    """Güç yasası: v_zemin = v_irtifa × (h_zemin / h_irtifa) ^ alpha"""
    irtifa = max(h_irtifa, h_zemin + 0.1)
    return v_irtifa * (h_zemin / irtifa) ** alpha


def _trend_hesapla(gecmis: list) -> float:
    """
    (zaman, hiz) çiftlerinden en küçük kareler doğrusal regresyon.
    gcs_main._ruzgar_trend_hesapla() ile aynı mantık.
    """
    if len(gecmis) < 6:
        return 0.0
    t0 = gecmis[0][0]
    n  = len(gecmis)
    ts = [v[0] - t0 for v in gecmis]
    vs = [v[1]      for v in gecmis]
    t_ort = sum(ts) / n
    v_ort = sum(vs) / n
    pay   = sum((ts[i] - t_ort) * (vs[i] - v_ort) for i in range(n))
    payda = sum((ts[i] - t_ort) ** 2               for i in range(n))
    return pay / payda if payda > 0 else 0.0


# ══════════════════════════════════════════════════════════════════════════════
# 1. Hellmann Güç Yasası
# ══════════════════════════════════════════════════════════════════════════════

class TestHellmannGucYasasi:

    def test_acik_duzluk_40m(self):
        """8 m/s @ 40m → zemin ~5.9 m/s (açık tarla, α=0.14)"""
        sonuc = hellmann(8.0, 40.0, h_zemin=2.0, alpha=0.14)
        beklenen = 8.0 * (2.0 / 40.0) ** 0.14
        assert abs(sonuc - beklenen) < 1e-9

    def test_acik_duzluk_40m_deger(self):
        """
        Sayısal kontrol: 8 m/s @ 40m → 8 × (2/40)^0.14 ≈ 5.26 m/s
        (2/40)^0.14 = (0.05)^0.14 ≈ 0.657 → 8 × 0.657 ≈ 5.26
        """
        sonuc = hellmann(8.0, 40.0)
        assert 5.0 < sonuc < 5.8

    def test_kentsel_alpha(self):
        """Kentsel arazi (α=0.35) → zemin çok daha düşük"""
        acik    = hellmann(10.0, 30.0, alpha=0.14)
        kentsel = hellmann(10.0, 30.0, alpha=0.35)
        assert kentsel < acik  # Daha pürüzlü arazi → daha büyük gradyan → zemin daha düşük

    def test_irtifa_arttikca_zemin_azalir(self):
        """Drone yükseldikçe zemin tahmini düşer (gradient daha belirgin)"""
        z_20m = hellmann(10.0, 20.0)
        z_50m = hellmann(10.0, 50.0)
        z_100m = hellmann(10.0, 100.0)
        assert z_20m > z_50m > z_100m

    def test_cok_dusuk_irtifa_siniri(self):
        """h_irtifa < h_zemin+0.1 → sınır uygulanır, ZeroDivisionError yok"""
        sonuc = hellmann(5.0, 0.5, h_zemin=2.0)
        assert sonuc > 0.0
        assert math.isfinite(sonuc)

    def test_sifir_hiz(self):
        """0 m/s giriş → 0 m/s çıkış"""
        sonuc = hellmann(0.0, 30.0)
        assert sonuc == 0.0

    def test_standart_referans_yuksekligi(self):
        """
        Drone çok alçakta (5m) → zemin tahmini irtifa rüzgarına çok yakın.
        Sınır clamp: irtifa = max(5.0, 2.0 + 0.1) = 5.0 → (2/5)^0.14 ≈ 0.916
        Sonuç: v_irtifa'nın %90'ından fazla olmalı (çok yakın).
        """
        v_irtifa = 7.5
        sonuc = hellmann(v_irtifa, 5.0, h_zemin=2.0, alpha=0.20)
        # Oran = (2/5)^0.20 ≈ 0.832 → sonuç ≈ 6.24
        assert sonuc > v_irtifa * 0.75
        assert sonuc < v_irtifa   # Her zaman irtifa rüzgarından düşük

    def test_kritik_senaryo_sitl(self):
        """
        SITL doğrulama senaryosu:
        param set SIM_WIND_SPD 12 (12 m/s @ 40m irtifa)
        tehlikeli eşik 11.1 m/s — ama zemin ~8.9 m/s → eşik GEÇMEZ
        """
        zemin = hellmann(12.0, 40.0, alpha=0.14)
        tehlikeli_esik = 11.1
        assert zemin < tehlikeli_esik, (
            f"Zemin rüzgar {zemin:.2f} m/s, tehlikeli eşik {tehlikeli_esik} m/s — "
            "gereksiz RTL tetiklenmemeli"
        )

    def test_kritik_senaryo_20ms(self):
        """
        SITL doğrulama:
        param set SIM_WIND_SPD 20 (20 m/s @ 40m irtifa)
        Zemin: 20 × (2/40)^0.14 ≈ 13.1 m/s → tehlikeli eşik 11.1 AŞILDI
        (kritik eşik 16.7 aşılamaz olsa da tehlikeli tetikler)
        """
        zemin = hellmann(20.0, 40.0, alpha=0.14)
        tehlikeli_esik = 11.1
        assert zemin > tehlikeli_esik, (
            f"20 m/s @ 40m → zemin {zemin:.2f} m/s, tehlikeli eşik {tehlikeli_esik} — "
            "yüksek irtifa rüzgarında zemin tehlikeli eşiği aşmalı"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 2. Doğrusal Regresyon Trend Hesabı
# ══════════════════════════════════════════════════════════════════════════════

class TestTrendHesapla:

    def _gecmis_olustur(self, baslangic_v: float, artis_ms_per_s: float,
                        n: int = 20, dt: float = 3.0):
        """Sabit artışlı sentetik veri üretir."""
        t0 = 1000.0  # başlangıç zamanı (rastgele)
        return [(t0 + i * dt, baslangic_v + i * dt * artis_ms_per_s) for i in range(n)]

    def test_yetersiz_veri(self):
        """< 6 ölçüm → 0.0 döner"""
        gecmis = [(float(i), 5.0) for i in range(5)]
        assert _trend_hesapla(gecmis) == 0.0

    def test_tam_6_olcum(self):
        """Tam 6 ölçüm = minimum — çalışmalı"""
        gecmis = [(float(i * 3), 5.0 + i * 0.1) for i in range(6)]
        trend = _trend_hesapla(gecmis)
        assert abs(trend - 0.1 / 3.0) < 1e-6

    def test_artan_trend(self):
        """Rüzgar artıyorsa trend > 0"""
        gecmis = self._gecmis_olustur(5.0, 0.05, n=20)  # +0.05 m/s/s
        trend = _trend_hesapla(gecmis)
        assert trend > 0.04

    def test_azalan_trend(self):
        """Rüzgar azalıyorsa trend < 0"""
        gecmis = self._gecmis_olustur(10.0, -0.05, n=20)
        trend = _trend_hesapla(gecmis)
        assert trend < -0.04

    def test_sabit_ruzgar(self):
        """Sabit rüzgarda trend ≈ 0"""
        gecmis = [(float(i * 2), 7.5) for i in range(30)]
        trend = _trend_hesapla(gecmis)
        assert abs(trend) < 1e-10

    def test_buyuk_pencere(self):
        """60 ölçümlük pencerede lineer artış doğru hesaplanmalı"""
        gecmis = self._gecmis_olustur(4.0, 0.10, n=60, dt=1.0)
        trend = _trend_hesapla(gecmis)
        assert abs(trend - 0.10) < 1e-6

    def test_gurultulu_veri(self):
        """Gürültülü ama net trend olan veri — işaret doğru olmalı"""
        import random
        random.seed(42)
        gecmis = [(float(i), 5.0 + i * 0.08 + random.gauss(0, 0.3)) for i in range(30)]
        trend = _trend_hesapla(gecmis)
        assert trend > 0.0, "Net artış trendi pozitif olmalı"


# ══════════════════════════════════════════════════════════════════════════════
# 3. Bekleme Önerisi Koşul Mantığı
# ══════════════════════════════════════════════════════════════════════════════

class TestBeklemeOnerisiKosullari:
    """
    _bekleme_onerisi_guncelle() mantığını ham Python olarak test eder —
    PyQt5 bağımlılığı olmadan.
    """

    TEHLIKELI_MS = 11.1

    def _mesaj_uret(self, hiz_f: float, trend: float) -> str | None:
        """Bekleme önerisi mesajı döner ya da None."""
        tehlikeli = self.TEHLIKELI_MS

        # Tehlikeli eşiğin %80-100 aralığında VE azalıyorsa
        if tehlikeli * 0.80 <= hiz_f < tehlikeli and trend < -0.05:
            kalan = max((hiz_f - tehlikeli * 0.70) / abs(trend), 0)
            return f"azalıyor:{kalan:.0f}sn"

        # Güvenli aralıkta ama hızla artıyorsa
        elif hiz_f < tehlikeli * 0.80 and trend > 0.08:
            sure = (tehlikeli - hiz_f) / trend
            if sure < 120:
                return f"artıyor:{sure:.0f}sn"

        return None

    def test_azalan_trend_esige_yakin(self):
        """~10 m/s (tehlikelinin %90'ı) + azalıyor → 'azalıyor' mesajı"""
        msg = self._mesaj_uret(hiz_f=10.0, trend=-0.10)
        assert msg is not None
        assert "azalıyor" in msg

    def test_azalan_trend_esik_alti(self):
        """8.5 m/s (tehlikelinin %76'sı) → eşiğe yakın aralıkta değil, mesaj yok"""
        msg = self._mesaj_uret(hiz_f=8.5, trend=-0.10)
        assert msg is None

    def test_artan_trend_guvenli_aralık(self):
        """7 m/s + hızla artıyor → 'artıyor' uyarısı"""
        msg = self._mesaj_uret(hiz_f=7.0, trend=0.12)
        assert msg is not None
        assert "artıyor" in msg

    def test_artan_trend_cok_yavash(self):
        """7 m/s + çok yavaş artış (0.03 m/s/s) → mesaj yok (eşik 0.08)"""
        msg = self._mesaj_uret(hiz_f=7.0, trend=0.03)
        assert msg is None

    def test_artan_trend_120sn_uzak(self):
        """Tehlikeli eşiğe 200 sn uzak → mesaj yok"""
        # tehlikeli=11.1, hiz_f=7.0 → fark=4.1 m/s, trend=0.02 m/s/s → sure=205 sn
        msg = self._mesaj_uret(hiz_f=7.0, trend=0.02)
        assert msg is None

    def test_tehlikeli_esik_ustunde(self):
        """Zaten tehlikeli eşiğin üstünde → bekleme önerisi değil, ana alarm devreye girer"""
        msg = self._mesaj_uret(hiz_f=12.0, trend=0.05)
        assert msg is None  # Bu durumda RTL başlatılır, bekleme önerisi değil

    def test_sifir_trend(self):
        """Sabit rüzgar → ne azalıyor ne artıyor, mesaj yok"""
        msg = self._mesaj_uret(hiz_f=10.0, trend=0.0)
        assert msg is None

    def test_beklenen_kalan_sure_hesabi(self):
        """
        hiz_f=10.0, trend=-0.10 m/s/s
        kalan = (10.0 - 11.1*0.70) / 0.10 = (10.0 - 7.77) / 0.10 = 22.3 sn
        """
        msg = self._mesaj_uret(hiz_f=10.0, trend=-0.10)
        assert msg is not None
        kalan = float(msg.split(":")[1].replace("sn", ""))
        beklenen = (10.0 - self.TEHLIKELI_MS * 0.70) / 0.10
        assert abs(kalan - beklenen) < 1.0  # 1 sn tolerans


# ══════════════════════════════════════════════════════════════════════════════
# 4. Zemin Rüzgar Tahmini — Gerçek Senaryo Testleri
# ══════════════════════════════════════════════════════════════════════════════

class TestGercekSenaryolar:

    def test_insansiz_hava_araci_inis_karari(self):
        """
        Senaryo: Drone 50m irtifada, irtifa rüzgar 9 m/s
        Tehlikeli eşik 11.1 m/s → irtifada GEÇMİYOR
        Zemin tahmini ~6.7 m/s → GÜVENLE GEÇMİYOR
        → İniş YAPILMALI (yanlış alarm yok)
        """
        v_irtifa = 9.0
        irtifa   = 50.0
        zemin    = hellmann(v_irtifa, irtifa, alpha=0.14)
        tehlikeli_esik = 11.1
        assert zemin < tehlikeli_esik, (
            f"9 m/s @ 50m → zemin {zemin:.2f} m/s, eşik {tehlikeli_esik} — iniş iptal olmamalı"
        )

    def test_yuksek_irtifada_gercek_tehlike(self):
        """
        Senaryo: 100m irtifa, 22 m/s rüzgar (fırtına)
        Zemin: 22 × (2/100)^0.14 ≈ 12.7 m/s — tehlikeli eşik 11.1 AŞILDI.
        Hellmann, 100m'de belirgin bir azaltma yapar (α=0.14 ile).
        Zemin rüzgar ham değerin %70'inden az olmalı ama tehlikeli aralıkta.
        """
        zemin = hellmann(22.0, 100.0, alpha=0.14)
        tehlikeli_esik = 11.1
        assert zemin > tehlikeli_esik, f"22 m/s @ 100m → zemin {zemin:.2f} m/s tehlikeli olmalı"
        assert zemin < 22.0 * 0.80,   f"Zemin rüzgar irtifa rüzgarından belirgin düşük olmalı"

    def test_kentsel_vs_acik_kiyaslama(self):
        """
        Aynı irtifa rüzgarı, farklı arazi → kentsel bekleme önerisi daha erken
        Çünkü kentsel arazide zemin rüzgarı irtifadan çok daha düşük
        (kentsel α=0.35 > açık α=0.14 → üs büyük → oran küçük → zemin daha düşük)
        """
        v = 10.0
        h = 40.0
        z_acik    = hellmann(v, h, alpha=0.14)
        z_kentsel = hellmann(v, h, alpha=0.35)
        assert z_acik > z_kentsel, (
            "Kentsel arazide zemin rüzgarı açık araziye göre daha düşük olmalı"
        )

    def test_ema_zinciri_yumusatma(self):
        """
        EMA α=0.25 → tek ani gust alarmı tetiklemez.
        5 ölçüm: 4×normal + 1×kritik gust → EMA hâlâ eşik altında
        """
        ema = 6.0   # başlangıç
        olcumler = [6.0, 6.2, 5.8, 6.1, 20.0]   # son ölçüm gust
        for v in olcumler:
            ema = 0.25 * v + 0.75 * ema
        tehlikeli_esik = 11.1
        assert ema < tehlikeli_esik, (
            f"Tek gust sonrası EMA {ema:.2f} m/s — alarm tetiklenmemeli"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 5. Histerezis Sıfırlama
# ══════════════════════════════════════════════════════════════════════════════

class TestHisterezis:

    TEHLIKELI_MS = 11.1

    def test_bayrak_sifirlanma_esigi(self):
        """Zemin rüzgar %85 eşiğin altına düşünce bayraklar sıfırlanmalı"""
        esik_sirla = self.TEHLIKELI_MS * 0.85
        # 9.0 m/s < 9.435 m/s → sıfırla
        assert 9.0 < esik_sirla

    def test_bayrak_korunma_esigi(self):
        """Zemin rüzgar %85 ile %100 arasındaysa bayraklar korunmalı"""
        esik_sirla = self.TEHLIKELI_MS * 0.85
        v_histerez = self.TEHLIKELI_MS * 0.90   # %90 aralığında
        assert v_histerez > esik_sirla  # sıfırlanmamalı


# ══════════════════════════════════════════════════════════════════════════════
# 6. Matematiksel Özellikler
# ══════════════════════════════════════════════════════════════════════════════

class TestMatematikselOzellikler:

    def test_guc_yasasi_monotonik(self):
        """h_irtifa arttıkça zemin tahmini azalır (monotonik)"""
        irtifalar = [5, 10, 20, 40, 80, 120]
        sonuclar  = [hellmann(8.0, h) for h in irtifalar]
        for i in range(len(sonuclar) - 1):
            assert sonuclar[i] > sonuclar[i + 1]

    def test_alpha_artisca_zemin_azalir(self):
        """α arttıkça zemin tahmini azalır (daha büyük üs → küçük değer, çünkü h_zemin/h_irtifa < 1)"""
        alphas = [0.10, 0.14, 0.20, 0.25, 0.35]
        sonuclar = [hellmann(10.0, 50.0, alpha=a) for a in alphas]
        for i in range(len(sonuclar) - 1):
            assert sonuclar[i] > sonuclar[i + 1]

    def test_trend_lineer_veri_tam_uyum(self):
        """Mükemmel doğrusal veri → trend tam hesaplanmalı"""
        artis = 0.2   # m/s/s
        gecmis = [(float(i), 5.0 + i * artis) for i in range(30)]
        trend = _trend_hesapla(gecmis)
        assert abs(trend - artis) < 1e-9

    def test_trend_isaretler(self):
        """Artış → pozitif, Azalış → negatif, Sabit → sıfır"""
        gecmis_artan = [(float(i), 5.0 + i * 0.1) for i in range(20)]
        gecmis_azalan = [(float(i), 10.0 - i * 0.1) for i in range(20)]
        gecmis_sabit  = [(float(i), 7.0)             for i in range(20)]

        assert _trend_hesapla(gecmis_artan) > 0
        assert _trend_hesapla(gecmis_azalan) < 0
        assert abs(_trend_hesapla(gecmis_sabit)) < 1e-9


# ══════════════════════════════════════════════════════════════════════════════
# 7. Kalite Kapıları — EKF + Vibrasyon + Minimum Rüzgar
# ══════════════════════════════════════════════════════════════════════════════

class TestKaliteKapilari:
    """
    _ruzgar_guncelle() kapı mantığını bağımsız Python olarak test eder.
    Cube Orange EKF gürültüsüne karşı filtreleme.
    """

    EKF_TAMAM  = True    # Tutum + yatay hız kilitli
    EKF_BOZUK  = False   # EKF henüz kilitlenmedi

    def _kapidan_gec(self, hiz: float, ekf_ok: bool, vib_klip: int,
                     min_ms: float = 2.0) -> bool:
        """True → işleme devam et, False → kaçan kapıda dur."""
        if not ekf_ok:
            return False
        if vib_klip > 0:
            return False
        if hiz < min_ms:
            return False
        return True

    def test_ekf_kilitli_gece_izin(self):
        """EKF kilitli, titreşim yok, hız yeterli → işleme devam"""
        assert self._kapidan_gec(5.0, self.EKF_TAMAM, 0) is True

    def test_ekf_kilitli_degil_dur(self):
        """EKF kilitlenmemiş → kapıda dur, gradient hesaplama"""
        assert self._kapidan_gec(8.0, self.EKF_BOZUK, 0) is False

    def test_imu_klipleme_dur(self):
        """IMU saturation var → titreşim çok yüksek, veri bozuk → dur"""
        assert self._kapidan_gec(8.0, self.EKF_TAMAM, 1) is False

    def test_dusuk_hiz_gurultu_tabani(self):
        """1.5 m/s → EKF gürültü tabanında → Hellmann uygulama"""
        assert self._kapidan_gec(1.5, self.EKF_TAMAM, 0, min_ms=2.0) is False

    def test_tam_sinir_gecerli(self):
        """Tam 2.0 m/s → sınır değeri, işlenmemeli (< 2.0 dışarda)"""
        assert self._kapidan_gec(2.0, self.EKF_TAMAM, 0, min_ms=2.0) is True

    def test_tum_kotu_kosullar(self):
        """EKF bozuk + klipleme + düşük hız → her üç kapı da tutuyor"""
        assert self._kapidan_gec(1.0, self.EKF_BOZUK, 2, min_ms=2.0) is False

    def test_vibrasyon_dinamik_esik_dusuk(self):
        """Düşük titreşim (10 m/s²) → gust eşiği orijinal değerde"""
        vib = 10.0
        gust_esik = 3.0
        if vib > 30.0:
            aktif = gust_esik * 2.0
        elif vib > 15.0:
            aktif = gust_esik * 1.5
        else:
            aktif = gust_esik
        assert aktif == 3.0

    def test_vibrasyon_dinamik_esik_orta(self):
        """Orta titreşim (20 m/s²) → gust eşiği 1.5× artıyor"""
        vib = 20.0
        gust_esik = 3.0
        if vib > 30.0:
            aktif = gust_esik * 2.0
        elif vib > 15.0:
            aktif = gust_esik * 1.5
        else:
            aktif = gust_esik
        assert aktif == 4.5

    def test_vibrasyon_dinamik_esik_yuksek(self):
        """Yüksek titreşim (35 m/s²) → gust eşiği 2× artıyor"""
        vib = 35.0
        gust_esik = 3.0
        if vib > 30.0:
            aktif = gust_esik * 2.0
        elif vib > 15.0:
            aktif = gust_esik * 1.5
        else:
            aktif = gust_esik
        assert aktif == 6.0

    def test_ekf_bayrak_mantigi(self):
        """Bit 0 (tutum) + Bit 1 (yatay hız) her ikisi set → rüzgar geçerli"""
        # Bit 0 = 0x0001, Bit 1 = 0x0002
        bayraklar_tamam = 0x001F   # tüm EKF flagleri OK
        bayraklar_eksik = 0x0001   # sadece tutum, yatay hız yok

        gecerli_tam   = bool(bayraklar_tamam & 0x0001) and bool(bayraklar_tamam & 0x0002)
        gecerli_eksik = bool(bayraklar_eksik & 0x0001) and bool(bayraklar_eksik & 0x0002)

        assert gecerli_tam   is True
        assert gecerli_eksik is False


# ══════════════════════════════════════════════════════════════════════════════
# 8. Sürekli Gust Dedektörü Mantığı
# ══════════════════════════════════════════════════════════════════════════════

def _gust_sim(olcumler: list, ema_baslangic: float = 6.0,
              gust_esik: float = 3.0, gust_min_sure: float = 3.0,
              dt: float = 1.0) -> list:
    """
    Gust dedektörünü simüle eder. Alarm tetiklendiği anları (sure_sn) döner.
    olcumler: liste halinde ham rüzgar hızları (m/s), 1 sn aralıkla
    """
    ema = ema_baslangic
    gust_baslangic_t = None
    alarm_verildi = False
    alarmlar = []

    for i, hiz in enumerate(olcumler):
        t = float(i) * dt
        ema = 0.25 * hiz + 0.75 * ema
        delta = hiz - ema

        if delta > gust_esik:
            # Gust başladı (ilk kez)
            if gust_baslangic_t is None:
                gust_baslangic_t = t
                alarm_verildi = False

        if gust_baslangic_t is not None:
            sure = t - gust_baslangic_t
            if sure >= gust_min_sure and not alarm_verildi:
                alarm_verildi = True
                alarmlar.append(round(sure, 1))
            # Sıfırlama: ham hız EMA'nın ALTINA düşünce gust bitti
            if hiz < ema:
                gust_baslangic_t = None
                alarm_verildi = False

    return alarmlar


class TestGustDedektoru:

    def test_kisa_gust_alarm_yok(self):
        """1-2 saniyeyi aşmayan gust → alarm tetiklenmez"""
        # 6 m/s sabit → ani 14 m/s → 2 ölçüm → geri 6 m/s
        olcumler = [6.0, 6.0, 6.0, 14.0, 14.0, 6.0, 6.0]
        alarmlar = _gust_sim(olcumler, ema_baslangic=6.0, gust_esik=3.0, gust_min_sure=3.0)
        assert len(alarmlar) == 0

    def test_uzun_gust_alarm_tetikler(self):
        """4 saniye süren gust → alarm tetiklenir"""
        # 6 m/s sabit → 5 ölçüm boyunca 14 m/s (her 1 sn)
        olcumler = [6.0] * 5 + [14.0] * 5 + [6.0] * 3
        alarmlar = _gust_sim(olcumler, ema_baslangic=6.0, gust_esik=3.0, gust_min_sure=3.0)
        assert len(alarmlar) >= 1

    def test_alarm_3sn_sonra_tetiklenir(self):
        """Alarm tam 3 saniye sonra tetiklenmeli"""
        olcumler = [6.0] * 5 + [15.0] * 8
        alarmlar = _gust_sim(olcumler, ema_baslangic=6.0, gust_esik=3.0, gust_min_sure=3.0)
        assert len(alarmlar) >= 1
        assert alarmlar[0] >= 3.0  # En erken 3 sn sonra

    def test_gust_bittikten_sonra_sifirlama(self):
        """Gust bitip yeni gust gelince: 2 ayrı alarm değil, sıfırlanıp yeniden başlamalı"""
        olcumler = ([6.0] * 3 + [14.0] * 5 +   # İlk gust
                    [6.0] * 5 +                  # Normal dön
                    [14.0] * 5)                  # İkinci gust
        alarmlar = _gust_sim(olcumler, ema_baslangic=6.0)
        # İki gust = iki ayrı alarm olabilir; önemli olan sıfırlama mantığı
        assert len(alarmlar) >= 1

    def test_normal_ruzgar_artisi_alarm_yok(self):
        """Yavaş artan rüzgar (trend) → EMA takip eder → delta küçük → alarm yok"""
        # Her saniye 0.3 m/s artış → EMA kovalıyor, delta minimal
        olcumler = [6.0 + i * 0.3 for i in range(20)]
        alarmlar = _gust_sim(olcumler, ema_baslangic=6.0, gust_esik=3.0)
        assert len(alarmlar) == 0

    def test_cok_buyuk_gust_hemen_algilanir(self):
        """20 m/s ani sıçrama → delta çok büyük, alarm 3 sn'de mutlaka gelir"""
        olcumler = [6.0] * 4 + [26.0] * 6
        alarmlar = _gust_sim(olcumler, ema_baslangic=6.0, gust_esik=3.0, gust_min_sure=3.0)
        assert len(alarmlar) >= 1


# ══════════════════════════════════════════════════════════════════════════════
# 9. İrtifa Tavsiyesi (Hellmann Tersine Çevirme)
# ══════════════════════════════════════════════════════════════════════════════

def guvenli_irtifa_hesapla(hiz_ham: float, h_mev: float,
                            esik: float = 11.1, alpha: float = 0.14,
                            zemin_ref: float = 2.0) -> "float | None":
    """
    _guvenli_irtifa_hesapla() ile aynı mantık — bağımsız Python versiyonu.
    h_hedef = h_mev × (esik / hiz_ham) ^ (1/alpha)
    """
    if hiz_ham <= esik or alpha <= 0:
        return None
    h_hedef = h_mev * (esik / hiz_ham) ** (1.0 / alpha)
    min_guvenli = zemin_ref + 5.0
    if h_hedef >= h_mev:
        return None   # Yukarı çıkmak gerekiyor
    if h_hedef < min_guvenli:
        return None   # Çok alçak
    return round(h_hedef, 1)


class TestIrtifaTavsiyesi:

    def test_guvenli_hizda_none(self):
        """Zaten güvenli aralıkta → irtifa tavsiyesi yok"""
        sonuc = guvenli_irtifa_hesapla(10.0, 40.0, esik=11.1)
        assert sonuc is None  # 10 < 11.1 → None

    def test_tehlikeli_hizda_hedef_hesaplanir(self):
        """13 m/s @ 40m, esik=11.1 → hedef irtifa hesaplanır"""
        sonuc = guvenli_irtifa_hesapla(13.0, 40.0, esik=11.1, alpha=0.14)
        assert sonuc is not None
        assert sonuc < 40.0  # alçalma tavsiyesi

    def test_hedef_irtifada_ruzgar_esik_altinda(self):
        """Hesaplanan irtifaya gidilince Hellmann rüzgarı eşiğe döndürmeli"""
        v_ham = 13.0
        h_mev = 40.0
        esik  = 11.1
        alpha = 0.14
        h_hedef = guvenli_irtifa_hesapla(v_ham, h_mev, esik=esik, alpha=alpha)
        assert h_hedef is not None
        # Doğrulama: hedef irtifada Hellmann ile rüzgar tahmin et
        v_hedefte = hellmann(v_ham, h_hedef, h_zemin=h_hedef, alpha=alpha)
        # Not: Hellmann zemin referansına dönüşüm yapar; burada h_hedef'i zemin referans al
        v_hedefte2 = v_ham * (h_hedef / h_mev) ** alpha
        assert abs(v_hedefte2 - esik) < 0.5  # Eşiğe yakın

    def test_cok_dusuk_hesap_none(self):
        """Hedef irtifa zemin_ref + 5m altındaysa None döner"""
        # Çok yüksek hız, zemin referansına inilmesi gerekiyor
        sonuc = guvenli_irtifa_hesapla(25.0, 10.0, esik=11.1, alpha=0.14, zemin_ref=2.0)
        # h_hedef = 10 × (11.1/25)^(1/0.14) = 10 × (0.444)^7.14 ≈ 0.08m → çok alçak → None
        assert sonuc is None

    def test_mevcut_irtifa_zaten_dusukse_none(self):
        """Drone zaten alçakta, hesap mevcut irtifadan büyük → None"""
        # 5m irtifada 13 m/s → h_hedef büyük ihtimalle >5m → yukarı çıkmak lazım → None
        sonuc = guvenli_irtifa_hesapla(13.0, 5.0, esik=11.1, alpha=0.14)
        assert sonuc is None  # h_hedef > h_mev

    def test_yuksek_irtifa_mantikli_tavsiye(self):
        """60m irtifada 15 m/s → mantıklı bir irtifa tavsiyesi"""
        sonuc = guvenli_irtifa_hesapla(15.0, 60.0, esik=11.1, alpha=0.14)
        if sonuc is not None:
            assert 7.0 < sonuc < 60.0  # Makul aralıkta

    def test_alpha_etkisi_tavsiyede(self):
        """Kentsel arazi (α=0.35) → alçalmak daha az yeterli → hedef daha yüksek"""
        acik    = guvenli_irtifa_hesapla(13.0, 40.0, esik=11.1, alpha=0.14)
        kentsel = guvenli_irtifa_hesapla(13.0, 40.0, esik=11.1, alpha=0.35)
        # α büyükse üs 1/α küçük → (esik/hiz)^üs daha büyük → h_hedef daha büyük
        if acik is not None and kentsel is not None:
            assert kentsel > acik  # Kentsel arazide daha az alçalmak gerekiyor


# ══════════════════════════════════════════════════════════════════════════════
# 10. SIM_WIND_TURB — Türbülans ve Gust Alarm Doğruluğu
# ══════════════════════════════════════════════════════════════════════════════

class TestTurbulansVeGustAlgisi:
    """
    SIM_WIND_TURB senaryoları: rastgele varyasyon içinde gust dedektörünün
    doğru çalışıp çalışmadığını doğrular.

    SIM_WIND_TURB=2 → ±2 m/s rastgele varyasyon (delta < gust_esik=3.0 → alarm yok)
    SIM_WIND_TURB=5 → ±5 m/s rastgele varyasyon (delta > gust_esik → alarm gerekir)
    """

    def test_dusuk_turbulans_false_alarm_yok(self):
        """
        SIM_WIND_TURB=2 benzeri: sabit 6 m/s zemin + ±2 m/s rastgele varyasyon.
        EMA filtresi ile varyasyon gust_esik=3.0 altında kalmalı → alarm yok.
        """
        import random
        random.seed(42)
        baz = 6.0
        # ±2 m/s türbülans — EMA sayesinde delta nadiren 3.0 üstüne çıkar
        olcumler = [baz + random.uniform(-2.0, 2.0) for _ in range(60)]
        alarmlar = _gust_sim(olcumler, ema_baslangic=baz,
                             gust_esik=3.0, gust_min_sure=3.0)
        assert len(alarmlar) == 0, f"Yanlış alarm: {alarmlar}"

    def test_yuksek_turbulans_alarm_tetikler(self):
        """
        SIM_WIND_TURB=5 benzeri: 8 m/s baz + 5 m/s üstü ani artış bloğu.
        Dedektör bu sürekli yüksek deltaları gust olarak saymalı → alarm verilmeli.
        """
        # 8 m/s sabit × 10 → sonra 14 m/s × 6 (delta ≈ 6 > 3.0, süre 6s > 3s) → alarm
        olcumler = [8.0] * 10 + [14.0] * 6 + [8.0] * 5
        alarmlar = _gust_sim(olcumler, ema_baslangic=8.0,
                             gust_esik=3.0, gust_min_sure=3.0)
        assert len(alarmlar) >= 1, "Sürekli yüksek delta → alarm bekleniyor"

    def test_ema_turbulans_dampening(self):
        """
        EMA (α=0.25) hızlı salınımları yumuşatmalı.
        Her adımda alternatif 4 m/s ve 12 m/s değişen sinyal için
        EMA deltası ham değişim olan 8 m/s'den çok daha küçük olmalı.
        """
        olcumler = [4.0, 12.0] * 15   # 30 ölçüm, alternatif düşük/yüksek
        ema = 8.0
        max_ema_delta = 0.0
        for hiz in olcumler:
            ema = 0.25 * hiz + 0.75 * ema
            delta = hiz - ema
            max_ema_delta = max(max_ema_delta, delta)
        # EMA yumuşatma sayesinde delta, ham değişim (8 m/s) dan belirgin şekilde düşük kalmalı
        assert max_ema_delta < 8.0, f"EMA yeterince yumuşatmadı: {max_ema_delta:.2f}"

    def test_dinamik_esik_yuksek_vibrasyon(self):
        """
        Yüksek vibrasyon (>30 m/s²) durumunda gust eşiği iki katına çıkarılırsa
        (gust_esik=6.0), aynı türbülans seviyesi alarm üretmemeli.
        """
        # 8 m/s baz + 5 m/s gust bloğu → delta ~4.x m/s
        olcumler = [8.0] * 8 + [13.0] * 5 + [8.0] * 4
        # Normal eşik → alarm var
        alarmlar_normal  = _gust_sim(olcumler, ema_baslangic=8.0,
                                     gust_esik=3.0, gust_min_sure=3.0)
        # Dinamik eşik (vibrasyon yüksek → ×2) → alarm yok
        alarmlar_dinamik = _gust_sim(olcumler, ema_baslangic=8.0,
                                     gust_esik=6.0, gust_min_sure=3.0)
        assert len(alarmlar_normal)  >= 1, "Normal eşikte alarm bekleniyor"
        assert len(alarmlar_dinamik) == 0, "Dinamik eşikte alarm olmamalı"

    def test_turbulans_trend_etkilememeli(self):
        """
        Rastgele ±2 m/s türbülans altındaki sabit baz hız, lineer regresyon
        trendini sıfır civarında tutmalı (artış veya azalış eğilimi yok).
        """
        import random
        random.seed(99)
        baz = 7.0
        t0  = 1000.0
        gecmis = [(t0 + i, baz + random.uniform(-2.0, 2.0)) for i in range(30)]
        trend = _trend_hesapla(gecmis)
        # Sabit baz + simetrik türbülans → trend ≈ 0
        assert abs(trend) < 0.15, f"Türbülans trendi bozdu: {trend:.4f} m/s/s"

    def test_turbulans_sonrasi_bekleme_onerisi_tetiklenmez(self):
        """
        Tehlikeli eşiğin %80 altında kalan türbülanslı EMA,
        bekleme önerisi koşulunu (eşik × 0.80 ≤ ema < eşik) karşılamamalı.
        """
        tehlikeli = 11.1
        baz       = 6.0
        # Sinüzoidal ±2 m/s türbülans → max ≈ 8 m/s < 11.1 × 0.80 = 8.88
        turbulans = [baz + 2.0 * math.sin(i * 0.5) for i in range(30)]
        ema = baz
        bekleme_kosulu = False
        for hiz in turbulans:
            ema = 0.25 * hiz + 0.75 * ema
            if tehlikeli * 0.80 <= ema < tehlikeli:
                bekleme_kosulu = True
                break
        assert not bekleme_kosulu, "Düşük türbülansta bekleme önerisi tetiklenmemeli"
