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

    def html_rapor_olustur(self) -> str:
        """
        Analiz yapar, interaktif grafik içeren HTML rapor oluşturur.
        Döndürür: .html dosya yolu (boşsa "").
        """
        if not self._veriler:
            return ""

        analiz   = self._analiz_et()
        zaman_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        dosya     = os.path.join(self._klasor, f"ucus_{zaman_str}.html")

        with open(dosya, "w", encoding="utf-8") as f:
            f.write(self._html_olustur(analiz))

        return dosya

    # ── HTML üretici ──────────────────────────────────────────────────────────

    def _html_olustur(self, a: dict) -> str:
        tarih_str = datetime.now().strftime("%d.%m.%Y %H:%M")
        sure_dk   = a["sure_sn"] / 60
        sure_str  = f"{int(sure_dk)}dk {int(a['sure_sn'] % 60)}sn"

        # Grafik verileri — her 5. ölçüm (performans için)
        v = self._veriler[::5] if len(self._veriler) > 200 else self._veriler
        t0 = v[0].zaman if v else 0
        etiketler  = json.dumps([f"{(x.zaman-t0)/60:.1f}" for x in v])
        irtifa_d   = json.dumps([round(x.irtifa, 1) for x in v])
        batarya_d  = json.dumps([x.batarya_yuzde if x.batarya_yuzde >= 0 else "null" for x in v])
        ruzgar_d   = json.dumps([round(x.ruzgar_ms * 3.6, 1) for x in v])
        hiz_d      = json.dumps([round(x.hiz, 1) for x in v])

        # Uyarı badge'leri
        uyarilar = []
        if a["kritik_bat"]:
            uyarilar.append(("kirmizi", f"⚠ Batarya kritik seviyeye (%{BATARYA_KRITIK_YDZ}) düştü!"))
        elif a["dusuk_bat"]:
            uyarilar.append(("sari", f"⚠ Batarya düşük seviyeye (%{BATARYA_DUSUK_YDZ}) geriledi."))
        if a["gps_kayip_sayisi"] > 0:
            uyarilar.append(("sari", f"⚠ {a['gps_kayip_sayisi']} kez GPS fix kaybı yaşandı."))
        if any(a["imu_asiri"]):
            idx = [i for i, x in enumerate(a["imu_asiri"]) if x]
            uyarilar.append(("kirmizi", f"⚠ IMU sıcaklığı aşıldı: {', '.join(f'IMU{i}' for i in idx)}"))
        if a["tehlikeli_ruzgar"]:
            uyarilar.append(("sari", f"⚠ Rüzgar {a['ruzgar_max_kmh']:.0f} km/h — tehlikeli eşiği aştı."))
        if a["ekf_max"] > 0.5:
            uyarilar.append(("sari", f"⚠ EKF hata puanı yüksek ({a['ekf_max']:.2f})."))

        if not uyarilar:
            uyarilar.append(("yesil", "✓ Uçuş sorunsuz tamamlandı — anormal durum tespit edilmedi."))

        uyari_html = "\n".join(
            f'<div class="badge {r}">{m}</div>' for r, m in uyarilar
        )

        genel_renk = "kirmizi" if any(r == "kirmizi" for r, _ in uyarilar) else \
                     "sari"    if any(r == "sari"    for r, _ in uyarilar) else "yesil"
        genel_yazi = "KRİTİK SORUN" if genel_renk == "kirmizi" else \
                     "UYARI VAR"    if genel_renk == "sari"     else "BAŞARILI"

        # IMU satırları
        imu_satirlar = "".join(
            f'<td>{a["imu_max"][i]:.1f} °C {"⚠" if a["imu_asiri"][i] else "✓"}</td>'
            for i in range(3)
        )

        return f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Uçuş Raporu — {tarih_str}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Barlow', 'Segoe UI', Arial, sans-serif; background: #f2f2f3; color: #1d1f20; }}
  header {{ background: #16222e; border-bottom: 1px solid rgba(148,188,227,0.22); padding: 18px 32px; display: flex; align-items: center; gap: 16px; }}
  header h1 {{ font-family: 'Barlow Condensed', sans-serif; font-weight: 700; letter-spacing: 0.04em; font-size: 1.4rem; color: #e7e7ea; }}
  header span {{ font-size: 0.9rem; color: #9ebbd8; }}
  .container {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 16px; margin-bottom: 24px; }}
  .card {{ background: transparent; border: 1px solid rgba(29,31,32,0.2); border-radius: 0; padding: 18px; text-align: center; }}
  .card .val {{ font-family: 'Barlow Condensed', sans-serif; font-size: 2rem; font-weight: 700; color: #416180; }}
  .card .lbl {{ font-size: 0.8rem; letter-spacing: 0.05em; text-transform: uppercase; color: #5d5d60; margin-top: 4px; }}
  .charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 24px; }}
  .chart-box {{ background: transparent; border: 1px solid rgba(29,31,32,0.2); border-radius: 0; padding: 20px; }}
  .chart-box h3 {{ font-size: 0.95rem; color: #5d5d60; margin-bottom: 14px; }}
  .badges {{ background: transparent; border: 1px solid rgba(29,31,32,0.2); border-radius: 0; padding: 20px; margin-bottom: 24px; }}
  .badges h2 {{ font-size: 1rem; margin-bottom: 14px; color: #5d5d60; }}
  .badge {{ padding: 10px 16px; border-radius: 0; margin-bottom: 8px; font-size: 0.9rem; font-weight: 500; }}
  .badge.yesil {{ background: rgba(143,191,122,0.12); border: 1px solid #8fbf7a; color: #4a7a3a; }}
  .badge.sari  {{ background: rgba(217,162,74,0.12); border: 1px solid #d9a24a; color: #8a6414; }}
  .badge.kirmizi {{ background: rgba(194,91,82,0.12); border: 1px solid #c25b52; color: #8f3b34; }}
  .tablo {{ background: transparent; border: 1px solid rgba(29,31,32,0.2); border-radius: 0; padding: 20px; margin-bottom: 24px; overflow-x: auto; }}
  .tablo h2 {{ font-size: 1rem; margin-bottom: 14px; color: #5d5d60; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; }}
  th {{ background: rgba(29,31,32,0.06); color: #5d5d60; padding: 8px 14px; text-align: left; }}
  td {{ padding: 8px 14px; border-bottom: 1px solid rgba(29,31,32,0.12); }}
  .genel {{ text-align: center; padding: 18px; border-radius: 0; margin-bottom: 24px; font-size: 1.1rem; font-weight: bold; }}
  .genel.yesil   {{ background: rgba(143,191,122,0.12); border: 1px solid #8fbf7a; color: #4a7a3a; }}
  .genel.sari    {{ background: rgba(217,162,74,0.12); border: 1px solid #d9a24a; color: #8a6414; }}
  .genel.kirmizi {{ background: rgba(194,91,82,0.12); border: 1px solid #c25b52; color: #8f3b34; }}
  footer {{ text-align: center; padding: 20px; color: #9a9a9c; font-size: 0.8rem; border-top: 1px solid rgba(29,31,32,0.12); margin-top: 8px; }}
  @media (max-width: 768px) {{ .charts {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>
<header>
  <div>
    <h1>🛸 Doğuş Üniversitesi LÖP — Uçuş Raporu</h1>
    <span>📅 {tarih_str} &nbsp;|&nbsp; ⏱ {sure_str}</span>
  </div>
</header>
<div class="container">

  <!-- Özet Kartları -->
  <div class="cards">
    <div class="card"><div class="val">{sure_str}</div><div class="lbl">Uçuş Süresi</div></div>
    <div class="card"><div class="val">{a['mesafe_m']:.0f} m</div><div class="lbl">Kat Edilen Yol</div></div>
    <div class="card"><div class="val">{a['irtifa_max']:.1f} m</div><div class="lbl">Maks İrtifa</div></div>
    <div class="card"><div class="val">{a['hiz_max']:.1f} m/s</div><div class="lbl">Maks Hız</div></div>
    <div class="card"><div class="val">{a['bat_baslangic']}% → {a['bat_bitis']}%</div><div class="lbl">Batarya Kullanımı</div></div>
    <div class="card"><div class="val">{a['ruzgar_max_kmh']:.0f} km/h</div><div class="lbl">Maks Rüzgar</div></div>
  </div>

  <!-- Grafikler -->
  <div class="charts">
    <div class="chart-box">
      <h3>📈 İrtifa (m)</h3>
      <canvas id="cIrtifa" height="140"></canvas>
    </div>
    <div class="chart-box">
      <h3>🔋 Batarya (%)</h3>
      <canvas id="cBatarya" height="140"></canvas>
    </div>
    <div class="chart-box">
      <h3>💨 Rüzgar (km/h)</h3>
      <canvas id="cRuzgar" height="140"></canvas>
    </div>
    <div class="chart-box">
      <h3>🚀 Hız (m/s)</h3>
      <canvas id="cHiz" height="140"></canvas>
    </div>
  </div>

  <!-- Uyarılar -->
  <div class="badges">
    <h2>⚠ Uyarılar ve Durum</h2>
    {uyari_html}
  </div>

  <!-- Detay Tablosu -->
  <div class="tablo">
    <h2>📊 Detaylı İstatistikler</h2>
    <table>
      <tr><th>Parametre</th><th>Değer</th></tr>
      <tr><td>Batarya Min Voltaj</td><td>{a['bat_min_v']:.2f} V</td></tr>
      <tr><td>Batarya Maks Akım</td><td>{a['bat_max_a']:.1f} A</td></tr>
      <tr><td>GPS Fix Kaybı</td><td>{a['gps_kayip_sayisi']} kez</td></tr>
      <tr><td>GPS Min Uydu</td><td>{a['gps_min_uydu']}</td></tr>
      <tr><td>IMU Maks Sıcaklık (0/1/2)</td><td>{imu_satirlar}</td></tr>
      <tr><td>EKF Maks Hata</td><td>{a['ekf_max']:.3f}</td></tr>
      <tr><td>Toplam Veri Noktası</td><td>{a['veri_sayisi']}</td></tr>
    </table>
  </div>

  <!-- Genel Değerlendirme -->
  <div class="genel {genel_renk}">{genel_yazi}</div>

</div>
<footer>Doğuş Üniversitesi LÖP GCS — Otomatik Uçuş Raporu</footer>
<script>
const ETIKETLER = {etiketler};
const _opts = (renk, dolu) => ({{
  responsive: true,
  plugins: {{ legend: {{ display: false }} }},
  scales: {{
    x: {{ ticks: {{ color: '#5d5d60', maxTicksLimit: 8 }}, grid: {{ color: 'rgba(29,31,32,0.08)' }} }},
    y: {{ ticks: {{ color: '#5d5d60' }}, grid: {{ color: 'rgba(29,31,32,0.08)' }} }}
  }},
  elements: {{ point: {{ radius: 0 }}, line: {{ tension: 0.3, borderWidth: 2, fill: dolu,
    backgroundColor: renk+'33' }} }}
}});
const _ds = (data, renk, dolu=false) => ({{
  data, borderColor: renk,
  backgroundColor: dolu ? renk+'33' : 'transparent',
  fill: dolu, spanGaps: true
}});
new Chart(document.getElementById('cIrtifa'),
  {{ type:'line', data:{{ labels:ETIKETLER, datasets:[_ds({irtifa_d},'#58a6ff',true)] }},
    options:_opts('#58a6ff',true) }});
new Chart(document.getElementById('cBatarya'),
  {{ type:'line', data:{{ labels:ETIKETLER, datasets:[_ds({batarya_d},'#3fb950',true)] }},
    options:_opts('#3fb950',true) }});
new Chart(document.getElementById('cRuzgar'),
  {{ type:'line', data:{{ labels:ETIKETLER, datasets:[_ds({ruzgar_d},'#d29922',false)] }},
    options:_opts('#d29922',false) }});
new Chart(document.getElementById('cHiz'),
  {{ type:'line', data:{{ labels:ETIKETLER, datasets:[_ds({hiz_d},'#bc8cff',false)] }},
    options:_opts('#bc8cff',false) }});
</script>
</body>
</html>"""

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
