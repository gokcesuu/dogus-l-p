-- terrain_brake.lua
-- Doğuş Üniversitesi LÖP
--
-- Arazi üzerindeki yükseklik (AGL) belirli bir eşiğin altına düşünce
-- otomatik olarak BRAKE moduna geçer.  Yer çarpışmasını önler.
--
-- Resmi ArduPilot copter_terrain_brake.lua ile karşılaştırılıp 3 koruma eklendi:
--   • Mod kısıtlaması — sadece pilot etkisindeki modlarda çalışır (LOITER/ALT_HOLD/
--     POSHOLD/STABILIZE/ACRO). AUTO/GUIDED/RTL/LAND modlarında devre dışı çünkü bu
--     modlarda kontrollü alçalma kasıtlı olabilir (örn. GCS'in LIDAR güvenli iniş
--     taraması GUIDED modda 5m AGL'e kadar iniyor — bu script onu kesmemeli).
--   • Ev'e yakınlık eşiği — kalkış/iniş sırasında ev noktasına yakınken (varsayılan
--     50m) tetiklenmez; bu bölgede düşük AGL beklenen bir durumdur.
--   • Tırmanış override'ı — dikey hız zaten yukarı doğruysa (tehlikeden uzaklaşıyor)
--     fren uygulanmaz.
--
-- Çalışma mantığı:
--   • 5 Hz'de terrain:height_above_terrain(true) oku (true = extrapolation, tile
--     eksikse de en yakın tahmini ver)
--   • Mod uygun + ev'den yeterince uzak + AGL < eşik + tırmanmıyor → BRAKE (mod 12)
--   • AGL > eşik * 1.5 → önceki moda geri dön (histerezis)
--
-- Parametreler:
--   SCR_USER1  — Tetikleme yüksekliği AGL (metre, varsayılan 30)
--   SCR_USER2  — Ev'e yakınlık eşiği (metre, varsayılan 50) — bu mesafe içinde pasif
--   SCR_USER3  — Tırmanış override hızı (m/s, varsayılan 0=devre dışı). >0 ise bu
--                hızdan daha hızlı tırmanırken fren uygulanmaz.
--
-- Kurulum:
--   1. Bu dosyayı SD kart → APM/scripts/ klasörüne kopyala
--   2. SCR_ENABLE = 1
--   3. İsteğe bağlı: SCR_USER1 = 20  (daha alçak tetikleme için)

local SCRIPT_ADI   = "terrain_brake"
local KONTROL_MS   = 200      -- 200ms → 5 Hz
local HIST_FAKT    = 1.5      -- çıkış eşiği = TA_ALT × 1.5
local ALT_VARSAYILAN  = 30.0  -- SCR_USER1 tanımsızsa kullan
local EV_VARSAYILAN   = 50.0  -- SCR_USER2 tanımsızsa kullan (metre)
local TIRMANIS_VARSAYILAN = 0.0  -- SCR_USER3 tanımsızsa kullan (0=devre dışı)

-- Sadece bu modlarda aktif — kontrollü/otonom alçalma modlarına dokunma
local IZIN_VERILEN_MODLAR = {
    [0]  = true,   -- STABILIZE
    [1]  = true,   -- ACRO
    [2]  = true,   -- ALT_HOLD
    [5]  = true,   -- LOITER
    [16] = true,   -- POSHOLD
}

-- SCR_USER1/2/3 parametrelerine bağlan
local p_alt      = Parameter()
local p_alt_ok   = p_alt:init("SCR_USER1")
local p_ev       = Parameter()
local p_ev_ok    = p_ev:init("SCR_USER2")
local p_tirmanis = Parameter()
local p_tirmanis_ok = p_tirmanis:init("SCR_USER3")

local function alt_esik()
    if p_alt_ok then
        local v = p_alt:get()
        if v and v > 0 then return v end
    end
    return ALT_VARSAYILAN
end

local function ev_esik()
    if p_ev_ok then
        local v = p_ev:get()
        if v and v >= 0 then return v end
    end
    return EV_VARSAYILAN
end

local function tirmanis_esik()
    if p_tirmanis_ok then
        local v = p_tirmanis:get()
        if v and v >= 0 then return v end
    end
    return TIRMANIS_VARSAYILAN
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
        "%s: AGL düşük — BRAKE moduna girildi (eşik=%.0fm)", SCRIPT_ADI, alt_esik()
    ))
end

local function brake_bitir()
    if not frenleme_aktif then return end
    frenleme_aktif = false
    local geri = onceki_mod or 5   -- yoksa LOITER
    vehicle:set_mode(geri)
    gcs:send_text(6, SCRIPT_ADI .. ": Güvenli yükseklik, önceki moda dönüldü.")
end

-- Ev noktasına mesafe (metre) — home yoksa nil döner
local function ev_mesafesi()
    local home = ahrs:get_home()
    local konum = ahrs:get_position()
    if home == nil or konum == nil then
        return nil
    end
    return home:get_distance(konum)
end

-- Dikey hız (m/s, + = yukarı) — alınamazsa nil döner
local function tirmanis_hizi()
    local vel = ahrs:get_velocity_NED()
    if vel == nil then
        return nil
    end
    return -vel:z()   -- NED'de z aşağı pozitif, tırmanış için işareti çeviriyoruz
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

    -- Mod uygun değilse (AUTO/GUIDED/RTL/LAND gibi kontrollü modlar) dokunma —
    -- zaten frenleme aktifse de bırak, kontrol o modun mantığına ait artık.
    local mevcut_mod = vehicle:get_mode()
    if not IZIN_VERILEN_MODLAR[mevcut_mod] then
        if frenleme_aktif then
            frenleme_aktif = false
            onceki_mod = nil
        end
        return update, KONTROL_MS
    end

    -- Ev'e yakınsa (kalkış/iniş bölgesi) pasif kal
    local ev_mesafe = ev_mesafesi()
    if ev_mesafe ~= nil and ev_mesafe < ev_esik() then
        return update, KONTROL_MS
    end

    local clearance = terrain:height_above_terrain(true)
    if clearance == nil then
        -- Terrain verisi yok — işlem yapma
        return update, KONTROL_MS
    end

    local e = alt_esik()
    if clearance < e then
        -- Zaten tırmanıyorsa (tehlikeden uzaklaşıyor) fren uygulama
        local t_esik = tirmanis_esik()
        local tirmaniyor = false
        if t_esik > 0 then
            local hiz = tirmanis_hizi()
            if hiz ~= nil and hiz > t_esik then
                tirmaniyor = true
            end
        end
        if not tirmaniyor then
            brake_baslat()
        end
    elseif clearance > e * HIST_FAKT then
        brake_bitir()
    end

    return update, KONTROL_MS
end

gcs:send_text(6, string.format(
    "%s yüklendi — AGL eşiği=%.0fm, ev yarıçapı=%.0fm (SCR_USER1/2)",
    SCRIPT_ADI, alt_esik(), ev_esik()
))
return update, 5000   -- ilk çalıştırma 5sn bekle
