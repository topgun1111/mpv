-- Ortak sahte `mp` (lua_harness*.lua kullanır). `reg` döndürür.
local reg = { bind = {}, obs = {}, ev = {}, props = {}, set = {}, osd = {}, cmds = {}, timers = {},
  msgs = {}, hud = {} }
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
  register_script_message = function(name, fn) reg.msgs[name] = fn end,
  create_osd_overlay = function()
    local o = { data = "" }
    function o:update() reg.hud[#reg.hud + 1] = self.data end
    return o
  end,
  get_mouse_pos = function() return { x = 0, y = 0 } end,
  msg = { info = function() end, warn = function() end, error = function() end },
}
package.preload["mp"] = function() return mp end
package.preload["mp.utils"] = function()
  return { parse_json = function() return dofile(os.getenv("DATA_LUA")) end }
end

return reg
