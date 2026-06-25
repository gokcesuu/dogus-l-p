--[[
acil_inis.lua
Doğuş Üniversitesi LÖP – Acil İniş Karar Sistemi

SD Kart: /APM/scripts/acil_inis.lua
Gereksinim: SCR_ENABLE = 1

Ana sistemden bağımsız çalışır — daha sık kontrol yapar.
Karar ağacı:
  1. GPS kaybı > eşik → LAND (hovering ile acil)
  2. EKF hatası yüksek → RTL veya LAND
  3. Batarya voltajı kritik (hücre başı) → LAND
  4. İrtifa aniden düşüyor (crash?) → LOG + uyarı
  5. ARM değilken hareket → uyarı
--]]

-- ── Sabitler ─────────────────────────────────────────────────────────────────

local DONGU_HZ              = 5      -- 200ms'de bir çalış (hızlı kontrol)

-- GPS
local GPS_KAYIP_SURE_MS     = 3000   -- 3 saniye GPS yoksa acil

-- Batarya hücre voltajı (LiPo)
local HUCRE_KRITIK_V        = 3.3   -- hücre başı kritik voltaj
local HUCRE_SAYISI          = 4     -- 4S batarya

-- İrtifa düşüşü
local IRTIFA_DUSUS_MS       = 1000   -- 1 saniyede
local IRTIFA_DUSUS_ESIK     = -3.0   -- m/s (dikey hız)

-- ── Durum değişkenleri ────────────────────────────────────────────────────────

local gps_son_gorulme_ms    = millis()
local son_irtifa            = 0.0
local inis_gonderildi       = false
local ekf_uyari_gonderildi  = false
local volt_uyari_gonderildi = false

-- ── Yardımcı ──────────────────────────────────────────────────────────────────

local function gcs_mesaj(seviye, metin)
    gcs:send_text(seviye, "[ACİL] " .. metin)
end

local function acil_inis_ver(sebep)
    if not inis_gonderildi then
        inis_gonderildi = true
        vehicle:set_mode(vehicle.LAND)
        gcs_mesaj(2, "ACİL İNİŞ BAŞLATILDI → " .. sebep)
    end
end

local function rtl_ver(sebep)
    if not inis_gonderildi then
        vehicle:set_mode(vehicle.RTL)
        gcs_mesaj(3, "ACİL RTL → " .. sebep)
    end
end

-- ── Ana döngü ─────────────────────────────────────────────────────────────────

local function guncelle()
    collectgarbage()

    local simdi_ms   = millis()
    local armed      = arming:is_armed()

    -- ── GPS Kontrolü ──────────────────────────────────────────────────────

    local gps_durum = gps:status(0)
    if gps_durum >= 3 then
        gps_son_gorulme_ms = simdi_ms  -- GPS var, zamanı güncelle
    elseif armed then
        local kayip_sure = simdi_ms - gps_son_gorulme_ms
        if kayip_sure > GPS_KAYIP_SURE_MS then
            acil_inis_ver(string.format(
                "GPS kayıp %.1f sn", kayip_sure / 1000
            ))
        end
    end

    -- ── EKF/AHRS Kontrolü ─────────────────────────────────────────────────
    -- ahrs:healthy() — basit, her zaman geçerli boolean sağlık kontrolü.
    -- (Önceki sürüm ahrs:get_vel_innovations_and_variances()'ın döndürdüğü
    -- Vector3f'i doğrudan sayıyla karşılaştırıyordu — bu tip uyuşmazlığı
    -- Lua runtime hatası fırlatır ve ArduPilot scripti art arda hata sonrası
    -- otomatik devre dışı bırakır, tüm acil_inis korumaları sessizce kaybolurdu.)
    local ahrs_saglikli = ahrs:healthy()
    if not ahrs_saglikli then
        if not ekf_uyari_gonderildi then
            ekf_uyari_gonderildi = true
            if armed then
                rtl_ver("EKF/AHRS sağlıksız")
            else
                gcs_mesaj(4, "EKF uyarı: AHRS sağlıksız. Kalibre et!")
            end
        end
    else
        ekf_uyari_gonderildi = false
    end

    -- ── Hücre Voltaj Kontrolü ─────────────────────────────────────────────

    local toplam_volt = battery:voltage()
    if toplam_volt > 1.0 then
        local hucre_volt = toplam_volt / HUCRE_SAYISI
        if hucre_volt < HUCRE_KRITIK_V and not volt_uyari_gonderildi then
            volt_uyari_gonderildi = true
            if armed then
                acil_inis_ver(string.format(
                    "Hücre voltaj kritik: %.2fV/hücre (<%0.1fV)",
                    hucre_volt, HUCRE_KRITIK_V
                ))
            else
                gcs_mesaj(3, string.format(
                    "Hücre voltaj kritik: %.2fV! Batarya değiştir.", hucre_volt
                ))
            end
        elseif hucre_volt >= HUCRE_KRITIK_V + 0.1 then
            volt_uyari_gonderildi = false
        end
    end

    -- ── Ani İrtifa Düşüşü Kontrolü ────────────────────────────────────────

    if armed then
        local irtifa = baro:get_altitude() or 0
        local dikey_hiz = (irtifa - son_irtifa) / (1000 / DONGU_HZ) * 1000
        son_irtifa = irtifa

        if dikey_hiz < IRTIFA_DUSUS_ESIK and irtifa > 5.0 then
            gcs_mesaj(3, string.format(
                "Hızlı alçalma tespit edildi: %.1f m/s (İrtifa: %.1fm)",
                dikey_hiz, irtifa
            ))
        end
    else
        -- ARM değilken irtifa referansını sıfırla
        son_irtifa = baro:get_altitude() or 0
        inis_gonderildi = false
    end

    return 1000 / DONGU_HZ  -- ms cinsinden sonraki çalışma süresi
end

return guncelle
