-- Recording-only top bar, with the same Editing menu and panel as the full app.
local mp=require "mp"
local menus=require "trackmenu"
local editor=require "editingui"
local M={}
local editing
for _,m in ipairs(menus.MENUS) do if m.id=="editing" then editing=m;break end end
assert(editing,"Missing shared Editing menu")
-- Each mpv script has its own Lua VM; filtering this table cannot affect the full app.
menus.MENUS={editing}
function M.new(available)
  local self={}
  local ov=mp.create_osd_overlay("ass-events");ov.z=8
  local captured=false
  local function action(cmd)
    local name=cmd:match("^edit_(.+)$")
    if not name then return end
    if name~="cancel" and not available() then
      mp.osd_message("Stop recording or camera export before editing",3);return
    end
    editor.action(name)
  end
  local engine=menus.new({run=action,state=function(cmd)
    return {enabled=cmd=="edit_cancel" or available()}
  end})
  local function render()
    local d=mp.get_property_native("osd-dimensions") or {}
    local w,h=d.w or 0,d.h or 0
    if w<=0 or h<=0 then return end
    engine.hd=mp.get_property_number("display-hidpi-scale",1) or 1
    engine:resize(w,h);engine:relayout()
    ov.res_x,ov.res_y=w,h;ov.data=engine:render();ov:update()
  end
  function self.over(pos)
    return pos and pos.x and (engine:over(pos.x,pos.y) or editor.over(pos.x,pos.y))
  end
  function self.mouse(pos)
    if pos and pos.x and pos.hover~=false then
      if engine:mouse(pos.x,pos.y) then render() end
    end
    editor.mouse(pos)
  end
  function self.pointer(ev,pos)
    local e=ev and ev.event or "press"
    if e=="up" then
      local handled=editor.pointer(ev,pos)
      local was=captured;captured=false
      return handled or was
    end
    if not pos or not pos.x then return false end
    if e~="down" and e~="press" then return false end
    if engine:over(pos.x,pos.y) or engine:is_open() then
      if engine:click(pos.x,pos.y) then captured=e=="down";render();return true end
      render()
    end
    if editor.pointer(ev,pos) then captured=e=="down";return true end
    return false
  end
  function self.busy() return editor.busy() end
  function self.close_editor() editor.close();engine:close();render() end
  mp.observe_property("osd-dimensions","native",render)
  mp.observe_property("display-hidpi-scale","number",render)
  mp.add_key_binding("F10","editing-menu",function() engine:key("f10");render() end)
  mp.register_script_message("editing-action",function(name) action("edit_"..name);render() end)
  render()
  return self
end
return M
