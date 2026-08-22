repo: gokcesuu/dogus-l-p
branch: main
path: gcs

> **NOT:** İlk sürüm (`Yer Istasyonu.dc.html`, `Yer Istasyonu standalone-src.dc.html`)
> repodan kaldırıldı — kafa karışıklığı olmasın diye sadece güncel/nihai tasarım
> (`Yer Istasyonu v2.dc.html`) ve onun çevrimdışı görünümü
> (`Yer Istasyonu (tek dosya).html`, v2 içeriğiyle üretilmiştir) tutuluyor.
> Kodda uygulanan tasarım budur (bkz. `../READMEe.md`).

## Last sync

date: 2026-08-21T16:48:52Z

### Updated in this project

- Türkçe yer istasyonu için iki uçuş ekranı düzeni tasarlandı (1a sekmeli, 1b harita sekmesiz)
- Harita & görev, parametreler, pre-arm, log, bağlantı ve uçuş raporu ekranları eklendi
- Tek dosya çevrimdışı HTML çıktısı üretildi

## Screen map

| Ekran | Kaynak dosyalar |
| --- | --- |
| 1a / 1b Uçuş (HUD, tile'lar, komutlar) | gcs/gcs_main.py, gcs/ui_widgets.py, gcs/ui_theme.py, gcs/mavlink_handler.py |
| 1c Harita & Görev | gcs/map_bridge.py, gcs/ucus_alani_hazirla.py, gcs/terrain_analiz.py, gcs/alan_inis_karar.py, gcs/fence_yukle.py, gcs/rally_yukle.py |
| 1d Parametreler | gcs/param_yukle.py, lua/param_lockdown.lua, config.json |
| 1e Pre-Arm | gcs/gcs_main.py, config.json, lua/ana_sistem.lua, lua/imu_thermal_control.lua |
| 1f Log | gcs/gcs_logger.py, gcs/workers.py |
| 1g Bağlantı / açılış | gcs/splash_screen.py, gcs/config_yukleyici.py, gcs/tile_cache.py, pi_kopru.py |
| 1h Uçuş raporu | gcs/ucus_raporlayici.py, gcs/ucus_raporu.py |
