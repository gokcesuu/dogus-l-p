-- terrain_brake.lua
-- Doğuş Üniversitesi LÖP
--
-- Arazi üzerindeki yükseklik (AGL) belirli bir eşiğin altına düşünce
-- otomatik olarak BRAKE moduna geçer.  Yer çarpışmasını önler.
--
-- Çalışma mantığı:
--   • 5 Hz'de terrain:height_above_terrain() oku
--   • AGL < TA_ALT → BRAKE (mod 12)
--   • AGL > TA_ALT * 1.5 → önceki moda geri dön (histerezis)
--
-- Parametreler:
--   SCR_USER1  — Tetikleme yüksekliği AGL (metre, varsayılan 30)
--
-- Kurulum:
--   1. Bu dosyayı SD kart → APM/scripts/ klasörüne kopyala
--   2. SCR_ENABLE = 1
--   3. İsteğe bağlı: SCR_USER1 = 20  (daha alçak tetikleme için)

local SCRIPT_ADI  = "terrain_brake"
local KONTROL_MS  = 200      -- 200ms → 5 Hz
local HIST_FAKT   = 1.5      -- çıkış eşiği = TA_ALT × 1.5
local VARSAYILAN  = 30.0     -- SCR_USER1 tanımsızsa kullan

-- SCR_USER1 parametresine bağlan
local ta_alt_param = Parameter()
local param_tamam  = ta_alt_param:init("SCR_USER1")

local function esik()
    if param_tamam then
        local v = ta_alt_param:get()
        if v and v > 0 then return v end
    end
    return VARSAYILAN
end

-- Durum
local frenleme_aktif = false
local onceki_mod     = nil

local function brake_baslat()
    if frenleme_aktif then return end
    onceki_mod      = vehicle:get_mode()
    frenleme_aktif  = true
    vehicle:set_mode(12)   -- BRAKE = 12
    gcs:send_text(2, string.format(
        "%s: AGL düşük — BRAKE moduna girildi (eşik=%.0fm)", SCRIPT_ADI, esik()
    ))
end

local function brake_bitir()
    if not frenleme_aktif then return end
    frenleme_aktif = false
    local geri = onceki_mod or 5   -- yoksa LOITER
    vehicle:set_mode(geri)
    gcs:send_text(6, SCRIPT_ADI .. ": Güvenli yükseklik, önceki moda dönüldü.")
end

function update()
    -- Sadece armed iken aktif
    if not arming:is_armed() then
        if frenleme_aktif then
            frenleme_aktif = false
            onceki_mod = nil
        end
        return update, 1000
    end

    local clearance = terrain:height_above_terrain()
    if clearance == nil then
        -- Terrain verisi yok — işlem yapma
        return update, KONTROL_MS
    end

    local e = esik()
    if clearance < e then
        brake_baslat()
    elseif clearance > e * HIST_FAKT then
        brake_bitir()
    end

    return update, KONTROL_MS
end

gcs:send_text(6, string.format(
    "%s yüklendi — tetikleme eşiği=%.0fm (SCR_USER1)", SCRIPT_ADI, esik()
))
return update, 5000   -- ilk çalıştırma 5sn bekle
