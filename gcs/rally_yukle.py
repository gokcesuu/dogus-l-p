"""
rally_yukle.py
Doğuş Üniversitesi LÖP — ArduPilot Rally Point Yükleme Modülü

Katman 2 donanımsal yedek: En güvenli N noktayı ArduPilot'un flash hafızasına
Rally Point olarak yükler. Pi çökse bile ArduPilot bu noktaları bilir.

Protokol: MAVLink legacy RALLY_POINT (msg 175) + RALLY_TOTAL parametresi
ArduPilot 3.x ve 4.x ile uyumlu.

Kullanım (komut satırı):
    python rally_yukle.py --npz alan_verisi.npz --baglanti tcp:127.0.0.1:5762

Kullanım (import):
    from rally_yukle import en_iyi_noktalar, rally_yukle
    noktalar = en_iyi_noktalar("alan_verisi.npz", n=5, merkez_lat=41.0, merkez_lon=28.9)
    rally_yukle(noktalar, "tcp:127.0.0.1:5762")
"""

import sys
import json
import time
import argparse
import math
import numpy as np

# Bkz. fence_yukle.py — aynı Windows konsol kod sayfası (cp1254/cp1252)
# nedeniyle "✓"/"✗" gibi karakterler print() içinde UnicodeEncodeError
# fırlatabiliyordu.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    from pymavlink import mavutil
    MAVLINK_MEVCUT = True
except ImportError:
    MAVLINK_MEVCUT = False

MAX_RALLY = 10          # ArduPilot varsayılan rally_max = 10
VARSAYILAN_IRTIFA = 50  # rally noktası iniş yüksekliği (ev üzerinde, metre)
MIN_ARALIK_M      = 80  # noktalar arası minimum mesafe (kümelenmeyi önler)


# ── Nokta seçimi ──────────────────────────────────────────────────────────────

def _haversine(lat1, lon1, lat2, lon2) -> float:
    R = 6371000.0
    f1, f2 = math.radians(lat1), math.radians(lat2)
    df = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(df/2)**2 + math.cos(f1)*math.cos(f2)*math.sin(dl/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


def en_iyi_noktalar(
    npz_dosya: str,
    n: int = 5,
    merkez_lat: float = None,
    merkez_lon: float = None,
) -> list:
    """
    alan_verisi.npz'den en güvenli N rally noktasını seçer.

    Seçim kriteri:
      1. Sadece durum=='GUVENLI' (eğim ≤ 5°) noktalar
      2. Eğime göre sırala (küçükten büyüğe)
      3. MIN_ARALIK_M filtresi: seçilen noktalar birbirine çok yakın olmasın
         (aynı düzlüğü birden fazla temsil etme)
      4. merkez verilmişse: önce merkeze yakın noktaları dene

    Dönüş: [{"lat", "lon", "egim", "id"}, ...]  — en fazla n eleman
    """
    data = np.load(npz_dosya, allow_pickle=True)
    noktalar = json.loads(str(data["noktalar_json"][0]))

    guvenli = [n for n in noktalar if n.get("durum") == "GUVENLI"]
    if not guvenli:
        raise RuntimeError("alan_verisi.npz içinde güvenli nokta yok.")

    # Eğime göre sırala
    guvenli.sort(key=lambda x: x["egim"])

    # Merkez varsa önce yakın olanları tercih et (ama eğim öncelikli kalır)
    if merkez_lat is not None:
        guvenli.sort(key=lambda x: (
            x["egim"],
            _haversine(merkez_lat, merkez_lon, x["lat"], x["lon"])
        ))

    # Kümelenme filtresi: seçilen noktalar birbirine MIN_ARALIK_M'den uzak olsun
    secilen = []
    for nokta in guvenli:
        cok_yakin = any(
            _haversine(nokta["lat"], nokta["lon"], s["lat"], s["lon"]) < MIN_ARALIK_M
            for s in secilen
        )
        if not cok_yakin:
            secilen.append(nokta)
        if len(secilen) >= n:
            break

    print(f"  {len(secilen)} rally noktası seçildi "
          f"({len(guvenli)} güvenli nokta arasından, aralık ≥ {MIN_ARALIK_M}m)")
    for i, s in enumerate(secilen):
        print(f"    R{i+1}: {s['lat']:.6f}, {s['lon']:.6f}  eğim={s['egim']:.1f}°")

    return secilen


# ── MAVLink yükleme ───────────────────────────────────────────────────────────

def _bekle_parametre_ack(conn, timeout: float = 5.0) -> bool:
    """PARAM_VALUE mesajı bekler — RALLY_TOTAL set sonrası onay."""
    bitis = time.time() + timeout
    while time.time() < bitis:
        msg = conn.recv_match(type="PARAM_VALUE", blocking=True, timeout=0.5)
        if msg and msg.param_id.startswith("RALLY_TOTAL"):
            return True
    return False


def rally_yukle(
    noktalar: list,
    baglanti_dizesi: str = "tcp:127.0.0.1:5762",
    irtifa_m: int = VARSAYILAN_IRTIFA,
    dogrula: bool = True,
    conn=None,
) -> bool:
    """
    Noktaları ArduPilot'a Rally Point olarak yükler.

    Protokol:
      1. RALLY_TOTAL parametresini len(noktalar) olarak set et
      2. Her nokta için RALLY_POINT mesajı gönder
      3. dogrula=True ise RALLY_FETCH_POINT ile oku ve karşılaştır

    conn: zaten açık ve heartbeat almış bir mavutil bağlantısı verilirse
    (örn. GCS'nin ana bağlantısı) kullanılır — YENİ bir soket AÇILMAZ.
    ArduPilot SITL'in TCP portu genelde tek istemciyle sınırlı olduğundan,
    GCS zaten bağlıyken ikinci bir bağlantı denemek heartbeat alamayıp
    zaman aşımına uğrar.

    Dönüş: True → başarı, False → hata
    """
    if not noktalar:
        raise ValueError("Nokta listesi boş.")
    if len(noktalar) > MAX_RALLY:
        print(f"Uyarı: {len(noktalar)} nokta → ilk {MAX_RALLY} alınıyor.")
        noktalar = noktalar[:MAX_RALLY]

    kendi_baglantisi = conn is None
    if kendi_baglantisi:
        if not MAVLINK_MEVCUT:
            raise ImportError("pip install pymavlink")
        print(f"\nArduPilot'a bağlanılıyor: {baglanti_dizesi}")
        conn = mavutil.mavlink_connection(
            baglanti_dizesi,
            autoreconnect=False,
            source_system=254,   # GCS sistem ID
        )
        print("  Heartbeat bekleniyor...")
        msg = conn.wait_heartbeat(timeout=10)
        if msg is None:
            print("HATA: Heartbeat alınamadı. Bağlantı kesildi.")
            return False
        print(f"  Bağlandı (sys={conn.target_system}, comp={conn.target_component})")
    else:
        print(f"\nMevcut MAVLink bağlantısı yeniden kullanılıyor "
              f"(sys={conn.target_system}, comp={conn.target_component})")

    n = len(noktalar)
    irtifa_cm = irtifa_m * 100   # RALLY_POINT alt alanı cm (ArduPilot legacy)

    # ── Adım 1: RALLY_TOTAL parametresini set et ────────────────────────────
    print(f"\nRALLY_TOTAL = {n} ayarlanıyor...")
    conn.mav.param_set_send(
        conn.target_system,
        conn.target_component,
        b"RALLY_TOTAL",
        float(n),
        mavutil.mavlink.MAV_PARAM_TYPE_INT8,
    )
    if not _bekle_parametre_ack(conn, timeout=5.0):
        print("  Uyarı: RALLY_TOTAL ACK alınamadı, devam ediliyor.")
    else:
        print("  RALLY_TOTAL onaylandı.")

    # ── Adım 2: Her rally noktasını gönder ──────────────────────────────────
    print(f"\n{n} rally noktası yükleniyor...")
    for i, nokta in enumerate(noktalar):
        lat_int = int(nokta["lat"] * 1e7)
        lng_int = int(nokta["lon"] * 1e7)

        conn.mav.rally_point_send(
            conn.target_system,
            conn.target_component,
            i,                  # idx
            n,                  # count (toplam)
            lat_int,            # lat (degE7)
            lng_int,            # lng (degE7)
            irtifa_cm,          # alt (cm, relative to home)
            irtifa_cm,          # break_alt (cm) — aynı irtifada tut
            0,                  # land_dir (centideg, 0=otomatik)
            0,                  # flags
        )
        time.sleep(0.1)   # 100ms arayla gönder (buffer taşmasın)
        print(f"  R{i+1} gönderildi: {nokta['lat']:.6f}, {nokta['lon']:.6f}")

    # ── Adım 3: Doğrulama ───────────────────────────────────────────────────
    if dogrula:
        print("\nDoğrulama — RALLY_FETCH_POINT ile geri okunuyor...")
        basarili = 0
        for i in range(n):
            conn.mav.rally_fetch_point_send(
                conn.target_system,
                conn.target_component,
                i,
            )
            yanit = conn.recv_match(type="RALLY_POINT", blocking=True, timeout=3.0)
            if yanit and yanit.idx == i:
                okunan_lat = yanit.lat / 1e7
                okunan_lon = yanit.lng / 1e7
                beklenen_lat = noktalar[i]["lat"]
                beklenen_lon = noktalar[i]["lon"]
                fark_m = _haversine(okunan_lat, okunan_lon, beklenen_lat, beklenen_lon)
                if fark_m < 5.0:   # 5m tolerans
                    print(f"  R{i+1} ✓ ({fark_m:.1f}m sapma)")
                    basarili += 1
                else:
                    print(f"  R{i+1} ✗ Büyük sapma: {fark_m:.1f}m")
            else:
                print(f"  R{i+1} ✗ Yanıt alınamadı")

        print(f"\nSonuç: {basarili}/{n} rally noktası doğrulandı.")
        return basarili == n

    print(f"\n{n} rally noktası yüklendi (doğrulama atlandı).")
    return True


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="ArduPilot'a Rally Point yükle (alan_verisi.npz'den)"
    )
    parser.add_argument("--npz",        default="alan_verisi.npz",
                        help="Pre-computed alan verisi (ucus_alani_hazirla.py çıktısı)")
    parser.add_argument("--baglanti",   default="tcp:127.0.0.1:5762",
                        help="MAVLink bağlantı dizesi")
    parser.add_argument("--n",          type=int, default=5,
                        help="Yüklenecek rally noktası sayısı (maks 10)")
    parser.add_argument("--irtifa",     type=int, default=VARSAYILAN_IRTIFA,
                        help="Rally iniş irtifası (metre, ev üzerinde)")
    parser.add_argument("--merkez-lat", type=float, default=None,
                        dest="merkez_lat",
                        help="Merkez enlemi (daha yakın noktaları öncelendir)")
    parser.add_argument("--merkez-lon", type=float, default=None,
                        dest="merkez_lon",
                        help="Merkez boylamı")
    parser.add_argument("--no-dogrula", action="store_true",
                        help="Doğrulama adımını atla")
    args = parser.parse_args()

    print(f"Alan verisi: {args.npz}")
    noktalar = en_iyi_noktalar(
        args.npz, n=args.n,
        merkez_lat=args.merkez_lat,
        merkez_lon=args.merkez_lon,
    )

    basarili = rally_yukle(
        noktalar,
        baglanti_dizesi=args.baglanti,
        irtifa_m=args.irtifa,
        dogrula=not args.no_dogrula,
    )
    sys.exit(0 if basarili else 1)


if __name__ == "__main__":
    main()
