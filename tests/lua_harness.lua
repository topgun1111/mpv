-- track.lua'yı sahte `mp` ile çalıştırır (texlua/lua 5.1+). Ortam: TRACK_LUA, VIDEO, DATA_LUA, TIMES.
local reg = { bind = {}, obs = {}, ev = {}, props = {}, set = {}, osd = {}, cmds = {}, timers = {} }
reg.props.path = os.getenv("VIDEO")
local mp = {
  add_key_binding = function(_, name, fn) reg.bind[name] = fn end,
  add_forced_key_binding = function(_, name, fn) reg.bind[name] = fn end,
  remove_key_binding = function(name) reg.bind[name] = nil end,
  observe_property = function(name, _, fn) reg.obs[name] = fn end,
  register_event = function(name, fn) reg.ev[name] = fn end,
  get_property = function(n) return reg.props[n] end,
  get_property_number = function(n, d) return reg.props[n] or d end,
  get_property_native = function(n) return reg.props[n] end,
  set_property_number = function(n, v) reg.set[n] = v end,
  osd_message = function(m) reg.osd[#reg.osd + 1] = m end,
  commandv = function(...) reg.cmds[#reg.cmds + 1] = table.concat({ ... }, " ") end,
  add_timeout = function(_, fn) reg.timers[#reg.timers + 1] = fn end,
  get_mouse_pos = function() return { x = 0, y = 0 } end,
  msg = { info = function() end, warn = function() end, error = function() end },
}
package.preload["mp"] = function() return mp end
package.preload["mp.utils"] = function()
  return { parse_json = function() return dofile(os.getenv("DATA_LUA")) end }
end
dofile(os.getenv("TRACK_LUA"))

local function last_osd() return reg.osd[#reg.osd] or "" end
local function out(...) print(table.concat({ ... }, "\t")) end

reg.ev["file-loaded"]()
out("HINT", last_osd())
reg.bind.offline()
out("ON", last_osd())
for t in os.getenv("TIMES"):gmatch("[^,]+") do
  reg.set = {}
  reg.obs["time-pos"](nil, tonumber(t))
  out("T", t, tostring(reg.set["video-zoom"]), tostring(reg.set["video-pan-x"]),
    tostring(reg.set["video-pan-y"]))
end
-- canlı mod açılınca offline kapanır ve görünüm sıfırlanır
reg.bind.toggle()
out("LIVE", last_osd(), tostring(reg.set["video-zoom"]))
reg.set = {}
reg.obs["time-pos"](nil, 1.0)
out("AFTER_LIVE_SET", tostring(reg.set["video-zoom"])) -- nil: offline kapalı, görünüm değişmez
-- offline tekrar açılınca canlı kapanır; gecikmeli yeniden uygulama zamanlayıcısı kurulur
reg.props["time-pos"] = 1.0
reg.bind.offline()
out("REON", last_osd(), tostring(#reg.timers))
reg.set = {}
reg.timers[1]()
out("TIMER", tostring(reg.set["video-zoom"]))
-- video değişince offline kapanır
reg.ev["end-file"]()
reg.set = {}
reg.obs["time-pos"](nil, 1.0)
out("ENDFILE", tostring(reg.set["video-zoom"]))
-- veri dosyası yoksa
reg.props.path = os.getenv("VIDEO") .. ".yok"
reg.bind.offline()
out("MISSING", last_osd())
