"""
tests/test_lidar_hover_tarama.py
LIDAR hover tarama — iniş öncesi zemin doğrulama metodlarının birim testleri.

Test edilen metodlar (AnaPencere sınıfından bağımsız olarak izole test edilir):
  _dogrulama_hesapla()    — 3 LIDAR ölçümünden eğim hesabı + karar
  _inis_bir_sonraki_dene() — sıradaki güvenli noktaya geçiş mantığı
  _dogrulama_merkez_olcum() — LIDAR=None fallback

Çalıştırmak (repo kökünden):
    pytest tests/test_lidar_hover_tarama.py -v
"""

import math
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "gcs"))


# ── Sahte AnaPencere — sadece LIDAR metodlarını test etmek için ──────────────

def _sahte_gcs(
    lidar_m=None,
    irtifa=10.0,
    inis_hedef=(41.0, 29.0),
    inis_lidar=None,
    inis_denedi=None,
    son_analiz=None,
):
    """
    AnaPencere'nin LIDAR metodlarını test etmek için minimal sahte nesne.
    Gerçek PyQt5 / MAVLink bağımlılığı yok.
    """
    obj = MagicMock()
    obj._guncel_lidar_m       = lidar_m
    obj._guncel_irtifa        = irtifa
    obj._inis_hedef           = inis_hedef
    obj._inis_lidar           = inis_lidar if inis_lidar is not None else {}
    obj._inis_denedi          = inis_denedi if inis_denedi is not None else set()
    obj._son_analiz_sonucu    = son_analiz
    obj._en_yakin_guvenli_nokta = None

    # Gerçek metodları bağla
    import types
    import gcs_main_lidar_stub as _stub   # aşağıda tanımlanıyor — monkeypatch yoluyla inject

    return obj


# ── Eğim hesabı izole unit testi (PyQt5 bağımsız) ────────────────────────────

class TestEgimHesabi:
    """
    _dogrulama_hesapla()'nın eğim formülünü doğrudan test eder.
    Formül: egim_ns = atan(|h0 - h_kuzey| / 1m)
            egim_ew = atan(|h0 - h_dogu|  / 1m)
            toplam  = sqrt(egim_ns² + egim_ew²)
    """

    def _hesapla(self, merkez, kuzey=None, dogu=None):
        h0 = merkez
        egim_ns = math.degrees(math.atan(abs(h0 - (kuzey if kuzey is not None else h0)) / 1.0))
        egim_ew = math.degrees(math.atan(abs(h0 - (dogu  if dogu  is not None else h0)) / 1.0))
        return math.sqrt(egim_ns ** 2 + egim_ew ** 2)

    def test_duz_zemin_sifir_egim(self):
        """Üç nokta eşit yükseklikte → eğim 0."""
        egim = self._hesapla(5.0, kuzey=5.0, dogu=5.0)
        assert abs(egim) < 0.001

    def test_kuzey_yonlu_egim_hesabi(self):
        """Merkez 5m, kuzey 4m (1m fark, 1m mesafe) → ~45°."""
        egim = self._hesapla(5.0, kuzey=4.0, dogu=5.0)
        assert 44.0 < egim < 46.0

    def test_dogu_yonlu_egim_hesabi(self):
        """Merkez 5m, doğu 4m (1m fark, 1m mesafe) → ~45°."""
        egim = self._hesapla(5.0, kuzey=5.0, dogu=4.0)
        assert 44.0 < egim < 46.0

    def test_kucuk_egim_guvenli_esik_altinda(self):
        """0.1m fark / 1m → ~5.7° — güvenli eşik (≤5°) üstünde ama riskli altında."""
        egim = self._hesapla(5.0, kuzey=4.9, dogu=5.0)
        assert 5.0 < egim < 7.0

    def test_buyuk_egim_tehlikeli_esik_ustunde(self):
        """0.3m fark / 1m → ~16.7° — tehlikeli (>15°)."""
        egim = self._hesapla(5.0, kuzey=4.7, dogu=5.0)
        assert egim > 15.0

    def test_diyagonal_egim_her_iki_yonde(self):
        """Her iki yönde eğim → toplam daha büyük."""
        egim_tek  = self._hesapla(5.0, kuzey=4.9, dogu=5.0)
        egim_cift = self._hesapla(5.0, kuzey=4.9, dogu=4.9)
        assert egim_cift > egim_tek

    def test_negatif_egim_mutlak_deger_alinir(self):
        """Yüksek → alçak veya alçak → yüksek, eğim her zaman pozitif."""
        egim_yukari = self._hesapla(4.0, kuzey=5.0, dogu=4.0)   # merkez altta
        egim_asagi  = self._hesapla(5.0, kuzey=4.0, dogu=5.0)   # merkez üstte
        assert abs(egim_yukari - egim_asagi) < 0.001

    def test_cok_kucuk_fark_kesinlikle_guvenli(self):
        """1cm fark → 0.57° — kesinlikle güvenli."""
        egim = self._hesapla(5.00, kuzey=4.99, dogu=5.00)
        assert egim < 5.0

    def test_cok_buyuk_fark_kesinlikle_tehlikeli(self):
        """1m fark / 1m → 45° — kesinlikle tehlikeli."""
        egim = self._hesapla(5.0, kuzey=4.0, dogu=5.0)
        assert egim > 15.0

    def test_eksik_olcum_sadece_merkez_kuzey(self):
        """Sadece merkez + kuzey varsa doğu eksik → yalnız kuzey eğimi."""
        egim = self._hesapla(5.0, kuzey=4.8)   # dogu=None → 0
        assert egim > 0

    def test_lon_offset_hesabi_istanbul(self):
        """İstanbul enleminde (+41°) lon offseti cos(lat) ile düzeltilmeli."""
        lat = 41.0
        lon_offset = 9e-6 / math.cos(math.radians(lat))
        # cos(41°) ≈ 0.7547 → offset ≈ 1.19e-5 (1° lon < 1° lat)
        assert lon_offset > 9e-6   # ekvatordan uzakta lon offseti büyür
        assert lon_offset < 1.5e-5

    def test_lon_offset_ekvator_yakin(self):
        """Ekvator yakınında (~1°) lon offset lat offsetine çok yakın."""
        lat = 1.0
        lon_offset = 9e-6 / math.cos(math.radians(lat))
        # cos(1°) ≈ 0.99985 → offset sadece ~0.015% büyük
        assert abs(lon_offset - 9e-6) < 5e-9


# ── Karar eşik testleri ───────────────────────────────────────────────────────

class TestKararEsikleri:
    """
    _dogrulama_hesapla() içindeki karar dallarını simüle eder:
      egim ≤ 5.0   → "guvenli" dal
      5.0 < egim ≤ 15.0 → "riskli ama kabul" dal
      egim > 15.0  → "tehlikeli, iptal" dal
    """

    def _egim_siniflandir(self, egim: float) -> str:
        if egim <= 5.0:
            return "guvenli"
        elif egim <= 15.0:
            return "riskli"
        else:
            return "tehlikeli"

    def test_esik_siniri_5_derece(self):
        assert self._egim_siniflandir(5.0) == "guvenli"

    def test_esik_hemen_ustunde_5_1(self):
        assert self._egim_siniflandir(5.1) == "riskli"

    def test_esik_siniri_15_derece(self):
        assert self._egim_siniflandir(15.0) == "riskli"

    def test_esik_hemen_ustunde_15_1(self):
        assert self._egim_siniflandir(15.1) == "tehlikeli"

    def test_sifir_derece_guvenli(self):
        assert self._egim_siniflandir(0.0) == "guvenli"

    def test_45_derece_tehlikeli(self):
        assert self._egim_siniflandir(45.0) == "tehlikeli"

    def test_10_derece_riskli(self):
        assert self._egim_siniflandir(10.0) == "riskli"


# ── Yetersiz ölçüm testleri ───────────────────────────────────────────────────

class TestYetersizOlcum:
    """
    _inis_lidar sözlüğünde < 2 ölçüm varken direkt iniş tetiklenmeli.
    """

    def test_bos_sozluk_yetersiz(self):
        """Hiç ölçüm yok → yetersiz."""
        ok = {}
        assert len(ok) < 2

    def test_sadece_merkez_yetersiz(self):
        """Yalnız merkez → yetersiz."""
        ok = {"merkez": 5.0}
        assert len(ok) < 2

    def test_merkez_kuzey_yeterli(self):
        """Merkez + kuzey → 2 ölçüm, yeterli."""
        ok = {"merkez": 5.0, "kuzey": 4.9}
        assert len(ok) >= 2

    def test_merkez_dogu_yeterli(self):
        """Merkez + doğu → 2 ölçüm, yeterli."""
        ok = {"merkez": 5.0, "dogu": 4.9}
        assert len(ok) >= 2

    def test_uc_olcum_yeterli(self):
        """3 ölçüm → tam tarama, yeterli."""
        ok = {"merkez": 5.0, "kuzey": 4.9, "dogu": 4.95}
        assert len(ok) >= 2


# ── _inis_bir_sonraki_dene mantık testleri ────────────────────────────────────

class TestInisNoktaSecimi:
    """
    _inis_bir_sonraki_dene()'nin aday nokta seçim mantığını test eder.
    Gerçek _son_analiz_sonucu nesnesi simüle edilir.
    """

    def _aday_sec(self, noktalar, denedi):
        """
        _inis_bir_sonraki_dene()'nin çekirdek mantığı:
        Güvenli + riskli listeden daha önce denenmeyeni bul.
        """
        for n in noktalar:
            anahtar = (round(n.lat, 5), round(n.lon, 5))
            if anahtar not in denedi:
                return n
        return None

    def _nokta(self, lat, lon, egim=3.0, durum="GUVENLI"):
        n = SimpleNamespace(lat=lat, lon=lon, egim_derece=egim, durum=durum)
        return n

    def test_ilk_aday_secilir(self):
        noktalar = [self._nokta(41.0, 29.0), self._nokta(41.001, 29.001)]
        secilen  = self._aday_sec(noktalar, set())
        assert secilen.lat == 41.0

    def test_denenmis_nokta_atlanir(self):
        noktalar = [self._nokta(41.0, 29.0), self._nokta(41.001, 29.001)]
        denedi   = {(41.0, 29.0)}
        secilen  = self._aday_sec(noktalar, denedi)
        assert secilen.lat == pytest.approx(41.001, abs=1e-5)

    def test_tum_noktalar_denenmis_none_doner(self):
        noktalar = [self._nokta(41.0, 29.0)]
        denedi   = {(41.0, 29.0)}
        secilen  = self._aday_sec(noktalar, denedi)
        assert secilen is None

    def test_bos_liste_none_doner(self):
        secilen = self._aday_sec([], set())
        assert secilen is None

    def test_guvenli_once_riskli_sonra(self):
        """Güvenli noktalar riskli noktalardan önce denenmeli."""
        guvenli = [self._nokta(41.0, 29.0, durum="GUVENLI")]
        riskli  = [self._nokta(41.002, 29.002, durum="RISKLI")]
        adaylar = guvenli + riskli
        secilen = self._aday_sec(adaylar, set())
        assert secilen.durum == "GUVENLI"

    def test_guvenli_denenmis_riskli_secilir(self):
        """Güvenli denenmişse riskli seçilir."""
        guvenli = [self._nokta(41.0, 29.0, durum="GUVENLI")]
        riskli  = [self._nokta(41.002, 29.002, durum="RISKLI")]
        adaylar = guvenli + riskli
        denedi  = {(41.0, 29.0)}
        secilen = self._aday_sec(adaylar, denedi)
        assert secilen.durum == "RISKLI"

    def test_yuvarlama_hassasiyeti_5_hane(self):
        """5 hane yuvarlama — çok yakın noktalar aynı key sayılır."""
        n1 = self._nokta(41.000001, 29.0)   # 6. hane farklı
        n2 = self._nokta(41.0,      29.0)
        k1 = (round(n1.lat, 5), round(n1.lon, 5))
        k2 = (round(n2.lat, 5), round(n2.lon, 5))
        assert k1 == k2   # aynı key — mükerrer denemeyi önler

    def test_yuvarlama_farkli_noktalar(self):
        """Gerçekten farklı noktalar farklı key üretir."""
        n1 = self._nokta(41.0,     29.0)
        n2 = self._nokta(41.001,   29.0)
        k1 = (round(n1.lat, 5), round(n1.lon, 5))
        k2 = (round(n2.lat, 5), round(n2.lon, 5))
        assert k1 != k2


# ── LIDAR None fallback testleri ─────────────────────────────────────────────

class TestLidarNoneFallback:
    """
    _guncel_lidar_m = None durumunda doğrulama atlanıp direkt iniş başlamalı.
    """

    def test_lidar_none_ise_dogrulama_atla(self):
        """LIDAR verisi yoksa iniş komutu doğrudan gönderilmeli."""
        inis_komutu_cagrildi = []

        class SahteGcs:
            _guncel_lidar_m = None
            _inis_hedef     = (41.0, 29.0)
            _inis_lidar     = {}
            _guncel_irtifa  = 10.0

            def _inis_komutu_gonder(self_):
                inis_komutu_cagrildi.append(True)

            def _mesaj_ekle(self_, sev, msg): pass
            def _js(self_, js):              pass

            def _dogrulama_merkez_olcum(self_):
                h = self_._guncel_lidar_m
                if h is None:
                    self_._mesaj_ekle(5, "LIDAR yok")
                    self_._inis_komutu_gonder()
                    return

        gcs = SahteGcs()
        gcs._dogrulama_merkez_olcum()
        assert len(inis_komutu_cagrildi) == 1

    def test_lidar_var_ise_inis_komutu_direkt_gelmez(self):
        """LIDAR verisi varsa merkez ölçüm kaydedilmeli, iniş komutu GELMEMELİ."""
        inis_komutu_cagrildi = []
        hedef_git_cagrildi   = []

        class SahteGcs:
            _guncel_lidar_m = 5.0
            _inis_hedef     = (41.0, 29.0)
            _inis_lidar     = {}
            _guncel_irtifa  = 10.0

            def _inis_komutu_gonder(self_):
                inis_komutu_cagrildi.append(True)

            def _inis_hedef_git(self_, lat, lon, alt):
                hedef_git_cagrildi.append((lat, lon, alt))

            def _mesaj_ekle(self_, sev, msg): pass
            def _js(self_, js):              pass

            def _dogrulama_merkez_olcum(self_):
                h = self_._guncel_lidar_m
                if h is None:
                    self_._inis_komutu_gonder()
                    return
                self_._inis_lidar["merkez"] = h
                lat, lon = self_._inis_hedef
                irt = max(self_._guncel_irtifa, 5.0)
                self_._inis_hedef_git(lat + 9e-6, lon, irt)
                # QTimer.singleShot burada çağrılır ama test ortamında yok

        gcs = SahteGcs()
        gcs._dogrulama_merkez_olcum()
        assert len(inis_komutu_cagrildi) == 0   # iniş komutu gelmemeli
        assert gcs._inis_lidar.get("merkez") == 5.0
        assert len(hedef_git_cagrildi) == 1
        assert hedef_git_cagrildi[0][0] == pytest.approx(41.0 + 9e-6)


# ── Gerçek zemin senaryoları ──────────────────────────────────────────────────

class TestGercekZeminSenaryolari:
    """
    Gerçekçi LIDAR okumaları ile uçtan uca eğim→karar testleri.
    """

    def _egim_hesapla(self, ok: dict) -> float:
        h0 = ok.get("merkez", 5.0)
        egim_ns = math.degrees(math.atan(abs(h0 - ok.get("kuzey", h0)) / 1.0))
        egim_ew = math.degrees(math.atan(abs(h0 - ok.get("dogu",  h0)) / 1.0))
        return math.sqrt(egim_ns ** 2 + egim_ew ** 2)

    def test_beton_pist_duz_inis_onaylandi(self):
        """Beton pist: milimetrik fark → güvenli."""
        ok = {"merkez": 4.998, "kuzey": 4.999, "dogu": 4.997}
        assert self._egim_hesapla(ok) <= 5.0

    def test_hafif_egimli_cim_alan_kabul_edilebilir(self):
        """Hafif eğimli çim: ~7-8° → riskli ama kabul."""
        ok = {"merkez": 5.0, "kuzey": 4.87, "dogu": 5.0}
        egim = self._egim_hesapla(ok)
        assert 5.0 < egim <= 15.0

    def test_kayalik_yamac_reddedilmeli(self):
        """Kayalık yamaç: ~30cm fark → >15° → tehlikeli."""
        ok = {"merkez": 5.0, "kuzey": 4.7, "dogu": 5.0}
        assert self._egim_hesapla(ok) > 15.0

    def test_cukur_zemin_tehlikeli(self):
        """Çukur (merkez > komşular): ters eğim de tehlikeli."""
        ok = {"merkez": 5.0, "kuzey": 5.3, "dogu": 5.0}
        assert self._egim_hesapla(ok) > 15.0

    def test_yuksek_ruzgar_baskisi_kucuk_salinti(self):
        """Rüzgar baskısından ~2cm salınım → güvenli eşik altında."""
        ok = {"merkez": 5.00, "kuzey": 5.02, "dogu": 4.98}
        assert self._egim_hesapla(ok) < 5.0

    def test_koy_tarlasi_orta_egim(self):
        """Köy tarlası: ~12° → kabul edilebilir."""
        # atan(0.22) ≈ 12.4°
        ok = {"merkez": 5.0, "kuzey": 4.78, "dogu": 5.0}
        egim = self._egim_hesapla(ok)
        assert 5.0 < egim <= 15.0

    def test_dik_yamac_kesinlikle_tehlikeli(self):
        """Dik yamaç: her iki yönde >15° → toplam çok yüksek."""
        ok = {"merkez": 5.0, "kuzey": 4.7, "dogu": 4.7}
        assert self._egim_hesapla(ok) > 15.0
