-- kayit.lua — Takipli Oynat KAYIT varyantı (R2). Tek özellik: video oynarken zoom düzeyini ayarla +
-- videoyu sürükle (aynı anda) → kamera hareketi kaydedilir (<video>.rec.json) → sonra dışa aktarılır.
-- Poz/model/takip YOK. Formüller recorder/geometry.py + recorder/keys.py ile birebir aynıdır
-- (tests/test_lua_kayit.py eşlik testi). Görünüm v = {zoom(log2), pan_x, pan_y}; merkez = 0.5 - pan.
local mp = require("mp")

local MAX_ZOOM, STEP = 4.0, 0.25 -- 1×–16×; tuş/tekerlek adımı 0.25 (log2)
local PRESETS = { 0.25, 0.5, 0.75, 1.0, 1.5, 2.0 } -- önizleme hızları (recorder.keys.SPEED_PRESETS)
local WALL_DT, HUD_Z = 0.033, 5 -- kayıt örnekleme (duvar saati, sn); HUD katmanı

local function clamp(v, lo, hi) return math.min(math.max(v, lo), hi) end
local function log2(x) return math.log(x) / math.log(2) end
local function round_even(x) -- Python round() ile aynı (yarımlar çifte)
  local f = math.floor(x)
  local d = x - f
  if d > 0.5 or (d == 0.5 and f % 2 == 1) then return f + 1 end
  return f
end

-- ---- geometri (recorder/geometry.py portu) ---------------------------------------------------
local function clamp_view(v)
  local z = clamp(v[1], 0, MAX_ZOOM)
  local lim = math.max(0.5 - 0.5 / 2 ^ z, 0)
  return { z, clamp(v[2], -lim, lim), clamp(v[3], -lim, lim) }
end

-- Zoom + sürüklemeyi AYNI ANDA uygular; (ax, ay) imlecin altındaki kare noktası imlecle kalır.
local function apply_gesture_at(v, ax, ay, dx, dy, factor)
  local z0 = math.max(v[1], 0)
  local z1 = clamp(z0 + (factor > 0 and log2(factor) or 0), 0, MAX_ZOOM)
  local s0, s1 = 2 ^ z0, 2 ^ z1
  local fx = (0.5 - v[2]) + (ax - 0.5) / s0
  local fy = (0.5 - v[3]) + (ay - 0.5) / s0
  local cx = fx - (ax + dx - 0.5) / s1
  local cy = fy - (ay + dy - 0.5) / s1
  return clamp_view({ z1, 0.5 - cx, 0.5 - cy })
end

local function set_zoom_at(v, ax, ay, zoom)
  local z0, z1 = math.max(v[1], 0), clamp(zoom, 0, MAX_ZOOM)
  return apply_gesture_at(v, ax, ay, 0, 0, 2 ^ (z1 - z0))
end

-- ---- hız / anahtar kareler (recorder/keys.py portu) --------------------------------------------
local function clamp_speed(s)
  if s ~= s then return 1.0 end
  return clamp(round_even(clamp(s, 0.25, 2.0) * 20) / 20, 0.25, 2.0)
end
local function key_dt(s) return clamp(0.033 * clamp_speed(s), 0.012, 0.066) end

-- Zaman en az min_dt ilerlemediyse (geri sarma/duraklatma) anahtar eklemez.
local function append_key(keys, t, v, min_dt)
  local last = keys[#keys]
  if last and t < last[1] + (min_dt or 0.03) then return false end
  keys[#keys + 1] = { t, v[1], v[2], v[3] }
  return true
end

-- ---- JSON (şema recorder.keys.save_recording ile aynı; vsig YAZILMAZ: Lua sha1 hesaplayamaz,
-- load_recording vsig yoksa denetimi atlar) --------------------------------------------------------
local ESC = { ['"'] = '\\"', ["\\"] = "\\\\", ["\n"] = "\\n", ["\r"] = "\\r", ["\t"] = "\\t" }
local function jstr(s)
  return '"' .. (s:gsub('[%c"\\]', function(c) return ESC[c] or string.format("\\u%04x", c:byte()) end)) .. '"'
end
local function num(x, p) return (string.format("%." .. p .. "f", x):gsub(",", ".")) end
local function basename(p) return p:match("[^/\\]*$") end

local function rec_json(video, keys, rotate, speed)
  local rows = {}
  for i, k in ipairs(keys) do
    rows[i] = string.format("[%s,%s,%s,%s]", num(k[1], 4), num(k[2], 6), num(k[3], 6), num(k[4], 6))
  end
  return string.format('{"version":1,"kind":"manual-camera","video":%s,"rotate":%d,"speed":%s,"views":[%s]}',
    jstr(basename(video)), rotate, num(speed, 2), table.concat(rows, ","))
end

local function write_atomic(path, data)
  local tmp = path .. ".tmp"
  local f = io.open(tmp, "wb")
  if not f then return false end
  f:write(data)
  f:close()
  os.remove(path) -- Windows'ta os.rename hedef varsa başarısız olur
  return os.rename(tmp, path) and true or false
end

local function video_path()
  local p = mp.get_property("path")
  if not p or p == "" or p:match("^%a[%w+.-]*://") then return nil end -- yalnız yerel dosya
  if not (p:match("^%a:[/\\]") or p:match("^[/\\]")) then
    local wd = mp.get_property("working-directory")
    if wd and wd ~= "" then p = wd .. "/" .. p end
  end
  return p
end

-- ---- durum + pencere/video geometrisi -----------------------------------------------------------
local V = { 0, 0, 0 }
local rec = { on = false, armed = false, id = 0, keys = {}, t = 0 }
local drag = { on = false, x = 0, y = 0 }
local hud = { ov = nil, last = nil }

local function osd(msg, sec) mp.osd_message("Kayıt: " .. msg, sec or 2) end

local function mouse_xy()
  local p = mp.get_property_native("mouse-pos")
  if p and p.x then return p end
  if mp.get_mouse_pos then return mp.get_mouse_pos() end
  return nil
end

-- Zoom=1, pan=0 iken videonun pencere içindeki dikdörtgeni (imleç oranları buna göre; letterbox'a dayanıklı).
local function box()
  local d = mp.get_property_native("osd-dimensions")
  if not d then return nil end
  local w, h = d.w, d.h
  local ow, oh = mp.get_property_number("osd-width", 0) or 0, mp.get_property_number("osd-height", 0) or 0
  if ow > 0 and oh > 0 then w, h = ow, oh end
  if not (w and h and w > 0 and h > 0) then return nil end
  local vp = mp.get_property_native("video-params")
  local dw, dh = vp and (vp.dw or vp.w), vp and (vp.dh or vp.h)
  if not (dw and dh and dw > 0 and dh > 0) then dw, dh = w, h end
  if (mp.get_property_number("video-rotate", 0) or 0) % 180 == 90 then dw, dh = dh, dw end
  local s = math.min(w / dw, h / dh)
  local bw, bh = dw * s, dh * s
  return { x = (w - bw) / 2, y = (h - bh) / 2, w = bw, h = bh }
end

local function hud_update()
  if not hud.ov then
    hud.ov = mp.create_osd_overlay("ass-events")
    hud.ov.z = HUD_Z
  end
  local zoom, txt = 2 ^ V[1], nil
  local head = "{\\an7\\pos(24,16)\\fs30\\bord2}"
  if rec.on then
    txt = string.format("%s{\\1c&H0000FF&}●{\\1c&HFFFFFF&} KAYIT  %.1f×  %.1f sn", head, zoom, rec.t or 0)
  else
    txt = string.format("%s%.1f×", head, zoom) -- zoom değeri her zaman görünür
  end
  if txt ~= hud.last then
    hud.last = txt
    hud.ov.res_x, hud.ov.res_y = 1280, 720
    hud.ov.data = txt
    hud.ov:update()
  end
end

local function set_view(nv)
  V = clamp_view(nv)
  mp.set_property_number("video-zoom", V[1])
  mp.set_property_number("video-pan-x", V[2])
  mp.set_property_number("video-pan-y", V[3])
  hud_update()
end

-- ---- fare: sol tuş basılı sürükle = kaydır, tekerlek = imleç etrafında zoom ---------------------
mp.add_key_binding(nil, "drag", function(ev)
  local e = ev and ev.event or "press"
  if e == "down" then
    local pos = mouse_xy()
    if pos and pos.x then drag.on, drag.x, drag.y = true, pos.x, pos.y end
  elseif e == "up" or e == "press" then
    drag.on = false
  end
end, { complex = true })

mp.observe_property("mouse-pos", "native", function(_, pos)
  if not (drag.on and pos and pos.x) then return end
  local b = box()
  if not b then return end
  local ax, ay = (drag.x - b.x) / b.w, (drag.y - b.y) / b.h -- tutulan nokta (önceki imleç konumu)
  local dx, dy = (pos.x - drag.x) / b.w, (pos.y - drag.y) / b.h
  drag.x, drag.y = pos.x, pos.y
  set_view(apply_gesture_at(V, ax, ay, dx, dy, 1))
end)

local function wheel(dir)
  local pos, b = mouse_xy(), box()
  if not (pos and pos.x and b) then return end
  -- sürüklerken de aynı imleç noktasında uygulanır; sürükleme tutamağı (drag.x/y) değişmez
  set_view(apply_gesture_at(V, (pos.x - b.x) / b.w, (pos.y - b.y) / b.h, 0, 0, 2 ^ (dir * STEP)))
end
mp.add_key_binding(nil, "wheel-in", function() wheel(1) end)
mp.add_key_binding(nil, "wheel-out", function() wheel(-1) end)

-- ---- klavye: + / - (basılı tut = sürekli), 0 = sıfırla, K = döndür, [ ] = hız ---------------------
local function zoom_key(dir)
  set_view(set_zoom_at(V, 0.5, 0.5, V[1] + dir * STEP))
end
mp.add_key_binding(nil, "zoom-in", function() zoom_key(1) end, { repeatable = true })
mp.add_key_binding(nil, "zoom-out", function() zoom_key(-1) end, { repeatable = true })
mp.add_key_binding(nil, "reset", function() set_view({ 0, 0, 0 }) end)

mp.add_key_binding(nil, "rotate", function()
  if rec.on then osd("kayıt sırasında döndürülemez"); return end
  mp.set_property_number("video-rotate", ((mp.get_property_number("video-rotate", 0) or 0) + 90) % 360)
  set_view({ 0, 0, 0 })
end)

local function speed_step(dir)
  local cur, idx = clamp_speed(mp.get_property_number("speed", 1) or 1), 1
  for i, p in ipairs(PRESETS) do
    if math.abs(p - cur) < math.abs(PRESETS[idx] - cur) then idx = i end
  end
  local sp = PRESETS[clamp(idx + dir, 1, #PRESETS)]
  mp.set_property_number("speed", sp)
  osd(string.format("hız %.2f×", sp), 1)
end
mp.add_key_binding(nil, "slower", function() speed_step(-1) end)
mp.add_key_binding(nil, "faster", function() speed_step(1) end)

-- ---- kayıt ------------------------------------------------------------------------------------
local function stop_rec()
  if not rec.on then return end
  rec.on = false
  if rec.timer then rec.timer:kill(); rec.timer = nil end
  local t = mp.get_property_number("time-pos", nil)
  if rec.armed and t then rec.t = t; append_key(rec.keys, t, V, 0.001) end
  hud_update()
  local keys, video = rec.keys, video_path()
  if #keys == 0 or not video then osd("kayıtta kamera hareketi yok"); return end
  if #keys == 1 then keys[2] = { keys[1][1] + 0.04, keys[1][2], keys[1][3], keys[1][4] } end
  local rot = (mp.get_property_number("video-rotate", 0) or 0) % 360
  if rot % 90 ~= 0 then rot = 0 end
  local out = video .. ".rec.json"
  local json = rec_json(video, keys, rot, clamp_speed(mp.get_property_number("speed", 1) or 1))
  if write_atomic(out, json) then
    osd(string.format("kaydedildi: %s (%d anahtar) — E: dışa aktar", basename(out), #keys), 4)
  else
    osd("dosya yazılamadı: " .. out, 5)
  end
end

local function tick(id)
  if not (rec.on and rec.id == id) then return end
  local t = mp.get_property_number("time-pos", nil)
  if rec.armed and t then
    rec.t = t
    append_key(rec.keys, t, V, key_dt(mp.get_property_number("speed", 1) or 1) * 0.5)
  end
  hud_update()
  rec.timer = mp.add_timeout(WALL_DT, function() tick(id) end)
end

local function start_rec()
  if not video_path() then osd("yalnız yerel video dosyası kaydedilir"); return end
  rec = { on = true, armed = false, id = rec.id + 1, keys = {}, t = 0 }
  set_view({ 0, 0, 0 })
  mp.commandv("seek", "0", "absolute", "exact") -- başa sar; anahtarlar seek bitince (playback-restart) başlar
  mp.set_property("pause", "no")
  osd("kayıt başladı (durdurmak için R)", 2)
  tick(rec.id)
end

mp.add_key_binding(nil, "record", function()
  if rec.on then stop_rec() else start_rec() end
end)

mp.register_event("playback-restart", function() if rec.on then rec.armed = true end end)
mp.register_event("end-file", function() stop_rec() end)
mp.register_event("file-loaded", function() set_view({ 0, 0, 0 }) end)
mp.observe_property("eof-reached", "native", function(_, v) if v then stop_rec() end end)

-- ---- dışa aktarma (R3): E = `pythonw -m recorder export`; ilerleme <çıktı>.export.json, Esc = iptal -----
local utils = require("mp.utils")
local exp = { running = false, id = 0, out = nil, prog = nil }

local function read_text(p)
  local f = io.open(p, "rb")
  local t = f and f:read("*a")
  if f then f:close() end
  return t
end
local function jfield(t, k) return t:match('"' .. k .. '"%s*:%s*"([^"]*)"') end -- basit alan okuyucu

local function python_exe() -- <mpv klasörünün üstü>/python/ (build_embedded.py); pythonw = konsol penceresi yok
  local exe = mp.command_native({ "expand-path", "~~exe_dir/" })
  if type(exe) ~= "string" or exe == "" then return nil end
  local root = exe:gsub("[/\\]+$", ""):gsub("[/\\][^/\\]*$", "")
  for _, name in ipairs({ "pythonw.exe", "python.exe" }) do
    local p = root .. "/python/" .. name
    if utils.file_info(p) then return p end
  end
  return nil
end

local function export_done(_, res)
  exp.running = false
  mp.remove_key_binding("export-cancel")
  local st, t = res and res.status, read_text(exp.prog) or ""
  if st == 0 then
    osd("Kaydedildi: " .. basename(exp.out), 8)
  elseif st == 3 or jfield(t, "state") == "cancelled" then
    osd("dışa aktarma iptal edildi", 4)
  else
    osd("dışa aktarma başarısız: " .. (jfield(t, "error") or (res and res.error_string) or ("kod " .. tostring(st))), 8)
  end
end

local function poll_export(id)
  if not (exp.running and exp.id == id) then return end
  local t = read_text(exp.prog) or ""
  if jfield(t, "state") == "running" then
    osd(string.format("dışa aktarılıyor %%%s (Esc: iptal)", t:match('"pct"%s*:%s*(%d+)') or "?"), 1.5)
  end
  mp.add_timeout(1, function() poll_export(id) end)
end

mp.add_key_binding(nil, "export", function()
  if exp.running then osd("dışa aktarma sürüyor (Esc: iptal)", 2); return end
  if rec.on then osd("kayıt sürerken dışa aktarılamaz"); return end
  local vp = video_path()
  if not vp then osd("yalnız yerel video dışa aktarılır"); return end
  if not read_text(vp .. ".rec.json") then osd("önce kayıt yap (R)", 3); return end
  local py = python_exe()
  if not py then osd("python/ bulunamadı: dışa aktarma başlatılamadı", 4); return end
  local out = vp:gsub("%.[^./\\]+$", "") .. ".kamera.mp4" -- recorder.keys.default_out ile aynı
  exp.running, exp.id, exp.out, exp.prog = true, exp.id + 1, out, out .. ".export.json"
  os.remove(exp.prog) -- önceki koşunun eski durumu karışmasın
  mp.add_forced_key_binding("ESC", "export-cancel", function()
    local f = io.open(out .. ".export.cancel", "wb")
    if f then f:close() end
    osd("iptal ediliyor…", 2)
  end)
  mp.command_native_async({ name = "subprocess", playback_only = false, capture_stdout = false,
    capture_stderr = false, args = { py, "-m", "recorder", "export", vp, "--out", out } }, export_done)
  osd("dışa aktarma başladı: " .. basename(out), 3)
  poll_export(exp.id)
end)

if rawget(_G, "KAYIT_EXPOSE") then -- yalnız testler (tests/lua_harness_kayit.lua)
  KAYIT_API = { apply_gesture_at = apply_gesture_at, set_zoom_at = set_zoom_at, clamp_view = clamp_view,
    clamp_speed = clamp_speed, key_dt = key_dt, append_key = append_key, state = function() return rec, V end, exp = exp }
end
hud_update()
