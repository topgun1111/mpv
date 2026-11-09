-- Takipli Oynat: tıklama ile hedef seçimi (Parça 2), hedef bırakma (Parça 6).
-- SAĞ TIK (track/pick): tıklanan noktadaki HERHANGİ bir nesneyi (oyuncu olmak zorunda değil) takip
-- eder; takip kapalıysa kendiliğinden açar. Sol tık (takip açıkken) oyuncu kimliğiyle seçer.
-- Ekran üstü ZOOM kontrolü (sağ kenar): + / - düğmeleri ve anlık zoom değeri; + / - tuşları da aynı işi yapar.
-- Tıklama -> video-normalize koordinat -> `script-message track-point` (sağ tık, nesne) ya da
-- `track-click` (sol tık, oyuncu) (Python IPC olarak alır).
-- Offline oynatma (Parça 10): `o` ile <video>.views.json'daki anahtar karelerden zoom/pan uygular
-- (Python gerekmez). Lua 5.1/LuaJIT uyumlu yazıldı (// ve goto yok).
local mp = require 'mp'
local utils = require 'mp.utils'

local enabled = false
local locked = false -- Python: bir hedef kilitli mi (track-hud'un 2. argümanı); zoom +/- ne yapacağını buna göre seçer
-- Ekran üstü zoom kontrolü durumu (çizim/yerleşim aşağıda). z = video-zoom (log2).
local zoomc = { z = 0, hover = nil, rects = {}, ov = nil, shown = "" }
local render_zoom -- ileri bildirim
local set_offline -- ileri bildirim: canlı mod açılınca offline kapatılır
local off -- ileri bildirim (offline durumu; HUD okur)
local sync_click_binding -- ileri bildirim: sol tık bağı (ekran üstü panel + hedef seçimi)
local refresh_panel -- ileri bildirim: ekran üstü panel yeniden çizimi

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

mp.register_script_message("track-hud", function(text, lock)
  hud.text = text or ""
  locked = (lock == "1")
  render_hud()
  render_zoom() -- + / - davranışı değişmiş olabilir; değer etiketi aynı kalır
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

-- Fare konumu: `mouse-pos` özelliği (mpv >= 0.30); yoksa eski mp.get_mouse_pos.
local function mouse_xy()
  local p = mp.get_property_native("mouse-pos")
  if p and p.x then return p end
  if mp.get_mouse_pos then return mp.get_mouse_pos() end
  return nil
end

-- msg: "track-point" (sağ tık: herhangi bir nesne) | "track-click" (sol tık: oyuncu kimliği)
local function on_click(msg)
  local d = mp.get_property_native("osd-dimensions")
  local params = mp.get_property_native("video-params")
  local pos = mouse_xy()
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
  mp.commandv("script-message", msg or "track-click",
    string.format("%.6f", nx), string.format("%.6f", ny),
    string.format("%d", math.floor(params.w)), string.format("%d", math.floor(params.h)),
    string.format("%.3f", t))
  osd(string.format("hedef (%d, %d) px", math.floor(nx * params.w), math.floor(ny * params.h)), 1) -- Lua 5.3+: %d tamsayı ister
end

local function set_enabled(on)
  if on == enabled then return end
  enabled = on
  if enabled then
    set_offline(false) -- canlı ve offline aynı anda görünümü sürmesin
  else
    hud.text, locked = "", false
    render_hud()
  end
  -- Takip açıkken sol tık da hedef seçer (sağ tık her zaman seçer)
  sync_click_binding()
  mp.commandv("script-message", "track-toggle", enabled and "on" or "off")
  osd(enabled and "AÇIK - nesneye sağ tıkla" or "KAPALI")
  if refresh_panel then refresh_panel() end
end

mp.add_key_binding(nil, "toggle", function() set_enabled(not enabled) end)

local function do_reset()
  set_offline(false)
  mp.set_property_number("video-zoom", 0)
  mp.set_property_number("video-pan-x", 0)
  mp.set_property_number("video-pan-y", 0)
  mp.commandv("script-message", "track-reset")
  zoomc.z, locked = 0, false
  render_zoom()
  osd("sıfırlandı")
end
mp.add_key_binding(nil, "reset", do_reset)

-- Hedefi bırak (takip açık kalır; yeni tıklama yeni hedef seçer; hedefe tekrar tıklamak da bırakır).
local function do_release() mp.commandv("script-message", "track-release") end
mp.add_key_binding(nil, "release", do_release)

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
    if refresh_panel then refresh_panel() end
    osd(string.format("offline AÇIK (hedef ID %s, %d anahtar kare)",
      tostring(off.target and off.target.id or "?"), off.n))
  else
    off.on, off.last = false, nil
    render_hud()
    if refresh_panel then refresh_panel() end
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

-- ---------------------------------------------------------------------------------------------
-- Ekran üstü düğme paneli (Parça 16): fare/dokunma hareketinde sol üstte görünür, 3 sn sonra gizlenir
-- (sabitlenebilir). Düğmeler tuşlarla aynı işi yapar. Panel yalnız imleç bir düğmenin üstündeyken sol
-- tıkı yakalar; böylece mpv'nin kendi OSC'si/tıklaması bozulmaz. Zoom kontrolü (sağ kenar) için de aynı.
local PANEL_HIDE_S = 3
local panel = { visible = false, pinned = false, hover = nil, rects = {}, ov = nil, timer = nil }
local ZOOM_Z, PANEL_Z = 2, 1 -- overlay katmanları: HUD 0, panel 1, zoom kontrolü 2

-- Zoom + / - (ekran düğmeleri ve + / - tuşları). Hedef kilitliyken hedefin kareyi doldurma oranı
-- (Python zoom'u buna göre sürer); aksi halde doğrudan video-zoom (log2) ±0.25 (0..4).
local ZOOM_STEP, ZOOM_MAX = 0.25, 4
local function zoom_step(dir)
  if off.on then
    osd("offline açıkken zoom sabit; önce offline'ı kapat", 2)
  elseif enabled and locked then
    mp.commandv("script-message", "track-setting", "fill", tostring(dir))
  else
    local z = (mp.get_property_number("video-zoom", 0) or 0) + dir * ZOOM_STEP
    if z < 0 then z = 0 elseif z > ZOOM_MAX then z = ZOOM_MAX end
    mp.set_property_number("video-zoom", z)
    zoomc.z = z
    render_zoom()
    osd(string.format("zoom x%.2f", 2 ^ z), 1)
  end
end
mp.add_key_binding(nil, "zoom-in", function() zoom_step(1) end, { repeatable = true })
mp.add_key_binding(nil, "zoom-out", function() zoom_step(-1) end, { repeatable = true })

local function setting_btn(key, dir)
  return function() mp.commandv("script-message", "track-setting", key, tostring(dir)) end
end

local buttons = {
  { label = function() return "Takip: " .. (enabled and "AÇIK" or "KAPALI") end,
    active = function() return enabled end, act = function() set_enabled(not enabled) end },
  { label = "Bırak", act = do_release },
  { label = "Sıfırla", act = do_reset },
  { label = function() return "Offline: " .. (off.on and "AÇIK" or "KAPALI") end,
    active = function() return off.on end, act = function() set_offline(not off.on) end },
  { label = "Tepki -", act = setting_btn("speed", -1) },
  { label = "Tepki +", act = setting_btn("speed", 1) },
  { label = "Öngörü -", act = setting_btn("lead", -1) },
  { label = "Öngörü +", act = setting_btn("lead", 1) },
  { label = "Kaydet", act = function() mp.commandv("script-message", "track-save") end },
  { label = "Durum", act = function() mp.commandv("script-message", "track-status") end },
  { label = function() return "Sabit: " .. (panel.pinned and "AÇIK" or "KAPALI") end,
    active = function() return panel.pinned end,
    act = function() panel.pinned = not panel.pinned end },
}

local function label_of(b) if type(b.label) == "function" then return b.label() end return b.label end

-- Saf yerleşim: W,H pencere pikseli; labels -> rects {x,y,w,h} (satıra sarar), yazı boyutu.
local function panel_layout(W, H, labels)
  local bh = math.max(30, math.floor(H * 0.06))
  local fs = math.floor(bh * 0.5)
  local gap = math.floor(bh * 0.2)
  local rects, x, y = {}, gap, gap
  for i, label in ipairs(labels) do
    local n = 0
    for _ in label:gmatch("[^\128-\191]") do n = n + 1 end -- UTF-8 karakter sayısı
    local w = math.floor(n * fs * 0.62 + bh * 0.8)
    if x > gap and x + w > W - gap then x, y = gap, y + bh + gap end
    rects[i] = { x = x, y = y, w = w, h = bh }
    x = x + w + gap
  end
  return rects, fs
end

local function hit(x, y)
  for i, r in ipairs(panel.rects) do
    if x >= r.x and x <= r.x + r.w and y >= r.y and y <= r.y + r.h then return i end
  end
  return nil
end

local function render_panel()
  if not panel.ov then
    panel.ov = mp.create_osd_overlay("ass-events")
    panel.ov.z = PANEL_Z
  end
  local d = mp.get_property_native("osd-dimensions")
  if not panel.visible or not (d and d.w and d.w > 0 and d.h and d.h > 0) then
    panel.rects = {}
    panel.ov.data = ""
    panel.ov:update()
    return
  end
  local labels = {}
  for i, b in ipairs(buttons) do labels[i] = label_of(b) end
  local rects, fs = panel_layout(d.w, d.h, labels)
  panel.rects = rects
  panel.ov.res_x, panel.ov.res_y = d.w, d.h
  local ev = {}
  for i, r in ipairs(rects) do
    local on = buttons[i].active and buttons[i].active()
    local col = on and "3C8C2E" or "303030" -- BGR
    if panel.hover == i then col = on and "50B040" or "707070" end
    ev[#ev + 1] = string.format(
      "{\\an7\\pos(%d,%d)\\bord0\\shad0\\1c&H%s&\\1a&H30&\\p1}m 0 0 l %d 0 l %d %d l 0 %d{\\p0}",
      r.x, r.y, col, r.w, r.w, r.h, r.h)
    ev[#ev + 1] = string.format("{\\an5\\pos(%d,%d)\\fs%d\\bord0\\shad0\\1c&HFFFFFF&}%s",
      r.x + math.floor(r.w / 2), r.y + math.floor(r.h / 2), fs, labels[i])
  end
  panel.ov.data = table.concat(ev, "\n")
  panel.ov:update()
end

-- Ekran üstü zoom kontrolü: sağ kenarda ortada dikey [ + ] / x1.5 / [ - ]. Takip açıkken, zoom
-- yapılmışken (>1x) ya da fare/dokunma hareketinden sonra görünür. Saf yerleşim `zoom_layout`.
local function zoom_layout(W, H)
  local bh = math.max(36, math.floor(H * 0.09))
  local gap = math.floor(bh * 0.15)
  local x = W - bh - gap
  local rh = math.floor(bh * 0.7) -- değer kutusu yüksekliği
  local total = bh + gap + rh + gap + bh
  local y0 = math.floor((H - total) / 2)
  local plus = { x = x, y = y0, w = bh, h = bh }
  local val = { x = x, y = y0 + bh + gap, w = bh, h = rh }
  local minus = { x = x, y = y0 + bh + gap + rh + gap, w = bh, h = bh }
  return { plus, minus }, val, math.floor(bh * 0.6), math.floor(bh * 0.34)
end

local function zoom_wanted()
  return panel.visible or enabled or off.on or zoomc.z > 0.01
end

local function zoom_text() return string.format("x%.1f", 2 ^ zoomc.z) end

local function zoom_hit(x, y)
  for i, r in ipairs(zoomc.rects) do
    if x >= r.x and x <= r.x + r.w and y >= r.y and y <= r.y + r.h then return i end
  end
  return nil
end

render_zoom = function()
  if not zoomc.ov then
    zoomc.ov = mp.create_osd_overlay("ass-events")
    zoomc.ov.z = ZOOM_Z
  end
  local d = mp.get_property_native("osd-dimensions")
  local ok = zoom_wanted() and d and d.w and d.w > 0 and d.h and d.h > 0
  if not ok then
    zoomc.rects, zoomc.hover = {}, nil
    if zoomc.shown ~= "" then zoomc.shown = ""; zoomc.ov.data = ""; zoomc.ov:update() end
    return
  end
  local rects, val, fs_btn, fs_val = zoom_layout(d.w, d.h)
  zoomc.rects = rects
  zoomc.ov.res_x, zoomc.ov.res_y = d.w, d.h
  local ev = {}
  for i, r in ipairs(rects) do
    local col = (zoomc.hover == i) and "707070" or "303030" -- BGR
    ev[#ev + 1] = string.format(
      "{\\an7\\pos(%d,%d)\\bord0\\shad0\\1c&H%s&\\1a&H30&\\p1}m 0 0 l %d 0 l %d %d l 0 %d{\\p0}",
      r.x, r.y, col, r.w, r.w, r.h, r.h)
    ev[#ev + 1] = string.format("{\\an5\\pos(%d,%d)\\fs%d\\b1\\bord0\\shad0\\1c&HFFFFFF&}%s",
      r.x + math.floor(r.w / 2), r.y + math.floor(r.h / 2), fs_btn, i == 1 and "+" or "-")
  end
  ev[#ev + 1] = string.format(
    "{\\an7\\pos(%d,%d)\\bord0\\shad0\\1c&H000000&\\1a&H60&\\p1}m 0 0 l %d 0 l %d %d l 0 %d{\\p0}",
    val.x, val.y, val.w, val.w, val.h, val.h)
  ev[#ev + 1] = string.format("{\\an5\\pos(%d,%d)\\fs%d\\b1\\bord0\\shad0\\1c&HFFFFFF&}%s",
    val.x + math.floor(val.w / 2), val.y + math.floor(val.h / 2), fs_val, zoom_text())
  local data = table.concat(ev, "\n")
  if data ~= zoomc.shown then -- değişmediyse yeniden çizme (takipte zoom sürekli güncellenir)
    zoomc.shown = data
    zoomc.ov.data = data
    zoomc.ov:update()
  end
end

-- Takip noktası: Python `track-dot <nx> <ny>` (video-normalize merkez) yollar, "off" gizler.
-- Kırmızı nokta, mpv'nin şu anki zoom/pan'ına göre ekrana çevrilir (osd-dimensions kenar boşlukları
-- zoom/pan dahildir) → takip çalışıyorsa nesnenin üstünde durur.
local DOT_Z = 3
local dot = { nx = nil, ny = nil, ov = nil }

local function render_dot()
  if not dot.ov then
    dot.ov = mp.create_osd_overlay("ass-events")
    dot.ov.z = DOT_Z
  end
  local d = mp.get_property_native("osd-dimensions")
  if not (dot.nx and enabled and not (off and off.on) and d and d.w and d.w > 0 and d.h and d.h > 0) then
    dot.ov.data = ""
    dot.ov:update()
    return
  end
  local x = d.ml + dot.nx * (d.w - d.ml - d.mr)
  local y = d.mt + dot.ny * (d.h - d.mt - d.mb)
  if x < 0 or x > d.w or y < 0 or y > d.h then -- ekran dışı: çizme
    dot.ov.data = ""
    dot.ov:update()
    return
  end
  local r = math.max(math.floor(d.h * 0.012), 5)
  local k = math.floor(r * 0.5523)
  dot.ov.res_x, dot.ov.res_y = d.w, d.h
  dot.ov.data = string.format(
    "{\\an7\\pos(%d,%d)\\bord2\\shad0\\1c&H0000FF&\\3c&HFFFFFF&\\p1}"
      .. "m %d 0 b %d 0 %d %d %d %d b %d %d %d %d %d %d b %d %d %d %d %d %d b %d %d %d %d %d %d{\\p0}",
    math.floor(x) - r, math.floor(y) - r,
    r, r + k, 2 * r, r - k, 2 * r, r,
    2 * r, r + k, r + k, 2 * r, r, 2 * r,
    r - k, 2 * r, 0, r + k, 0, r,
    0, r - k, r - k, 0, r, 0)
  dot.ov:update()
end

mp.register_script_message("track-dot", function(nx, ny)
  dot.nx, dot.ny = tonumber(nx), tonumber(ny) -- "off" → nil
  render_dot()
end)
mp.observe_property("video-pan-x", "number", function() render_dot() end)
mp.observe_property("video-pan-y", "number", function() render_dot() end)
mp.observe_property("osd-dimensions", "native", function() render_dot() end)

-- video-zoom (takipte Python, elle zoomda biz) değişince değer etiketi güncellenir
mp.observe_property("video-zoom", "number", function(_, z)
  zoomc.z = z or 0
  render_zoom()
  render_dot()
end)

local zoom_buttons = { function() zoom_step(1) end, function() zoom_step(-1) end }

-- Sağ tık: takip noktası. Takip kapalıysa açılır; tıklanan noktadaki nesne (ne olursa olsun) hedef
-- olur (hedefin üstüne tekrar sağ tık hedefi bırakır). Panel/zoom düğmelerinin üstünde işlem yapmaz.
local function pick_target()
  if panel.hover or zoomc.hover then return end
  if not enabled then set_enabled(true) end
  on_click("track-point")
end
mp.add_key_binding(nil, "pick", pick_target)

sync_click_binding = function()
  local want = enabled or panel.hover ~= nil or zoomc.hover ~= nil
  if want and not panel.bound then
    mp.add_forced_key_binding("MBTN_LEFT", "track-click-bind", function()
      if panel.hover then
        buttons[panel.hover].act()
        render_panel()
      elseif zoomc.hover then
        zoom_buttons[zoomc.hover]()
        render_zoom()
      elseif enabled then
        on_click()
      end
    end)
    panel.bound = true
  elseif not want and panel.bound then
    mp.remove_key_binding("track-click-bind")
    panel.bound = false
  end
end

refresh_panel = function()
  if panel.visible then render_panel() end
  render_zoom()
end

local function hide_panel()
  if panel.pinned then return end
  if panel.hover or zoomc.hover then panel.timer:resume() return end
  panel.visible, panel.hover = false, nil
  render_panel()
  render_zoom() -- zoom yapılmıyor ve takip kapalıysa kontrol de gizlenir
  sync_click_binding()
end

mp.observe_property("mouse-pos", "native", function(_, pos)
  if not pos or pos.hover == false then return end
  local was_visible, was_hover = panel.visible, panel.hover
  panel.visible = true
  if not panel.rects[1] then render_panel() end -- ilk çizimde yerleşim lazım
  panel.hover = hit(pos.x or -1, pos.y or -1)
  if not was_visible or was_hover ~= panel.hover then render_panel() end
  local was_zoom_hover = zoomc.hover
  if not zoomc.rects[1] then render_zoom() end -- ilk çizimde yerleşim lazım
  zoomc.hover = zoom_hit(pos.x or -1, pos.y or -1)
  if was_zoom_hover ~= zoomc.hover or not was_visible then render_zoom() end
  sync_click_binding()
  if not panel.timer then
    panel.timer = mp.add_timeout(PANEL_HIDE_S, hide_panel)
  else
    panel.timer:kill()
    panel.timer:resume()
  end
end)

mp.add_key_binding(nil, "panel", function() -- panelin sabitlenmesini aç/kapa
  panel.pinned = not panel.pinned
  panel.visible = true
  render_panel()
  osd(panel.pinned and "panel sabit" or "panel otomatik gizlenir", 1)
end)

mp.msg.info("track.lua yüklendi")
