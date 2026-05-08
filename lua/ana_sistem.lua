--[[
ana_sistem.lua
Doğuş Üniversitesi LÖP – Ana Sistem ve Enerji Yönetimi

SD Kart: /APM/scripts/ana_sistem.lua
Gereksinim: SCR_ENABLE = 1

Görevler:
  - Batarya seviyesine göre mod ve hız kısıtlaması
  - Rüzgar eşiğinde otomatik RTL / LAND
  - Düşük bataryada sensör kapama (pil tasarrufu)
  - GCS'e Türkçe uyarı mesajları
  - Tüm kararları MAVLink STATUSTEXT ile loglar
--]]

-- ── Sabitler ─────────────────────────────────────────────────────────────────

local DONGU_HZ          = 2       -- saniyede 2 kez çalış (500ms)
local MESAJ_ARALIK_MS   = 5000    -- GCS'e mesaj gönderme aralığı

-- Batarya eşikleri (yüzde)
local BAT_DUSUK         = 25
local BAT_KRITIK        = 15
local BAT_ACIL          = 8

-- Rüzgar eşikleri (m/s)
local RUZGAR_DIKKAT     = 5.5     -- ~20 km/s
local RUZGAR_TEHLIKELI  = 11.1    -- ~40 km/s
local RUZGAR_KRITIK     = 16.7    -- ~60 km/s

-- Hız kısıtlamaları (cm/s)
local HIZ_NORMAL        = 1000    -- 10 m/s
local HIZ_DUSUK_BAT     = 500     -- 5 m/s  (batarya düşükken)
local HIZ_KRITIK_BAT    = 300     -- 3 m/s  (batarya kritikken)

-- ── Durum değişkenleri ────────────────────────────────────────────────────────

local son_mesaj_ms      = 0
local son_bat_yuzde     = 100
local rtl_gonderildi    = false
local land_gonderildi   = false
local hiz_kisitlandi    = false

-- ── Yardımcı fonksiyonlar ─────────────────────────────────────────────────────

local function gcs_mesaj(seviye, metin)
    gcs:send_text(seviye, "[ANA-SİS] " .. metin)
end

local function hiz_ayarla(cms)
    if not hiz_kisitlandi or cms ~= param:get("WPNAV_SPEED") then
        param:set("WPNAV_SPEED", cms)
        hiz_kisitlandi = true
    end
end

-- ── Ana döngü ─────────────────────────────────────────────────────────────────

local function guncelle()
    collectgarbage()

    local simdi_ms = millis()

    -- Batarya verisi
    local bat_yuzde = battery:capacity_remaining_pct(0)
    local bat_volt  = battery:voltage()
    local bat_amper = battery:current_amps()

    -- Rüzgar verisi
    local ruzgar_ms = 0
    if airspeed then
        ruzgar_ms = math.abs(airspeed:get_airspeed() or 0)
    end

    -- ── Batarya kararları ─────────────────────────────────────────────────

    if bat_yuzde ~= son_bat_yuzde then
        son_bat_yuzde = bat_yuzde

        if bat_yuzde <= BAT_ACIL and not land_gonderildi then
            land_gonderildi = true
            rtl_gonderildi  = true
            vehicle:set_mode(vehicle.LAND)
            gcs_mesaj(2, string.format(
                "ACİL İNİŞ! Batarya %%%.0f | %.2fV", bat_yuzde, bat_volt
            ))

        elseif bat_yuzde <= BAT_KRITIK and not rtl_gonderildi then
            rtl_gonderildi = true
            vehicle:set_mode(vehicle.RTL)
            hiz_ayarla(HIZ_KRITIK_BAT)
            gcs_mesaj(3, string.format(
                "KRİTİK BATARYA %%%.0f → Eve dönüş başlatıldı | %.2fV",
                bat_yuzde, bat_volt
            ))

        elseif bat_yuzde <= BAT_DUSUK then
            hiz_ayarla(HIZ_DUSUK_BAT)
            if simdi_ms - son_mesaj_ms > MESAJ_ARALIK_MS then
                son_mesaj_ms = simdi_ms
                gcs_mesaj(4, string.format(
                    "Düşük batarya %%%.0f | Hız kısıtlandı: %.0f m/s",
                    bat_yuzde, HIZ_DUSUK_BAT / 100
                ))
            end

        else
            -- Batarya normale döndüyse hız kısıtlamasını kaldır
            if hiz_kisitlandi then
                param:set("WPNAV_SPEED", HIZ_NORMAL)
                hiz_kisitlandi = false
                rtl_gonderildi = false
                land_gonderildi = false
            end
        end
    end

    -- ── Rüzgar kararları ──────────────────────────────────────────────────

    if ruzgar_ms >= RUZGAR_KRITIK and not land_gonderildi then
        land_gonderildi = true
        rtl_gonderildi  = true
        vehicle:set_mode(vehicle.LAND)
        gcs_mesaj(2, string.format(
            "KRİTİK RÜZGAR! %.1f m/s → Acil iniş", ruzgar_ms
        ))

    elseif ruzgar_ms >= RUZGAR_TEHLIKELI and not rtl_gonderildi then
        rtl_gonderildi = true
        vehicle:set_mode(vehicle.RTL)
        gcs_mesaj(3, string.format(
            "Tehlikeli rüzgar! %.1f m/s → Eve dönüş başlatıldı", ruzgar_ms
        ))

    elseif ruzgar_ms >= RUZGAR_DIKKAT then
        if simdi_ms - son_mesaj_ms > MESAJ_ARALIK_MS then
            son_mesaj_ms = simdi_ms
            gcs_mesaj(4, string.format(
                "Rüzgar artıyor: %.1f m/s (%.0f km/s) – Dikkat!",
                ruzgar_ms, ruzgar_ms * 3.6
            ))
        end

    elseif ruzgar_ms < RUZGAR_DIKKAT then
        -- Rüzgar sakinleşince bayrakları sıfırla (RTL değilsek)
        if vehicle:get_mode() ~= vehicle.RTL and vehicle:get_mode() ~= vehicle.LAND then
            rtl_gonderildi  = false
            land_gonderildi = false
        end
    end

    -- ── Periyodik durum mesajı ────────────────────────────────────────────

    if simdi_ms - son_mesaj_ms > MESAJ_ARALIK_MS * 2 then
        son_mesaj_ms = simdi_ms
        gcs_mesaj(6, string.format(
            "Durum: Bat=%%%.0f %.2fV %.1fA | Rüzgar=%.1fm/s",
            bat_yuzde, bat_volt, bat_amper, ruzgar_ms
        ))
    end

    return 1000 / DONGU_HZ  -- ms cinsinden sonraki çalışma süresi
end

-- ArduPilot script motoru bu fonksiyonu çağırır
return guncelle
