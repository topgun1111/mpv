-- kayit.lua harness (Ortam: KAYIT_LUA, VIDEO). Çıktı: SEKME ayrımlı satırlar; test_lua_kayit.py okur.
local dir = (arg and arg[0] or ""):match("^(.*)[/\\]") or "."
local reg = dofile(dir .. "/lua_mp_stub.lua")
KAYIT_EXPOSE = true
-- dışa aktarma (R3) için sahte mpv alt süreç/dosya API'si (kayit.lua yüklenmeden ÖNCE takılır)
local mpx, utils = require("mp"), require("mp.utils")
local have = { ["C:/app/python/pythonw.exe"] = true }
mpx.command_native = function() return "C:/app/mpv/" end -- expand-path ~~exe_dir/
utils.file_info = function(p) return have[p] and { is_file = true } or nil end
local async
mpx.command_native_async = function(t, cb) async = { t = t, cb = cb } end
dofile(os.getenv("KAYIT_LUA"))
local A = KAYIT_API
local function out(...) print(table.concat({ ... }, "\t")) end
local function f(x) return string.format("%.9f", x) end
local function has(s, pat) return s ~= nil and s:find(pat, 1, true) ~= nil end
local function hud() return reg.ov[5] or "" end
local function frame_at(v, ax, ay) -- imlecin altındaki kare noktası
  local s = 2 ^ v[1]
  return (0.5 - v[2]) + (ax - 0.5) / s, (0.5 - v[3]) + (ay - 0.5) / s
end

-- 1) Android/Python referansı + ardışık hareket dizisi (Python ile birebir karşılaştırılır)
local v = A.apply_gesture_at({ 0, 0, 0 }, 0.75, 0.25, 0, 0, 2.0)
out("REF", f(v[1]), f(v[2]), f(v[3]))
local s = { 0, 0, 0 }
for _, g in ipairs({ { 0.5, 0.5, 0, 0, 1.5 }, { 0.3, 0.6, 0.02, -0.01, 1.3 }, { 0.8, 0.2, -0.05, 0.04, 1.0 },
  { 0.5, 0.5, 0, 0, 0.5 }, { 0.1, 0.9, 0.1, -0.1, 3.0 } }) do
  s = A.apply_gesture_at(s, g[1], g[2], g[3], g[4], g[5])
  out("SEQ", f(s[1]), f(s[2]), f(s[3]))
end

-- 2) imleç sabitleme değişmezi: zoom (imleç etrafında) ve zoom + sürükleme aynı anda
local v0, ax, ay = { 2.0, 0.1, -0.05 }, 0.3, 0.7
local x0, y0 = frame_at(v0, ax, ay)
local x1, y1 = frame_at(A.apply_gesture_at(v0, ax, ay, 0, 0, 1.3), ax, ay)
local v2 = A.apply_gesture_at(v0, ax, ay, 0.04, -0.03, 1.3)
local x2, y2 = frame_at(v2, ax + 0.04, ay - 0.03)
out("INV", f(math.max(math.abs(x1 - x0), math.abs(y1 - y0))), f(math.max(math.abs(x2 - x0), math.abs(y2 - y0))))

-- 3) fare entegrasyonu (1280×720 pencere, 1920×1080 video → letterbox yok)
reg.props["osd-dimensions"] = { w = 1280, h = 720, ml = 0, mr = 0, mt = 0, mb = 0 }
reg.props["video-params"] = { dw = 1920, dh = 1080, w = 1920, h = 1080 }
reg.props["video-rotate"], reg.props.speed, reg.props["time-pos"] = 0, 1, 0
local function move(x, y)
  reg.props["mouse-pos"] = { x = x, y = y, hover = true }
  reg.obs["mouse-pos"]("mouse-pos", reg.props["mouse-pos"])
end
local function vals() return f(reg.set["video-zoom"] or -1), f(reg.set["video-pan-x"] or 0), f(reg.set["video-pan-y"] or 0) end
out("HUD0", tostring(has(hud(), "1.0×")), tostring(has(hud(), "KAYIT")))
move(320, 180)
reg.bind["wheel-in"]()
out("WHEEL1", vals())
move(640, 360)
for _ = 1, 7 do reg.bind["wheel-in"]() end
out("ZOOM2", vals()) -- 8 adım = 2.0 log2
reg.bind.drag({ event = "down" })
move(700, 380)
out("DRAG", vals())
reg.bind["wheel-in"]() -- sürüklerken tekerlek (imleç (700,380) noktasında)
out("DRAGWHEEL", vals())
move(690, 370)
out("DRAGMORE", vals())
reg.bind.drag({ event = "up" })
move(10, 10)
out("NODRAG", vals()) -- tuş bırakıldı: kayma yok
reg.bind["zoom-out"]()
out("KEYOUT", vals())
reg.bind["zoom-in"]()
out("KEYIN", vals())
reg.bind.reset()
local rz, rx, ry = vals()
out("RESET", rz, rx, ry, tostring(has(hud(), "1.0×")))

-- 4) kayıt: R → başa sar; playback-restart'tan önce anahtar yok; geri sarma/duraklatma anahtar üretmez
reg.cmds = {}
reg.bind.record()
out("START", reg.cmds[#reg.cmds], tostring(has(hud(), "KAYIT")), tostring(has(hud(), "●")))
reg.props["time-pos"] = 10 -- seek tamamlanmadan eski saat
reg.timers[#reg.timers]()
local rec = A.state()
out("PREARM", tostring(#rec.keys))
reg.props["time-pos"] = 0
reg.ev["playback-restart"]()
for i = 0, 39 do
  reg.props["time-pos"] = i * 0.033
  if i == 15 then move(640, 360); reg.bind["wheel-in"]() end -- kayıt sırasında zoom
  reg.timers[#reg.timers]()
end
local n_play = #rec.keys
reg.timers[#reg.timers]() -- duraklatma: saat ilerlemedi
reg.props["time-pos"] = 0.2
reg.timers[#reg.timers]() -- geri sarma
out("NOKEY", tostring(n_play), tostring(#rec.keys))
out("HUDREC", tostring(has(hud(), "KAYIT")), tostring(has(hud(), "1.2×")))
reg.props["video-rotate"] = 0
reg.bind.rotate()
out("ROT_REC", tostring(reg.props["video-rotate"]), tostring(has(reg.osd[#reg.osd], "döndürülemez")))
reg.props["time-pos"] = 40 * 0.033
reg.bind.record() -- durdur + kaydet
out("STOP", tostring(has(hud(), "KAYIT")), tostring(has(reg.osd[#reg.osd], ".rec.json")))
local fh = io.open(os.getenv("VIDEO") .. ".rec.json", "rb")
out("JSON", fh and fh:read("*a") or "<yok>")
if fh then fh:close() end
out("TMP", tostring(io.open(os.getenv("VIDEO") .. ".rec.json.tmp", "rb") == nil))

-- 5) kayıt dışı: döndürme, hız
reg.bind.rotate()
out("ROT", tostring(reg.props["video-rotate"]))
reg.bind.faster(); local up = reg.props.speed
reg.bind.slower(); reg.bind.slower()
out("SPEED", tostring(up), tostring(reg.props.speed))

-- 6) kayıt dosyası yazılamazsa uyarı; anahtar yoksa dosya yok
reg.props.path = os.getenv("VIDEO") .. "-yok-dizin/x/clip.mp4"
reg.bind.record(); reg.ev["playback-restart"](); reg.props["time-pos"] = 0
reg.timers[#reg.timers]()
reg.bind.record()
out("WRITEFAIL", tostring(has(reg.osd[#reg.osd], "yazılamadı")))

-- 7) dışa aktarma (R3): E → `pythonw -m recorder export`, ilerleme .export.json, Esc iptal, sonuç OSD
local VID = os.getenv("VIDEO")
local OUT = VID:gsub("%.[^./\\]+$", "") .. ".kamera.mp4"
local function last_osd() return reg.osd[#reg.osd] or "" end
local function write(path, text) local fh = io.open(path, "wb"); fh:write(text); fh:close() end
local function exists(path) local fh = io.open(path, "rb"); if fh then fh:close() end; return fh ~= nil end
reg.props.path = VID .. "-yok.mp4"; reg.bind.export()
out("EXP_NOREC", tostring(has(last_osd(), "önce kayıt yap")), tostring(async == nil))
reg.props.path = VID
reg.bind.record(); reg.bind.export(); reg.bind.record()
out("EXP_RECON", tostring(has(reg.osd[#reg.osd - 1], "kayıt sürerken")), tostring(async == nil))
have = {}; reg.bind.export()
out("EXP_NOPY", tostring(has(last_osd(), "python/ bulunamadı")), tostring(async == nil))
have = { ["C:/app/python/python.exe"] = true }; reg.bind.export() -- pythonw yoksa python.exe
out("EXP_PYFALLBACK", async and async.t.args[1] or "<yok>")
async.cb(true, { status = 1 }); have = { ["C:/app/python/pythonw.exe"] = true }
os.remove(OUT .. ".export.json"); os.remove(OUT .. ".export.cancel")
reg.bind.export(); local a = async.t
out("EXP_ARGS", table.concat(a.args, "|"), tostring(a.playback_only), tostring(reg.bind["export-cancel"] ~= nil))
reg.bind.export()
out("EXP_BUSY", tostring(has(last_osd(), "sürüyor")))
write(OUT .. ".export.json", '{"state": "running", "n": 5, "total": 10, "pct": 50, "error": null}')
reg.timers[#reg.timers]()
out("EXP_PROGRESS", tostring(has(last_osd(), "%50")), tostring(has(last_osd(), "Esc")))
reg.bind["export-cancel"]()
out("EXP_CANCELFILE", tostring(exists(OUT .. ".export.cancel")))
async.cb(true, { status = 3 })
out("EXP_CANCELLED", tostring(has(last_osd(), "iptal edildi")), tostring(reg.bind["export-cancel"] == nil))
os.remove(OUT .. ".export.cancel")
reg.bind.export(); async.cb(true, { status = 0 })
out("EXP_DONE", tostring(has(last_osd(), "Kaydedildi: clip.kamera.mp4")), tostring(reg.bind["export-cancel"] == nil))
reg.bind.export()
write(OUT .. ".export.json", '{"state": "error", "n": 0, "total": 0, "pct": null, "error": "video açılamadı"}')
async.cb(true, { status = 1 })
out("EXP_ERROR", tostring(has(last_osd(), "başarısız: video açılamadı")))
reg.bind.export(); async.cb(true, { status = 7 })
out("EXP_NOJSON", tostring(has(last_osd(), "kod 7")))
os.remove(OUT .. ".export.json")
