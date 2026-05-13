"""
ucus_alani_hazirla.py  —  v2 (AWS S3 anonim erişim)
Doğuş Üniversitesi LÖP — Uçuş Öncesi Alan Hazırlama Scripti

Uçuştan ÖNCE bir kez çalıştırılır:
  1. Copernicus GLO-30 DEM'i AWS S3'ten indir  ← kimlik bilgisi GEREKMİYOR
  2. Eğim haritası hesapla (Horn yöntemi, numpy vektörize)
  3. Güvenli noktaları otomatik tespit et (eğim ≤ 5°, OSM engel maskesi opsiyonel)
  4. alan_verisi.npz  → AlanInisKarar tarafından uçuş anında kullanılır
  5. ArduPilot terrain .DAT tile'ları üret  → SD karta kopyala (opsiyonel)

Kullanım:
    # Temel — kimlik bilgisi YOK
    python ucus_alani_hazirla.py --alan 40.9 41.1 28.8 29.0

    # Tüm seçenekler
    python ucus_alani_hazirla.py \
        --alan 40.9 41.1 28.8 29.0 \
        --cikti alan_verisi.npz \
        --dem-dosya alan_dem.tif \
        --adim 5 \
        --gorsel \
        --osm \
        --terrain-dat terrain_sd/ \
        --spacing 30

Gereksinimler:
    pip install boto3 rasterio numpy

İsteğe bağlı:
    pip install overpy matplotlib
"""

import os
import sys
import json
import math
import struct
import argparse
import tempfile
import shutil
import numpy as np

# ── Bağımlılık kontrolleri ────────────────────────────────────────────────────

try:
    import boto3
    from botocore import UNSIGNED
    from botocore.client import Config as BotoConfig
    BOTO3_MEVCUT = True
except ImportError:
    BOTO3_MEVCUT = False

try:
    import rasterio
    from rasterio.merge import merge as rasterio_merge
    RASTERIO_MEVCUT = True
except ImportError:
    RASTERIO_MEVCUT = False

try:
    import overpy as _overpy
    OVERPY_MEVCUT = True
except ImportError:
    OVERPY_MEVCUT = False

try:
    import matplotlib.pyplot as plt
    import matplotlib.colors as mc
    MATPLOTLIB_MEVCUT = True
except ImportError:
    MATPLOTLIB_MEVCUT = False

# ── Sabitler ─────────────────────────────────────────────────────────────────

GUVENLI_EGIM  = 5.0    # derece
RISKLI_EGIM   = 15.0   # derece
PIKSEL_M      = 30.0   # GLO-30 nominal piksel boyutu (metre)

# AWS S3 — anonim erişim, kayıt gerekmez
# https://copernicus-dem-30m.s3.amazonaws.com/readme.html
AWS_BUCKET_30M = "copernicus-dem-30m"

# OSM engel tipleri
_OSM_FILTRELER = [
    '"building"', '"landuse"="forest"', '"natural"="wood"',
    '"natural"="water"', '"waterway"~"river|canal|stream"',
    '"landuse"="residential"', '"landuse"="industrial"', '"aeroway"',
]
OSM_ZAMAN_ASIMI = 15


# ── 1. AWS S3 anonim indirme ──────────────────────────────────────────────────

def _s3_anonim():
    """Kimlik bilgisi gerektirmeyen boto3 S3 istemcisi."""
    if not BOTO3_MEVCUT:
        raise ImportError("pip install boto3")
    return boto3.client(
        "s3",
        config=BotoConfig(signature_version=UNSIGNED),
        region_name="eu-central-1",
    )


def _tile_prefix(lat_floor: int, lon_floor: int) -> str:
    """
    Taban lat/lon → tile prefix.
    GLO-30 bucket adlandırması:
      s3://copernicus-dem-30m/Copernicus_DSM_COG_10_N41_00_E028_00_DEM/
    """
    lh = "N" if lat_floor >= 0 else "S"
    oh = "E" if lon_floor >= 0 else "W"
    return (f"Copernicus_DSM_COG_10_{lh}{abs(lat_floor):02d}_00"
            f"_{oh}{abs(lon_floor):03d}_00_DEM")


def _gereken_tileler(lat_min, lat_max, lon_min, lon_max) -> list:
    """Bounding box'ı kapsayan 1°×1° tile (lat_floor, lon_floor) listesi."""
    tileler = []
    for lat in range(int(math.floor(lat_min)), int(math.ceil(lat_max))):
        for lon in range(int(math.floor(lon_min)), int(math.ceil(lon_max))):
            tileler.append((lat, lon))
    return tileler


def dem_indir(
    lat_min: float, lat_max: float,
    lon_min: float, lon_max: float,
    cikti:   str = "alan_dem.tif",
) -> str:
    """
    Copernicus GLO-30 DEM'i AWS S3'ten anonim olarak indirir.
    Birden fazla 1°×1° tile gerekiyorsa birleştirir (mosaic).
    Döndürür: GeoTIFF dosya yolu.
    """
    if not RASTERIO_MEVCUT:
        raise ImportError("pip install rasterio")

    s3 = _s3_anonim()
    tileler = _gereken_tileler(lat_min, lat_max, lon_min, lon_max)
    print(f"[DEM] {len(tileler)} tile gerekiyor  "
          f"BB: [{lat_min},{lat_max}] × [{lon_min},{lon_max}]")

    with tempfile.TemporaryDirectory(prefix="lop_dem_") as tmp:
        indirilen = []
        for lat_f, lon_f in tileler:
            prefix   = _tile_prefix(lat_f, lon_f)
            s3_key   = f"{prefix}/{prefix}.tif"
            yol      = os.path.join(tmp, f"{prefix}.tif")

            print(f"  ↓  s3://{AWS_BUCKET_30M}/{s3_key}")
            try:
                s3.download_file(AWS_BUCKET_30M, s3_key, yol)
                indirilen.append(yol)
            except Exception as e:
                print(f"  ⚠  Tile indirilemedi ({prefix}): {e}")

        if not indirilen:
            raise RuntimeError(
                "Hiç tile indirilemedi. Koordinatları ve internet bağlantısını kontrol et.\n"
                "Not: Armenia ve Azerbaijan tile'ları kamuya açık değil."
            )

        if len(indirilen) == 1:
            shutil.copy2(indirilen[0], cikti)
        else:
            print(f"  ⚙  {len(indirilen)} tile birleştiriliyor (mosaic)…")
            aciklar = [rasterio.open(f) for f in indirilen]
            try:
                mozaik, mozaik_tf = rasterio_merge(aciklar)
                profil = aciklar[0].profile.copy()
                profil.update(height=mozaik.shape[1],
                              width=mozaik.shape[2],
                              transform=mozaik_tf)
                with rasterio.open(cikti, "w", **profil) as dst:
                    dst.write(mozaik)
            finally:
                for f in aciklar:
                    f.close()

    print(f"  ✓  DEM kaydedildi: {cikti}  ({os.path.getsize(cikti)//1024} KB)")
    return cikti


# ── 2. DEM okuma ──────────────────────────────────────────────────────────────

def dem_oku(dem_dosya: str):
    """GeoTIFF → (dem_float32, rasterio_transform, bounds)"""
    if not RASTERIO_MEVCUT:
        raise ImportError("pip install rasterio")
    with rasterio.open(dem_dosya) as src:
        dem       = src.read(1).astype(np.float32)
        transform = src.transform
        bounds    = src.bounds
    dem[dem < -9000] = np.nan  # NoData maskeleme
    print(f"[DEM] Boyut: {dem.shape}  "
          f"(~{dem.shape[0]*PIKSEL_M/1000:.1f}km × {dem.shape[1]*PIKSEL_M/1000:.1f}km)")
    return dem, transform, bounds


# ── 3. Eğim haritası (Horn yöntemi, vektörize) ───────────────────────────────

def egim_hesapla(dem: np.ndarray, piksel_m: float = PIKSEL_M) -> np.ndarray:
    """
    Horn yöntemi ile eğim haritası (derece).
    3×3 konvolüsyon — np.gradient'e göre kenar etkileri daha az.
    """
    print("[EĞİM] Horn yöntemi ile hesaplanıyor…")
    pad = np.pad(dem, 1, mode="edge")

    nw = pad[:-2, :-2]; n = pad[:-2, 1:-1]; ne = pad[:-2, 2:]
    w  = pad[1:-1, :-2];                     e  = pad[1:-1, 2:]
    sw = pad[2:,  :-2]; s = pad[2:,  1:-1]; se = pad[2:,  2:]

    dzdx = ((ne + 2*e + se) - (nw + 2*w + sw)) / (8.0 * piksel_m)
    dzdy = ((sw + 2*s + se) - (nw + 2*n + ne)) / (8.0 * piksel_m)

    egim = np.degrees(np.arctan(np.sqrt(dzdx**2 + dzdy**2))).astype(np.float32)
    egim = np.where(np.isnan(dem), np.nan, egim)

    gecerli = int(np.sum(~np.isnan(egim)))
    if gecerli:
        guv_oran = float(np.nansum(egim <= GUVENLI_EGIM)) / gecerli * 100
        print(f"  Güvenli alan (≤{GUVENLI_EGIM}°): %{guv_oran:.1f}  "
              f"({gecerli * PIKSEL_M**2 / 1e6:.2f} km² toplam)")
    return egim


# ── 4. OSM engel maskesi ──────────────────────────────────────────────────────

def osm_engel_maskesi(
    egim:    np.ndarray,
    transform,
    lat_min: float, lat_max: float,
    lon_min: float, lon_max: float,
) -> np.ndarray:
    """
    Overpass API ile bina/orman/su poligonlarını çeker,
    engel olan pikselleri True olarak işaretler.
    overpy kurulu değilse sıfır maskesi döner (sessiz geçer).
    """
    maske = np.zeros(egim.shape, dtype=bool)
    if not OVERPY_MEVCUT:
        print("[OSM] overpy kurulu değil — engel maskesi atlandı.")
        return maske

    print("[OSM] Engel poligonları çekiliyor (Overpass API)…")
    try:
        api = _overpy.Overpass()
        filtreler_str = "\n  ".join(
            f"way[{f}]({lat_min:.6f},{lon_min:.6f},{lat_max:.6f},{lon_max:.6f});"
            for f in _OSM_FILTRELER
        )
        sorgu = (f"[out:json][timeout:{OSM_ZAMAN_ASIMI}];\n"
                 f"(\n  {filtreler_str}\n);\nout body;\n>;\nout skel qt;\n")
        sonuc     = api.query(sorgu)
        node_map  = {n.id: (float(n.lat), float(n.lon)) for n in sonuc.nodes}
        poligonlar = []
        for way in sonuc.ways:
            pts = [node_map[nid] for nid in way._node_ids if nid in node_map]
            if len(pts) >= 3:
                poligonlar.append(pts)
        print(f"  {len(poligonlar)} poligon alındı.")

        rows, cols = np.where(~np.isnan(egim))
        for r, c in zip(rows, cols):
            lon, lat = transform * (c, r)
            if any(_icinde_mi(lat, lon, p) for p in poligonlar):
                maske[r, c] = True

        print(f"  Engelli piksel: {maske.sum()}")
    except Exception as ex:
        print(f"  ⚠  OSM sorgusu başarısız: {ex} — maske sıfırlandı.")

    return maske


def _icinde_mi(lat: float, lon: float, poly: list) -> bool:
    """Ray casting — nokta poligon içinde mi?"""
    n = len(poly)
    icinde = False
    j = n - 1
    for i in range(n):
        yi, xi = poly[i]
        yj, xj = poly[j]
        if ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / (yj - yi) + xi
        ):
            icinde = not icinde
        j = i
    return icinde


# ── 5. Güvenli nokta tespiti ──────────────────────────────────────────────────

def guvenli_noktalari_bul(
    egim:    np.ndarray,
    transform,
    maske:   np.ndarray = None,
    adim:    int        = 5,
) -> list:
    """
    Eğim ≤ GUVENLI_EGIM  → GUVENLI
    Eğim ≤ RISKLI_EGIM   → RISKLI
    OSM engeli varsa      → atla
    adim: piksel örnekleme adımı (5 → her ~150m'de bir nokta)
    """
    print(f"[NOKTALAR] Güvenli noktalar tespit ediliyor (adım={adim} piksel)…")
    noktalar = []

    rows = np.arange(0, egim.shape[0], adim)
    cols = np.arange(0, egim.shape[1], adim)
    rr, cc = np.meshgrid(rows, cols, indexing="ij")
    rr, cc = rr.ravel(), cc.ravel()

    for r, c in zip(rr, cc):
        e = egim[r, c]
        if np.isnan(e) or e > RISKLI_EGIM:
            continue
        if maske is not None and maske[r, c]:
            continue

        lon, lat = transform * (c, r)
        durum = "GUVENLI" if e <= GUVENLI_EGIM else "RISKLI"
        noktalar.append({
            "id":    f"{durum[0]}{len(noktalar)+1:04d}",
            "lat":   round(float(lat), 6),
            "lon":   round(float(lon), 6),
            "egim":  round(float(e), 2),
            "durum": durum,
        })

    guvenli = sum(1 for n in noktalar if n["durum"] == "GUVENLI")
    print(f"  ✓  {guvenli} güvenli  |  {len(noktalar)-guvenli} riskli  nokta")
    return noktalar


# ── 6. ArduPilot terrain .DAT üretici ────────────────────────────────────────

def terrain_dat_uret(
    dem:        np.ndarray,
    transform,
    bounds,
    spacing_m:  int = 30,
    cikti_klas: str = "terrain_sd",
) -> int:
    """
    ArduPilot AP_Terrain uyumlu .DAT tile dosyaları üretir.

    Üretilen dosyaları SD karta kopyala:
        cp terrain_sd/*.DAT /media/SD/APM/TERRAIN/

    ArduPilot parametreleri:
        TERRAIN_ENABLE  = 1
        TERRAIN_SPACING = 30   # (metre, spacing_m ile eşleşmeli)

    Dosya formatı:
        4B  magic "APCO"
        2B  grid spacing (uint16 LE, metre)
        4B  lat_origin (int32 LE, ×1e7)
        4B  lon_origin (int32 LE, ×1e7)
        2B  n_lat (uint16 LE)
        2B  n_lon (uint16 LE)
        N×  int16 LE yükseklik verisi (satır-majör, lat artan yönde)
    """
    os.makedirs(cikti_klas, exist_ok=True)
    print(f"[DAT] ArduPilot terrain tile'ları üretiliyor → {cikti_klas}/")

    lat_min = bounds.bottom
    lat_max = bounds.top
    lon_min = bounds.left
    lon_max = bounds.right

    tile_sayisi = 0
    for lat_f in range(int(math.floor(lat_min)), int(math.ceil(lat_max))):
        for lon_f in range(int(math.floor(lon_min)), int(math.ceil(lon_max))):
            _tek_tile_yaz(dem, transform, lat_f, lon_f, spacing_m, cikti_klas)
            tile_sayisi += 1

    print(f"  ✓  {tile_sayisi} .DAT tile → {cikti_klas}/")
    print(f"  SD karta kopyala:")
    print(f"    cp {cikti_klas}/*.DAT /media/SD/APM/TERRAIN/")
    return tile_sayisi


def _pix_yukseklik(dem: np.ndarray, transform, lat: float, lon: float) -> int:
    """DEM array'inden verilen koordinatın yüksekliğini int16 olarak döndürür."""
    try:
        from rasterio.transform import rowcol
        r, c = rowcol(transform, lon, lat)
        if 0 <= r < dem.shape[0] and 0 <= c < dem.shape[1]:
            v = dem[r, c]
            if not np.isnan(v):
                return int(np.clip(v, -32768, 32767))
    except Exception:
        pass
    return 0


def _tek_tile_yaz(dem, transform, lat_taban, lon_taban, spacing_m, cikti_klas):
    """Tek 1°×1° tile için .DAT dosyası yazar."""
    lh = "N" if lat_taban >= 0 else "S"
    oh = "E" if lon_taban >= 0 else "W"
    dosya_adi = f"{lh}{abs(lat_taban):02d}{oh}{abs(lon_taban):03d}.DAT"
    yol       = os.path.join(cikti_klas, dosya_adi)

    m_per_deg_lat = 111320.0
    m_per_deg_lon = 111320.0 * math.cos(math.radians(lat_taban + 0.5))
    n_lat = max(2, int(m_per_deg_lat / spacing_m))
    n_lon = max(2, int(m_per_deg_lon / spacing_m)) if m_per_deg_lon > 0 else 2

    veriler = []
    for i in range(n_lat):
        for j in range(n_lon):
            lat = lat_taban + i * spacing_m / m_per_deg_lat
            lon = lon_taban + j * spacing_m / m_per_deg_lon if m_per_deg_lon > 0 else lon_taban
            veriler.append(_pix_yukseklik(dem, transform, lat, lon))

    with open(yol, "wb") as f:
        f.write(b"APCO")
        f.write(struct.pack("<H", spacing_m))
        f.write(struct.pack("<i", int(lat_taban * 1e7)))
        f.write(struct.pack("<i", int(lon_taban * 1e7)))
        f.write(struct.pack("<H", n_lat))
        f.write(struct.pack("<H", n_lon))
        f.write(struct.pack(f"<{len(veriler)}h", *veriler))


# ── 7. Görselleştirme ─────────────────────────────────────────────────────────

def gorselleştir(
    egim:      np.ndarray,
    noktalar:  list,
    transform,
    osm_maske: np.ndarray = None,
    cikti:     str = "egim_haritasi.png",
):
    if not MATPLOTLIB_MEVCUT:
        print("[GÖRSEL] matplotlib kurulu değil — atlandı. pip install matplotlib")
        return

    fig, ax = plt.subplots(figsize=(14, 11))
    sinirlar = [0, 5, 10, 15, 25, 45, 90]
    norm = mc.BoundaryNorm(sinirlar, 256)
    im   = ax.imshow(egim, cmap="RdYlGn_r", norm=norm, interpolation="nearest")
    plt.colorbar(im, ax=ax, label="Eğim (°)", shrink=0.8, ticks=sinirlar)

    if osm_maske is not None and osm_maske.any():
        rgba = np.zeros((*osm_maske.shape, 4), dtype=np.float32)
        rgba[osm_maske] = [1.0, 0.0, 0.0, 0.45]
        ax.imshow(rgba, interpolation="nearest")

    renk_map = {"GUVENLI": "#00ff44", "RISKLI": "#ffdd00"}
    for n in noktalar:
        col = (n["lon"] - transform.c) / transform.a
        row = (n["lat"] - transform.f) / transform.e
        renk = renk_map.get(n["durum"], "grey")
        ax.plot(col, row, "o", color=renk, markersize=4,
                markeredgecolor="black", markeredgewidth=0.4, alpha=0.8)

    from matplotlib.patches import Patch
    legend_elems = [
        Patch(color="#00ff44", label=f"Güvenli (≤{GUVENLI_EGIM}°)"),
        Patch(color="#ffdd00", label=f"Riskli  (≤{RISKLI_EGIM}°)"),
    ]
    if osm_maske is not None and osm_maske.any():
        legend_elems.append(Patch(color="red", alpha=0.45, label="OSM Engel"))
    ax.legend(handles=legend_elems, loc="lower right", fontsize=9)

    ax.set_title(
        "Eğim Haritası — Güvenli İniş Noktaları  "
        "(Copernicus GLO-30 | AWS S3 Anonim)", fontsize=12
    )
    ax.set_xlabel("Sütun (piksel)")
    ax.set_ylabel("Satır (piksel)")
    plt.tight_layout()
    plt.savefig(cikti, dpi=150)
    print(f"[GÖRSEL] Kaydedildi: {cikti}")
    plt.close()


# ── 8. NPZ kaydetme ───────────────────────────────────────────────────────────

def kaydet(
    egim:      np.ndarray,
    dem:       np.ndarray,
    transform,
    bounds,
    noktalar:  list,
    cikti:     str = "alan_verisi.npz",
):
    """
    AlanInisKarar + terrain server tarafından kullanılacak NPZ dosyasını yazar.

    Format:
        egim          – float32 eğim matrisi (AlanInisKarar için)
        dem           – float32 yükseklik matrisi (terrain server için)
        transform     – 6-eleman float64 (rasterio Affine uyumlu)
        bounds        – 4-eleman float64 [left, bottom, right, top]
        noktalar_json – JSON string (güvenli/riskli nokta listesi)
    """
    t_arr = np.array([
        transform.a, transform.b, transform.c,
        transform.d, transform.e, transform.f,
    ], dtype=np.float64)
    b_arr = np.array(
        [bounds.left, bounds.bottom, bounds.right, bounds.top],
        dtype=np.float64,
    )
    np.savez_compressed(
        cikti,
        egim          = egim,
        dem           = dem,   # yükseklik — terrain server TERRAIN_DATA yanıtları için
        transform     = t_arr,
        bounds        = b_arr,
        noktalar_json = np.array([json.dumps(noktalar, ensure_ascii=False)]),
    )
    boyut_kb = os.path.getsize(cikti) // 1024
    guvenli  = sum(1 for n in noktalar if n["durum"] == "GUVENLI")
    print(f"\n✓  Kaydedildi: {cikti}  ({boyut_kb} KB)")
    print(f"   Güvenli nokta : {guvenli}")
    print(f"   Riskli nokta  : {len(noktalar) - guvenli}")
    print(f"   Eğim matrisi  : {egim.shape[0]}×{egim.shape[1]} piksel  "
          f"(~{egim.shape[0]*PIKSEL_M:.0f}m × {egim.shape[1]*PIKSEL_M:.0f}m)")


# ── Bağımlılık kontrolü ───────────────────────────────────────────────────────

def _bagimlilik_kontrol():
    eksik = []
    if not BOTO3_MEVCUT:
        eksik.append("boto3")
    if not RASTERIO_MEVCUT:
        eksik.append("rasterio")
    if eksik:
        print(f"HATA: Zorunlu paketler eksik: {', '.join(eksik)}")
        print(f"  pip install {' '.join(eksik)}")
        sys.exit(1)


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Uçuş alanı DEM + eğim haritası hazırlama\n"
            "Copernicus GLO-30 → AWS S3 anonim erişim (kimlik bilgisi GEREKMİYOR)"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--alan", nargs=4, type=float, required=True,
        metavar=("LAT_MIN", "LAT_MAX", "LON_MIN", "LON_MAX"),
        help="Uçuş alanı bounding box  (örn: 40.9 41.1 28.8 29.0)",
    )
    parser.add_argument("--cikti",       default="alan_verisi.npz",
                        help="NPZ çıktısı — AlanInisKarar tarafından okunur")
    parser.add_argument("--dem-dosya",   default="alan_dem.tif",
                        help="Ara DEM GeoTIFF (saklanabilir veya silinebilir)")
    parser.add_argument("--adim",        type=int, default=5,
                        help="Nokta örnekleme adımı (piksel, varsayılan=5 → ~150m)")
    parser.add_argument("--gorsel",      action="store_true",
                        help="Eğim haritası PNG oluştur")
    parser.add_argument("--osm",         action="store_true",
                        help="OSM engel maskesi uygula (pip install overpy gerektirir)")
    parser.add_argument("--terrain-dat", default="", metavar="KLASOR",
                        help="ArduPilot terrain .DAT tile üret (SD kart için)")
    parser.add_argument("--spacing",     type=int, default=30,
                        help="Terrain DAT grid aralığı metre (varsayılan=30, "
                             "ArduPilot TERRAIN_SPACING ile eşleşmeli)")
    args = parser.parse_args()

    _bagimlilik_kontrol()

    lat_min, lat_max, lon_min, lon_max = args.alan

    print("=" * 62)
    print("  Doğuş Üni LÖP — Alan Hazırlama  (Copernicus GLO-30 / AWS S3)")
    print(f"  Alan : LAT [{lat_min}, {lat_max}]  LON [{lon_min}, {lon_max}]")
    print("=" * 62)

    # 1 — DEM indir
    dem_dosya = dem_indir(lat_min, lat_max, lon_min, lon_max, cikti=args.dem_dosya)

    # 2 — DEM oku
    dem, transform, bounds = dem_oku(dem_dosya)

    # 3 — Eğim hesapla
    egim = egim_hesapla(dem)

    # 4 — OSM maskesi (opsiyonel)
    osm_maske = None
    if args.osm:
        osm_maske = osm_engel_maskesi(
            egim, transform, lat_min, lat_max, lon_min, lon_max
        )

    # 5 — Güvenli noktaları bul
    noktalar = guvenli_noktalari_bul(egim, transform, maske=osm_maske, adim=args.adim)

    # 6 — Görsel (opsiyonel)
    if args.gorsel:
        gorselleştir(egim, noktalar, transform, osm_maske=osm_maske)

    # 7 — NPZ kaydet (egim + dem birlikte)
    kaydet(egim, dem, transform, bounds, noktalar, cikti=args.cikti)

    # 8 — ArduPilot terrain DAT (opsiyonel)
    if args.terrain_dat:
        terrain_dat_uret(dem, transform, bounds,
                         spacing_m=args.spacing,
                         cikti_klas=args.terrain_dat)

    print("\n" + "=" * 62)
    print("  Hazırlık tamamlandı.")
    print(f"  NPZ → {args.cikti}  (AlanInisKarar + GCS terrain server)")
    if args.terrain_dat:
        print(f"  DAT → {args.terrain_dat}/  (SD kart APM/TERRAIN/ klasörüne kopyala)")
    print("=" * 62)


if __name__ == "__main__":
    main()
