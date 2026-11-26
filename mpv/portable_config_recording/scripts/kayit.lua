-- kayit.lua — Takipli Oynat KAYIT varyantı. Tek özellik: zoom (tekerlek, +/-) + SOL tuşla sürükle (aynı anda)
-- → kamera hareketi kaydedilir (<video>.rec.json) → S ile yeni videoya dışa aktarılır.
-- Akış: KAYDET düğmesi = hazır (oynatma BAŞLAMAZ, hız ayarlanır) → Space = kayıt hemen başlar;
-- sonra Space = duraklat/sürdür → düğme = durdur → S = dışa aktar.
-- Poz/model/takip YOK. Formüller recorder/geometry.py + recorder/keys.py ile birebir aynıdır
-- (tests/test_lua_kayit.py eşlik testi). Görünüm v = {zoom(log2), pan_x, pan_y}; merkez = 0.5 - pan.
local mp = require("mp")

local MAX_ZOOM, STEP = 4.0, 0.25 -- 1×–16×; tuş/tekerlek adımı 0.25 (log2)
local PRESETS = { 0.25, 0.5, 0.75, 1.0, 1.5, 2.0 } -- önizleme hızları (recorder.keys.SPEED_PRESETS)
local WALL_DT, HUD_Z = 0.033, 5 -- kayıt örnekleme (duvar saati, sn); HUD katmanı
local BTN = { x = 1090, y = 12, w = 178, h = 46 } -- KAYDET düğmesi (1280×720 HUD koordinatı)
local SPD = { x = 900, y = 12, w = 178, h = 46 } -- HIZ düğmesi (KAYDET'in solunda)
local ROTL = { x = 716, y = 12, w = 84, h = 46 } -- ◄ 90° (saat yönü tersi) döndür düğmesi
local ROTR = { x = 806, y = 12, w = 84, h = 46 } -- 90° ► (saat yönü) döndür düğmesi

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

local function rec_json(video, keys, rotate, speed, breaks)
  local rows = {}
  for i, k in ipairs(keys) do
    rows[i] = string.format("[%s,%s,%s,%s]", num(k[1], 4), num(k[2], 6), num(k[3], 6), num(k[4], 6))
  end
  return string.format('{"version":1,"kind":"manual-camera","video":%s,"rotate":%d,"speed":%s,"views":[%s],"breaks":[%s]}',
    jstr(basename(video)), rotate, num(speed, 2), table.concat(rows, ","), table.concat(breaks or {}, ","))
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
local rec = { on = false, run = false, started = false, armed = false, id = 0, gen = 0, keys = {}, breaks = {}, brk = false, t = 0 }
local drag = { on = false, x = 0, y = 0 }
local hud = { ov = nil, last = nil, w = 0, h = 0 }
local hud_font, hud_status_font = 26,30
local exp = { running = false, id = 0, out = nil, prog = nil } -- dışa aktarma durumu (aşağıda doldurulur)
local menu

local function osd(msg, sec) mp.osd_message("Kayıt: " .. msg, sec or 2) end

local function mouse_xy()
  local p = mp.get_property_native("mouse-pos")
  if p and p.x then return p end
  if mp.get_mouse_pos then
    local x,y=mp.get_mouse_pos()
    if type(x)=="table" then return x end
    if type(x)=="number" and type(y)=="number" then return {x=x,y=y} end
  end
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

-- All drawing and hit testing share actual client pixels, not a stretched virtual canvas.
local function viewport()
  local d=mp.get_property_native("osd-dimensions") or {}
  local w,h=d.w or 0,d.h or 0
  if w<=0 or h<=0 then
    w,h=mp.get_property_number("osd-width",0) or 0,mp.get_property_number("osd-height",0) or 0
  end
  if w<=0 or h<=0 then return nil end
  return math.floor(w),math.floor(h)
end

local function hud_layout(w,h,top,dpi)
  local scale=math.min(clamp(dpi or 1,.75,3),w/580,math.max(1,h-top)/100)
  local function px(n) return math.max(1,math.floor(n*scale+.5)) end
  local right=w-px(12)
  local function place(b,width,gap)
    b.w,b.h=px(width),px(46)
    b.x,b.y=right-b.w,top
    right=b.x-px(gap)
  end
  place(BTN,178,12);place(SPD,178,10);place(ROTR,84,6);place(ROTL,84,10)
  hud_font,hud_status_font=math.max(10,px(26)),math.max(10,px(30))
  return px(24),top+BTN.h+px(6)
end

local function box_ass(b, col, label)
  return string.format("\n{\\an7\\pos(%d,%d)\\bord0\\shad0\\1c%s\\p1}m 0 0 l %d 0 %d %d 0 %d{\\p0}", b.x, b.y, col, b.w, b.w, b.h, b.h)
    .. string.format("\n{\\an5\\pos(%d,%d)\\fs%d\\bord0\\shad0\\1c&HFFFFFF&}%s", math.floor(b.x+b.w/2), math.floor(b.y+b.h/2),hud_font,label)
end

-- Döndürme düğmeleri yalnız kayıt BAŞLAMADAN (boşta / hazır) görünür ve çalışır; kayıt başlayınca döndürme kilitli.
local function rot_visible() return not (rec.on and rec.started) end

local function buttons_ass(exporting)
  local label, col = "●  KAYDET", "&H3030C8&"
  if rec.on then label, col = "■  DURDUR", "&H2020F0&" end
  if exporting then label, col = "AKTARILIYOR…", "&H606060&" end
  local sp = clamp_speed(mp.get_property_number("speed", 1) or 1)
  local rot = ""
  if rot_visible() then
    rot = box_ass(ROTL, "&H606060&", "◄ 90°") .. box_ass(ROTR, "&H606060&", "90° ►")
  end
  return box_ass(BTN, col, label) .. box_ass(SPD, "&H805030&", string.format("HIZ %g×", sp)) .. rot
end

local function hud_update()
  if not hud.ov then
    hud.ov = mp.create_osd_overlay("ass-events")
    hud.ov.z = HUD_Z
  end
  local w,h=viewport()
  if not w then
    if rawget(_G,"KAYIT_EXPOSE") then w,h=1280,720 else return end
  end
  local dpi=mp.get_property_number("display-hidpi-scale",1) or 1
  local top=menu and menu.hud_top() or 12
  top=math.min(top,math.max(0,h-20))
  local sx,sy=hud_layout(w,h,top,dpi)
  local zoom, txt = 2 ^ V[1], nil
  local head=string.format("{\\an7\\pos(%d,%d)\\fs%d\\bord2}",sx,sy,hud_status_font)
  if rec.on and rec.run then
    txt = string.format("%s{\\1c&H0000FF&}●{\\1c&HFFFFFF&} KAYIT  %.1f×  %.1f sn", head, zoom, rec.t or 0)
  elseif rec.on and rec.started then
    txt = string.format("%sKAYIT DURAKLADI  %.1f×  %.1f sn  (Space: devam)", head, zoom, rec.t or 0)
  elseif rec.on then
    txt = string.format("%sHAZIR  %.1f×  (Space: kaydı başlat)", head, zoom)
  else
    txt = string.format("%s%.1f×", head, zoom) -- zoom değeri her zaman görünür
  end
  if w<720 or w/hud_status_font<24 then
    if rec.on and rec.run then txt=string.format("%s● KAYIT %.1f× %.1f sn",head,zoom,rec.t or 0)
    elseif rec.on and rec.started then txt=string.format("%sDURAKLADI %.1f×",head,zoom)
    elseif rec.on then txt=string.format("%sHAZIR %.1f×",head,zoom) end
  end
  txt = txt .. buttons_ass(exp and exp.running)
  if txt ~= hud.last or w~=hud.w or h~=hud.h then
    hud.last,hud.w,hud.h = txt,w,h
    hud.ov.res_x, hud.ov.res_y = w,h
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

local start_export -- aşağıda
local toggle_record, speed_cycle, rotate_by -- aşağıda tanımlanır
local function hit(pos,b)
  if not pos or not pos.x or not pos.y or pos.hover==false then return false end
  hud_update()
  return pos.x>=b.x and pos.x<b.x+b.w and pos.y>=b.y and pos.y<b.y+b.h
end

-- ---- fare: SOL tuş basılı sürükle = kaydır; sol tık ekrandaki düğmelerde = KAYDET / HIZ; sağ tık HIZ'da =
-- yavaşlat; tekerlek = imleç etrafında zoom (sürüklerken de, aynı anda). Çift tık oynatmayı değiştirmez. ---
mp.add_key_binding(nil, "drag", function(ev)
  local e = ev and ev.event or "press"
  local pos = mouse_xy()
  if menu and menu.pointer(ev,pos) then drag.on=false;return end
  if e == "down" then
    if pos and pos.x and hit(pos, BTN) then drag.on = false; toggle_record(); return end
    if pos and pos.x and hit(pos, SPD) then drag.on = false; speed_cycle(1); return end
    if pos and pos.x and rot_visible() and hit(pos, ROTL) then drag.on = false; rotate_by(-90); return end
    if pos and pos.x and rot_visible() and hit(pos, ROTR) then drag.on = false; rotate_by(90); return end
    if pos and pos.x then drag.on, drag.x, drag.y = true, pos.x, pos.y end
  elseif e == "up" or e == "press" then
    drag.on = false
  end
end, { complex = true })

mp.add_key_binding(nil, "rclick", function(ev) -- sağ tık: yalnız HIZ düğmesinde (yavaşlat)
  local e = ev and ev.event or "press"
  if e ~= "down" and e ~= "press" then return end
  local pos = mouse_xy()
  if menu and menu.over(pos) then return end
  if pos and pos.x and hit(pos, SPD) then speed_cycle(-1) end
end, { complex = true })

mp.observe_property("mouse-pos", "native", function(_, pos)
  if menu then menu.mouse(pos) end
  if not pos or pos.hover==false then drag.on=false;return end
  if not (drag.on and pos.x and pos.y) then return end
  local b = box()
  if not b then return end
  local ax, ay = (drag.x - b.x) / b.w, (drag.y - b.y) / b.h -- tutulan nokta (önceki imleç konumu)
  local dx, dy = (pos.x - drag.x) / b.w, (pos.y - drag.y) / b.h
  drag.x, drag.y = pos.x, pos.y
  set_view(apply_gesture_at(V, ax, ay, dx, dy, 1))
end)

local function wheel(dir)
  local pos, b = mouse_xy(), box()
  if menu and menu.over(pos) then return end
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

-- Döndürme: kayıt başlamadan önce (boşta ya da hazırken) yapılır; dönüş kayda yazılır (rec.json "rotate") ve
-- dışa aktarma önce kareyi döndürür, sonra kırpar → kaydedilen video döndürülmüş çıkar.
function rotate_by(delta)
  if not rot_visible() then osd("kayıt sırasında döndürülemez"); return end
  local r = ((mp.get_property_number("video-rotate", 0) or 0) + delta) % 360
  mp.set_property_number("video-rotate", r)
  set_view({ 0, 0, 0 })
  osd(string.format("döndürme %d°", r), 1.5)
end
mp.add_key_binding(nil, "rotate", function() rotate_by(90) end)

local function speed_step(dir)
  local cur, idx = clamp_speed(mp.get_property_number("speed", 1) or 1), 1
  for i, p in ipairs(PRESETS) do
    if math.abs(p - cur) < math.abs(PRESETS[idx] - cur) then idx = i end
  end
  local sp = PRESETS[clamp(idx + dir, 1, #PRESETS)]
  mp.set_property_number("speed", sp)
  hud_update()
  osd(string.format("hız %.2f×", sp), 1)
end
function speed_cycle(dir) -- ekrandaki HIZ düğmesi: önayarlar arasında döner (0.25× … 2×)
  local cur, idx = clamp_speed(mp.get_property_number("speed", 1) or 1), 1
  for i, p in ipairs(PRESETS) do
    if math.abs(p - cur) < math.abs(PRESETS[idx] - cur) then idx = i end
  end
  local sp = PRESETS[(idx - 1 + dir) % #PRESETS + 1]
  mp.set_property_number("speed", sp)
  hud_update()
  osd(string.format("hız %g×", sp), 1)
end
mp.add_key_binding(nil, "slower", function() speed_step(-1) end)
mp.add_key_binding(nil, "faster", function() speed_step(1) end)

-- Anahtar ekler. Geri sarma / atlama (seek olayı ya da zaman geri gitti) = YENİ PARÇA: anahtar her zaman eklenir ve
-- rec.breaks'e (yeni parçanın ilk anahtarının 0 tabanlı indeksi) yazılır; böylece geri sarıp tekrar oynattığın yer
-- kayda tekrar girer ve dışa aktarmada parçalar kaydedilen SIRAYLA art arda eklenir. rec.t = toplam kayıt süresi.
local function push_key(t, min_dt)
  local last = rec.keys[#rec.keys]
  if last and (rec.brk or t < last[1] - 0.001) then
    rec.breaks[#rec.breaks + 1] = #rec.keys
    rec.keys[#rec.keys + 1] = { t, V[1], V[2], V[3] }
    rec.brk = false
    return true
  end
  rec.brk = false
  if append_key(rec.keys, t, V, min_dt) then
    if last then rec.t = rec.t + (t - last[1]) end
    return true
  end
  return false
end

-- ---- kayıt: KAYDET/R = hazır (oynatma başlamaz) → Space = başlat / duraklat / sürdür → KAYDET/R = durdur → S ---
local function stop_rec()
  if not rec.on then return false end
  rec.on, rec.run = false, false
  if rec.timer then rec.timer:kill(); rec.timer = nil end
  local t = mp.get_property_number("time-pos", nil)
  if rec.armed and t then push_key(t, 0.001) end
  hud_update()
  local keys, video = rec.keys, video_path()
  if #keys == 0 or not video then osd("kayıtta kamera hareketi yok"); return false end
  if #keys == 1 then keys[2] = { keys[1][1] + 0.04, keys[1][2], keys[1][3], keys[1][4] } end
  local rot = (mp.get_property_number("video-rotate", 0) or 0) % 360
  if rot % 90 ~= 0 then rot = 0 end
  local out = video .. ".rec.json"
  local json = rec_json(video, keys, rot, clamp_speed(mp.get_property_number("speed", 1) or 1), rec.breaks)
  if write_atomic(out, json) then
    osd(string.format("kaydedildi: %s (%d anahtar) — S: videoyu kaydet", basename(out), #keys), 4)
    return true
  end
  osd("dosya yazılamadı: " .. out, 5)
  return false
end

local function tick(gen)
  if not (rec.on and rec.run and rec.gen == gen) then return end
  local t = mp.get_property_number("time-pos", nil)
  if rec.armed and t then push_key(t, key_dt(mp.get_property_number("speed", 1) or 1) * 0.5) end
  hud_update()
  rec.timer = mp.add_timeout(WALL_DT, function() tick(gen) end)
end

local function open_rec()
  if exp.running or (menu and menu.busy()) then osd("Export is active");return end
  if menu then menu.close_editor() end
  if not video_path() then osd("yalnız yerel video dosyası kaydedilir"); return end
  rec = { on = true, run = false, started = false, armed = false,
          id = rec.id + 1, gen = 0, keys = {}, breaks = {}, brk = false, t = 0 }
  set_view({ 0, 0, 0 })
  mp.set_property("pause", "yes") -- hazır: oynatma başlamaz; hız ayarlanır, Space ile kayıt başlar
  mp.commandv("seek", "0", "absolute", "exact")
  hud_update()
  osd("hazır: hızı ayarla, Space ile başlat", 3)
end

local function start_run() -- Space: kayıt + oynatma hemen başlar
  rec.run, rec.started = true, true
  rec.gen = rec.gen + 1
  local t = mp.get_property_number("time-pos", 0) or 0
  if t < 0.05 then rec.armed = true else mp.commandv("seek", "0", "absolute", "exact") end -- seek bitince (playback-restart) başlar
  mp.set_property("pause", "no")
  hud_update()
  tick(rec.gen)
end

local function space() -- hazırken başlat, kayıtta duraklat, duraklamada sürdür
  if not rec.on then osd("önce KAYDET düğmesine bas", 2); return end
  if rec.run then
    rec.run = false
    if rec.timer then rec.timer:kill(); rec.timer = nil end
    mp.set_property("pause", "yes")
    hud_update()
    osd("kayıt duraklatıldı (Space: devam)", 2)
    return
  end
  if rec.started then -- duraklamadan devam
    rec.run, rec.gen = true, rec.gen + 1
    mp.set_property("pause", "no")
    hud_update()
    tick(rec.gen)
    return
  end
  start_run()
end

function toggle_record()
  if rec.on then stop_rec() else open_rec() end
end
mp.add_key_binding(nil, "record", toggle_record)
mp.add_key_binding(nil, "space", space)

-- seek (geri sarma / ileri atlama): yeni parça başlar; seek bitene (playback-restart) kadar eski time-pos yazılmaz
mp.register_event("seek", function() if rec.on and rec.started then rec.armed, rec.brk = false, true end end)
mp.register_event("playback-restart", function() if rec.on and rec.started then rec.armed = true end end)
mp.register_event("end-file", function() drag.on=false;stop_rec() end)
mp.register_event("file-loaded", function()
  drag.on=false
  set_view({ 0, 0, 0 })
  mp.set_property("pause", "yes") -- video açılınca oynatma kendiliğinden başlamaz
end)
mp.observe_property("eof-reached", "native", function(_, v) if v and rec.on then stop_rec() end end)
mp.observe_property("speed", "native", function() hud_update() end)

-- ---- dışa aktarma (R3): E = `pythonw -m recorder export`; ilerleme <çıktı>.export.json, Esc = iptal -----
local utils = require("mp.utils")

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
  hud_update()
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

function start_export()
  if menu and menu.busy() then osd("Editing export is active");return end
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
  hud_update()
  poll_export(exp.id)
end
mp.add_key_binding(nil, "export", function() start_export() end)

-- Native menu actions use the same camera functions and recording state as the HUD.
if not rawget(_G,"KAYIT_EXPOSE") then
  local ok,mod=pcall(require,"recordingmenu")
  if not ok then
    local path=mp.command_native({"expand-path","~~/script-modules/recordingmenu.lua"})
    if type(path)=="string" then ok,mod=pcall(dofile,path) end
  end
  if ok then
    local actions={
      zoom_in=function() zoom_key(1) end,
      zoom_out=function() zoom_key(-1) end,
      reset=function() set_view({0,0,0}) end,
      rotate_left=function() rotate_by(-90) end,
      rotate_right=function() rotate_by(90) end,
      record=toggle_record, record_pause=space, camera_export=start_export,
      slower=function() speed_step(-1) end, faster=function() speed_step(1) end,
      play_pause=function() if rec.on then space() else mp.commandv("cycle","pause") end end,
    }
    menu=mod.new({
      run=function(cmd) if actions[cmd] then actions[cmd]() end end,
      state=function()
        local vp=video_path()
        local saved=vp and utils.file_info(vp..".rec.json")
        return {recording=rec.on, started=rec.started, running=rec.run,
          exporting=exp.running, local_video=vp~=nil, saved=saved and saved.is_file or false}
      end,
    })
    local last_w,last_h
    mp.observe_property("osd-dimensions","native",function()
      local w,h=viewport()
      -- Zoom changes OSD margins too. Cancel a drag only on an actual client resize.
      if w~=last_w or h~=last_h then drag.on=false;last_w,last_h=w,h end
      hud_update()
    end)
    mp.observe_property("display-hidpi-scale","number",function() hud_update() end)
  else mp.msg.error("Recording menu unavailable: "..tostring(mod)) end
end

if rawget(_G, "KAYIT_EXPOSE") then -- yalnız testler (tests/lua_harness_kayit.lua)
  KAYIT_API = { apply_gesture_at = apply_gesture_at, set_zoom_at = set_zoom_at, clamp_view = clamp_view,
    clamp_speed = clamp_speed, key_dt = key_dt, append_key = append_key, state = function() return rec, V end, exp = exp,
    hud_layout=function(w,h,top,dpi)
      hud_layout(w,h,top,dpi)
      local out={}
      for i,b in ipairs({BTN,SPD,ROTL,ROTR}) do out[i]={x=b.x,y=b.y,w=b.w,h=b.h} end
      return out,hud_font
    end }
end
hud_update()
