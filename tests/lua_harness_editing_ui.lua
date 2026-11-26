-- Execute real UI module with a small mp API fake and test mouse/slider behavior.
package.path="mpv/portable_config/script-modules/?.lua;"..package.path
local filters={{label="other",name="format"}}
local props={path="sample.mp4",["video-params/w"]=1280,["video-params/gamma"]="bt.1886",["options/window-dragging"]="yes"}
local overlay={}
local dims={w=1280,h=720}
local observers={}
local timer
local reject=false
local notices={}
local mp={
  msg={info=function() end,error=function() end},
  get_property=function(k,d) return props[k] or d end,
  get_property_number=function(k,d) return props[k] or d end,
  get_property_native=function(k)
    if k=="vf" then return filters elseif k=="osd-dimensions" then return dims end
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
  observe_property=function(k,_,fn) observers[k]=fn end,register_event=function() end,
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
-- Read the actual rendered geometry instead of depending on fixed pixels.
local function locate(label)
  for line in overlay.data:gmatch("[^\n]+") do
    local x,y,fs=line:match("\\pos%((%d+),(%d+)%)\\fnSegoe UI\\fs(%d+)")
    if x and line:sub(-#label)==label then return tonumber(x),tonumber(y),tonumber(fs) end
  end
  error("Missing rendered label: "..label)
end
local function panel()
  local x,y,w,h=overlay.data:match("\\pos%((%d+),(%d+)%)%S-m 0 0 l (%d+) 0 l %d+ (%d+)")
  assert(x and y and w and h,"Missing panel rectangle")
  return tonumber(x),tonumber(y),tonumber(w),tonumber(h)
end
local x,y,w,h=panel()
assert(w>=900 and x>0 and x<250 and math.abs(x+w/2-640)<8,"panel should be wide and centered")
local hx,hy,hfs=locate("Editing")
assert(hfs>=22,"title font too small")
local sx,sy,fs=locate("Dehaze")
assert(fs>=20,"slider label too small")
assert(E.pointer({event="down"},{x=hx+10,y=hy}))
E.mouse({x=hx+65,y=hy+20,hover=true})
assert(E.pointer({event="up"},{x=hx+65,y=hy+20}))
local mx,my=panel()
assert(mx>x and my>y,"title did not move the panel")
assert(filters[2].params.graph==C.graph(C.preset("moderate")),"moving changed settings")
E.action("center")
local cx,cy=panel()
assert(cx==x and cy==y,"Center did not restore default")
sx,sy=locate("Dehaze")
local tx=sx+math.floor(w*.25)
assert(E.over(tx,sy))
assert(E.pointer({event="down"},{x=tx,y=sy}))
E.mouse({x=tx+130,y=sy,hover=true})
assert(timer,"drag did not schedule preview update");timer()
assert(E.pointer({event="up"},{x=tx+130,y=sy}))
assert(filters[2].params.graph~=C.graph(C.preset("moderate")))
local adjusted=filters[2].params.graph
E.action("compare");assert(#filters==1 and filters[1].label=="other")
E.action("compare");assert(filters[2].params.graph==adjusted)
E.action("reset");assert(#filters==1)
reject=true;E.action("strong")
assert(#filters==1 and overlay.data:find("Preview failed",1,true))
reject=false
-- Compact mode has smaller geometry; the large mode restores it.
E.action("size")
local _,_,cw=panel()
assert(cw<w)
E.action("size")
local _,_,lw=panel()
assert(lw==w)
-- Small windows paginate at a readable font, and the panel stays inside the viewport.
dims={w=640,h=480};observers["osd-dimensions"]()
local px,py,pw,ph=panel()
assert(px>=0 and py>=0 and px+pw<=640 and py+ph<=480)
assert(overlay.data:find("Page 1/",1,true),"pagination status hidden, possibly by filter error")
assert(overlay.data:find("Preview failed",1,true),"filter failure status should remain visible")
local _,_,smallfs=locate("Dehaze")
assert(smallfs>=16)
E.action("next")
assert(overlay.data:find("Page 2/",1,true),"next page not rendered")
E.action("prev")
assert(overlay.data:find("Dehaze",1,true))
dims={w=1920,h=1080};props["display-hidpi-scale"]=1.5;observers["osd-dimensions"]()
local _,_,largefs=locate("Dehaze")
assert(largefs>=30)
E.close();assert(not E.is_open() and props["options/window-dragging"]=="yes" and overlay.data=="")
print("EDITING_UI_OK")
