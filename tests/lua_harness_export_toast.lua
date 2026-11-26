-- Exercise real toast layout, lifetime, escaping, update and DPI behavior.
package.path="mpv/portable_config/script-modules/?.lua;"..package.path
local dims={w=1280,h=720}
local dpi=1
local overlay
local timers,observers={},{}
local mp={
  get_property=function(k) if k=="current-vo" then return "gpu" end end,
  get_property_native=function(k) if k=="osd-dimensions" then return dims end end,
  get_property_number=function() return dpi end,
  command_native=function(args)
    assert(args[1]=="escape-ass")
    return (args[2]:gsub("{","\\{"):gsub("\n","\\N"))
  end,
  create_osd_overlay=function() overlay={update=function() end};return overlay end,
  observe_property=function(k,_,fn) observers[k]=fn end,
  add_timeout=function(_,fn)
    local t={fn=fn,kill=function(self) self.killed=true end}
    timers[#timers+1]=t;return t
  end,
}
package.loaded.mp=mp
local T=require "exporttoast"
T.show("Exporting 42%",0)
assert(overlay.z>8 and overlay.z>6 and #timers==0)
local function position()
  local x,y,fs=overlay.data:match("\\pos%((%d+),(%d+)%)\\fnSegoe UI\\fs(%d+)")
  return tonumber(x),tonumber(y),tonumber(fs)
end
local x,y,fs=position()
assert(x==640 and y>360 and y<720 and fs>=12)
T.show("Exporting 75%",0)
assert(overlay.data:find("75%",1,true) and #timers==0)
dims={w=420,h=320};dpi=2
observers["osd-dimensions"]()
x,y,fs=position()
assert(overlay.res_x==420 and overlay.res_y==320 and x==210 and y>160 and y<320)
T.show("Saved {example}.mp4",8)
assert(overlay.data:find("\\{example}",1,true))
local old=timers[#timers]
T.show("Exporting another file",0)
assert(old.killed);old.fn()
assert(overlay.data:find("another file",1,true),"old timer cleared newer toast")
T.show("Export failed: "..string.rep("ü",100),8)
assert(overlay.data:find("\\N",1,true),"long path was not wrapped")
timers[#timers].fn()
assert(overlay.data=="")
print("EXPORT_TOAST_OK")
