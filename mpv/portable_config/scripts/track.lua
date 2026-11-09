-- Takipli Oynat: tıklama ile hedef seçimi (Parça 2).
-- Tıklama -> video-normalize koordinat -> `script-message track-click` (Python IPC olarak alır).
-- Offline oynatma Parça 10'da eklenecek.
local mp = require 'mp'

local enabled = false

local function osd(msg, sec) mp.osd_message("Takipli Oynat: " .. msg, sec or 2) end

-- Pencere pikselini video-normalize (0..1) koordinata çevirir; video dışındaysa nil.
-- tracker/geometry.py::screen_to_video ile aynı formül.
-- d: osd-dimensions (w,h pencere; ml,mr,mt,mb video kenar boşlukları, zoom/pan dahil).
local function screen_to_video(mx, my, d)
  local vw = d.w - d.ml - d.mr
  local vh = d.h - d.mt - d.mb
  if vw <= 0 or vh <= 0 then return nil end
  local nx = (mx - d.ml) / vw
  local ny = (my - d.mt) / vh
  if nx < 0 or nx > 1 or ny < 0 or ny > 1 then return nil end
  return nx, ny
end

local function on_click()
  local d = mp.get_property_native("osd-dimensions")
  local params = mp.get_property_native("video-params")
  local pos = mp.get_mouse_pos()
  if not (d and params and params.w and params.h and pos) then
    osd("video henüz hazır değil")
    return
  end
  local nx, ny = screen_to_video(pos.x, pos.y, d)
  if not nx then
    osd("tıklama video dışında", 1)
    return
  end
  local t = mp.get_property_number("time-pos", 0)
  mp.commandv("script-message", "track-click",
    string.format("%.6f", nx), string.format("%.6f", ny),
    string.format("%d", params.w), string.format("%d", params.h),
    string.format("%.3f", t))
  osd(string.format("hedef (%d, %d) px", nx * params.w, ny * params.h), 1)
end

local function set_enabled(on)
  if on == enabled then return end
  enabled = on
  if enabled then
    -- Takip açıkken sol tık hedef seçer (varsayılan sol tık davranışını geçersiz kılar)
    mp.add_forced_key_binding("MBTN_LEFT", "track-click-bind", on_click)
  else
    mp.remove_key_binding("track-click-bind")
  end
  mp.commandv("script-message", "track-toggle", enabled and "on" or "off")
  osd(enabled and "AÇIK - hedefe sol tıkla" or "KAPALI")
end

mp.add_key_binding(nil, "toggle", function() set_enabled(not enabled) end)

mp.add_key_binding(nil, "reset", function()
  mp.set_property_number("video-zoom", 0)
  mp.set_property_number("video-pan-x", 0)
  mp.set_property_number("video-pan-y", 0)
  mp.commandv("script-message", "track-reset")
  osd("sıfırlandı")
end)

mp.msg.info("track.lua yüklendi")
