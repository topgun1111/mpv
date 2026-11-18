-- Tracker paneli (L / «Tracker» sekmesi) + mod kapıları. Ortam: TRACK_LUA, TRACK_MODULES, VIDEO, DATA_LUA.
-- DATA_LUA: Python `track-cfg` özetini temsil eden tablo (sahte parse_json bunu döndürür).
local dir = (arg and arg[0] or ""):match("^(.*)[/\\]") or "."
local reg = dofile(dir .. "/lua_mp_stub.lua")
TRACK_SHOW_MENU = true
dofile(os.getenv("TRACK_LUA"))
local TM, TP = require("trackmenu"), require("trackpanel")
local function out(...) print(table.concat({ ... }, "\t")) end
local W, H = 1280, 720
reg.props["osd-dimensions"] = { w = W, h = H, ml = 0, mr = 0, mt = 0, mb = 0 }
reg.obs["osd-dimensions"]("osd-dimensions", reg.props["osd-dimensions"])
local function move(x, y)
  reg.props["mouse-pos"] = { x = x, y = y, hover = true }
  reg.obs["mouse-pos"]("mouse-pos", reg.props["mouse-pos"]) end
local function click(x, y)
  move(x, y); reg.cmds = {}
  if reg.bind["track-click-bind"] then reg.bind["track-click-bind"]({ event = "press" }) end
end
local function P() return reg.ov[3] or "" end
local bar, bh = TM.bar_layout(W, H, TM.MENUS)
local cfg = dofile(os.getenv("DATA_LUA"))
local function find(act, a, b)
  local L = TP.layout(W, H, { cfg = cfg }, bh)
  for _, w in ipairs(L.widgets) do
    if w.act == act and (a == nil or w.a == a) and (b == nil or w.b == b) then return w.x + 3, w.y + 3, L end
  end
end
local function cmds() return table.concat(reg.cmds, "|") end

-- L: panel açılır, Python'dan ayar özeti istenir
reg.cmds = {}
reg.bind.tracker()
out("OPEN", tostring(P():find("Takip", 1, true) ~= nil), tostring(cmds():find("track-cfg-get", 1, true) ~= nil), tostring(reg.bind["trackpanel-ESC"] ~= nil))
-- Python özeti gelince değerler çizilir (+ ayar yokken «—»)
out("NOCFG", tostring(P():find("—", 1, true) ~= nil))
reg.msgs["track-cfg"]("{}")
out("CFG", tostring(P():find("%30", 1, true) ~= nil), tostring(P():find("—", 1, true) == nil))
-- Vücut kartı: parça «Tüm kişi» + takip açılır; Nokta kartı: parça serbest
click(find("mode", "body"))
out("BODY", tostring(cmds():find("track-part person", 1, true) ~= nil), tostring(cmds():find("track-toggle on", 1, true) ~= nil))
click(find("mode", "point"))
out("POINT", tostring(cmds():find("track-part auto", 1, true) ~= nil))
-- Parça çipi vücut moduna geçirir
click(find("part", "left_leg"))
out("CHIP", tostring(cmds():find("track-part left_leg", 1, true) ~= nil))
-- Adım düğmeleri: temel ayar track-setting, ek ayar track-option; seçenek track-option toggle
click(find("step", "fill", 1)); out("STEP1", cmds())
click(find("step", "pbox", -1)); out("STEP2", cmds())
click(find("flag", "kp_filter")); out("FLAG", cmds())
-- GPU selection deliberately requires a second tap to avoid accidental app restarts.
click(find("gpu", "dml:1")); click(find("gpu", "dml:1")); out("GPU", cmds())
out("GPULABEL", tostring(P():find("NVIDIA", 1, true) ~= nil), tostring(P():find("EKRAN KARTI", 1, true) ~= nil))
do local _, _, L = find("save"); out("FIT", tostring(L.card.y + L.card.h <= H), tostring(L.s > 0.5)) end
out("CLIP", TP.clip("Çok uzun ekran kartı adı", 8), TP.clip("kısa", 8))
click(find("gpu_default")); out("GPUDEF", cmds())
click(find("save")); out("SAVE", cmds())
click(find("defaults")); out("DEF", cmds())
-- Panel üstündeyken oklar yakalanır; dışına çıkınca bırakılır
out("ARROWS", tostring(reg.bind["trackpanel-DOWN"] ~= nil))
move(5, H - 5)
out("ARROWOFF", tostring(reg.bind["trackpanel-DOWN"] == nil), tostring(reg.bind["track-click-bind"] == nil))
-- Mod kapıları. Dikdörtgen: sağ tık hedef seçmez
move(5, H - 5)
click(find("mode", "rect")); move(5, H - 5)
reg.cmds, reg.osd = {}, {}
reg.bind.pick({ event = "press" })
out("RECTGATE", tostring(cmds():find("track-point", 1, true) == nil), tostring((reg.osd[#reg.osd] or ""):find("Dikdörtgen modu", 1, true) ~= nil))
-- Nokta: sürükleme alan seçmez
click(find("mode", "point")); move(20, 300) -- kartın solu (panel dışı)
reg.cmds, reg.osd = {}, {}
reg.bind.pick({ event = "down" }); move(60, 500); reg.bind.pick({ event = "up" })
out("POINTGATE", tostring(cmds():find("track-rect", 1, true) == nil), tostring((reg.osd[#reg.osd] or ""):find("Nokta modu", 1, true) ~= nil))
-- G tuşu (sonraki parça) modu «Vücut» yapar; HUD'da «Mod:» satırı
reg.bind.part()
reg.msgs["track-hud"]("Takip: hedef seç", "0", "Model: x")
local hud = ""
for _, h in ipairs(reg.hud) do if h:find("Mod:", 1, true) then hud = h end end
out("HUDMODE", tostring(hud:find("Mod: Vücut", 1, true) ~= nil))
-- Esc kapatır; «Tracker» sekmesine tık açar, tekrar tık kapatır
reg.bind["trackpanel-ESC"]()
out("ESC", tostring(P() == ""), tostring(reg.bind["trackpanel-ESC"] == nil))
click(bar[5].x + 20, 5)
out("TAB", tostring(P() ~= ""))
click(bar[5].x + 20, 5)
out("TABOFF", tostring(P() == ""))
