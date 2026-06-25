-- deadreckon_home.lua
-- Doğuş Üniversitesi LÖP
--
-- GPS 3D fix kaybolunca GUIDED_NOGPS moduna geçer ve son bilinen
-- ev yönünde sabit hızla ilerler.  GPS geri gelince RTL başlatır.
--
-- Çalışma mantığı:
--   1. Arm anında ahrs:get_home() ile ev konumunu kaydet
--   2. GPS fix < 3D için 3sn sayaç tut
--   3. Sayaç dolunca GUIDED_NOGPS + velocity komutuyla eve ilerle
--   4. Önce MIN_IRTIFA_M'ye çık (zemin yakınsa)
--   5. GPS geri gelince RTL
--
-- Kurulum:
--   1. SD kart → APM/scripts/ klasörüne kopyala
--   2. SCR_ENABLE = 1
--
-- Not: vehicle:set_target_velocity_NED() ArduPilot 4.2+ gerektirir.

local SCRIPT_ADI     = "deadreckon_home"
local GPS_KAYIP_MS   = 3000    -- GPS kayıp sayılması için bekleme (ms)
local MIN_IRTIFA_M   = 20.0    -- Eve dönmeden önce minimum yükseklik (AGL)
local HIZLANMA_MS    = 4.0     -- Eve doğru hız (m/s)
local KONTROL_MS     = 500     -- 2 Hz normal kontrol

-- Durum
local ev_konum       = nil     -- {lat_deg, lon_deg}  (arm'da kaydedilir)
local son_arm        = false
local gps_kayip_t    = nil     -- GPS kaybının zamanı (millis)
local aktif          = false   -- script müdahale ediyor mu?

-- ── Yardımcı fonksiyonlar ────────────────────────────────────────────────────

local function bearing_rad(lat1, lon1, lat2, lon2)
    local dlon = math.rad(lon2 - lon1)
    local rl1, rl2 = math.rad(lat1), math.rad(lat2)
    local y = math.sin(dlon) * math.cos(rl2)
    local x = math.cos(rl1) * math.sin(rl2) -
              math.sin(rl1) * math.cos(rl2) * math.cos(dlon)
    return math.atan(y, x)
end

-- ── Ana döngü ────────────────────────────────────────────────────────────────

function update()
    local simdi = millis()
    local simdiki_arm = arming:is_armed()

    -- Arm olunca ev konumunu kaydet
    if simdiki_arm and not son_arm then
        local home = ahrs:get_home()
        if home then
            ev_konum = {
                lat = home:lat() / 1e7,
                lon = home:lng() / 1e7,
            }
            gcs:send_text(6, string.format(
                "%s: Ev → %.5f, %.5f", SCRIPT_ADI, ev_konum.lat, ev_konum.lon
            ))
        end
    end
    son_arm = simdiki_arm

    -- Disarm → sıfırla
    if not simdiki_arm then
        aktif       = false
        gps_kayip_t = nil
        return update, 1000
    end

    -- GPS durumu
    local gps_fix = gps:status(0)
    local gps_iyi = (gps_fix ~= nil and gps_fix >= 3)

    if gps_iyi then
        -- GPS geri geldi
        gps_kayip_t = nil
        if aktif then
            aktif = false
            vehicle:set_mode(6)   -- RTL
            gcs:send_text(4, SCRIPT_ADI .. ": GPS geri geldi → RTL başlatıldı.")
        end
        return update, KONTROL_MS
    end

    -- GPS yok — sayaç başlat
    if gps_kayip_t == nil then
        gps_kayip_t = simdi
        gcs:send_text(4, SCRIPT_ADI .. ": GPS zayıfladı, sayaç başladı...")
        return update, KONTROL_MS
    end

    -- Bekleme süresi dolmadıysa bekle
    if (simdi - gps_kayip_t) < GPS_KAYIP_MS then
        return update, KONTROL_MS
    end

    -- Ev konumu bilinmiyor → güvenli LAND
    if ev_konum == nil then
        if not aktif then
            aktif = true
            vehicle:set_mode(9)   -- LAND
            gcs:send_text(3, SCRIPT_ADI .. ": Ev yok — LAND!")
        end
        return update, 2000
    end

    -- İlk kez müdahale
    if not aktif then
        aktif = true
        vehicle:set_mode(15)   -- GUIDED_NOGPS
        gcs:send_text(2, SCRIPT_ADI .. ": GPS kayıp → GUIDED_NOGPS, eve ilerliyor...")
    end

    -- Mevcut pozisyonu IMU/barometer'dan al
    local pos = ahrs:get_position()
    if pos == nil then
        return update, KONTROL_MS
    end

    local guncel_lat = pos:lat() / 1e7
    local guncel_lon = pos:lng() / 1e7

    -- Önce yeterli yüksekliğe çık (acil_inis.lua ile aynı, doğrulanmış API)
    local irtifa = baro:get_altitude()
    if irtifa ~= nil and irtifa < MIN_IRTIFA_M then
        local vel = Vector3f()
        vel:x(0.0)
        vel:y(0.0)
        vel:z(-2.0)   -- 2 m/s yukarı (NED: negatif = yukarı)
        vehicle:set_target_velocity_NED(vel)
        return update, 200   -- 5 Hz
    end

    -- Eve doğru velocity komutu
    local br = bearing_rad(guncel_lat, guncel_lon, ev_konum.lat, ev_konum.lon)
    local vel = Vector3f()
    vel:x(HIZLANMA_MS * math.cos(br))   -- Kuzey bileşeni
    vel:y(HIZLANMA_MS * math.sin(br))   -- Doğu bileşeni
    vel:z(0.0)
    vehicle:set_target_velocity_NED(vel)

    return update, 200   -- 5 Hz — velocity komutu sürekli yenilensin
end

gcs:send_text(6, string.format(
    "%s yüklendi — GPS kayıp eşiği=%.0fs, min irtifa=%.0fm",
    SCRIPT_ADI, GPS_KAYIP_MS / 1000, MIN_IRTIFA_M
))
return update, 5000   -- ilk çalıştırma 5sn bekle
