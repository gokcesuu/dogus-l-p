"""
ucus_alani_hazirla.py
Doğuş Üniversitesi LÖP — Uçuş Öncesi Alan Hazırlama Scripti

Uçuştan ÖNCE bir kez çalıştırılır:
  1. Copernicus Data Space'ten GLO-30 DEM indir (resmi S3 API)
  2. Eğim haritası hesapla (Horn yöntemi)
  3. Güvenli noktaları otomatik tespit et (eğim ≤ 5°)
  4. alan_verisi.npz dosyasına yaz

Uçuş anında network/hesaplama yok — sadece lookup.

Kullanım:
    python ucus_alani_hazirla.py \
        --config ../config.json \
        --alan 40.9 41.1 28.8 29.0 \
        --cikti alan_verisi.npz --gorsel

    # Ya da kimlik bilgisi doğrudan:
    python ucus_alani_hazirla.py \
        --kullanici ad@mail.com --sifre GİZLİ \
        --s3-key ACCESS --s3-secret SECRET \
        --alan 40.9 41.1 28.8 29.0 --gorsel

Copernicus Hesabı:
    1. https://dataspace.copernicus.eu adresinden ücretsiz kayıt
    2. User Settings → S3 Access → yeni anahtar oluştur
    3. config.json'a kullanici_adi, sifre, s3_access_key, s3_secret_key yaz
"""

import os
import sys
import json
import argparse
import tempfile
import numpy as np
import requests

try:
    import rasterio
    from rasterio.transform import from_bounds
    from rasterio.merge import merge as rasterio_merge
    RASTERIO_MEVCUT = True
except ImportError:
    RASTERIO_MEVCUT = False

try:
    import boto3
    from botocore.client import Config as BotoConfig
    BOTO3_MEVCUT = True
except ImportError:
    BOTO3_MEVCUT = False

try:
    from pystac_client import Client as StacClient
    PYSTAC_MEVCUT = True
except ImportError:
    PYSTAC_MEVCUT = False

try:
    import matplotlib.pyplot as plt
    MATPLOTLIB_MEVCUT = True
except ImportError:
    MATPLOTLIB_MEVCUT = False

# ── Sabitler ─────────────────────────────────────────────────────────────────
GUVENLI_EGIM = 5.0
RISKLI_EGIM  = 15.0
PIKSEL_BOYUT = 30.0   # GLO-30 piksel boyutu (metre)

COPERNICUS_TOKEN_URL = (
    "https://identity.dataspace.copernicus.eu"
    "/auth/realms/CDSE/protocol/openid-connect/token"
)
COPERNICUS_S3_ENDPOINT = "https://eodata.dataspace.copernicus.eu"
COPERNICUS_STAC_URL    = "https://stac.dataspace.copernicus.eu"
COPERNICUS_DEM_KOLEKSIYON = "cop-dem-glo-30"


# ── 1. Kimlik doğrulama ───────────────────────────────────────────────────────

def token_al(kullanici: str, sifre: str, token_url: str = COPERNICUS_TOKEN_URL) -> str:
    """
    Copernicus Data Space OAuth2 token alır.
    Token her ~10 dakikada bir yenilenmeli — bu script tek seferlik kullanım için yeterli.
    """
    print("Copernicus kimlik doğrulaması yapılıyor...")
    r = requests.post(
        token_url,
        data={
            "client_id":  "cdse-public",
            "grant_type": "password",
            "username":   kullanici,
            "password":   sifre,
        },
        timeout=30,
    )
    if r.status_code != 200:
        raise RuntimeError(
            f"Token alınamadı ({r.status_code}): {r.text[:300]}\n"
            "→ Kullanıcı adı/şifreyi config.json'da kontrol edin."
        )
    token = r.json().get("access_token")
    if not token:
        raise RuntimeError("Token yanıtında 'access_token' bulunamadı.")
    print("  Token alındı.")
    return token


def s3_istemci_olustur(
    s3_access_key: str,
    s3_secret_key: str,
    s3_endpoint: str = COPERNICUS_S3_ENDPOINT,
):
    """
    Copernicus S3 uyumlu nesne deposuna boto3 istemcisi oluşturur.
    Anahtarlar: dataspace.copernicus.eu → User Settings → S3 Access
    """
    if not BOTO3_MEVCUT:
        raise ImportError("pip install boto3")
    return boto3.client(
        "s3",
        endpoint_url=s3_endpoint,
        aws_access_key_id=s3_access_key,
        aws_secret_access_key=s3_secret_key,
        config=BotoConfig(signature_version="s3v4"),
        region_name="default",
    )


# ── 2. STAC ile tile arama ────────────────────────────────────────────────────

def tile_listesi_bul(
    lat_min: float, lat_max: float,
    lon_min: float, lon_max: float,
    stac_url: str = COPERNICUS_STAC_URL,
    koleksiyon: str = COPERNICUS_DEM_KOLEKSIYON,
) -> list:
    """
    STAC API ile verilen bounding box'ı kapsayan GLO-30 tile'larını bulur.
    Her tile: {'item_id': ..., 's3_path': ..., 'bbox': ...}
    """
    if not PYSTAC_MEVCUT:
        raise ImportError("pip install pystac-client")

    print(f"STAC tile araması: [{lat_min},{lat_max}] x [{lon_min},{lon_max}]")
    katalog = StacClient.open(stac_url)

    arama = katalog.search(
        collections=[koleksiyon],
        bbox=[lon_min, lat_min, lon_max, lat_max],
        max_items=50,
    )

    tileler = []
    for item in arama.items():
        # GLO-30 asset anahtarı genellikle "data" veya "dem"
        asset = item.assets.get("data") or item.assets.get("dem")
        if asset is None:
            # Tüm asset anahtarlarından ilkini dene
            asset = next(iter(item.assets.values()), None)
        if asset is None:
            continue

        href = asset.href  # s3://eodata/... veya https://...
        tileler.append({
            "item_id": item.id,
            "href":    href,
            "bbox":    item.bbox,
        })

    print(f"  {len(tileler)} tile bulundu.")
    if not tileler:
        raise RuntimeError(
            "Verilen koordinatlara ait tile bulunamadı. "
            "Bounding box doğru mu?"
        )
    return tileler


# ── 3. S3'ten indirme ─────────────────────────────────────────────────────────

def _s3_yolu_ayristir(href: str):
    """
    's3://bucket/key/path.tif' → ('bucket', 'key/path.tif')
    'https://eodata.dataspace.../path' → ('eodata', 'path')
    """
    if href.startswith("s3://"):
        parca = href[5:].split("/", 1)
        return parca[0], parca[1]
    # HTTPS href: endpoint'ten sonraki kısmı al
    # https://eodata.dataspace.copernicus.eu/Copernicus/DEM/.../file.tif
    idx = href.find("/Copernicus")
    if idx == -1:
        idx = href.index("/", 8)          # https:// sonrası ilk /
    return "eodata", href[idx + 1:]       # bucket=eodata, key=...


def tile_indir(s3, href: str, hedef_dosya: str):
    """Tek bir tile'ı S3'ten indirir."""
    bucket, key = _s3_yolu_ayristir(href)
    print(f"  İndiriliyor: {os.path.basename(key)}")
    s3.download_file(bucket, key, hedef_dosya)


# ── 4. Birden fazla tile'ı birleştir ─────────────────────────────────────────

def dem_indir(
    lat_min: float, lat_max: float,
    lon_min: float, lon_max: float,
    s3_access_key: str,
    s3_secret_key: str,
    kullanici: str = "",
    sifre: str = "",
    s3_endpoint: str = COPERNICUS_S3_ENDPOINT,
    stac_url: str    = COPERNICUS_STAC_URL,
    koleksiyon: str  = COPERNICUS_DEM_KOLEKSIYON,
    cikti: str       = "alan_dem.tif",
) -> str:
    """
    Copernicus GLO-30 DEM'i indirir, gerekirse tile'ları birleştirir.
    Çıktı: GeoTIFF dosyası (dem_oku() ile okunabilir).
    """
    if not RASTERIO_MEVCUT:
        raise ImportError("pip install rasterio")
    if not BOTO3_MEVCUT:
        raise ImportError("pip install boto3")
    if not PYSTAC_MEVCUT:
        raise ImportError("pip install pystac-client")

    # S3 istemcisi (token gerekmez, doğrudan S3 anahtarıyla)
    s3 = s3_istemci_olustur(s3_access_key, s3_secret_key, s3_endpoint)

    # Tile listesi bul
    tileler = tile_listesi_bul(lat_min, lat_max, lon_min, lon_max, stac_url, koleksiyon)

    with tempfile.TemporaryDirectory(prefix="lop_dem_") as tmp:
        indirilen = []
        for i, tile in enumerate(tileler):
            hedef = os.path.join(tmp, f"tile_{i:03d}.tif")
            tile_indir(s3, tile["href"], hedef)
            indirilen.append(hedef)

        if len(indirilen) == 1:
            # Tek tile → doğrudan kopyala
            import shutil
            shutil.copy2(indirilen[0], cikti)
        else:
            # Birden fazla tile → birleştir (mosaic)
            print(f"  {len(indirilen)} tile birleştiriliyor (mosaic)...")
            acik_dosyalar = [rasterio.open(f) for f in indirilen]
            try:
                mozaik, mozaik_transform = rasterio_merge(acik_dosyalar)
                profil = acik_dosyalar[0].profile.copy()
                profil.update({
                    "height":    mozaik.shape[1],
                    "width":     mozaik.shape[2],
                    "transform": mozaik_transform,
                })
                with rasterio.open(cikti, "w", **profil) as dst:
                    dst.write(mozaik)
            finally:
                for f in acik_dosyalar:
                    f.close()

    boyut_kb = os.path.getsize(cikti) // 1024
    print(f"  Kaydedildi: {cikti} ({boyut_kb} KB)")
    return cikti


# ── 5. DEM okuma ──────────────────────────────────────────────────────────────

def dem_oku(dem_dosya: str):
    if not RASTERIO_MEVCUT:
        raise ImportError("pip install rasterio")
    with rasterio.open(dem_dosya) as src:
        dem       = src.read(1).astype(np.float32)
        dem[dem < -9000] = np.nan
        transform = src.transform
        bounds    = src.bounds
    print(f"  DEM boyutu: {dem.shape}  "
          f"(~{dem.shape[0]*PIKSEL_BOYUT:.0f}m x {dem.shape[1]*PIKSEL_BOYUT:.0f}m)")
    return dem, transform, bounds


# ── 6. Eğim haritası ─────────────────────────────────────────────────────────

def egim_hesapla(dem: np.ndarray, piksel_m: float = PIKSEL_BOYUT) -> np.ndarray:
    print("Eğim haritası hesaplanıyor...")
    dy, dx = np.gradient(dem, piksel_m, piksel_m)
    egim   = np.degrees(np.arctan(np.sqrt(dx**2 + dy**2)))
    egim   = np.where(np.isnan(dem), np.nan, egim)
    toplam = np.sum(~np.isnan(egim))
    oran   = np.nansum(egim <= GUVENLI_EGIM) / toplam * 100 if toplam else 0
    print(f"  Güvenli alan (≤{GUVENLI_EGIM}°): %{oran:.1f}")
    return egim.astype(np.float32)


# ── 7. Güvenli noktalar ───────────────────────────────────────────────────────

def guvenli_noktalari_otomatik_bul(egim_array: np.ndarray, transform, adim: int = 3) -> list:
    """
    Eğim ≤ GUVENLI_EGIM olan tüm pikselleri güvenli nokta olarak işaretler.
    adim: her kaç pikselde bir nokta alınsın (çok fazla nokta olmasın diye)
    """
    print("Güvenli noktalar otomatik tespit ediliyor...")
    noktalar = []
    rows, cols = np.where(egim_array <= GUVENLI_EGIM)

    for r, c in zip(rows[::adim], cols[::adim]):
        if RASTERIO_MEVCUT:
            lon, lat = transform * (c, r)
        else:
            t = transform
            lon = t[2] + c * t[0]
            lat = t[5] + r * t[4]
        noktalar.append({
            "id":    f"G{len(noktalar)+1}",
            "lat":   round(float(lat), 6),
            "lon":   round(float(lon), 6),
            "egim":  round(float(egim_array[r, c]), 2),
            "durum": "GUVENLI",
        })

    print(f"  {len(noktalar)} güvenli nokta bulundu (eğim ≤ {GUVENLI_EGIM}°)")
    return noktalar


# ── 8. Görselleştirme ─────────────────────────────────────────────────────────

def gorselleştir(egim_array, noktalar_sonuc, transform, cikti="egim_haritasi.png"):
    if not MATPLOTLIB_MEVCUT:
        print("  (matplotlib yok — görsel atlandı)")
        return
    import matplotlib.colors as mc
    fig, ax = plt.subplots(figsize=(12, 10))
    norm = mc.BoundaryNorm([0, 5, 10, 15, 25, 45, 90], 256)
    im   = ax.imshow(egim_array, cmap="RdYlGn_r", norm=norm, interpolation="nearest")
    plt.colorbar(im, ax=ax, label="Eğim (°)", shrink=0.8)
    for n in noktalar_sonuc:
        col, row = ~transform * (n["lon"], n["lat"])
        renk = {"GUVENLI": "lime", "RISKLI": "yellow", "TEHLIKELI": "red"}.get(
            n["durum"], "grey"
        )
        ax.plot(col, row, "o", color=renk, markersize=6, markeredgecolor="black")
    ax.set_title("Eğim Haritası — Güvenli İniş Noktaları  (Copernicus GLO-30)")
    plt.tight_layout()
    plt.savefig(cikti, dpi=150)
    print(f"  Görsel: {cikti}")
    plt.close()


# ── 9. Kaydetme ───────────────────────────────────────────────────────────────

def kaydet(egim_array, transform, bounds, noktalar_sonuc, cikti="alan_verisi.npz"):
    t_arr = np.array([transform.a, transform.b, transform.c,
                      transform.d, transform.e, transform.f])
    b_arr = np.array([bounds.left, bounds.bottom, bounds.right, bounds.top])
    np.savez_compressed(
        cikti,
        egim          = egim_array,
        transform     = t_arr,
        bounds        = b_arr,
        noktalar_json = np.array([json.dumps(noktalar_sonuc, ensure_ascii=False)]),
    )
    print(f"\nKaydedildi: {cikti} ({os.path.getsize(cikti) // 1024} KB)")


# ── 10. Config yükleme yardımcısı ────────────────────────────────────────────

def _config_oku(config_dosya: str) -> dict:
    with open(config_dosya, encoding="utf-8") as f:
        return json.load(f)


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Uçuş alanı DEM + eğim haritası hazırlama (Copernicus GLO-30)"
    )
    parser.add_argument("--config",     default="../config.json",
                        help="config.json yolu (Copernicus kimlik bilgileri oradan okunur)")
    parser.add_argument("--kullanici",  default="",
                        help="Copernicus kullanıcı adı (e-posta) — config'i ezer")
    parser.add_argument("--sifre",      default="",
                        help="Copernicus şifre — config'i ezer")
    parser.add_argument("--s3-key",     default="",
                        dest="s3_key",
                        help="S3 Access Key — config'i ezer")
    parser.add_argument("--s3-secret",  default="",
                        dest="s3_secret",
                        help="S3 Secret Key — config'i ezer")
    parser.add_argument("--alan",       nargs=4, type=float, required=True,
                        metavar=("LAT_MIN", "LAT_MAX", "LON_MIN", "LON_MAX"))
    parser.add_argument("--cikti",       default="alan_verisi.npz")
    parser.add_argument("--dem-dosya",   default="alan_dem.tif")
    parser.add_argument("--gorsel",      action="store_true")
    # Katman 2: Rally Point yükleme
    parser.add_argument("--rally-yukle", action="store_true",
                        dest="rally_yukle",
                        help="Alan hazırlandıktan sonra en iyi 5 noktayı "
                             "ArduPilot'a Rally Point olarak yükle")
    parser.add_argument("--rally-baglanti", default="tcp:127.0.0.1:5762",
                        dest="rally_baglanti",
                        help="Rally yükleme için MAVLink bağlantı dizesi")
    parser.add_argument("--rally-n",    type=int, default=5,
                        dest="rally_n",
                        help="Yüklenecek rally noktası sayısı (varsayılan: 5)")
    args = parser.parse_args()

    # Kimlik bilgilerini config'den ya da argümandan al
    cfg_cop = {}
    if os.path.isfile(args.config):
        try:
            cfg_cop = _config_oku(args.config).get("copernicus", {})
        except Exception as e:
            print(f"Uyarı: config.json okunamadı ({e}) — komut satırı argümanları kullanılıyor.")

    kullanici  = args.kullanici  or cfg_cop.get("kullanici_adi", "")
    sifre      = args.sifre      or cfg_cop.get("sifre", "")
    s3_key     = args.s3_key     or cfg_cop.get("s3_access_key", "")
    s3_secret  = args.s3_secret  or cfg_cop.get("s3_secret_key", "")
    s3_ep      = cfg_cop.get("s3_endpoint",  COPERNICUS_S3_ENDPOINT)
    stac_url   = cfg_cop.get("stac_url",     COPERNICUS_STAC_URL)
    koleksiyon = cfg_cop.get("dem_koleksiyonu", COPERNICUS_DEM_KOLEKSIYON)

    if not s3_key or not s3_secret:
        print(
            "HATA: S3 erişim anahtarı bulunamadı.\n"
            "  → config.json → copernicus → s3_access_key / s3_secret_key\n"
            "  → veya --s3-key / --s3-secret argümanları\n"
            "  Anahtarı almak için: dataspace.copernicus.eu → User Settings → S3 Access"
        )
        sys.exit(1)

    lat_min, lat_max, lon_min, lon_max = args.alan

    # İndirme
    dem_dosya = dem_indir(
        lat_min, lat_max, lon_min, lon_max,
        s3_access_key=s3_key,
        s3_secret_key=s3_secret,
        kullanici=kullanici,
        sifre=sifre,
        s3_endpoint=s3_ep,
        stac_url=stac_url,
        koleksiyon=koleksiyon,
        cikti=args.dem_dosya,
    )

    dem, transform, bounds = dem_oku(dem_dosya)
    egim = egim_hesapla(dem)
    noktalar_sonuc = guvenli_noktalari_otomatik_bul(egim, transform)

    if args.gorsel:
        gorselleştir(egim, noktalar_sonuc, transform)

    kaydet(egim, transform, bounds, noktalar_sonuc, args.cikti)

    # ── Katman 2: Rally Point yükleme ────────────────────────────────────────
    if args.rally_yukle:
        print(f"\n{'─'*50}")
        print("Rally Point yükleme başlatılıyor (Katman 2 — Donanımsal Yedek)...")
        try:
            from rally_yukle import en_iyi_noktalar, rally_yukle
            # Merkez = alan ortası
            merkez_lat = (lat_min + lat_max) / 2
            merkez_lon = (lon_min + lon_max) / 2
            rally_noktalar = en_iyi_noktalar(
                args.cikti, n=args.rally_n,
                merkez_lat=merkez_lat, merkez_lon=merkez_lon,
            )
            basarili = rally_yukle(rally_noktalar, baglanti_dizesi=args.rally_baglanti)
            if basarili:
                print(f"✓ {len(rally_noktalar)} rally noktası ArduPilot'a yüklendi.")
            else:
                print("✗ Rally yükleme başarısız — log'u kontrol edin.")
        except ImportError as e:
            print(f"Uyarı: rally_yukle.py yüklenemedi ({e})")
        except Exception as e:
            print(f"Rally yükleme hatası: {e}")


if __name__ == "__main__":
    main()
