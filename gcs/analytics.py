"""
Real-time Analytics Paneli — Uçuş metrikleri toplayıp hesaplayan modül.

Hem canlı bağlantıdan hem CSV replay'den veri alır.
Metrics (Temel + Güvenlik + Gelişmiş).
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import math


@dataclass
class AnalyticsMetrics:
    """Uçuş analitikleri — tüm metrikleri saklar."""
    
    # ─────── TEMEL METRİKLER ───────
    flight_duration_s: float = 0.0              # Saniye
    distance_traveled_m: float = 0.0            # Metre
    max_altitude_m: float = 0.0                 # AGL, metre
    avg_altitude_m: float = 0.0                 # Ortalama AGL
    max_speed_ms: float = 0.0                   # Metre/saniye
    avg_speed_ms: float = 0.0                   # Ortalama hız
    energy_consumed_mah: float = 0.0            # mAh (batarya kaybından hesap)
    energy_consumed_wh: Optional[float] = None  # Wh (volt varsa)
    
    # ─────── GÜVENLİK ODAKLI ───────
    max_distance_from_home_m: float = 0.0       # Drift/range
    min_battery_cell_volt: float = 0.0          # En düşük hücre voltajı
    ekf_error_count: int = 0                    # EKF hata sayısı
    ekf_error_duration_s: float = 0.0           # Toplam EKF hata süresi
    rc_signal_loss_count: int = 0               # RC sinyali kaybolma
    rc_signal_loss_duration_s: float = 0.0      # Toplam RC kayıp süresi
    gps_signal_loss_count: int = 0              # GPS kaybolma
    gps_signal_loss_duration_s: float = 0.0     # Toplam GPS kayıp süresi
    max_descent_rate_ms: float = 0.0            # Maksimum dikey (negatif)
    avg_wind_speed_ms: float = 0.0              # Ortalama rüzgar
    max_wind_speed_ms: float = 0.0              # Maksimum rüzgar
    
    # ─────── GELİŞMİŞ METRİKLER ───────
    imu_temp_min: float = 999.0                 # Min IMU sıcaklığı
    imu_temp_max: float = -999.0                # Max IMU sıcaklığı
    mode_change_count: int = 0                  # Kaç kez mod değişti
    max_vibration: float = 0.0                  # Maksimum titreşim (accel norm)
    
    # ─────── İç DURUM ───────
    _total_points: int = 0                      # İşlenen nokta sayısı
    _last_timestamp_s: float = 0.0              # Son timestamp (uçuş süresi için)
    _last_altitude: float = 0.0                 # Son irtifa (mesafe für için)
    _last_lat: float = 0.0                      # Son latitude
    _last_lon: float = 0.0                      # Son longitude
    _altitude_samples: List[float] = field(default_factory=list)
    _speed_samples: List[float] = field(default_factory=list)
    _wind_samples: List[float] = field(default_factory=list)
    _battery_percent_start: Optional[float] = None
    _battery_percent_last: Optional[float] = None
    _battery_voltage_nominal: float = 16.8      # 4S LiPo nominal (4 * 4.2V)
    _cell_count: int = 4
    
    def reset(self):
        """Metrikleri sıfırla (yeni uçuş için)."""
        self.flight_duration_s = 0.0
        self.distance_traveled_m = 0.0
        self.max_altitude_m = 0.0
        self.avg_altitude_m = 0.0
        self.max_speed_ms = 0.0
        self.avg_speed_ms = 0.0
        self.energy_consumed_mah = 0.0
        self.max_distance_from_home_m = 0.0
        self.min_battery_cell_volt = 999.0
        self.ekf_error_count = 0
        self.ekf_error_duration_s = 0.0
        self.rc_signal_loss_count = 0
        self.rc_signal_loss_duration_s = 0.0
        self.gps_signal_loss_count = 0
        self.gps_signal_loss_duration_s = 0.0
        self.max_descent_rate_ms = 0.0
        self.avg_wind_speed_ms = 0.0
        self.max_wind_speed_ms = 0.0
        self.imu_temp_min = 999.0
        self.imu_temp_max = -999.0
        self.mode_change_count = 0
        self.max_vibration = 0.0
        
        self._total_points = 0
        self._last_timestamp_s = 0.0
        self._last_altitude = 0.0
        self._last_lat = 0.0
        self._last_lon = 0.0
        self._altitude_samples.clear()
        self._speed_samples.clear()
        self._wind_samples.clear()
        self._battery_percent_start = None
        self._battery_percent_last = None


class AnalyticsCollector:
    """Telemetri verilerini toplayıp metrikleri hesaplar."""
    
    def __init__(self, battery_nominal_v: float = 16.8, cell_count: int = 4):
        """
        battery_nominal_v: Batarya nominal voltajı (4S = 16.8V varsayılan)
        cell_count: Hücre sayısı (kritik volt hesabı için)
        """
        self.metrics = AnalyticsMetrics()
        self.metrics._battery_voltage_nominal = battery_nominal_v
        self.metrics._cell_count = cell_count
        
        self._ekf_error_active = False
        self._ekf_error_start_s = 0.0
        self._rc_loss_active = False
        self._rc_loss_start_s = 0.0
        self._gps_loss_active = False
        self._gps_loss_start_s = 0.0
        self._last_mode: Optional[str] = None
        self._last_lat_home: Optional[float] = None
        self._last_lon_home: Optional[float] = None
    
    def update_from_dict(self, data: Dict, timestamp_s: float = 0.0):
        """
        Tek bir telemetri örneğini işle (CSV row veya live VFR/GPS/Batarya).
        
        Beklenen alanlar (hepsi opsiyonel):
        - timestamp_s: Uçuş başlangıcından saniye
        - lat, lon, alt_agl_m, climb_rate_ms
        - speed_ms, gps_speed_ms
        - battery_volt, battery_percent, battery_current_a
        - wind_speed_ms
        - imu0_temp, imu1_temp, imu2_temp (derece C)
        - mode: Uçuş modu (string)
        - ekf_error: EKF hata/uyarı (bool veya int)
        - rc_lost: RC sinyali kaybı (bool)
        - gps_fix: GPS fix türü (int) — 0=yok, 1-5=var
        - vibration: Titreşim norm (float)
        """
        if self.metrics._battery_percent_start is None:
            self.metrics._battery_percent_start = data.get("battery_percent", 100.0)
        
        # Timestamp / Uçuş Süresi
        if timestamp_s > 0:
            self.metrics._last_timestamp_s = timestamp_s
            self.metrics.flight_duration_s = timestamp_s
        
        # Pozisyon / Mesafe / Drift
        lat = data.get("lat")
        lon = data.get("lon")
        if lat is not None and lon is not None:
            if self.metrics._last_lat == 0 and self.metrics._last_lon == 0:
                # İlk pozisyon = ev noktası
                self._last_lat_home = lat
                self._last_lon_home = lon
            
            # Mesafe hesapla
            if self.metrics._last_lat != 0 and self.metrics._last_lon != 0:
                dist = self._haversine(
                    self.metrics._last_lat, self.metrics._last_lon,
                    lat, lon
                )
                self.metrics.distance_traveled_m += dist
            
            # Eve uzaklık
            if self._last_lat_home is not None:
                drift = self._haversine(
                    self._last_lat_home, self._last_lon_home,
                    lat, lon
                )
                self.metrics.max_distance_from_home_m = max(
                    self.metrics.max_distance_from_home_m, drift
                )
            
            self.metrics._last_lat = lat
            self.metrics._last_lon = lon
        
        # İrtifa
        alt = data.get("alt_agl_m")
        if alt is not None:
            self.metrics._altitude_samples.append(alt)
            self.metrics.max_altitude_m = max(self.metrics.max_altitude_m, alt)
        
        # Hız
        speed = data.get("speed_ms") or data.get("gps_speed_ms")
        if speed is not None:
            self.metrics._speed_samples.append(speed)
            self.metrics.max_speed_ms = max(self.metrics.max_speed_ms, speed)
        
        # Dikey hız (descent rate)
        climb = data.get("climb_rate_ms")
        if climb is not None and climb < 0:
            # Negatif = iniş
            self.metrics.max_descent_rate_ms = min(
                self.metrics.max_descent_rate_ms, climb
            )
        
        # Batarya
        batt_percent = data.get("battery_percent")
        if batt_percent is not None:
            self.metrics._battery_percent_last = batt_percent
        
        batt_volt = data.get("battery_volt")
        if batt_volt is not None:
            cell_volt = batt_volt / self.metrics._cell_count
            self.metrics.min_battery_cell_volt = min(
                self.metrics.min_battery_cell_volt, cell_volt
            )
        
        # Enerji tüketimi (batarya % düşüşünden)
        if (self.metrics._battery_percent_start is not None and 
            self.metrics._battery_percent_last is not None):
            percent_drop = self.metrics._battery_percent_start - self.metrics._battery_percent_last
            # Tipik kapasiteler (config'den alınabilir)
            battery_capacity_mah = 5000.0  # Örnek: 5000 mAh
            self.metrics.energy_consumed_mah = (percent_drop / 100.0) * battery_capacity_mah
        
        # Rüzgar
        wind = data.get("wind_speed_ms")
        if wind is not None:
            self.metrics._wind_samples.append(wind)
            self.metrics.max_wind_speed_ms = max(self.metrics.max_wind_speed_ms, wind)
        
        # IMU Sıcaklık
        for imu_key in ["imu0_temp", "imu1_temp", "imu2_temp"]:
            temp = data.get(imu_key)
            if temp is not None:
                self.metrics.imu_temp_min = min(self.metrics.imu_temp_min, temp)
                self.metrics.imu_temp_max = max(self.metrics.imu_temp_max, temp)
        
        # Mod değişimi
        mode = data.get("mode")
        if mode is not None:
            if self._last_mode is not None and self._last_mode != mode:
                self.metrics.mode_change_count += 1
            self._last_mode = mode
        
        # EKF Hatası
        ekf_error = data.get("ekf_error")
        if ekf_error:
            if not self._ekf_error_active:
                self._ekf_error_active = True
                self._ekf_error_start_s = timestamp_s
                self.metrics.ekf_error_count += 1
        else:
            if self._ekf_error_active:
                self._ekf_error_active = False
                duration = timestamp_s - self._ekf_error_start_s
                self.metrics.ekf_error_duration_s += max(0, duration)
        
        # RC Kaybı
        rc_lost = data.get("rc_lost", False)
        if rc_lost:
            if not self._rc_loss_active:
                self._rc_loss_active = True
                self._rc_loss_start_s = timestamp_s
                self.metrics.rc_signal_loss_count += 1
        else:
            if self._rc_loss_active:
                self._rc_loss_active = False
                duration = timestamp_s - self._rc_loss_start_s
                self.metrics.rc_signal_loss_duration_s += max(0, duration)
        
        # GPS Kaybı
        gps_fix = data.get("gps_fix", 0)
        gps_has_fix = gps_fix > 0
        if not gps_has_fix:
            if not self._gps_loss_active:
                self._gps_loss_active = True
                self._gps_loss_start_s = timestamp_s
                self.metrics.gps_signal_loss_count += 1
        else:
            if self._gps_loss_active:
                self._gps_loss_active = False
                duration = timestamp_s - self._gps_loss_start_s
                self.metrics.gps_signal_loss_duration_s += max(0, duration)
        
        # Titreşim
        vibration = data.get("vibration", 0.0)
        if vibration > 0:
            self.metrics.max_vibration = max(self.metrics.max_vibration, vibration)
        
        self.metrics._total_points += 1
    
    def finalize(self):
        """Uçuş sonunda ortalama/final hesaplarını yap."""
        if self.metrics._altitude_samples:
            self.metrics.avg_altitude_m = sum(self.metrics._altitude_samples) / len(
                self.metrics._altitude_samples
            )
        
        if self.metrics._speed_samples:
            self.metrics.avg_speed_ms = sum(self.metrics._speed_samples) / len(
                self.metrics._speed_samples
            )
        
        if self.metrics._wind_samples:
            self.metrics.avg_wind_speed_ms = sum(self.metrics._wind_samples) / len(
                self.metrics._wind_samples
            )
        
        # Enerji Wh hesabı (ortalama volttan)
        if self.metrics.energy_consumed_mah > 0:
            avg_volt = self.metrics._battery_voltage_nominal * 0.9  # Ortalama ~90%
            self.metrics.energy_consumed_wh = (
                self.metrics.energy_consumed_mah / 1000.0 * avg_volt
            )
    
    def get_metrics(self) -> AnalyticsMetrics:
        """Güncel metrikleri döner."""
        return self.metrics
    
    @staticmethod
    def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """İki GPS koordinatı arasındaki mesafeyi metre cinsinden hesapla."""
        from math import radians, sin, cos, sqrt, atan2
        
        R = 6371000.0  # Dünya yarıçapı metre
        
        lat1_rad = radians(lat1)
        lat2_rad = radians(lat2)
        delta_lat = radians(lat2 - lat1)
        delta_lon = radians(lon2 - lon1)
        
        a = (
            sin(delta_lat / 2) ** 2 +
            cos(lat1_rad) * cos(lat2_rad) * sin(delta_lon / 2) ** 2
        )
        c = 2 * atan2(sqrt(a), sqrt(1 - a))
        distance = R * c
        
        return distance


# ─────────────────────────────────────────────────────────────────────────────
# Uygun Formatlar (CSV'den ve Live Telemetri'den veri çıkarmak için)
# ─────────────────────────────────────────────────────────────────────────────

def extract_csv_row_to_dict(row: Dict[str, str]) -> Dict:
    """
    gcs_logger.py'nin CSV satırını analytics dict'e çevir.

    gcs_logger.py'nin gerçek CSV sütun adları Türkçe (zaman, irtifa, hiz,
    bat_volt, bat_yuzde, ruzgar_ms, imu0_c, mod_id, ekf_hata, ...) —
    aşağıdaki eşleme, gcs_main.py'nin canlı telemetri yolunda kullandığı
    aynı Türkçe→İngilizce çeviriyi CSV replay için de uygular.
    """
    def _flt(anahtar):
        try:
            deger = row.get(anahtar, "")
            return float(deger) if deger not in (None, "") else None
        except (ValueError, TypeError):
            return None

    out = {}
    out["timestamp_s"] = _flt("zaman") or 0.0

    out["lat"] = _flt("lat")
    out["lon"] = _flt("lon")
    out["alt_agl_m"] = _flt("irtifa")
    out["climb_rate_ms"] = _flt("dikey_hiz")
    out["speed_ms"] = _flt("hiz")
    out["gps_speed_ms"] = None   # ayrı bir GPS-hız sütunu yok, VFR hızı kullanılıyor
    out["battery_volt"] = _flt("bat_volt")
    out["battery_percent"] = _flt("bat_yuzde")
    out["battery_current_a"] = _flt("bat_amper")
    out["wind_speed_ms"] = _flt("ruzgar_ms")
    out["imu0_temp"] = _flt("imu0_c")
    out["imu1_temp"] = _flt("imu1_c")
    out["imu2_temp"] = _flt("imu2_c")
    out["vibration"] = None   # gcs_logger.py CSV'sinde titreşim sütunu yok

    # RC kaybı CSV'de tutulmuyor (canlı yolda da MAVLink handler'ından geliyor)
    out["rc_lost"] = False
    # ekf_hata bir hata metriği (float) — canlı yoldaki 0.8 eşiğiyle aynı mantık
    ekf_hata = _flt("ekf_hata")
    out["ekf_error"] = bool(ekf_hata is not None and ekf_hata > 0.8)

    try:
        out["gps_fix"] = int(float(row.get("gps_fix", 0) or 0))
    except (ValueError, TypeError):
        out["gps_fix"] = 0

    out["mode"] = row.get("mod_id")   # mode değişimi sayımı için mod_id yeterli

    return out
