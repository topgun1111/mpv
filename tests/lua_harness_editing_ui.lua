-- Execute real UI module with a small mp API fake and test mouse/slider behavior.
package.path="mpv/portable_config/script-modules/?.lua;"..package.path
local filters={{label="other",name="format"}}
local props={path="sample.mp4",["video-params/w"]=1280,["video-params/gamma"]="bt.1886",["options/window-dragging"]="yes"}
local overlay={}
local timer
local reject=false
local notices={}
local mp={
  msg={info=function() end,error=function() end},
  get_property=function(k,d) return props[k] or d end,
  get_property_number=function(k,d) return props[k] or d end,
  get_property_native=function(k)
    if k=="vf" then return filters elseif k=="osd-dimensions" then return {w=1280,h=720} end
    return props[k]
  end,
  set_property=function(k,v) props[k]=v;return true end,
  commandv=function(cmd,op,arg)
    assert(cmd=="vf")
    if reject and op=="add" then return nil,"test failure" end
    for i=#filters,1,-1 do if filters[i].label=="videoediting" then table.remove(filters,i) end end
    if op=="add" then
      local n,g=arg:match("^@videoediting:lavfi=graph=%%(%d+)%%(.*)$")
      assert(n and tonumber(n)==#g,"bad graph escaping")
      filters[#filters+1]={label="videoediting",name="lavfi",params={graph=g}}
    end
    return true
  end,
  osd_message=function(s) notices[#notices+1]=s end,
  create_osd_overlay=function() overlay.update=function() end;return overlay end,
  observe_property=function() end,register_event=function() end,
  add_forced_key_binding=function() end,remove_key_binding=function() end,
  add_timeout=function(_,fn) timer=fn;return {kill=function() timer=nil end} end,
}
package.loaded.mp=mp
package.loaded["mp.utils"]={}
local E=require "editingui"
local C=require "editingcore"
E.action("moderate")
assert(filters[2].params.graph==C.graph(C.preset("moderate")))
E.action("adjust")
assert(E.is_open() and overlay.data:find("Dehaze",1,true) and overlay.data:find("Export CRF",1,true))
assert(props["options/window-dragging"]=="no")
-- 1280x720 layout: panel x=760, first rail starts x=966, first row y=103..140.
assert(E.over(1100,120))
assert(E.pointer({event="down"},{x=1100,y=120}))
E.mouse({x=1200,y=120,hover=true})
assert(timer);timer()
assert(E.pointer({event="up"},{x=1200,y=120}))
assert(filters[2].params.graph~=C.graph(C.preset("moderate")))
local adjusted=filters[2].params.graph
E.action("compare");assert(#filters==1 and filters[1].label=="other")
E.action("compare");assert(filters[2].params.graph==adjusted)
E.action("reset");assert(#filters==1)
reject=true;E.action("strong")
assert(#filters==1 and overlay.data:find("Preview failed",1,true))
reject=false
E.close();assert(not E.is_open() and props["options/window-dragging"]=="yes" and overlay.data=="")
print("EDITING_UI_OK")
