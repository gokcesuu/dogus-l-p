"""
ucus_raporu.py
Doğuş Üniversitesi LÖP – Uçuş Sonrası Otomatik Türkçe Rapor

Uçuş sırasında veri kaydeder, iniş sonrası analiz yapıp rapor üretir.

Kullanım (GCS'den):
    from ucus_raporu import UcusKaydedici
    kayit = UcusKaydedici()
    kayit.baslat()
    # uçuş sırasında her saniye:
    kayit.veri_ekle(telemetri_dict)
    # iniş sonrası:
    rapor_yolu = kayit.rapor_olustur()
"""

import os
import json
import math
import time
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional


# ── Eşikler ───────────────────────────────────────────────────────────────────

BATARYA_KRITIK_YDZ   = 15     # %
BATARYA_DUSUK_YDZ    = 25     # %
IMU_SICAKLIK_YUKSEK  = 65.0   # °C
TITRESIM_ESIK        = 2.5    # m/s² (ham IMU değeri normalize edilmiş)
RUZGAR_TEHLIKELI_KMH = 40.0
GPS_KAYIP_ESIK_SN    = 5.0    # saniye


# ── Telemetri anlık kaydı ─────────────────────────────────────────────────────

@dataclass
class AnlikVeri:
    zaman:      float   # time.time()
    irtifa:     float   = 0.0
    hiz:        float   = 0.0
    dikey_hiz:  float   = 0.0
    lat:        float   = 0.0
    lon:        float   = 0.0
    batarya_v:  float   = 0.0
    batarya_a:  float   = 0.0
    batarya_yuzde: int  = -1
    ruzgar_ms:  float   = 0.0
    imu0_c:     float   = 0.0
    imu1_c:     float   = 0.0
    imu2_c:     float   = 0.0
    gps_fix:    int     = 0
    gps_uydu:   int     = 0
    ekf_hata:   float   = 0.0
    mod_id:     int     = 0


# ── Kaydedici ─────────────────────────────────────────────────────────────────

class UcusKaydedici:
    """
    Uçuş sırasında telemetri verisi toplar.
    iniş sonrası rapor_olustur() ile Türkçe metin rapor üretir.
    """

    def __init__(self, kayit_klasoru: str = None):
        self._klasor = kayit_klasoru or os.path.join(
            os.path.expanduser("~"), ".dogus_gcs", "ucus_kayitlari"
        )
        os.makedirs(self._klasor, exist_ok=True)
        self._veriler: list[AnlikVeri] = []
        self._baslangic: Optional[float] = None
        self._aktif = False

    def baslat(self):
        self._veriler = []
        self._baslangic = time.time()
        self._aktif = True

    def durdur(self):
        self._aktif = False

    def veri_ekle(self, t: dict):
        """GCS'den her saniye çağrılır. t = telemetri sözlüğü."""
        if not self._aktif:
            return
        self._veriler.append(AnlikVeri(
            zaman       = time.time(),
            irtifa      = t.get("irtifa", 0.0),
            hiz         = t.get("hiz", 0.0),
            dikey_hiz   = t.get("dikey_hiz", 0.0),
            lat         = t.get("lat", 0.0),
            lon         = t.get("lon", 0.0),
            batarya_v   = t.get("batarya_v", 0.0),
            batarya_a   = t.get("batarya_a", 0.0),
            batarya_yuzde = t.get("batarya_yuzde", -1),
            ruzgar_ms   = t.get("ruzgar_ms", 0.0),
            imu0_c      = t.get("imu0_c", 0.0),
            imu1_c      = t.get("imu1_c", 0.0),
            imu2_c      = t.get("imu2_c", 0.0),
            gps_fix     = t.get("gps_fix", 0),
            gps_uydu    = t.get("gps_uydu", 0),
            ekf_hata    = t.get("ekf_hata", 0.0),
            mod_id      = t.get("mod_id", 0),
        ))

    # ── Rapor ─────────────────────────────────────────────────────────────────

    def rapor_olustur(self) -> str:
        """Analiz yapar, .txt rapor dosyası oluşturur ve yolunu döndürür."""
        if not self._veriler:
            return ""

        analiz = self._analiz_et()
        rapor_metni = self._metin_olustur(analiz)

        zaman_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        dosya = os.path.join(self._klasor, f"ucus_{zaman_str}.txt")
        with open(dosya, "w", encoding="utf-8") as f:
            f.write(rapor_metni)

        # JSON ham veri de kaydet
        json_dosya = os.path.join(self._klasor, f"ucus_{zaman_str}.json")
        with open(json_dosya, "w", encoding="utf-8") as f:
            json.dump([asdict(v) for v in self._veriler], f, ensure_ascii=False, indent=2)

        return dosya

    # ── İç analiz ─────────────────────────────────────────────────────────────

    def _analiz_et(self) -> dict:
        v = self._veriler
        sure_sn = v[-1].zaman - v[0].zaman if len(v) > 1 else 0

        # Batarya
        bat_baslangic  = next((x.batarya_yuzde for x in v if x.batarya_yuzde >= 0), -1)
        bat_bitis      = next((x.batarya_yuzde for x in reversed(v) if x.batarya_yuzde >= 0), -1)
        bat_min_v      = min((x.batarya_v for x in v if x.batarya_v > 0), default=0)
        bat_max_a      = max((x.batarya_a for x in v), default=0)
        kritik_bat     = any(0 <= x.batarya_yuzde <= BATARYA_KRITIK_YDZ for x in v)
        dusuk_bat      = any(0 <= x.batarya_yuzde <= BATARYA_DUSUK_YDZ for x in v)

        # IMU sıcaklık
        imu_max = [
            max((x.imu0_c for x in v), default=0),
            max((x.imu1_c for x in v), default=0),
            max((x.imu2_c for x in v), default=0),
        ]
        imu_asiri = [t > IMU_SICAKLIK_YUKSEK for t in imu_max]

        # GPS
        gps_kayip_sayisi = sum(1 for x in v if x.gps_fix < 3)
        gps_min_uydu     = min((x.gps_uydu for x in v), default=0)

        # Rüzgar
        ruzgar_max_kmh = max((x.ruzgar_ms * 3.6 for x in v), default=0)
        tehlikeli_ruzgar = ruzgar_max_kmh >= RUZGAR_TEHLIKELI_KMH

        # EKF
        ekf_max = max((x.ekf_hata for x in v), default=0)

        # İrtifa
        irtifa_max = max((x.irtifa for x in v), default=0)
        hiz_max    = max((x.hiz for x in v), default=0)

        # Kat edilen mesafe (haversine toplamı)
        mesafe_m = 0.0
        for i in range(1, len(v)):
            mesafe_m += self._haversine(v[i-1].lat, v[i-1].lon, v[i].lat, v[i].lon)

        return {
            "sure_sn":         sure_sn,
            "mesafe_m":        mesafe_m,
            "irtifa_max":      irtifa_max,
            "hiz_max":         hiz_max,
            "bat_baslangic":   bat_baslangic,
            "bat_bitis":       bat_bitis,
            "bat_min_v":       bat_min_v,
            "bat_max_a":       bat_max_a,
            "kritik_bat":      kritik_bat,
            "dusuk_bat":       dusuk_bat,
            "imu_max":         imu_max,
            "imu_asiri":       imu_asiri,
            "gps_kayip_sayisi": gps_kayip_sayisi,
            "gps_min_uydu":    gps_min_uydu,
            "ruzgar_max_kmh":  ruzgar_max_kmh,
            "tehlikeli_ruzgar": tehlikeli_ruzgar,
            "ekf_max":         ekf_max,
            "veri_sayisi":     len(v),
        }

    def _metin_olustur(self, a: dict) -> str:
        sure_dk = a["sure_sn"] / 60
        sure_str = f"{int(sure_dk)}dk {int(a['sure_sn'] % 60)}sn"
        tarih_str = datetime.now().strftime("%d.%m.%Y %H:%M")

        satirlar = [
            "=" * 60,
            "  DOĞUŞ ÜNİVERSİTESİ LÖP – UÇUŞ SONRASI RAPORU",
            "=" * 60,
            f"  Tarih          : {tarih_str}",
            f"  Uçuş Süresi    : {sure_str}",
            f"  Kat Edilen Yol : {a['mesafe_m']:.0f} m",
            f"  Max İrtifa     : {a['irtifa_max']:.1f} m",
            f"  Max Hız        : {a['hiz_max']:.1f} m/s",
            f"  Veri Noktası   : {a['veri_sayisi']}",
            "",
            "── BATARYA ──────────────────────────────────────────",
        ]

        if a["bat_baslangic"] >= 0:
            satirlar += [
                f"  Başlangıç      : %{a['bat_baslangic']}",
                f"  Bitiş          : %{a['bat_bitis']}",
                f"  Min Voltaj     : {a['bat_min_v']:.2f} V",
                f"  Max Akım       : {a['bat_max_a']:.1f} A",
            ]
        if a["kritik_bat"]:
            satirlar.append(f"  ⚠  UYARI: Batarya kritik seviyeye (%{BATARYA_KRITIK_YDZ}) düştü!")
        elif a["dusuk_bat"]:
            satirlar.append(f"  ⚠  BİLGİ: Batarya düşük seviyeye (%{BATARYA_DUSUK_YDZ}) geriledi.")
        else:
            satirlar.append("  ✓  Batarya normal seviyelerde kaldı.")

        satirlar += [
            "",
            "── IMU SICAKLIKLARI ─────────────────────────────────",
        ]
        for i, (maks, asiri) in enumerate(zip(a["imu_max"], a["imu_asiri"])):
            durum = f"⚠  AŞIRI ({maks:.1f}°C > {IMU_SICAKLIK_YUKSEK}°C)" if asiri else f"✓  Normal ({maks:.1f}°C)"
            satirlar.append(f"  IMU {i}           : {durum}")

        satirlar += [
            "",
            "── GPS ──────────────────────────────────────────────",
            f"  Min Uydu Sayısı: {a['gps_min_uydu']}",
        ]
        if a["gps_kayip_sayisi"] > 0:
            satirlar.append(f"  ⚠  UYARI: {a['gps_kayip_sayisi']} kez GPS fix kaybı (fix < 3D).")
        else:
            satirlar.append("  ✓  GPS bağlantısı kesintisiz.")

        satirlar += [
            "",
            "── RÜZGAR ───────────────────────────────────────────",
            f"  Max Rüzgar     : {a['ruzgar_max_kmh']:.1f} km/s",
        ]
        if a["tehlikeli_ruzgar"]:
            satirlar.append(f"  ⚠  UYARI: Rüzgar {RUZGAR_TEHLIKELI_KMH:.0f} km/s eşiğini aştı!")
        else:
            satirlar.append("  ✓  Rüzgar güvenli sınırlar içinde kaldı.")

        satirlar += [
            "",
            "── EKF ──────────────────────────────────────────────",
        ]
        if a["ekf_max"] > 0.5:
            satirlar.append(f"  ⚠  UYARI: EKF hata puanı yüksek ({a['ekf_max']:.2f}). İMU kalibrasyonu önerilir.")
        else:
            satirlar.append(f"  ✓  EKF sağlıklı ({a['ekf_max']:.2f}).")

        # Genel değerlendirme
        uyari_sayisi = sum([
            a["kritik_bat"], a["gps_kayip_sayisi"] > 0,
            any(a["imu_asiri"]), a["tehlikeli_ruzgar"], a["ekf_max"] > 0.5
        ])
        satirlar += [
            "",
            "── GENEL DEĞERLENDİRME ──────────────────────────────",
        ]
        if uyari_sayisi == 0:
            satirlar.append("  ✓  Uçuş sorunsuz tamamlandı. Anormal durum tespit edilmedi.")
        elif uyari_sayisi <= 2:
            satirlar.append(f"  ⚠  {uyari_sayisi} uyarı tespit edildi. İnceleme önerilir.")
        else:
            satirlar.append(f"  ✗  {uyari_sayisi} kritik uyarı! Bir sonraki uçuştan önce bakım yapın.")

        satirlar += ["", "=" * 60, ""]
        return "\n".join(satirlar)

    @staticmethod
    def _haversine(lat1, lon1, lat2, lon2) -> float:
        if lat1 == 0 or lat2 == 0:
            return 0.0
        R = 6371000
        f1, f2 = math.radians(lat1), math.radians(lat2)
        df = math.radians(lat2 - lat1)
        dl = math.radians(lon2 - lon1)
        a = math.sin(df/2)**2 + math.cos(f1)*math.cos(f2)*math.sin(dl/2)**2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
