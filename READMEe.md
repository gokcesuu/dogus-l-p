# Handoff: Türkçe Yer İstasyonu (LÖP GCS) — arayüz yenilemesi

## Genel bakış
Doğuş Üniversitesi LÖP yerli uçuş kontrol kartı için ArduPilot/MAVLink tabanlı Türkçe yer
kontrol yazılımının (GCS) arayüz tasarımı. Mevcut uygulama PyQt5 ile yazılmış
(`gcs/gcs_main.py`, `gcs/ui_widgets.py`, `gcs/ui_theme.py`); bu paket o arayüzün
yeniden düzenlenmiş halini tanımlar. Kaynak depo: `gokcesuu/dogus-l-p` (branch `main`, `gcs/`).

Kapsam: 1 uçuş ekranı için 2 alternatif düzen + 6 yardımcı ekran.

## Tasarım dosyaları hakkında
Bu paketteki HTML dosyaları **tasarım referansıdır** — hedeflenen görünüm ve davranışı
gösteren prototiplerdir, doğrudan üretime kopyalanacak kod değildir. Görev, bu tasarımları
projenin kendi ortamında **yeniden inşa etmektir**: bu projede hedef ortam **PyQt5**
(`QMainWindow` + `QTabWidget` + `QWebEngineView` harita köprüsü). Yani HTML'i gömmek değil,
mevcut widget yapısını ve `ui_theme.py` stil sayfasını bu tasarıma göre güncellemek gerekir.
Tek istisna: 1H uçuş raporu ekranı zaten HTML olarak üretiliyor (`gcs/ucus_raporlayici.py`),
orada markup doğrudan uyarlanabilir.

## Fidelity
**High-fidelity (hifi).** Renkler, tipografi, ölçüler ve durum renkleri nihaidir; 1920×1080
için ölçeklenmiştir. Pikselleri birebir uygulayın; ölçüler px cinsinden verilmiştir ve
PyQt stylesheet'e doğrudan çevrilebilir.

## Tasarım sistemi
Görsel dil **Industry** tasarım sistemidir: açık teknik zemin, tek çelik-mavi aksan,
Barlow Condensed başlık + Barlow gövde, köşesiz (radius 0) hatlı çerçeveler ve çerçeve
köşelerinde "+" registration işaretleri. Uçuş ekranları bu sistemin en koyu aksan
basamağı (`#1d2d3d`) üzerine ters çevrilmiş halidir; rapor ekranı açık zeminde kalır.

Prototipte sistemin gerçek sınıfları kullanılır: `.btn/.btn-primary/.btn-secondary`,
`.table`, `.card/.card-kicker/.card-title`, `.tag`, `.input`, `.blueprint` + `.corner`.
PyQt tarafında bunların karşılığı `ui_theme.py` içindeki QSS seçicileridir
(`QPushButton[primary="true"]`, `QTableWidget`, `QGroupBox` vb.).

## Ekranlar

### 1A — Uçuş ekranı, sekmeli düzen (mevcut yapının cilalanmışı)
**Amaç:** uçuş sırasında tek ekrandan telemetri + harita + komut.
**Düzen:** dikey akış — üst bar 54px, sekme şeridi 38px, içerik `flex` 12px boşluklu.
İçerik iki kolon: sol `flex:55`, sağ (harita) `flex:45`, aralık 12px, dış padding 12px.
Sol kolon yukarıdan aşağı: HUD paneli (`flex:1`), durum şeridi 38px, 4×2 tile ızgarası
(gap 8px), komut şeridi (acil `flex:5` / mod `flex:5` / diğer `flex:2`), alt panel 196px.
**Bileşenler:**
- Üst bar: zemin `#16222e`, alt kenar `rgba(148,188,227,0.22)`. Solda 9px yeşil bağlantı
  ledi (`#8fbf7a`, glow `0 0 8px`), başlık 17px/700 Barlow Condensed, letter-spacing .18em.
  Bağlantı dizesi alanı 196×30, zemin `#111c26`. BAĞLAN = primary buton 30px yüksek,
  KES = kırmızı hatlı (`rgba(194,91,82,0.55)`). Sağda 32px yüksek 5 durum kutusu
  (MOD / DURUM / EKF / RC / GPS): etiket 9px/600 .16em `#7e9cb8`, değer 14px/700 .08em.
- HUD: 352px yapay ufuk (daire, üst `#597ea3` / alt `#424244`, roll rotate, ufuk çizgisi
  1px `#e7e7ea`, uçak imi aksan `#94bce3`), solda 74px hız şeridi, sağda 88px irtifa şeridi
  (değer 30px/700 tabular-nums), altta 34px pusula şeridi (aktif başlık alt çizgili aksan).
- Tile: 8 kutu, etiket 10px/600 .16em `#627d98`, değer 38px/700 tabular-nums; irtifa aksan
  `#bdd8f2`, batarya uyarı `#d9a24a`, diğerleri `#e7e7ea`.
- Komutlar: 3'lü ızgara, buton yüksekliği 44px, etiket 14-15px/700 Barlow Condensed
  .1em, tek satır (`white-space:nowrap`). RTL iki hücre genişliğinde.
  Acil = dolu kırmızı `#8f3b34` / kenar `#c25b52` / hover `#a8443c`.
  PARAŞÜT = kesikli kırmızı kenar (geri alınamaz komut işareti). KES = düz kırmızı kenar.
  Aktif uçuş modu = primary dolgu `#94bce3`, metin `#12202c`.
- Alt panel: 5 sekme (IMU/ESC, Grafik, Mesaj logu, Pre-arm, RC), IMU listesi 250px,
  ESC tablosu `60px + 4×1fr` ızgara, satır 13px tabular-nums.
- Harita paneli: 38px araç şeridi (26px hatlı butonlar), gövde blueprint ızgara zemin
  (`#16222e` + 48px 1px `rgba(148,188,227,0.07)` çizgiler), drone imi 16px kırmızı daire
  + beyaz 2px kenar + glow, ev imi 12px yeşil kare 45° döndürülmüş, waypoint imleri 24px
  aksan dolgulu kare (numara 12px/700), fence kesikli yeşil dikdörtgen, güvenli iniş
  bölgeleri yarı saydam yeşil / riskli sarı daireler, sağ üstte katman lejantı,
  altta durum şeridi ve 200m ölçek çubuğu.

### 1B — Uçuş ekranı, harita sekmesiz düzen (önerilen)
Farklar: sekme şeridi yerine **96px dikey ray** (ikon + 10px etiket, aktif olanda 2px
aksan sol kenar ve `rgba(148,188,227,0.1)` zemin); üst barın altında **52px kalıcı acil
şeridi** (`rgba(194,91,82,0.1)` zemin, 36px butonlar: RTL 210px, ACİL İNİŞ 170px, diğerleri
150px + uçuş modu grubu); sol enstrüman kolonu 430px sabit (252px yapay ufuk, 2×2 tile,
batarya kartı, rüzgar & arazi kartı, sistem mesajları kartı); sağda harita **ve altında
238px görev tablosu** (`44px 150px 1fr 1fr 90px 90px 110px` kolonlar, aktif satır
`rgba(148,188,227,0.09)` zemin + "aktif ▸").

### 1C — Harita & görev planlama (tam ekran)
Sol: 40px araç şeridi (WP EKLE aktif=primary, GRID TARA, ALAN ÇİZ, FENCE ÇİZ, RALLY YÜKLE,
GÜVENLİ İNİŞ ANALİZİ=yeşil hatlı) + harita gövdesi (64px ızgara). Sağ: 520px görev paneli —
40px başlık, varsayılan irtifa / WP yarıçapı / hız alanları (30px `.input`), görev listesi
(`30px 1fr 62px 66px`), altta arazi analizi kutusu (yeşil hatlı) ve 3 buton
(DRONE'DAN OKU / TEMİZLE / GÖREVİ YÜKLE=primary, `flex 1:1:1.4`).

### 1D — Parametreler
34px araç şeridi (PARAMETRELERİ İNDİR=primary, DEĞİŞİKLİKLERİ UYGULA (3), YEDEKLE,
GERİ YÜKLE, KARŞILAŞTIR) + 360px arama alanı. Sol 230px grup listesi (BATT, FS, EKF3,
FENCE, TERRAIN, SCR, WPNAV; sayaçlar sağa yaslı; altta sarı hatlı uyarı kutusu).
Sağda gerçek tablo: kolonlar Parametre 300 / Değer 120 / Yeni değer 120 / Açıklama esnek /
Aralık 120. Değiştirilmiş satır: zemin `rgba(217,162,74,0.09)`, yeni değer `#d9a24a` 600.
Altta 34px açıklama şeridi ("Satıra çift tıklayarak değeri düzenle…").

### 1E — Pre-Arm kontrol listesi
Sol kolon: başlık + 6 kontrol satırı (`230px 220px 1fr 90px` ızgara, padding 14/16,
geçen = yeşil kenar `rgba(143,191,122,0.4)`, uyarı = sarı kenar + `rgba(217,162,74,0.08)`
zemin, sağda 13px/700 .16em durum etiketi) + ArduPilot mesaj kartı.
Sağ 430px: ARM DURUMU kartı (blueprint + card; başlık 46px/600 `#d9a24a`, 52px primary
"MOTORLARI ARM ET" butonu), GÜVENLİK KATMANLARI kartı (K1–K5), KALİBRASYON kartı (3×38px buton).

### 1F — Log indirme
Araç şeridi (LOG LİSTESİNİ AL=primary, SEÇİLİ LOGU İNDİR, KAYDEDİLEN LOGU AÇ) + indirme
klasörü metni; ilerleme kartı (12px hatlı bar, dolgu aksan, yüzde + kalan süre); gerçek
tablo (Log ID 90 / Boyut 130 / Tarih 210 / Süre 130 / Özet esnek / Durum 120; indiriliyor=aksan,
indirildi=yeşil, kartta=gri). Sağ 420px: seçili log özeti kartı (6 satır) + yerel CSV
kartı + KLASÖRÜ AÇ / HTML RAPOR OLUŞTUR (primary) butonları.

### 1G — Açılış / bağlantı ekranı
Ortalanmış iki kolon (560px + 520px, 80px aralık, 120px yan padding), zemin 80px blueprint
ızgara. Sol: kicker 12px .3em, başlık 66px/700 iki satır, alt açıklama 16px; bağlantı
dizesi `.input` 46px (aksan kenar) + yardım metni; SON KULLANILANLAR ve ŞİFRELEME alanları;
56px BAĞLAN (primary) + 210px SITL BAŞLAT. Sağ: blueprint kart — SİSTEM ÖN KONTROLÜ
(6 satır, eksik bağımlılık `#d9a24a`) ve UÇUŞ ALANI (3 satır) + bilgi kutusu.
Altta 44px durum çubuğu.

### 1H — Uçuş sonrası rapor (açık zemin, yazdırılabilir)
Zemin `#f2f2f3`, metin `#1d1f20`. 54px koyu üst bar (PDF OLARAK KAYDET=primary).
İçerik 40/64px padding: başlık bloğu (kicker 12px .26em aksan, başlık 44px/700, sağda
uçuş künyesi), 6'lı metrik kart ızgarası (blueprint + card, etiket 10px .18em, değer 34px/700),
altta iki kolon: sol `flex:1.4` irtifa & hız profili SVG + olay zaman çizelgesi kartı,
sağ `flex:1` uçuş izi SVG + sistem sağlığı kartı.

## Etkileşim ve davranış
- Sekmeler / dikey ray: tıklama ile ekran değiştirir; aktif olanda 2px aksan gösterge.
- Butonlar: hover = aksan 300 (primary) veya `rgba(148,188,227,0.12)` (hatlı);
  pressed = bir basamak koyu; klavye odağı 2px aksan outline + 2px offset.
- Acil komutlar: RTL / ACİL İNİŞ / PARAŞÜT geri alınamaz — uygulamada onay diyaloğu ister
  (mevcut kodda `_komut_onaylandi` sinyali zaten var).
- Parametre satırı: çift tıklama ile düzenlenir; yazılmamış değişiklik sarı işaretli kalır
  ve "DEĞİŞİKLİKLERİ UYGULA (n)" sayacı artar.
- Bağlantı kesilirse üst barın altında 30px kırmızı failsafe bandı görünür
  (prototipte `uyariBandi` prop'u ile açılıp kapanır).
- Harita: WP EKLE aktifken tıklama nokta ekler, sağ tık komut değiştirir, ESC çıkar.
- Log indirme: ilerleme çubuğu + kalan süre; tamamlanınca durum "indirildi" olur.
- Telemetri güncelleme hızı mevcut kodun MAVLink sinyalleriyle aynı (1–10 Hz);
  sayı alanları `tabular-nums` olduğu için genişlik zıplaması olmamalı.

## Durum (state)
- `baglanti`: kopuk | baglaniyor | bagli (üst bar ledi, BAĞLAN/KES, failsafe bandı)
- `arm_durumu`: disarmed | hazir | armed (renk + ARM butonu)
- `ucus_modu`: STABILIZE | LOITER | BRAKE | AUTO | GUIDED | SMART_RTL | RTL | LAND
- `telemetri`: irtifa, agl, hiz, dikey_hiz, roll, pitch, yaw, eve_uzaklik, batarya
  (yuzde/volt/amper/mah), gps (fix/uydu/hdop), ekf (bayrak/hata), rc (rssi/kanallar),
  ruzgar (hiz/yon/seviye), imu_sicaklik[], esc[] (rpm/sicaklik/volt/akim)
- `gorev`: waypoint listesi + aktif indeks + toplam mesafe/süre
- `parametreler`: indirilen sözlük + bekleyen değişiklikler
- `loglar`: liste + indirme ilerlemesi
- `prearm`: 6 kontrolün sonucu (gecti | dikkat | hata)

## Tasarım tokenları
Renkler (Industry + uçuş semantiği):
- Zemin (kokpit) `#1d2d3d` · panel/bar `#16222e` · gömme alan `#111c26`
- Metin `#e7e7ea` · ikincil `#9ebbd8` · üçüncül `#7e9cb8` · soluk `#627d98`
- Aksan `#94bce3` (hover `#b5d9fd`, pressed `#749dc4`, koyu `#597ea3`/`#416180`)
- Kenar `rgba(148,188,227,0.22)` · ince ayırıcı `rgba(148,188,227,0.08–0.16)`
- Durum: iyi `#8fbf7a` / `#a8cf94` · dikkat `#d9a24a` · alarm `#c25b52` (dolgu `#8f3b34`)
- Rapor (açık): zemin `#f2f2f3`, metin `#1d1f20`, aksan `#5980a6`, kenar `rgba(29,31,32,0.2)`
Tipografi: başlık/etiket Barlow Condensed 600–700 (10–66px, letter-spacing .06–.3em,
çoğunlukla büyük harf), gövde Barlow 400–600 (11–17px), sayılar `tabular-nums`.
Boşluk: 6 / 8 / 10 / 12 / 14 / 16 / 20 / 24 px. Radius: 0 (her yerde). Gölge: yok — hatlı çerçeve.
Minimum dokunma/tıklama hedefi: 26px araç şeridi, 30–34px form, 36–44px komut butonları.

## Varlıklar
Görsel varlık yok. Haritalar prototipte blueprint ızgara yer tutucusudur; üretimde mevcut
Leaflet + tile önbelleği (`gcs/map_bridge.py`, `gcs/tile_cache.py`) kullanılır.
İkonlar: Lucide, stroke-width 1.5. Fontlar: Barlow + Barlow Condensed (Google Fonts);
çevrimdışı kullanım için TTF'leri repoya gömün.

## Dosyalar
- `Yer Istasyonu v2.dc.html` — güncel tasarım (Industry sınıflarına bağlı, 8 ekran). Ana referans.
- `Yer Istasyonu.dc.html` — ilk sürüm (tamamı inline stil), karşılaştırma için.
- `Yer Istasyonu (tek dosya).html` — çevrimdışı açılan tek dosya çıktı; tarayıcıda incelemek için.
- `industry-styles.css` — tasarım sisteminin token + bileşen stil sayfası (renk/tipografi kaynağı).
- `github.md` — hangi ekranın hangi Python dosyalarından türetildiğini gösteren eşleştirme.

## Uygulama sırası (öneri)
1. `ui_theme.py` QSS'i yukarıdaki tokenlara göre yenile (renk, font, radius 0, buton varyantları).
2. Üst bar + durum kutuları + failsafe bandı.
3. 1B düzenine geç: sekme yerine dikey ray, kalıcı acil şeridi, harita + görev tablosu tek ekran.
4. Parametre ve log tablolarını `QTableWidget` başlık/satır stilleriyle güncelle.
5. Pre-arm ekranını 6 kontrol satırı + sağ kart kolonuna böl.
6. `ucus_raporlayici.py` HTML çıktısını 1H markup'ına göre yenile.
