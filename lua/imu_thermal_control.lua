--[[
  imu_thermal_control.lua
  Doğuş Üniversitesi LÖP – Yerli Uçuş Kontrol Kartı

  Her IMU için bağımsız histerezis ısı kontrolü.
  Isıtma devresine bağlı GPIO pinlerini yönetir.

  SD kart konumu: /APM/scripts/imu_thermal_control.lua
  Gerekli ArduPilot parametresi: SCR_ENABLE = 1

  GPIO pin atamaları (kartınıza göre ayarlayın):
    IMU 0 → HEAT_PIN_0
    IMU 1 → HEAT_PIN_1
    IMU 2 → HEAT_PIN_2
--]]

-- ── Yapılandırma ─────────────────────────────────────────────────────────────

local HEAT_PIN = {54, 55, 56}   -- GPIO pin numaraları (IMU 0, 1, 2)
                                 -- ArduPilot'ta GPIO numaraları donanıma göre değişir;
                                 -- kendi kartınızın pinout tablosuna bakınız.

local SICAKLIK_HEDEF_NORMAL  = 35.0   -- °C  – ısıtmayı KAPATMA eşiği
local SICAKLIK_AKTIF_NORMAL  = 30.0   -- °C  – ısıtmayı AÇMA eşiği

local SICAKLIK_HEDEF_SOGUK   = 40.0   -- °C  – soğuk hava hedefi
local SICAKLIK_AKTIF_SOGUK   = 35.0   -- °C  – soğuk hava açma eşiği
local SOGUK_HAVA_SINIRI      = -10.0  -- °C  – bu değerin altında soğuk protokol

local KONTROL_PERIYODU_MS    = 200    -- ms  – kontrol döngüsü süresi
local MESAJ_PERIYODU_MS      = 5000   -- ms  – GCS mesajı gönderme sıklığı
local IMU_SAYISI             = 3

-- ── Durum değişkenleri ────────────────────────────────────────────────────────

local isiticiler_acik = {false, false, false}
local son_mesaj_zaman = 0
local toplam_cevrim   = 0

-- ── Yardımcı işlevler ─────────────────────────────────────────────────────────

local function gcs_yaz(metin)
  gcs:send_text(6, "IMU-ISI: " .. metin)  -- severity 6 = INFO
end

local function gcs_uyar(metin)
  gcs:send_text(4, "IMU-ISI UYARI: " .. metin)  -- severity 4 = WARNING
end

local function pin_ayarla(pin_no, acik)
  -- gpio.write() ArduPilot Lua API'sinde mevcuttur.
  -- Doğrudan dijital çıkış: HIGH ısıtmayı açar, LOW kapatır.
  gpio.write(pin_no, acik and 1 or 0)
end

local function sicaklik_oku(imu_idx)
  -- ins:get_temperature(index) ArduPilot 4.1+ Lua API
  local t = ins:get_temperature(imu_idx)
  if t == nil then return nil end
  return t
end

local function soguk_hava_mi()
  -- En soğuk IMU'ya bak ya da dış ortam sıcaklığı sensörü varsa onu kullan.
  -- Burada IMU 0'ı referans alıyoruz.
  local t = sicaklik_oku(0)
  if t == nil then return false end
  return t < SOGUK_HAVA_SINIRI
end

-- ── Ana kontrol döngüsü ───────────────────────────────────────────────────────

local function kontrol_et()
  collectgarbage()
  toplam_cevrim = toplam_cevrim + 1

  local soguk_protokol = soguk_hava_mi()
  local hedef, aktif_esik

  if soguk_protokol then
    hedef      = SICAKLIK_HEDEF_SOGUK
    aktif_esik = SICAKLIK_AKTIF_SOGUK
  else
    hedef      = SICAKLIK_HEDEF_NORMAL
    aktif_esik = SICAKLIK_AKTIF_NORMAL
  end

  local durum_satirlari = {}

  for i = 0, IMU_SAYISI - 1 do
    local t = sicaklik_oku(i)
    local pin = HEAT_PIN[i + 1]

    if t == nil then
      -- Sensör okunamıyorsa ısıtmayı kapat (güvenli varsayılan)
      isiticiler_acik[i + 1] = false
      pin_ayarla(pin, false)
      table.insert(durum_satirlari, string.format("IMU%d:?°C", i))
    else
      local yeni_durum = isiticiler_acik[i + 1]

      -- Histerezis: açma eşiğinin altındaysa aç, kapama eşiğinin üstündeyse kapat
      if t < aktif_esik then
        yeni_durum = true
      elseif t > hedef then
        yeni_durum = false
      end
      -- aktif_esik ≤ t ≤ hedef aralığında mevcut durum korunur

      if yeni_durum ~= isiticiler_acik[i + 1] then
        -- Durum değişti, hemen uygula ve GCS'e bildir
        isiticiler_acik[i + 1] = yeni_durum
        pin_ayarla(pin, yeni_durum)
        if yeni_durum then
          gcs_yaz(string.format("IMU%d isitici ACILDI (%.1f°C < %.1f°C)", i, t, aktif_esik))
        else
          gcs_yaz(string.format("IMU%d isitici KAPATILDI (%.1f°C > %.1f°C)", i, t, hedef))
        end
      else
        pin_ayarla(pin, yeni_durum)
      end

      table.insert(
        durum_satirlari,
        string.format("IMU%d:%.1f°C(%s)", i, t, yeni_durum and "ON" or "off")
      )

      -- Kritik uyarılar
      if t > 70.0 then
        gcs_uyar(string.format("IMU%d ASIRI SICAKLIK: %.1f°C", i, t))
      end
    end
  end

  -- Periyodik durum mesajı
  local simdi = millis()
  if simdi - son_mesaj_zaman >= MESAJ_PERIYODU_MS then
    son_mesaj_zaman = simdi
    local protokol_str = soguk_protokol and " [SOGUK PROTOKOL]" or ""
    gcs_yaz(table.concat(durum_satirlari, " | ") .. protokol_str)
  end

  return KONTROL_PERIYODU_MS
end

-- ── Başlangıç ─────────────────────────────────────────────────────────────────

-- GPIO pinlerini çıkış olarak ayarla ve başlangıçta kapat
for i = 1, IMU_SAYISI do
  gpio.mode(HEAT_PIN[i], gpio.OUTPUT)
  pin_ayarla(HEAT_PIN[i], false)
end

gcs_yaz(string.format(
  "IMU isi kontrolu basladi. Pinler: %d/%d/%d | Normal: <%d°C ac, >%d°C kapat",
  HEAT_PIN[1], HEAT_PIN[2], HEAT_PIN[3],
  SICAKLIK_AKTIF_NORMAL, SICAKLIK_HEDEF_NORMAL
))

-- ArduPilot Lua scheduler: return değeri bir sonraki çağrıya kadar beklenecek ms
return kontrol_et()
