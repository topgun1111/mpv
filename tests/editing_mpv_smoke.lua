-- Real mpv process test, not a mocked Lua API.
local mp=require "mp"
local dir=assert(os.getenv("EDITING_MODULES"))
package.path=dir.."/?.lua;"..package.path
local E=require "editingui"
local C=require "editingcore"
local function filter()
  for _,f in ipairs(mp.get_property_native("vf") or {}) do
    if f.label=="videoediting" then return f end
  end
end
local function check()
  local ok,err=pcall(function()
    assert(mp.get_property_number("video-params/w"),"no video frame")
    E.action("moderate")
    local f=assert(filter(),"moderate preset did not install filter")
    assert(f.name=="lavfi","wrong filter")
    assert(f.params and f.params.graph==C.graph(C.preset("moderate")),"preview graph mismatch")
    E.action("strong")
    assert(filter().params.graph==C.graph(C.preset("strong")),"strong preset did not replace graph")
    E.action("compare");assert(not filter(),"before did not remove filter")
    E.action("compare");assert(filter(),"after did not restore filter")
    E.action("reset");assert(not filter(),"reset left filter active")
  end)
  if not ok then mp.msg.error(tostring(err));mp.commandv("quit",1)
  else mp.msg.info("EDITING_MPV_SMOKE_OK");mp.commandv("quit",0) end
end
local tries=0
local function wait_frame()
  if mp.get_property_number("video-params/w") then check();return end
  tries=tries+1
  if tries>100 then mp.msg.error("No decoded video frame");mp.commandv("quit",1);return end
  mp.add_timeout(.05,wait_frame)
end
mp.register_event("file-loaded",wait_frame)
