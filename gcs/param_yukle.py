"""param_yukle.py
Doğuş Üniversitesi LÖP — ArduPilot Parametre Yedekleme / Geri Yükleme

Tüm ArduPilot parametrelerini JSON olarak kaydeder.
Konfigürasyon değişikliği veya kaza sonrası geri yükleme için kullanılır.

Kullanım (komut satırı):
    # Tüm parametreleri yedekle
    python param_yukle.py yedekle --baglanti tcp:127.0.0.1:5762 --cikti params_2026.json

    # Belirli prefix'lerle yedekle
    python param_yukle.py yedekle --prefix BATT FS EKF

    # Geri yükle
    python param_yukle.py geri-yukle --json params_2026.json --baglanti tcp:127.0.0.1:5762

    # Sadece güvenlik parametrelerini geri yükle
    python param_yukle.py geri-yukle --json params_2026.json --prefix FS BATT

Kullanım (import):
    from param_yukle import param_yedekle, param_geri_yukle
    param_yedekle("tcp:127.0.0.1:5762", "yedek.json")
    param_geri_yukle("yedek.json", "tcp:127.0.0.1:5762")
"""

import sys
import json
import time
import argparse
import datetime
import os

try:
    from pymavlink import mavutil
    MAVLINK_MEVCUT = True
except ImportError:
    MAVLINK_MEVCUT = False

ZAMAN_ASIMI_S  = 30.0    # Tüm parametre indirme timeout
PARAM_SET_ARALIK = 0.05  # Her PARAM_SET arasında bekleme (sn)


# ── Bağlantı yardımcısı ───────────────────────────────────────────────────────

def _baglan(baglanti_dizesi: str):
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
        raise RuntimeError("Heartbeat alınamadı — bağlantı başarısız.")
    print(f"  Bağlandı (sys={conn.target_system}, comp={conn.target_component})")
    return conn


# ── Yedekleme ─────────────────────────────────────────────────────────────────

def param_yedekle(
    baglanti_dizesi: str = "tcp:127.0.0.1:5762",
    cikti_dosya: str = "param_yedek.json",
    prefix_filtre: list = None,
) -> dict:
    """
    Tüm ArduPilot parametrelerini indirir ve JSON dosyasına kaydeder.

    Parametreler:
        baglanti_dizesi : MAVLink bağlantı dizesi
        cikti_dosya     : Kaydedilecek JSON dosyası yolu
        prefix_filtre   : ["BATT", "FS"] gibi prefix listesi — None ise hepsi

    Dönüş: {param_ad: deger, ...}  sözlüğü
    """
    conn = _baglan(baglanti_dizesi)

    print("\nParametreler isteniyor (PARAM_REQUEST_LIST)...")
    conn.mav.param_request_list_send(
        conn.target_system,
        conn.target_component,
    )

    parametreler: dict[str, float] = {}
    toplam   = None
    bitis    = time.time() + ZAMAN_ASIMI_S
    son_gelen = time.time()

    while time.time() < bitis:
        msg = conn.recv_match(type="PARAM_VALUE", blocking=True, timeout=2.0)
        if msg is None:
            # 5sn veri gelmediyse bitir
            if time.time() - son_gelen > 5.0:
                break
            continue

        son_gelen = time.time()
        ad    = msg.param_id.strip("\x00")
        deger = float(msg.param_value)
        if toplam is None and msg.param_count > 0:
            toplam = msg.param_count
        parametreler[ad] = deger

        # İlerleme
        n = len(parametreler)
        if toplam and n % 50 == 0:
            print(f"  {n}/{toplam} parametre alındı ({100*n//toplam}%)")

        # Hepsi alındı mı?
        if toplam and len(parametreler) >= toplam:
            break

    print(f"\n  Toplam {len(parametreler)} parametre alındı"
          + (f" / {toplam}" if toplam else ""))

    # Prefix filtresi
    if prefix_filtre:
        prefix_filtre = [p.upper() for p in prefix_filtre]
        filtrelendi = {
            k: v for k, v in parametreler.items()
            if any(k.startswith(p) for p in prefix_filtre)
        }
        print(f"  Prefix filtresi [{', '.join(prefix_filtre)}]: "
              f"{len(filtrelendi)} parametre seçildi")
        parametreler = filtrelendi

    if not parametreler:
        raise RuntimeError("Hiç parametre alınamadı.")

    # JSON kaydet
    cikti = {
        "_meta": {
            "tarih":   datetime.datetime.now().isoformat(timespec="seconds"),
            "baglanti": baglanti_dizesi,
            "toplam":  len(parametreler),
        },
        "parametreler": parametreler,
    }
    with open(cikti_dosya, "w", encoding="utf-8") as f:
        json.dump(cikti, f, indent=2, ensure_ascii=False)

    boyut_kb = os.path.getsize(cikti_dosya) // 1024
    print(f"\n✓ Yedek kaydedildi: {cikti_dosya}  ({len(parametreler)} parametre, {boyut_kb} KB)")
    return parametreler


# ── Geri yükleme ──────────────────────────────────────────────────────────────

def param_geri_yukle(
    json_dosya: str,
    baglanti_dizesi: str = "tcp:127.0.0.1:5762",
    prefix_filtre: list = None,
    kuru_calistir: bool = False,
) -> int:
    """
    JSON yedek dosyasından parametreleri ArduPilot'a yükler.

    Parametreler:
        json_dosya      : param_yedekle() ile oluşturulan JSON
        baglanti_dizesi : MAVLink bağlantı dizesi
        prefix_filtre   : Sadece belirtilen prefix'ler geri yüklensin
        kuru_calistir   : True → gerçek PARAM_SET göndermez, sadece listeler

    Dönüş: Gönderilen parametre sayısı
    """
    with open(json_dosya, encoding="utf-8") as f:
        veri = json.load(f)

    parametreler: dict = veri.get("parametreler", veri)  # eski format uyumluluğu
    meta = veri.get("_meta", {})

    print(f"\nYedek: {json_dosya}")
    if meta:
        print(f"  Tarih   : {meta.get('tarih', '?')}")
        print(f"  Toplam  : {meta.get('toplam', len(parametreler))} parametre")

    # Prefix filtresi
    if prefix_filtre:
        prefix_filtre = [p.upper() for p in prefix_filtre]
        parametreler = {
            k: v for k, v in parametreler.items()
            if any(k.startswith(p) for p in prefix_filtre)
        }
        print(f"  Filtre [{', '.join(prefix_filtre)}]: {len(parametreler)} parametre seçildi")

    if not parametreler:
        print("  Uyarı: Geri yüklenecek parametre yok.")
        return 0

    if kuru_calistir:
        print(f"\n[Kuru çalıştırma] {len(parametreler)} parametre gönderilecekti:")
        for ad, val in list(parametreler.items())[:20]:
            print(f"  {ad:24s} = {val}")
        if len(parametreler) > 20:
            print(f"  ... ve {len(parametreler)-20} parametre daha")
        return len(parametreler)

    conn = _baglan(baglanti_dizesi)

    print(f"\n{len(parametreler)} parametre gönderiliyor...")
    gonderilen = 0
    for ad, deger in parametreler.items():
        conn.mav.param_set_send(
            conn.target_system,
            conn.target_component,
            ad.encode("utf-8"),
            float(deger),
            mavutil.mavlink.MAV_PARAM_TYPE_REAL32,
        )
        gonderilen += 1
        time.sleep(PARAM_SET_ARALIK)

        if gonderilen % 50 == 0:
            print(f"  {gonderilen}/{len(parametreler)} gönderildi")

    print(f"\n✓ {gonderilen} parametre gönderildi.")
    print("  Not: Yeniden başlatma gerektirebilir (EEPROM parametreleri).")
    return gonderilen


# ── Fark raporu ───────────────────────────────────────────────────────────────

def param_fark(json_dosya: str, baglanti_dizesi: str = "tcp:127.0.0.1:5762") -> list:
    """
    JSON yedek ile mevcut ArduPilot parametrelerini karşılaştırır.
    Farklı olanları döndürür: [{"ad", "yedek", "guncel"}, ...]
    """
    conn = _baglan(baglanti_dizesi)
    conn.mav.param_request_list_send(conn.target_system, conn.target_component)

    guncel: dict[str, float] = {}
    bitis = time.time() + ZAMAN_ASIMI_S
    toplam = None
    while time.time() < bitis:
        msg = conn.recv_match(type="PARAM_VALUE", blocking=True, timeout=2.0)
        if msg is None:
            break
        ad = msg.param_id.strip("\x00")
        guncel[ad] = float(msg.param_value)
        if msg.param_count > 0:
            toplam = msg.param_count
        if toplam and len(guncel) >= toplam:
            break

    with open(json_dosya, encoding="utf-8") as f:
        veri = json.load(f)
    yedek: dict = veri.get("parametreler", veri)

    farklar = []
    for ad, yedek_val in yedek.items():
        guncel_val = guncel.get(ad)
        if guncel_val is None:
            farklar.append({"ad": ad, "yedek": yedek_val, "guncel": None})
        elif abs(guncel_val - yedek_val) > 1e-4:
            farklar.append({"ad": ad, "yedek": yedek_val, "guncel": guncel_val})
    return farklar


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="ArduPilot parametre yedekleme / geri yükleme",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    alt = parser.add_subparsers(dest="komut", required=True)

    # yedekle
    yp = alt.add_parser("yedekle", help="Parametreleri JSON'a kaydet")
    yp.add_argument("--baglanti", default="tcp:127.0.0.1:5762")
    yp.add_argument("--cikti",    default="", help="JSON çıktı dosyası")
    yp.add_argument("--prefix",   nargs="*", default=None,
                    help="Sadece bu prefix'ler (örn: BATT FS EKF)")

    # geri-yukle
    gp = alt.add_parser("geri-yukle", help="JSON yedekten parametreleri yükle")
    gp.add_argument("--json",     required=True)
    gp.add_argument("--baglanti", default="tcp:127.0.0.1:5762")
    gp.add_argument("--prefix",   nargs="*", default=None)
    gp.add_argument("--kuru",     action="store_true",
                    help="Gerçek gönderme yapma, sadece listele")

    # fark
    fp = alt.add_parser("fark", help="Yedek ile mevcut parametreleri karşılaştır")
    fp.add_argument("--json",     required=True)
    fp.add_argument("--baglanti", default="tcp:127.0.0.1:5762")

    args = parser.parse_args()

    if args.komut == "yedekle":
        cikti = args.cikti or \
            f"param_yedek_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        param_yedekle(args.baglanti, cikti, prefix_filtre=args.prefix)

    elif args.komut == "geri-yukle":
        n = param_geri_yukle(
            args.json, args.baglanti,
            prefix_filtre=args.prefix,
            kuru_calistir=args.kuru,
        )
        sys.exit(0 if n > 0 else 1)

    elif args.komut == "fark":
        farklar = param_fark(args.json, args.baglanti)
        if not farklar:
            print("Fark yok — parametreler yedekle uyuşuyor.")
        else:
            print(f"\n{len(farklar)} farklı parametre:\n")
            print(f"  {'Parametre':<24} {'Yedek':>12} {'Güncel':>12}")
            print("  " + "-" * 50)
            for f in farklar:
                yedek_s  = f"{f['yedek']:.4f}" if f["yedek"] is not None else "?"
                guncel_s = f"{f['guncel']:.4f}" if f["guncel"] is not None else "YOK"
                print(f"  {f['ad']:<24} {yedek_s:>12} {guncel_s:>12}")
        sys.exit(0)


if __name__ == "__main__":
    main()
