"""fence_yukle.py
Doğuş Üniversitesi LÖP — ArduPilot AC_Fence Yükleme Modülü

Bounding box'tan dörtgen polygon fence oluşturur ve ArduPilot'a yükler.
Drone bounding box dışına çıkarsa FENCE_ACTION'a göre tepki verir
(varsayılan: 1 = RTL).

Protokol: Legacy FENCE_POINT (msg 160) + FENCE_TOTAL / FENCE_ENABLE parametreleri
ArduPilot 3.x ve 4.x ile uyumlu.

Kullanım (komut satırı):
    python fence_yukle.py --alan 40.9 41.1 28.8 29.0 --baglanti tcp:127.0.0.1:5762

Kullanım (import):
    from fence_yukle import dikdortgen_cit, fence_yukle
    noktalar = dikdortgen_cit(40.9, 41.1, 28.8, 29.0)
    fence_yukle(noktalar, "tcp:127.0.0.1:5762", alt_max=120.0)

Kullanım (NPZ'den otomatik):
    from fence_yukle import fence_yukle_npz
    fence_yukle_npz("alan_verisi.npz", "tcp:127.0.0.1:5762")
"""

import sys
import time
import argparse

import numpy as np

# GCS'nin ana penceresinden bir QThread içinde çağrıldığında stdout, Windows
# konsolunun varsayılan kod sayfasını (cp1254/cp1252 vb.) miras alır — bu kod
# sayfaları "✓"/"✗" gibi karakterleri içermediğinden print() UnicodeEncodeError
# fırlatıp yükleme işlemini "hata" gibi gösteriyordu. stdout'u UTF-8'e
# yeniden yapılandırmak (mümkünse) veya en azından kodlanamayan karakterleri
# sessizce değiştirmek bu sınıf hataları tamamen ortadan kaldırır.
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

VARSAYILAN_ALT_MAX = 120.0   # metre (AGL)
VARSAYILAN_EYLEM   = 1       # 0=sadece mesaj, 1=RTL, 2=LAND, 3=Smart RTL
EYLEM_ADLARI = {0: "Sadece Mesaj", 1: "RTL", 2: "LAND", 3: "Smart RTL"}


# ── Polygon oluşturma ─────────────────────────────────────────────────────────

def dikdortgen_cit(
    lat_min: float, lat_max: float,
    lon_min: float, lon_max: float,
) -> list:
    """
    4 köşeli kapalı polygon (5 nokta: son nokta = ilk nokta).

    ArduPilot FENCE_POINT protokolü: son nokta = ilk nokta (polygon kapatma).
    Sıralama: SW → SE → NE → NW → SW

    Dönüş: [{"lat": float, "lon": float, "isim": str}, ...]
    """
    return [
        {"lat": lat_min, "lon": lon_min, "isim": "SW"},
        {"lat": lat_min, "lon": lon_max, "isim": "SE"},
        {"lat": lat_max, "lon": lon_max, "isim": "NE"},
        {"lat": lat_max, "lon": lon_min, "isim": "NW"},
        {"lat": lat_min, "lon": lon_min, "isim": "SW (kapatma)"},
    ]


def fence_yukle_npz(npz_dosya: str, baglanti_dizesi: str, conn=None, **kwargs) -> bool:
    """
    alan_verisi.npz'deki bounds'tan otomatik fence polygon oluştur ve yükle.
    kwargs → fence_yukle() fonksiyonuna iletilir.

    conn: zaten açık bir mavutil bağlantısı verilirse (örn. GCS'nin ana
    bağlantısı) YENİ bir soket açılmaz — bu, ArduPilot SITL'in TCP portunun
    (5762 vb.) genellikle tek bir istemciyle sınırlı olması nedeniyle önemli:
    GCS zaten bağlıyken ikinci bir mavutil.mavlink_connection() denemesi,
    ArduPilot bağlantıyı kabul etmediği için heartbeat bekleyip zaman aşımına
    uğrar (~10sn) ve yükleme sessizce başarısız görünür.

    NPZ bounds formatı: [lon_min, lat_min, lon_max, lat_max]
    """
    data = np.load(npz_dosya, allow_pickle=True)
    b    = data["bounds"]   # [lon_min, lat_min, lon_max, lat_max]
    lon_min, lat_min, lon_max, lat_max = (
        float(b[0]), float(b[1]), float(b[2]), float(b[3])
    )
    print(f"[Fence] NPZ bounds: LAT [{lat_min:.5f}, {lat_max:.5f}]  "
          f"LON [{lon_min:.5f}, {lon_max:.5f}]")
    noktalar = dikdortgen_cit(lat_min, lat_max, lon_min, lon_max)
    return fence_yukle(noktalar, baglanti_dizesi, conn=conn, **kwargs)


# ── MAVLink yardımcısı ────────────────────────────────────────────────────────

def _param_set(conn, param_id: str, value: float, param_type=None):
    """PARAM_SET gönder ve kısa bekle."""
    if param_type is None:
        param_type = mavutil.mavlink.MAV_PARAM_TYPE_REAL32
    conn.mav.param_set_send(
        conn.target_system,
        conn.target_component,
        param_id.encode(),
        float(value),
        param_type,
    )
    time.sleep(0.3)


# ── MAVLink yükleme ───────────────────────────────────────────────────────────

def fence_yukle(
    noktalar: list,
    baglanti_dizesi: str = "tcp:127.0.0.1:5762",
    alt_max: float = VARSAYILAN_ALT_MAX,
    fence_action: int = VARSAYILAN_EYLEM,
    dogrula: bool = False,
    conn=None,
) -> bool:
    """
    Noktaları ArduPilot'a AC_Fence polygon olarak yükler.

    Adımlar:
      1. FENCE_TOTAL = len(noktalar) parametresini set et
      2. Her nokta için FENCE_POINT (msg 160) gönder
      3. FENCE_ENABLE=1, FENCE_ACTION, FENCE_ALT_MAX parametrelerini ayarla
      4. (opsiyonel) FENCE_FETCH_POINT ile doğrula

    conn: zaten açık ve heartbeat almış bir mavutil bağlantısı verilirse
    (örn. GCS'nin ana bağlantısı) kullanılır — YENİ bir soket AÇILMAZ.
    Verilmezse (CLI kullanımı gibi) eskisi gibi kendi bağlantısını açar.

    Dönüş: True → başarı, False → hata
    """
    if not noktalar:
        raise ValueError("Nokta listesi boş.")

    n = len(noktalar)
    kendi_baglantisi = conn is None

    if kendi_baglantisi:
        if not MAVLINK_MEVCUT:
            raise ImportError("pip install pymavlink")
        print(f"\nArduPilot'a bağlanılıyor: {baglanti_dizesi}")
        conn = mavutil.mavlink_connection(
            baglanti_dizesi,
            autoreconnect=False,
            source_system=254,
        )
        print("  Heartbeat bekleniyor...")
        msg = conn.wait_heartbeat(timeout=10)
        if msg is None:
            print("HATA: Heartbeat alınamadı. Bağlantı başarısız.")
            return False
        print(f"  Bağlandı (sys={conn.target_system}, comp={conn.target_component})")
    else:
        print(f"\nMevcut MAVLink bağlantısı yeniden kullanılıyor "
              f"(sys={conn.target_system}, comp={conn.target_component})")

    # ── Adım 1: FENCE_TOTAL ──────────────────────────────────────────────────
    print(f"\nFENCE_TOTAL = {n} ayarlanıyor...")
    _param_set(conn, "FENCE_TOTAL", float(n),
               mavutil.mavlink.MAV_PARAM_TYPE_INT8)

    # ── Adım 2: Fence noktaları ──────────────────────────────────────────────
    print(f"{n} fence noktası yükleniyor...")
    for i, nokta in enumerate(noktalar):
        conn.mav.fence_point_send(
            conn.target_system,
            conn.target_component,
            i,                  # idx
            n,                  # count
            nokta["lat"],
            nokta["lon"],
        )
        time.sleep(0.15)
        isim = nokta.get("isim", f"#{i}")
        print(f"  F{i} ({isim}): {nokta['lat']:.6f}, {nokta['lon']:.6f}")

    # ── Adım 3: Parametreler ─────────────────────────────────────────────────
    eylem_ad = EYLEM_ADLARI.get(fence_action, str(fence_action))
    print(f"\nFENCE_ENABLE=1  FENCE_ACTION={fence_action} ({eylem_ad})  "
          f"FENCE_ALT_MAX={alt_max}m ayarlanıyor...")
    _param_set(conn, "FENCE_ENABLE",  1.0,
               mavutil.mavlink.MAV_PARAM_TYPE_INT8)
    _param_set(conn, "FENCE_ACTION",  float(fence_action),
               mavutil.mavlink.MAV_PARAM_TYPE_INT8)
    _param_set(conn, "FENCE_ALT_MAX", alt_max)

    # ── Adım 4: Doğrulama (opsiyonel) ────────────────────────────────────────
    if dogrula:
        print("\nDoğrulama — FENCE_FETCH_POINT ile geri okunuyor...")
        basarili_d = 0
        for i in range(n):
            conn.mav.fence_fetch_point_send(
                conn.target_system,
                conn.target_component,
                i,
            )
            yanit = conn.recv_match(type="FENCE_POINT", blocking=True, timeout=3.0)
            if yanit and yanit.idx == i:
                fark_lat = abs(yanit.lat - noktalar[i]["lat"])
                fark_lon = abs(yanit.lng - noktalar[i]["lon"])
                if fark_lat < 1e-5 and fark_lon < 1e-5:
                    print(f"  F{i} ✓")
                    basarili_d += 1
                else:
                    print(f"  F{i} ✗ Sapma dlat={fark_lat:.7f} dlon={fark_lon:.7f}")
            else:
                print(f"  F{i} ✗ Yanıt alınamadı")
        print(f"\nSonuç: {basarili_d}/{n} fence noktası doğrulandı.")
        return basarili_d == n

    print(f"\n✓ AC_Fence yüklendi — {n} nokta, eylem: {eylem_ad}, "
          f"alt_max: {alt_max}m")
    return True


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description=(
            "ArduPilot'a AC_Fence polygon yükle\n"
            "Bounding box'tan dörtgen fence oluşturur, FENCE_ENABLE=1 ayarlar."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument(
        "--alan", nargs=4, type=float,
        metavar=("LAT_MIN", "LAT_MAX", "LON_MIN", "LON_MAX"),
        help="Bounding box koordinatları",
    )
    grp.add_argument(
        "--npz", type=str, default=None,
        help="alan_verisi.npz — bounds otomatik okunur (ucus_alani_hazirla.py çıktısı)",
    )
    parser.add_argument(
        "--baglanti", default="tcp:127.0.0.1:5762",
        help="MAVLink bağlantı dizesi",
    )
    parser.add_argument(
        "--alt-max", type=float, default=VARSAYILAN_ALT_MAX,
        dest="alt_max",
        help=f"Maksimum irtifa (metre AGL, varsayılan={VARSAYILAN_ALT_MAX})",
    )
    parser.add_argument(
        "--eylem", type=int, default=VARSAYILAN_EYLEM,
        help="Fence ihlal eylemi: 0=mesaj 1=RTL(varsayılan) 2=LAND 3=SmartRTL",
    )
    parser.add_argument(
        "--dogrula", action="store_true",
        help="FENCE_FETCH_POINT ile yüklenen noktaları doğrula",
    )
    args = parser.parse_args()

    if args.alan:
        lat_min, lat_max, lon_min, lon_max = args.alan
        noktalar = dikdortgen_cit(lat_min, lat_max, lon_min, lon_max)
        basarili = fence_yukle(
            noktalar, args.baglanti,
            alt_max=args.alt_max, fence_action=args.eylem,
            dogrula=args.dogrula,
        )
    else:
        basarili = fence_yukle_npz(
            args.npz, args.baglanti,
            alt_max=args.alt_max, fence_action=args.eylem,
            dogrula=args.dogrula,
        )

    sys.exit(0 if basarili else 1)


if __name__ == "__main__":
    main()
