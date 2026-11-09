-- Takipli Oynat: tıklama ile hedef seçimi (Parça 2), hedef bırakma (Parça 6).
-- Tıklama -> video-normalize koordinat -> `script-message track-click` (Python IPC olarak alır).
-- Offline oynatma (Parça 10): `o` ile <video>.views.json'daki anahtar karelerden zoom/pan uygular
-- (Python gerekmez). Lua 5.1/LuaJIT uyumlu yazıldı (// ve goto yok).
local mp = require 'mp'
local utils = require 'mp.utils'

local enabled = false
local set_offline -- ileri bildirim: canlı mod açılınca offline kapatılır
local off -- ileri bildirim (offline durumu; HUD okur)

-- Köşe durum etiketi (Parça 13): Python `script-message-to track track-hud <metin>` gönderir.
-- Offline açıkken "Takip: offline ID n" gösterilir. `track/hud` tuşu etiketi gizler/gösterir.
local hud = { text = "", visible = true, ov = nil }

local function render_hud()
  if not hud.ov then hud.ov = mp.create_osd_overlay("ass-events") end
  local text = hud.text
  if off and off.on then
    text = "Takip: offline ID " .. tostring(off.target and off.target.id or "?")
  end
  text = text:gsub("[{}\\\n]", " ") -- ASS kaçışlarını ve satır sonunu etkisiz kıl
  if hud.visible and text ~= "" then
    hud.ov.data = "{\\an9\\fs20\\bord2\\shad0\\1c&HFFFFFF&\\3c&H000000&}" .. text
  else
    hud.ov.data = ""
  end
  hud.ov:update()
end

mp.register_script_message("track-hud", function(text)
  hud.text = text or ""
  render_hud()
end)

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
    set_offline(false) -- canlı ve offline aynı anda görünümü sürmesin
    -- Takip açıkken sol tık hedef seçer (varsayılan sol tık davranışını geçersiz kılar)
    mp.add_forced_key_binding("MBTN_LEFT", "track-click-bind", on_click)
  else
    mp.remove_key_binding("track-click-bind")
    hud.text = ""
    render_hud()
  end
  mp.commandv("script-message", "track-toggle", enabled and "on" or "off")
  osd(enabled and "AÇIK - hedefe sol tıkla" or "KAPALI")
end

mp.add_key_binding(nil, "toggle", function() set_enabled(not enabled) end)

mp.add_key_binding(nil, "reset", function()
  set_offline(false)
  mp.set_property_number("video-zoom", 0)
  mp.set_property_number("video-pan-x", 0)
  mp.set_property_number("video-pan-y", 0)
  mp.commandv("script-message", "track-reset")
  osd("sıfırlandı")
end)

-- Hedefi bırak (takip açık kalır; yeni tıklama yeni hedef seçer; hedefe tekrar tıklamak da bırakır).
mp.add_key_binding(nil, "release", function()
  mp.commandv("script-message", "track-release")
end)

-- ---------------------------------------------------------------------------------------------
-- Offline oynatma
off = { on = false, n = 0, T = {}, Z = {}, PX = {}, PY = {}, last = nil, target = nil }

local function read_file(path)
  local f = io.open(path, "rb")
  if not f then return nil end
  local s = f:read("*a")
  f:close()
  return s
end

local function video_path()
  local p = mp.get_property("path")
  if not p or p:match("^%a[%w+.-]*://") then return nil end -- URL/akış: yan dosya yok
  return p
end

-- Anahtar kareler [[t, zoom, pan_x, pan_y], ...] → paralel diziler. Geçersizse nil, sebep.
local function load_views(vpath)
  local reason = "bulunamadı: " .. vpath .. ".views.json (offline ... --target-id)"
  for _, suffix in ipairs({ ".views.json", ".track.json" }) do
    local text = read_file(vpath .. suffix)
    if text then
      local doc, err = utils.parse_json(text)
      if not doc then
        reason = suffix .. " okunamadı: " .. tostring(err)
      elseif doc.version ~= 1 then
        reason = suffix .. ": desteklenmeyen sürüm " .. tostring(doc.version)
      elseif type(doc.views) ~= "table" or #doc.views == 0 then
        reason = suffix .. ": hedef seçilmemiş (offline-view --target-id N)"
      else
        local o = { n = #doc.views, T = {}, Z = {}, PX = {}, PY = {}, target = doc.target }
        for i, k in ipairs(doc.views) do
          o.T[i], o.Z[i], o.PX[i], o.PY[i] = k[1], k[2], k[3], k[4]
        end
        return o
      end
    end
  end
  return nil, reason
end

-- tracker/offline.py::view_at ile aynı: anahtar kareler arası doğrusal, uçlarda sabit.
local function view_at(o, t)
  local n, T = o.n, o.T
  if t <= T[1] then return o.Z[1], o.PX[1], o.PY[1] end
  if t >= T[n] then return o.Z[n], o.PX[n], o.PY[n] end
  local lo, hi = 1, n
  while hi - lo > 1 do
    local mid = math.floor((lo + hi) / 2)
    if T[mid] <= t then lo = mid else hi = mid end
  end
  local f = 0
  if T[hi] > T[lo] then f = (t - T[lo]) / (T[hi] - T[lo]) end
  return o.Z[lo] + (o.Z[hi] - o.Z[lo]) * f,
    o.PX[lo] + (o.PX[hi] - o.PX[lo]) * f,
    o.PY[lo] + (o.PY[hi] - o.PY[lo]) * f
end

local function apply_view(z, px, py)
  local l = off.last
  if l and math.abs(l[1] - z) < 1e-4 and math.abs(l[2] - px) < 1e-4
      and math.abs(l[3] - py) < 1e-4 then
    return
  end
  off.last = { z, px, py }
  mp.set_property_number("video-zoom", z)
  mp.set_property_number("video-pan-x", px)
  mp.set_property_number("video-pan-y", py)
end

set_offline = function(on)
  if on == off.on then return end
  if on then
    local vpath = video_path()
    if not vpath then osd("offline: yerel video dosyası yok"); return end
    local data, reason = load_views(vpath)
    if not data then osd("offline " .. reason, 4); return end
    local was_live = enabled
    if was_live then set_enabled(false) end -- canlı modu kapat
    off.n, off.T, off.Z, off.PX, off.PY = data.n, data.T, data.Z, data.PX, data.PY
    off.target, off.last, off.on = data.target, nil, true
    local function reapply()
      local t = mp.get_property_number("time-pos")
      if off.on and t then off.last = nil; apply_view(view_at(off, t)) end
    end
    reapply()
    -- Canlı mod kapanırken Python'un gönderdiği 1x sıfırlaması gecikmeli gelebilir: yeniden uygula
    if was_live then mp.add_timeout(0.5, reapply) end
    render_hud()
    osd(string.format("offline AÇIK (hedef ID %s, %d anahtar kare)",
      tostring(off.target and off.target.id or "?"), off.n))
  else
    off.on, off.last = false, nil
    render_hud()
    mp.set_property_number("video-zoom", 0)
    mp.set_property_number("video-pan-x", 0)
    mp.set_property_number("video-pan-y", 0)
    osd("offline KAPALI")
  end
end

-- time-pos oynatmada ve duraklatılmışken atlamada da gelir
mp.observe_property("time-pos", "number", function(_, t)
  if off.on and t then apply_view(view_at(off, t)) end
end)

mp.add_key_binding(nil, "offline", function() set_offline(not off.on) end)

mp.register_event("end-file", function()
  if off.on then -- veri eski videoya aitti
    off.on, off.last = false, nil
    render_hud()
  end
end)

mp.register_event("file-loaded", function()
  local vpath = video_path()
  if vpath and not off.on and read_file(vpath .. ".views.json") then
    osd("offline takip verisi var - o tuşuyla aç", 3)
  end
end)

-- ---------------------------------------------------------------------------------------------
-- Canlı ayar tuşları (Parça 13): Python `track-setting` mesajını işler (canlı mod çalışıyorsa).
local function setting(key, dir)
  return function() mp.commandv("script-message", "track-setting", key, tostring(dir)) end
end
mp.add_key_binding(nil, "fill-up", setting("fill", 1))
mp.add_key_binding(nil, "fill-down", setting("fill", -1))
mp.add_key_binding(nil, "speed-up", setting("speed", 1))
mp.add_key_binding(nil, "speed-down", setting("speed", -1))
mp.add_key_binding(nil, "lead-up", setting("lead", 1))
mp.add_key_binding(nil, "lead-down", setting("lead", -1))
mp.add_key_binding(nil, "settings-reset", setting("all", 0))
mp.add_key_binding(nil, "settings-save", function() mp.commandv("script-message", "track-save") end)
mp.add_key_binding(nil, "status", function() mp.commandv("script-message", "track-status") end)
mp.add_key_binding(nil, "hud", function()
  hud.visible = not hud.visible
  render_hud()
  osd(hud.visible and "durum etiketi AÇIK" or "durum etiketi KAPALI", 1)
end)

mp.msg.info("track.lua yüklendi")
