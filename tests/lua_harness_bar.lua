-- U2: mpcbar.lua alt çubuğu (Ortam: BAR_LUA). 1280x700 → u = 1: seek y640-660, düğmeler y664-696.
local dir = (arg and arg[0] or ""):match("^(.*)[/\\]") or "."
local reg = dofile(dir .. "/lua_mp_stub.lua")
local mp = require("mp")
mp.get_property_bool = function(n, d) local v = reg.props[n]; if v == nil then return d end return v end
mp.set_property_bool = function(n, v) reg.props[n] = v; reg.set[n] = v end
mp.command = function(c) reg.cmds[#reg.cmds + 1] = c end
local mk = mp.create_osd_overlay
mp.create_osd_overlay = function(...)
  local o = mk(...)
  function o:remove() reg.removed = (reg.removed or 0) + 1; reg.ov[self.z or 0] = "" end
  return o
end
_G.mp = mp
reg.props["osd-width"], reg.props["osd-height"] = 1280, 700
reg.props.duration, reg.props["time-pos"], reg.props["volume-max"] = 100, 0, 130
reg.props.volume, reg.props.speed = 100, 1
dofile(os.getenv("BAR_LUA"))

local function out(...) print(table.concat({ ... }, "\t")) end
local function move(x, y) reg.obs["mouse-pos"](nil, { hover = true, x = x, y = y }) end
local function bound() return reg.bind["mpcbar-MBTN_LEFT"] ~= nil and "1" or "0" end
local function click(x, y)
  move(x, y); reg.cmds = {}
  if reg.bind["mpcbar-MBTN_LEFT"] then reg.bind["mpcbar-MBTN_LEFT"]({ event = "down" }) end
end

out("INIT", bound())
move(640, 300); out("VIDEO", bound())                       -- video üstü: sol tık serbest
move(20, 680); out("ONPLAY", bound(), reg.bind["mpcbar-MBTN_LEFT_DBL"] and "1" or "0")
move(640, 300); out("LEAVE", bound())
click(20, 680); out("PLAY", reg.cmds[1])
click(60, 680); out("STOP", reg.cmds[1] or "-", tostring(reg.set.pause))

-- seek: oran, ipucu, sürükleme, sınır
click(640, 650); out("SEEK", reg.cmds[1])
out("TIP", (reg.ov[0] or ""):find("00:00:50", 1, true) and "1" or "0")
move(5000, 650); out("DRAG_OUT", reg.cmds[#reg.cmds], bound())   -- çubuk dışına sürüklerken bağ kalır
reg.bind["mpcbar-MBTN_LEFT"]({ event = "up" }); out("UP", bound())
move(640, 300); out("AFTER", bound())

-- ses sürgüsü (x 1146..1230, vmax 130): uçlar, orta, dışarı sürükleme, mute açılır
reg.props.mute = true
click(1188, 680); out("VOL_MID", tostring(reg.set.volume), tostring(reg.props.mute))
move(1000, 680); out("VOL_LOW", tostring(reg.set.volume))
move(5000, 680); out("VOL_HIGH", tostring(reg.set.volume))
reg.bind["mpcbar-MBTN_LEFT"]({ event = "up" }); move(640, 300)

-- hız düğmeleri
click(330, 680); out("SPD_UP", tostring(reg.set.speed), reg.osd[#reg.osd] or "-")
click(250, 680); out("SPD_DN", tostring(reg.set.speed))
click(290, 680); out("SPD_RESET", tostring(reg.set.speed))
move(640, 300)

-- tam ekran: fare çubuktayken gizlenmez; ayrılınca zamanlayıcıyla gizlenir, bağ kalkar
reg.props.fullscreen = true
reg.obs.fullscreen(nil, true)
move(20, 680); reg.removed = 0
reg.timers[#reg.timers](); out("FS_HOVER", tostring(reg.removed), bound())
move(640, 300); reg.timers[#reg.timers](); out("FS_HIDE", tostring(reg.removed > 0), bound())
reg.props.fullscreen = false
reg.obs.fullscreen(nil, false); reg.removed = 0
move(640, 300); reg.timers[#reg.timers](); out("WIN_STAYS", tostring(reg.removed))
