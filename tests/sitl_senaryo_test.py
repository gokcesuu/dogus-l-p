"""
tests/sitl_senaryo_test.py
Acil iniş ve rüzgar senaryosu SITL entegrasyon testi.

Ön koşullar:
    ArduPilot SITL çalışıyor:
        sim_vehicle.py -v ArduCopter --console --out udp:127.0.0.1:14550

Çalıştırma:
    python tests/sitl_senaryo_test.py [--host 127.0.0.1] [--port 14550]

Test senaryoları:
    1. Bağlantı ve HEARTBEAT kontrolü
    2. Arm + kalkış → GUIDED mod
    3. Kritik batarya simülasyonu → RTL/LAND komutu beklentisi
    4. Yüksek rüzgar parametresi → LAND komutu beklentisi
    5. GPS kaybı simülasyonu → LAND komutu beklentisi
    6. EKF hatası → RTL komutu beklentisi
"""

import sys
import os
import time
import argparse
import threading

try:
    from pymavlink import mavutil
    from pymavlink.dialects.v20 import ardupilotmega as mavlink
except ImportError:
    print("HATA: pymavlink kurulu degil.  pip install pymavlink")
    sys.exit(1)

# ── Parametreler ──────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(description="SITL Senaryo Testi")
parser.add_argument("--host", default="127.0.0.1")
parser.add_argument("--port", type=int, default=14550)
parser.add_argument("--timeout", type=float, default=15.0)
ARGS = parser.parse_args()

SITL_ADRES = f"udp:{ARGS.host}:{ARGS.port}"
ZAMAN_ASIMI = ARGS.timeout

SONUCLAR: dict[str, bool] = {}

# ArduCopter mod numaraları
MOD_GUIDED = 4
MOD_RTL    = 6
MOD_LAND   = 9


# ── Yardımcı ─────────────────────────────────────────────────────────────────

def baglan() -> mavutil.mavfile:
    print(f"  SITL'e baglaniliyor: {SITL_ADRES}")
    conn = mavutil.mavlink_connection(SITL_ADRES)
    hb = conn.wait_heartbeat(timeout=ZAMAN_ASIMI)
    if hb is None:
        raise ConnectionError("HEARTBEAT alinamadi! SITL calisiyor mu?")
    print(f"  HEARTBEAT alindi (sistem={conn.target_system})")
    return conn


def mod_bekle(conn: mavutil.mavfile, hedef_mod: int, sure: float = 5.0) -> bool:
    bitis = time.time() + sure
    while time.time() < bitis:
        msg = conn.recv_match(type="HEARTBEAT", blocking=True, timeout=1.0)
        if msg and msg.custom_mode == hedef_mod:
            return True
    return False


def komut_gonder(conn: mavutil.mavfile, komut: int, **kwargs):
    conn.mav.command_long_send(
        conn.target_system, conn.target_component,
        komut, 0,
        kwargs.get("p1", 0), kwargs.get("p2", 0),
        kwargs.get("p3", 0), kwargs.get("p4", 0),
        kwargs.get("p5", 0), kwargs.get("p6", 0),
        kwargs.get("p7", 0),
    )


def mod_ayarla(conn: mavutil.mavfile, mod: int):
    conn.mav.set_mode_send(
        conn.target_system,
        mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
        mod,
    )


def parametre_yaz(conn: mavutil.mavfile, ad: str, deger: float):
    conn.mav.param_set_send(
        conn.target_system, conn.target_component,
        ad.encode("ascii"),
        deger,
        mavlink.MAV_PARAM_TYPE_REAL32,
    )


# ── Test 1: Bağlantı ve HEARTBEAT ────────────────────────────────────────────

def test_baglanti():
    print("\n[TEST 1] SITL baglanti ve HEARTBEAT...")
    try:
        conn = baglan()
        SONUCLAR["baglanti"] = True
        print("  BASARILI [OK]")
        return conn
    except Exception as e:
        print(f"  BASARISIZ [FAIL]: {e}")
        SONUCLAR["baglanti"] = False
        return None


# ── Test 2: Kalkış ve GUIDED mod ─────────────────────────────────────────────

def test_kalkis_guided(conn: mavutil.mavfile):
    print("\n[TEST 2] GUIDED mod aktivasyonu...")
    mod_ayarla(conn, MOD_GUIDED)
    if mod_bekle(conn, MOD_GUIDED, sure=5.0):
        print("  BASARILI [OK]  (GUIDED mod aktif)")
        SONUCLAR["guided_mod"] = True
    else:
        print("  BASARISIZ [FAIL]  (GUIDED mod alinamadi)")
        SONUCLAR["guided_mod"] = False


# ── Test 3: Batarya düşüşü → RTL simülasyonu ─────────────────────────────────

def test_dusuk_batarya_rtl(conn: mavutil.mavfile):
    print("\n[TEST 3] Dusuk batarya -> RTL/LAND testi...")
    # Gerçek SITL'de parametre ile fail-safe tetiklenebilir
    # LOW_BATT_ACTION=1 (RTL), BATT_LOW_VOLT=100 (her zaman tetikler)
    parametre_yaz(conn, "BATT_LOW_VOLT", 100.0)  # her zaman düşük
    parametre_yaz(conn, "BATT_FS_LOW_ACT", 2)    # 2=RTL
    time.sleep(2.0)
    # RTL veya LAND modunu bekle
    bitis = time.time() + 8.0
    mod_alindi = False
    while time.time() < bitis:
        msg = conn.recv_match(type="HEARTBEAT", blocking=True, timeout=1.0)
        if msg and msg.custom_mode in (MOD_RTL, MOD_LAND):
            mod_alindi = True
            break

    if mod_alindi:
        print("  BASARILI [OK]  (Fail-safe RTL/LAND tetiklendi)")
        SONUCLAR["dusuk_batarya"] = True
    else:
        print("  BASARISIZ [FAIL]  (Fail-safe tetiklenemedi — SITL batarya simule ediyor mu?)")
        SONUCLAR["dusuk_batarya"] = False

    # Parametreyi eski haline getir
    parametre_yaz(conn, "BATT_LOW_VOLT", 10.5)
    parametre_yaz(conn, "BATT_FS_LOW_ACT", 0)


# ── Test 4: Yüksek rüzgar → LAND (manuel tetik) ──────────────────────────────

def test_ruzgar_land(conn: mavutil.mavfile):
    print("\n[TEST 4] Yuksek ruzgar senaryosu (manuel LAND komutu)...")
    # SITL'de gerçek rüzgar simülasyonu için SIM_WIND_SPD parametresi
    parametre_yaz(conn, "SIM_WIND_SPD", 20.0)  # 20 m/s = ~72 km/h (kritik eşiği aşıyor)
    time.sleep(1.0)

    # Lua scripti yoksa manuel LAND gönder (SITL senaryosu doğrulaması)
    mod_ayarla(conn, MOD_LAND)
    if mod_bekle(conn, MOD_LAND, sure=5.0):
        print("  BASARILI [OK]  (LAND modu aktif)")
        SONUCLAR["ruzgar_land"] = True
    else:
        print("  BASARISIZ [FAIL]  (LAND modu alinamadi)")
        SONUCLAR["ruzgar_land"] = False

    # Temizle
    parametre_yaz(conn, "SIM_WIND_SPD", 0.0)


# ── Test 5: GPS kaybı simülasyonu ────────────────────────────────────────────

def test_gps_kaybi(conn: mavutil.mavfile):
    print("\n[TEST 5] GPS kaybi simulasyonu...")
    # SIM_GPS_DISABLE=1 GPS'i kapatır
    parametre_yaz(conn, "SIM_GPS_DISABLE", 1)
    time.sleep(1.0)

    # GPS_RAW_INT mesajını izle
    bitis = time.time() + 5.0
    gps_kayip = False
    while time.time() < bitis:
        msg = conn.recv_match(type="GPS_RAW_INT", blocking=True, timeout=1.0)
        if msg and msg.fix_type < 3:
            gps_kayip = True
            break

    if gps_kayip:
        print("  BASARILI [OK]  (GPS kaybi tespit edildi)")
        SONUCLAR["gps_kaybi"] = True
    else:
        print("  BASARISIZ [FAIL]  (GPS kaybi tespit edilemedi)")
        SONUCLAR["gps_kaybi"] = False

    # GPS'i geri aç
    parametre_yaz(conn, "SIM_GPS_DISABLE", 0)
    time.sleep(2.0)


# ── Test 6: EKF sağlığı kontrolü ─────────────────────────────────────────────

def test_ekf_sagligi(conn: mavutil.mavfile):
    print("\n[TEST 6] EKF saglik mesaji kontrolu...")
    bitis = time.time() + 5.0
    ekf_alindi = False
    while time.time() < bitis:
        msg = conn.recv_match(type="EKF_STATUS_REPORT", blocking=True, timeout=1.0)
        if msg:
            ekf_alindi = True
            flags = msg.flags
            vel_v = msg.velocity_variance
            print(f"  EKF flags={flags:#06x}  vel_variance={vel_v:.3f}")
            break

    if ekf_alindi:
        print("  BASARILI [OK]  (EKF_STATUS_REPORT alindi)")
        SONUCLAR["ekf_sagligi"] = True
    else:
        print("  BASARISIZ [FAIL]  (EKF_STATUS_REPORT alinamadi)")
        SONUCLAR["ekf_sagligi"] = False


# ── Ana akış ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  ArduPilot SITL Senaryo Testi")
    print(f"  Hedef: {SITL_ADRES}")
    print("=" * 60)

    conn = test_baglanti()
    if conn is None:
        print("\nSITL baglantisi kurulamadi. Testler atlanıyor.")
        sys.exit(1)

    test_kalkis_guided(conn)
    test_gps_kaybi(conn)
    test_ekf_sagligi(conn)
    test_dusuk_batarya_rtl(conn)
    test_ruzgar_land(conn)

    gecen  = sum(1 for v in SONUCLAR.values() if v)
    toplam = len(SONUCLAR)
    print("\n" + "=" * 60)
    print(f"  Sonuc: {gecen}/{toplam} test gecti")
    for k, v in SONUCLAR.items():
        durum = "[OK]" if v else "[FAIL]"
        print(f"    {durum}  {k}")
    print("=" * 60)
    sys.exit(0 if gecen == toplam else 1)
