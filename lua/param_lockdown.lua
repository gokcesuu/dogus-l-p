-- param_lockdown.lua
-- Doğuş Üniversitesi LÖP
--
-- Arm anında güvenlik-kritik parametrelerin anlık değerini "kilitler".
-- Uçuş sırasında (armed) bu parametrelerden biri GCS/operatör tarafından
-- (yanlışlıkla veya bilerek) değiştirilirse script onu eski değerine
-- geri döndürür ve GCS'e uyarı gönderir.
--
-- Neden gerekli: MAVLink PARAM_SET mesajı arm durumunu kontrol etmez —
-- uçuş sırasında FENCE_ENABLE=0 veya BATT_LOW_VOLT=0 gibi bir komut
-- (operatör hatası, yanlış tıklama, başka bir GCS'den çakışan komut)
-- gönderilirse firmware bunu sessizce kabul eder. Bu script son savunma
-- hattı olarak çalışır.
--
-- Çalışma mantığı:
--   • Disarm iken parametreler normal şekilde değiştirilebilir (kurulum/ayar
--     serbest).
--   • Arm anında korunan parametrelerin o anki değeri "kilit" olarak alınır.
--   • Armed kaldığı sürece 1 Hz'de bu değerler kontrol edilir; sapma
--     görülürse anında eski değere geri yazılır + GCS'e uyarı gönderilir.
--   • Disarm olunca kilit kalkar (sonraki arm'da yeni anlık değer alınır).
--
-- Parametreler:
--   SCR_USER4  — 1 = kilitleme aktif (varsayılan), 0 = devre dışı

local SCRIPT_ADI = "param_lockdown"
local KONTROL_MS = 1000   -- 1 Hz yeterli — parametre değişimi sık olmaz

-- Korunan parametre listesi — güvenlik/failsafe ile ilgili olanlar
local KORUNAN_PARAMLAR = {
    "FENCE_ENABLE", "FENCE_TYPE", "FENCE_ALT_MAX", "FENCE_RADIUS",
    "FS_GCS_ENABLE", "FS_THR_ENABLE", "FS_EKF_ACTION", "FS_CRASH_CHECK",
    "BATT_LOW_VOLT", "BATT_CRT_VOLT", "BATT_FS_LOW_ACT", "BATT_FS_CRT_ACT",
    "RTL_ALT", "ARMING_CHECK",
}

local kilit_param_obj  = {}   -- {[isim] = Parameter()}
local kilitli_degerler = {}   -- {[isim] = deger}
local kilitleme_aktif  = false
local onceki_armed     = false

local p_enable    = Parameter()
local p_enable_ok = p_enable:init("SCR_USER4")

local function kilit_aktif_mi()
    if p_enable_ok then
        local v = p_enable:get()
        if v ~= nil then return v >= 0.5 end
    end
    return true   -- SCR_USER4 tanımsızsa varsayılan: aktif
end

-- Parametre nesnelerini bir kez kur (her update'de yeniden init etmeye gerek yok)
for _, isim in ipairs(KORUNAN_PARAMLAR) do
    local p = Parameter()
    if p:init(isim) then
        kilit_param_obj[isim] = p
    end
end

local function sayisini_say(t)
    local n = 0
    for _ in pairs(t) do n = n + 1 end
    return n
end

local function deger_kaydet()
    kilitli_degerler = {}
    for isim, p in pairs(kilit_param_obj) do
        kilitli_degerler[isim] = p:get()
    end
    gcs:send_text(6, string.format(
        "%s: %d parametre kilitlendi (arm).", SCRIPT_ADI, sayisini_say(kilitli_degerler)
    ))
end

function update()
    if not kilit_aktif_mi() then
        return update, KONTROL_MS
    end

    local armed = arming:is_armed()

    if armed and not onceki_armed then
        -- Arm anında anlık değerleri kilitle
        deger_kaydet()
        kilitleme_aktif = true
    elseif not armed then
        kilitleme_aktif = false
    end
    onceki_armed = armed

    if kilitleme_aktif then
        for isim, p in pairs(kilit_param_obj) do
            local mevcut = p:get()
            local kilitli = kilitli_degerler[isim]
            if mevcut ~= nil and kilitli ~= nil and mevcut ~= kilitli then
                p:set(kilitli)
                gcs:send_text(2, string.format(
                    "%s: %s degistirilmeye calisildi (%.3f -> %.3f) — engellendi!",
                    SCRIPT_ADI, isim, mevcut, kilitli
                ))
            end
        end
    end

    return update, KONTROL_MS
end

gcs:send_text(6, SCRIPT_ADI ..
    " yuklendi — arm aninda guvenlik parametreleri kilitlenecek (SCR_USER4=0 ile devre disi).")
return update, 3000   -- ilk calistirma 3sn bekle
