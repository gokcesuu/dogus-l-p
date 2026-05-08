"""
ucus_raporlayici.py
Doğuş Üniversitesi LÖP – Uçuş Verisi Analiz ve Raporlama

ArduPilot'un ürettiği .bin (DataFlash) veya .tlog (MAVLink telemetri)
dosyalarını okuyarak otomatik Türkçe analiz raporu üretir.

Kullanım:
    python ucus_raporlayici.py ucus.bin
    python ucus_raporlayici.py ucus.tlog
    python ucus_raporlayici.py  # son .bin dosyasını otomatik bulur

Bağımlılık:
    pip install pymavlink
"""

import os
import sys
import math
import argparse
from datetime import datetime, timezone
from collections import defaultdict

try:
    from pymavlink import mavutil, DFReader
    PYMAVLINK_MEVCUT = True
except ImportError:
    PYMAVLINK_MEVCUT = False


# ── Eşikler ───────────────────────────────────────────────────────────────────

BAT_KRITIK_YDZ      = 15
BAT_DUSUK_YDZ       = 25
BAT_MIN_HUCRE_V     = 3.3   # 4S için
HUCRE_SAYISI        = 4
RUZGAR_TEHLIKELI    = 11.1  # m/s (~40 km/s)
IMU_SICAK_ESIK      = 65.0  # °C
GPS_KAYIP_FIX       = 3     # fix < 3 → kayıp
EKF_HATA_ESIK       = 0.8
TITRESIM_ESIK       = 30.0  # IMU ham değer farkı (normalleştirilmemiş)


# ── Ana analiz sınıfı ─────────────────────────────────────────────────────────

class UcusAnalizcisi:

    def __init__(self, dosya_yolu: str):
        self.dosya = dosya_yolu
        self.uzanti = os.path.splitext(dosya_yolu)[1].lower()
        self._veri: dict = defaultdict(list)

    def analiz_et(self) -> str:
        """Dosyayı okur, analiz yapar, Türkçe rapor metni döndürür."""
        if not PYMAVLINK_MEVCUT:
            return "HATA: pymavlink kurulu değil. pip install pymavlink"

        if not os.path.exists(self.dosya):
            return f"HATA: Dosya bulunamadı: {self.dosya}"

        if self.uzanti == ".bin":
            self._bin_oku()
        elif self.uzanti in (".tlog", ".log"):
            self._tlog_oku()
        else:
            return f"HATA: Desteklenmeyen format: {self.uzanti} (.bin veya .tlog olmalı)"

        return self._rapor_olustur()

    # ── .bin okuyucu (DataFlash) ──────────────────────────────────────────────

    def _bin_oku(self):
        mlog = DFReader.DFReader_binary(self.dosya, zero_time_base=True)
        while True:
            msg = mlog.recv_msg()
            if msg is None:
                break
            tip = msg.get_type()

            if tip == "BATT":
                self._veri["bat_volt"].append(getattr(msg, "Volt", 0))
                self._veri["bat_curr"].append(getattr(msg, "Curr", 0))
                self._veri["bat_pct"].append(getattr(msg, "CurrTot", -1))
                self._veri["bat_zaman"].append(msg._timestamp)

            elif tip == "GPS":
                self._veri["gps_fix"].append(getattr(msg, "Status", 0))
                self._veri["gps_uydu"].append(getattr(msg, "NSats", 0))
                self._veri["gps_lat"].append(getattr(msg, "Lat", 0))
                self._veri["gps_lon"].append(getattr(msg, "Lng", 0))
                self._veri["gps_spd"].append(getattr(msg, "Spd", 0))
                self._veri["gps_zaman"].append(msg._timestamp)

            elif tip == "IMU":
                ax = getattr(msg, "AccX", 0)
                ay = getattr(msg, "AccY", 0)
                az = getattr(msg, "AccZ", 0)
                self._veri["imu_acc"].append(math.sqrt(ax**2 + ay**2 + az**2))

            elif tip in ("IMT", "IMT2"):
                self._veri["imu_sicak"].append(getattr(msg, "Temp", 0))

            elif tip == "ARSP":
                self._veri["ruzgar"].append(getattr(msg, "Airspeed", 0))

            elif tip == "ATT":
                self._veri["roll"].append(getattr(msg, "Roll", 0))
                self._veri["pitch"].append(getattr(msg, "Pitch", 0))

            elif tip == "BARO":
                self._veri["irtifa"].append(getattr(msg, "Alt", 0))

            elif tip == "EKF1":
                self._veri["ekf_vel_var"].append(
                    abs(getattr(msg, "VN", 0)) + abs(getattr(msg, "VE", 0))
                )

            elif tip == "MODE":
                self._veri["modlar"].append((
                    msg._timestamp,
                    getattr(msg, "Mode", 0),
                    getattr(msg, "ModeNum", 0),
                ))

            elif tip == "MSG":
                metin = getattr(msg, "Message", "")
                self._veri["mesajlar"].append((msg._timestamp, metin))

    # ── .tlog okuyucu (MAVLink telemetri log) ─────────────────────────────────

    def _tlog_oku(self):
        mlog = mavutil.mavlink_connection(self.dosya, robust_parsing=True)
        while True:
            msg = mlog.recv_match(blocking=False)
            if msg is None:
                break
            tip = msg.get_type()

            if tip == "SYS_STATUS":
                volt = getattr(msg, "voltage_battery", 0) / 1000.0
                curr = getattr(msg, "current_battery", -1) / 100.0
                pct  = getattr(msg, "battery_remaining", -1)
                if volt > 0:
                    self._veri["bat_volt"].append(volt)
                if curr >= 0:
                    self._veri["bat_curr"].append(curr)
                if pct >= 0:
                    self._veri["bat_pct"].append(pct)
                self._veri["bat_zaman"].append(getattr(msg, "_timestamp", 0))

            elif tip == "GPS_RAW_INT":
                self._veri["gps_fix"].append(getattr(msg, "fix_type", 0))
                self._veri["gps_uydu"].append(getattr(msg, "satellites_visible", 0))
                self._veri["gps_lat"].append(getattr(msg, "lat", 0) / 1e7)
                self._veri["gps_lon"].append(getattr(msg, "lon", 0) / 1e7)

            elif tip == "VFR_HUD":
                self._veri["irtifa"].append(getattr(msg, "alt", 0))
                self._veri["hiz"].append(getattr(msg, "groundspeed", 0))
                self._veri["ruzgar"].append(abs(getattr(msg, "airspeed", 0) -
                                                getattr(msg, "groundspeed", 0)))

            elif tip == "ATTITUDE":
                self._veri["roll"].append(math.degrees(getattr(msg, "roll", 0)))
                self._veri["pitch"].append(math.degrees(getattr(msg, "pitch", 0)))

            elif tip == "SCALED_IMU":
                ax = getattr(msg, "xacc", 0) / 1000.0
                ay = getattr(msg, "yacc", 0) / 1000.0
                az = getattr(msg, "zacc", 0) / 1000.0
                if hasattr(msg, "temperature"):
                    self._veri["imu_sicak"].append(msg.temperature / 100.0)
                self._veri["imu_acc"].append(math.sqrt(ax**2 + ay**2 + az**2))

            elif tip == "STATUSTEXT":
                self._veri["mesajlar"].append((
                    getattr(msg, "_timestamp", 0),
                    getattr(msg, "text", ""),
                ))

            elif tip == "HEARTBEAT":
                self._veri["modlar"].append((
                    getattr(msg, "_timestamp", 0),
                    getattr(msg, "custom_mode", 0),
                    getattr(msg, "base_mode", 0),
                ))

    # ── Rapor üretici ─────────────────────────────────────────────────────────

    def _rapor_olustur(self) -> str:
        v = self._veri

        def _max(lst, varsayilan=0):
            return max(lst) if lst else varsayilan

        def _min(lst, varsayilan=0):
            return min(lst) if lst else varsayilan

        def _ort(lst, varsayilan=0):
            return sum(lst) / len(lst) if lst else varsayilan

        # ── Temel istatistikler ────────────────────────────────────────────
        irtifa_max  = _max(v["irtifa"])
        hiz_max     = _max(v.get("hiz", v.get("gps_spd", [])))

        # Batarya
        bat_volt_min = _min(v["bat_volt"], 0)
        bat_curr_max = _max(v["bat_curr"])
        bat_pct_min  = _min([p for p in v["bat_pct"] if p >= 0], 100)
        bat_pct_bas  = next((p for p in v["bat_pct"] if p >= 0), -1)
        kritik_bat   = bat_pct_min <= BAT_KRITIK_YDZ and bat_pct_min >= 0
        dusuk_bat    = bat_pct_min <= BAT_DUSUK_YDZ  and bat_pct_min >= 0
        hucre_min_v  = bat_volt_min / HUCRE_SAYISI if bat_volt_min > 0 else 0

        # GPS
        gps_kayip = sum(1 for f in v["gps_fix"] if f < GPS_KAYIP_FIX)
        gps_uydu_min = _min(v["gps_uydu"], 0)

        # IMU
        imu_sicak_max = _max(v["imu_sicak"])
        imu_asiri     = imu_sicak_max > IMU_SICAK_ESIK

        # Titreşim (ivme normu sapması)
        if v["imu_acc"]:
            ort_acc = _ort(v["imu_acc"])
            titresim_skor = max(abs(a - ort_acc) for a in v["imu_acc"])
        else:
            titresim_skor = 0
        anormal_titresim = titresim_skor > TITRESIM_ESIK

        # Rüzgar
        ruzgar_max_ms  = _max(v["ruzgar"])
        ruzgar_max_kmh = ruzgar_max_ms * 3.6
        teh_ruzgar     = ruzgar_max_ms >= RUZGAR_TEHLIKELI

        # EKF
        ekf_max = _max(v["ekf_vel_var"])

        # Kat edilen mesafe
        mesafe_m = 0.0
        lats = v["gps_lat"]
        lons = v["gps_lon"]
        for i in range(1, min(len(lats), len(lons))):
            mesafe_m += self._haversine(lats[i-1], lons[i-1], lats[i], lons[i])

        # Toplam veri noktası sayısını süre tahmini olarak kullan
        veri_sayisi = max(len(v["bat_volt"]), len(v["irtifa"]), len(v["gps_fix"]))

        # ── Rapor metni ───────────────────────────────────────────────────
        tarih = datetime.now().strftime("%d.%m.%Y %H:%M")
        dosya_adi = os.path.basename(self.dosya)

        satirlar = [
            "=" * 62,
            "  DOĞUŞ ÜNİVERSİTESİ LÖP – UÇUŞ VERİSİ ANALİZ RAPORU",
            "=" * 62,
            f"  Tarih          : {tarih}",
            f"  Kaynak Dosya   : {dosya_adi}",
            f"  Veri Noktası   : {veri_sayisi}",
            f"  Max İrtifa     : {irtifa_max:.1f} m",
            f"  Max Hız        : {hiz_max:.1f} m/s",
            f"  Kat Edilen Yol : {mesafe_m:.0f} m",
            "",
            "── BATARYA ──────────────────────────────────────────────",
            f"  Başlangıç      : %{bat_pct_bas}" if bat_pct_bas >= 0 else "  Başlangıç      : --",
            f"  Min Yüzde      : %{bat_pct_min}" if bat_pct_min < 100 else "  Min Yüzde      : --",
            f"  Min Voltaj     : {bat_volt_min:.2f} V  (Hücre: {hucre_min_v:.2f} V)",
            f"  Max Akım       : {bat_curr_max:.1f} A",
        ]

        if kritik_bat:
            satirlar.append(f"  ✗  KRİTİK: Batarya %{BAT_KRITIK_YDZ} altına düştü!")
        elif dusuk_bat:
            satirlar.append(f"  ⚠  UYARI: Batarya %{BAT_DUSUK_YDZ} altına geriledi.")
        else:
            satirlar.append("  ✓  Batarya normal seviyelerde kaldı.")

        if hucre_min_v > 0 and hucre_min_v < BAT_MIN_HUCRE_V:
            satirlar.append(f"  ✗  KRİTİK: Hücre voltajı {hucre_min_v:.2f}V < {BAT_MIN_HUCRE_V}V!")

        satirlar += [
            "",
            "── IMU / SENSÖR ─────────────────────────────────────────",
            f"  Max IMU Sıcaklık : {imu_sicak_max:.1f} °C",
        ]
        if imu_asiri:
            satirlar.append(f"  ✗  UYARI: IMU sıcaklığı {IMU_SICAK_ESIK}°C eşiğini aştı!")
        else:
            satirlar.append("  ✓  IMU sıcaklıkları normal.")

        satirlar.append(f"  Titreşim Skoru   : {titresim_skor:.1f}")
        if anormal_titresim:
            satirlar.append("  ⚠  Anormal titreşim tespit edildi. Motor/pervane kontrolü önerilir.")
        else:
            satirlar.append("  ✓  Titreşim normal.")

        satirlar += [
            "",
            "── GPS ──────────────────────────────────────────────────",
            f"  Min Uydu Sayısı  : {gps_uydu_min}",
            f"  Fix Kaybı Sayısı : {gps_kayip}",
        ]
        if gps_kayip > 0:
            satirlar.append(f"  ⚠  {gps_kayip} kez GPS fix kaybı yaşandı (fix < 3D).")
        else:
            satirlar.append("  ✓  GPS bağlantısı kesintisiz.")

        satirlar += [
            "",
            "── RÜZGAR ───────────────────────────────────────────────",
            f"  Max Rüzgar : {ruzgar_max_ms:.1f} m/s  ({ruzgar_max_kmh:.0f} km/s)",
        ]
        if teh_ruzgar:
            satirlar.append(f"  ⚠  Tehlikeli rüzgar eşiği ({RUZGAR_TEHLIKELI:.0f} m/s) aşıldı!")
        else:
            satirlar.append("  ✓  Rüzgar güvenli sınırlar içinde kaldı.")

        satirlar += [
            "",
            "── EKF ──────────────────────────────────────────────────",
            f"  Max EKF Sapma : {ekf_max:.3f}",
        ]
        if ekf_max > EKF_HATA_ESIK:
            satirlar.append(f"  ⚠  EKF sapması yüksek ({ekf_max:.2f}). Kalibrasyon gerekebilir.")
        else:
            satirlar.append("  ✓  EKF sağlıklı.")

        # Son sistem mesajları
        if v["mesajlar"]:
            satirlar += ["", "── SON SİSTEM MESAJLARI (son 5) ─────────────────────────"]
            for zaman, metin in v["mesajlar"][-5:]:
                satirlar.append(f"  • {metin}")

        # Genel değerlendirme
        uyari_sayisi = sum([
            kritik_bat, gps_kayip > 0, imu_asiri,
            anormal_titresim, teh_ruzgar, ekf_max > EKF_HATA_ESIK
        ])
        satirlar += [
            "",
            "── GENEL DEĞERLENDİRME ──────────────────────────────────",
        ]
        if uyari_sayisi == 0:
            satirlar.append("  ✓  Uçuş sorunsuz tamamlandı.")
        elif uyari_sayisi <= 2:
            satirlar.append(f"  ⚠  {uyari_sayisi} uyarı tespit edildi. İnceleme önerilir.")
        else:
            satirlar.append(f"  ✗  {uyari_sayisi} sorun! Sonraki uçuştan önce bakım yapın.")

        satirlar += ["", "=" * 62, ""]
        return "\n".join(satirlar)

    @staticmethod
    def _haversine(lat1, lon1, lat2, lon2) -> float:
        if not all([lat1, lon1, lat2, lon2]):
            return 0.0
        R = 6371000
        f1, f2 = math.radians(lat1), math.radians(lat2)
        df = math.radians(lat2 - lat1)
        dl = math.radians(lon2 - lon1)
        a = math.sin(df/2)**2 + math.cos(f1)*math.cos(f2)*math.sin(dl/2)**2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


# ── Komut satırı ──────────────────────────────────────────────────────────────

def son_bin_bul() -> str | None:
    """Mevcut dizindeki en yeni .bin dosyasını bulur."""
    binler = [f for f in os.listdir(".") if f.endswith(".bin")]
    if not binler:
        return None
    return max(binler, key=os.path.getmtime)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="ArduPilot .bin/.tlog dosyasından Türkçe uçuş raporu üretir."
    )
    parser.add_argument("dosya", nargs="?", help=".bin veya .tlog dosyası")
    args = parser.parse_args()

    dosya = args.dosya
    if not dosya:
        dosya = son_bin_bul()
        if not dosya:
            print("HATA: .bin dosyası bulunamadı. Dosya yolunu argüman olarak ver.")
            sys.exit(1)
        print(f"Otomatik bulunan: {dosya}\n")

    analizci = UcusAnalizcisi(dosya)
    rapor = analizci.analiz_et()
    print(rapor)

    # Raporu kaydet
    cikti = dosya.rsplit(".", 1)[0] + "_rapor.txt"
    with open(cikti, "w", encoding="utf-8") as f:
        f.write(rapor)
    print(f"Rapor kaydedildi: {cikti}")
