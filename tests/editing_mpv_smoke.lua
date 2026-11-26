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
    -- Exercise every individual setting, not just presets; export CRF is intentionally not a filter.
    for _,c in ipairs(C.controls) do
      if c[1]~="crf" then
        E.action("reset")
        assert(E.set_control(c[1],c[4]),"control failed: "..c[1])
        local g=assert(filter(),"missing filter "..c[1]).params.graph
        assert(g==C.graph({[c[1]]=c[4]}),"wrong graph "..c[1])
        mp.msg.info("EDITING_GRAPH|"..c[1].."|"..g)
        if c[3]<0 then
          assert(E.set_control(c[1],c[3]),"negative control failed: "..c[1])
          local neg=assert(filter()).params.graph
          assert(neg==C.graph({[c[1]]=c[3]}) and neg~=g,"negative graph "..c[1])
          mp.msg.info("EDITING_GRAPH|"..c[1].."_negative|"..neg)
        end
      end
    end
    E.action("reset");assert(not filter())
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
