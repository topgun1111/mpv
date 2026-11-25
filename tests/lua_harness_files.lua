-- M2: Dosya menüsü (Ortam: TRACK_LUA, TRACK_MODULES, VIDEO, TRACK_STATE_DIR). track.lua gerçekten yüklenir;
-- mpv `subprocess` (PowerShell) sahte: komut satırı yakalanır, stdout elle verilir.
local dir = (arg and arg[0] or ""):match("^(.*)[/\\]") or "."
local reg = dofile(dir .. "/lua_mp_stub.lua")
TRACK_SHOW_MENU = true
TRACK_FORCE_WIN = true
local mp = require("mp")

-- Küçük JSON (yalnız bu testin ihtiyacı: nesne/dizi/dize/sayı)
local function enc(v)
  local t = type(v)
  if t == "string" then return '"' .. v:gsub('[\\"]', "\\%0") .. '"' end
  if t ~= "table" then return tostring(v) end
  if #v > 0 then local a = {}; for i, x in ipairs(v) do a[i] = enc(x) end; return "[" .. table.concat(a, ",") .. "]" end
  local a = {}
  for k, x in pairs(v) do a[#a + 1] = enc(k) .. ":" .. enc(x) end
  table.sort(a)
  return "{" .. table.concat(a, ",") .. "}"
end
local function dec(s)
  local i = 1
  local function ws() i = s:find("%S", i) or #s + 1 end
  local val
  local function str()
    local out = {}
    i = i + 1
    while s:sub(i, i) ~= '"' do
      local c = s:sub(i, i)
      if c == "\\" then i = i + 1; c = s:sub(i, i) end
      out[#out + 1] = c; i = i + 1
    end
    i = i + 1
    return table.concat(out)
  end
  function val()
    ws()
    local c = s:sub(i, i)
    if c == '"' then return str() end
    if c == "{" or c == "[" then
      local o, close = {}, (c == "{") and "}" or "]"
      i = i + 1; ws()
      if s:sub(i, i) == close then i = i + 1; return o end
      while true do
        if c == "{" then ws(); local k = str(); ws(); i = i + 1; o[k] = val() else o[#o + 1] = val() end
        ws()
        local d = s:sub(i, i); i = i + 1
        if d == close then return o end
      end
    end
    local n = s:match("^-?[%d.eE+-]+", i)
    if n then i = i + #n; return tonumber(n) end
    error("json: " .. s:sub(i, i + 10))
  end
  local ok, r = pcall(val)
  if ok then return r end
  return nil, r
end
package.preload["mp.utils"] = function()
  return { parse_json = dec, format_json = enc, file_info = function() return nil end }
end
mp.command_native_async = function(t, cb) reg.async = { t = t, cb = cb } end

dofile(os.getenv("TRACK_LUA"))
local TM = require("trackmenu")
local TF = require("trackfiles")
local function out(...) print(table.concat({ ... }, "\t")) end
local W, H = 1280, 720
reg.props["osd-dimensions"] = { w = W, h = H, ml = 0, mr = 0, mt = 0, mb = 0 }
local function lastcmd() return reg.cmds[#reg.cmds] or "-" end
local function readf(p) local f = io.open(p, "rb"); if not f then return nil end; local s = f:read("*a"); f:close(); return s end
-- Dosya menüsünü F10 ile aç, k-ıncı seçilebilir öğeye in, Enter
local function pick(k)
  reg.bind.menu()
  for _ = 2, k do reg.bind["trackmenu-DOWN"]() end -- F10 ilk öğeyi seçer
  reg.bind["trackmenu-ENTER"]()
end
local function answer(stdout, status) local a = reg.async; reg.async = nil; a.cb(true, { status = status or 0, stdout = stdout }) end

-- Ctrl+O: PowerShell diyaloğu; seçilen yol (Türkçe harf, CRLF) yüklenir, son açılanlara yazılır
reg.cmds = {}
reg.bind.open()
local a = reg.async.t
out("OPEN_ARGS", a.args[1], tostring(a.capture_stdout), tostring(a.playback_only), tostring(a.args[#a.args]:find("OpenFileDialog", 1, true) ~= nil))
reg.bind.open() -- diyalog açıkken ikinci çağrı yok sayılır
local same = reg.async.t == a
answer("C:\\Videolar\\maç ğüşi.mp4\r\n")
out("OPEN_LOAD", lastcmd(), tostring(same))
local st = dec(readf(os.getenv("TRACK_STATE_DIR") .. "/TakipliOynat/recent.json"))
out("OPEN_STATE", st.dir, st.recent[1])
-- iptal (boş çıktı) → komut yok
reg.cmds = {}
reg.bind.open(); answer("")
out("CANCEL", tostring(#reg.cmds == 0), tostring(reg.async == nil))
-- hata (status≠0) → OSD, yükleme yok
reg.bind.open(); answer("", 1)
out("FAIL", tostring(#reg.cmds == 0), (reg.toast ~= "" and reg.toast or (reg.osd[#reg.osd] or "-")))

-- Menüden: 2. seçilebilir öğe = Son açılanlar (liste PowerShell dizisi olarak gömülür)
reg.cmds = {}
pick(2)
local sc = reg.async.t.args[#reg.async.t.args]
out("RECENT", tostring(sc:find("Son açılanlar", 1, true) ~= nil), tostring(sc:find("'C:\\Videolar\\maç ğüşi.mp4'", 1, true) ~= nil))
answer("C:\\Videolar\\maç ğüşi.mp4")
out("RECENT_PICK", lastcmd())
-- Klasör (3.) ve URL (4.)
pick(3); out("FOLDER", tostring(reg.async.t.args[#reg.async.t.args]:find("FolderBrowserDialog", 1, true) ~= nil)); answer("E:\\Maclar")
out("FOLDER_LOAD", lastcmd())
st = dec(readf(os.getenv("TRACK_STATE_DIR") .. "/TakipliOynat/recent.json"))
out("FOLDER_DIR", st.dir)
pick(4); answer("not a url"); out("URL_BAD", tostring(lastcmd() == "loadfile E:\\Maclar replace"))
pick(4); answer("https://example.com/v.mp4"); out("URL_OK", lastcmd())

-- Görünümü kaydet (5.) / yükle (6.): <video>.view.json
reg.props["video-zoom"], reg.props["video-pan-x"], reg.props["video-pan-y"], reg.props["video-rotate"] = 1.5, 0.25, -0.5, 90
pick(5)
local snap = dec(readf(os.getenv("VIDEO") .. ".view.json"))
out("SAVE_VIEW", tostring(snap.zoom), tostring(snap.pan_x), tostring(snap.pan_y), tostring(snap.rotate))
reg.set = {}
reg.props["video-zoom"], reg.props["video-pan-x"], reg.props["video-pan-y"], reg.props["video-rotate"] = 0, 0, 0, 0
pick(6)
out("LOAD_VIEW", tostring(reg.set["video-zoom"]), tostring(reg.set["video-pan-x"]), tostring(reg.set["video-pan-y"]), tostring(reg.set["video-rotate"]))
-- bozuk dosya kabul edilmez
local f = io.open(os.getenv("VIDEO") .. ".view.json", "wb"); f:write('{"version":1,"zoom":99,"pan_x":0,"pan_y":0}'); f:close()
reg.set = {}; pick(6)
out("LOAD_BAD", tostring(reg.set["video-zoom"] == nil), reg.toast ~= "" and reg.toast or (reg.osd[#reg.osd] or "-"))
-- Takip açıkken yükleme reddedilir
reg.bind.toggle(); reg.set = {}; pick(6)
out("LOAD_BUSY", tostring(reg.set["video-zoom"] == nil), reg.toast ~= "" and reg.toast or (reg.osd[#reg.osd] or "-"))
reg.bind.toggle()

-- Videoyu kapat (7.)
reg.cmds = {}; pick(7); out("CLOSE", lastcmd())

-- A1: Hedefli iş akışı: video yüklenir/duraklar; hedef seçimi kuyruğa alınır; Play taramayı başlatır.
reg.props["video-params"] = { w = 1920, h = 1080 }
mp.command_native = function(t) reg.spawn = t; return { status = 0 } end
reg.props["mouse-pos"] = { x = 640, y = 400 }
if reg.bind["trackpanel-ESC"] then reg.bind["trackpanel-ESC"]() end
reg.obs["mouse-pos"](nil, reg.props["mouse-pos"])
reg.props["video-zoom"], reg.props["video-pan-x"], reg.props["video-pan-y"] = 0, 0, 0
reg.cmds = {}; reg.bind.pick()
assert(lastcmd():find("track-point", 1, true), lastcmd())
reg.bind.pick({event="down"})
reg.props["mouse-pos"] = { x = 700, y = 440 }
reg.bind.pick({event="up"})
assert(lastcmd():find("track-rect", 1, true), lastcmd())
-- hedefli açma beklenmiyorken: tarama BAŞLAMAZ
out("SCAN_NOT_PENDING", tostring(reg.spawn == nil))
pick(8)
answer("C:\\Videolar\\hedef.mp4")
out("SCAN_OPEN", lastcmd(), tostring(reg.set.pause))
reg.obs["mouse-pos"](nil, { x = 640, y = 400 }) -- fare videonun üstüne geldi (menü sıcak değil)
-- Nokta modunda sağ tık hedefi kuyruğa alır; Play taramayı başlatır.
reg.msgs["track-mode"]("auto")
if reg.bind["trackpanel-ESC"] then reg.bind["trackpanel-ESC"]() end -- ayar panelini kapat
reg.props["mouse-pos"] = { x = 640, y = 400 }
reg.obs["mouse-pos"](nil, { x = 640, y = 400 })
local n0 = #reg.timers
reg.bind.pick()
out("SCAN_QUEUED", tostring(reg.spawn == nil), reg.toast ~= "" and reg.toast or (reg.osd[#reg.osd] or "-"))
reg.obs["pause"](nil, false) -- kullanıcı Play'e basar
local a = reg.async.t.args
out("SCAN_SPAWN", tostring(reg.async.t.playback_only == false), a[1], table.concat({ a[2], a[3], a[4] }, " "), a[6], a[7],
  tostring(a[8]), tostring(reg.set.pause))
out("SCAN_ARGS", tostring(a[8] == "--preset" and a[9] == "person"
  and tonumber(a[11]) ~= nil and tonumber(a[12]) ~= nil and tonumber(a[13]) ~= nil))
reg.spawn = nil; reg.bind.pick() -- ikinci tık yeni tarama başlatmaz
out("SCAN_ONCE", tostring(reg.spawn == nil))
-- Scan launch is asserted above; completion polling is covered by dedicated offline tests.

-- E1: Dışa aktar (9.): görünüm dosyası yoksa uyarı; varsa detached `export` + ilerleme
reg.spawn = nil; pick(9)
out("EXPORT_NOVIEWS", tostring(reg.spawn == nil), reg.toast ~= "" and reg.toast or (reg.osd[#reg.osd] or "-"))
local vf = io.open(os.getenv("VIDEO") .. ".views.json", "wb"); vf:write('{"views":[[0,0,0,0]]}'); vf:close()
pick(9)
local want = os.getenv("VIDEO"):gsub("%.[^./\\]+$", "") .. ".takipli.mp4"
assert(reg.async.t.args[#reg.async.t.args]:find("SaveFileDialog", 1, true))
answer("") -- cancel must not launch the exporter
assert(reg.async == nil)
pick(9); answer(want)
local e = reg.async.t.args
out("EXPORT_SPAWN", tostring(reg.async.t.playback_only == false), e[4], e[5], tostring(e[6] == os.getenv("VIDEO")), tostring(e[7] == "--views" and e[10] == want))
local ef = io.open(want .. ".export.json", "wb"); ef:write('{"state":"running","pct":55}'); ef:close()
reg.timers[#reg.timers]()
out("EXPORT_PROGRESS", reg.toast ~= "" and reg.toast or (reg.osd[#reg.osd] or "-"))
ef = io.open(want .. ".export.json", "wb"); ef:write('{"state":"done","pct":100}'); ef:close()
reg.timers[#reg.timers]()
out("EXPORT_DONE", reg.toast ~= "" and reg.toast or (reg.osd[#reg.osd] or "-"))
os.remove(want .. ".export.json"); os.remove(os.getenv("VIDEO") .. ".views.json")

-- Saf modül
out("PURE_QUOTE", TF.ps_quote("a'b"))
out("PURE_CLEAN", tostring(TF.clean("\239\187\191 C:\\a b.mp4 \r\nfoo")), tostring(TF.clean("  \r\n")))
out("PURE_RECENT", table.concat(TF.add_recent(TF.add_recent(TF.add_recent(TF.sanitize(nil), "/a/1.mp4"), "/b/2.mp4"), "/a/1.mp4").recent, ","))
local many = TF.sanitize(nil)
for i = 1, 15 do many = TF.add_recent(many, "/v/" .. i .. ".mp4") end
out("PURE_CAP", tostring(#many.recent), many.recent[1], tostring(many.dir))
out("PURE_URL", tostring(TF.is_url("https://a/b")), tostring(TF.is_url("C:\\a.mp4")), tostring(TF.parent_dir("https://a/b")))
out("PURE_SNAP", tostring(select(4, TF.parse_snapshot({ version = 1, zoom = 1, pan_x = 0, pan_y = 0, rotate = 100 }))),
  tostring(TF.parse_snapshot({ version = 2 })), tostring(TF.parse_snapshot({ version = 1, zoom = 0 / 0, pan_x = 0, pan_y = 0 })))
-- menü tablosu: Dosya'daki todo olmayan her komutun eylemi var (sahte mpv'de seçilebilir sayısı 8)
local n = 0
for _, it in ipairs(TM.MENUS[1].items) do if it.cmd and not it.todo then n = n + 1 end end
out("MENU_COUNT", tostring(n))
