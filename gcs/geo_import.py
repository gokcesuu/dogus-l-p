"""
Geofence dosya içe aktarma — SHP ve KML dosyalarından polygon köşe listesi okur.

Her iki fonksiyon da [[lat, lon], ...] formatında bir liste döner — bu format,
gcs_main.py'deki mevcut haritadan-çizme akışıyla (fenceBitir/_fence_noktalar)
aynıdır, böylece aynı yükleme (_fence_polygon_yukle) pipeline'ı kullanılabilir.
"""


def shp_oku(dosya_yolu: str) -> list:
    """SHP dosyasındaki ilk şeklin köşelerini [lat, lon] listesi olarak döner."""
    import shapefile

    sf = shapefile.Reader(dosya_yolu)
    if sf.numRecords == 0 and not sf.shapes():
        raise ValueError("SHP dosyasında hiç şekil yok")
    shape = sf.shape(0)  # ilk şekil (polygon varsayılıyor)
    if not shape.points:
        raise ValueError("SHP dosyasındaki ilk şeklin köşesi yok")
    # Shapefile noktaları (lon, lat) sırasında tutar
    return [[float(pt[1]), float(pt[0])] for pt in shape.points]


def kml_oku(dosya_yolu: str) -> list:
    """KML dosyasındaki ilk Polygon/coordinates'ı [lat, lon] listesi olarak döner."""
    import xml.etree.ElementTree as ET

    tree = ET.parse(dosya_yolu)
    ns = {"kml": "http://www.opengis.net/kml/2.2"}

    coord_el = tree.find(".//kml:Polygon//kml:coordinates", ns)
    if coord_el is None:
        # Bazı KML üreticileri namespace'i farklı yazabiliyor veya hiç kullanmıyor
        coord_el = tree.find(".//{*}Polygon//{*}coordinates")
    if coord_el is None or not coord_el.text:
        raise ValueError("KML içinde Polygon/coordinates bulunamadı")

    noktalar = []
    for grup in coord_el.text.strip().split():
        parcalar = grup.strip().split(",")
        if len(parcalar) < 2:
            continue
        lon, lat = float(parcalar[0]), float(parcalar[1])
        noktalar.append([lat, lon])

    if len(noktalar) < 3:
        raise ValueError("KML polygon'unda yeterli köşe yok (min 3)")
    return noktalar


def dosyadan_oku(dosya_yolu: str) -> list:
    """Uzantıya göre shp_oku/kml_oku'ya yönlendirir."""
    yol_kucuk = dosya_yolu.lower()
    if yol_kucuk.endswith(".shp"):
        return shp_oku(dosya_yolu)
    if yol_kucuk.endswith(".kml"):
        return kml_oku(dosya_yolu)
    raise ValueError(f"Desteklenmeyen dosya uzantısı: {dosya_yolu}")
