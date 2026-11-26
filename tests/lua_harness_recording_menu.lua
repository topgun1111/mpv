-- Run the actual recording menu, with mocked file picker and camera actions.
package.path="mpv/portable_config_recording/script-modules/?.lua;mpv/portable_config/script-modules/?.lua;"..package.path
local calls,bindings,messages,events={}, {}, {}, {}
local state={recording=false,started=false,running=false,exporting=false,local_video=true,saved=true}
local props={path="C:/clips/source.mp4",["video-params/w"]=640,pause=true,hwdec="auto-copy"}
local overlay,dialog
local dims={w=1280,h=720}
local observers={}
local mp={
  get_property=function(k,d) return props[k] or d end,
  get_property_number=function(k,d) return props[k] or d end,
  get_property_native=function(k)
    if k=="osd-dimensions" then return dims end
    return props[k]
  end,
  create_osd_overlay=function() overlay={update=function() end};return overlay end,
  observe_property=function(k,_,fn) observers[k]=fn end,
  register_event=function(k,fn) events[k]=fn end,
  add_key_binding=function(_,k,fn) bindings[k]=fn end,
  add_forced_key_binding=function(_,k,fn) bindings[k]=fn end,
  remove_key_binding=function(k) bindings[k]=nil end,
  register_script_message=function(k,fn) messages[k]=fn end,
  commandv=function(...) calls[#calls+1]={...} end,
  set_property=function(k,v) props[k]=v;return true end,
  command_native_async=function(t,fn) dialog={args=t.args,fn=fn};return 1 end,
  osd_message=function() end,
}
package.loaded.mp=mp
package.loaded["mp.utils"]={file_info=function(p)
  if p=="C:/clips/source.mp4" or p=="C:/clips/a b.mp4" then return {is_file=true} end
end,join_path=function(a,b) return a.."/"..b end}
local edits={}
package.loaded.editingui={action=function(a) edits[#edits+1]=a end,busy=function() return false end,
  close=function() end,over=function() return false end,mouse=function() end,pointer=function() return false end}
local M=require "recordingmenu"
local m=M.new({run=function(cmd) calls[#calls+1]={cmd} end,state=function() return state end})
local function locate(label)
  for line in overlay.data:gmatch("[^\n]+") do
    local x,y=line:match("\\pos%((%d+),(%d+)%)")
    if x and line:sub(-#label)==label then return {x=tonumber(x)+2,y=tonumber(y),hover=true} end
  end
  error("Missing menu label "..label)
end
local function click(label)
  local p=locate(label)
  assert(m.pointer({event="down"},p))
  assert(m.pointer({event="up"},p))
end
for _,label in ipairs({"File","View","Playback","Recording","Editing","Performance"}) do assert(locate(label)) end
click("File");click("Open file…")
assert(dialog and dialog.args[#dialog.args]:find("OpenFileDialog",1,true))
dialog.fn(true,{status=0,stdout="C:/clips/a b.mp4"})
assert(calls[#calls][1]=="loadfile" and calls[#calls][2]=="C:/clips/a b.mp4")
events["file-loaded"]()
click("File");click("Recent files…")
assert(dialog.args[#dialog.args]:find("C:/clips/source.mp4",1,true))
dialog.fn(true,{status=0,stdout=""})
local count=#calls
click("View");click("Zoom in");assert(calls[#calls][1]=="zoom_in")
click("Recording");click("Prepare recording");assert(calls[#calls][1]=="record")
state.recording=true
messages["recording-menu-action"]("open")
assert(#calls==count+2 and not m.busy(),"busy menu opened file")
messages["recording-menu-action"]("record_pause");assert(calls[#calls][1]=="record_pause")
state.recording=false
click("Editing");click("Dehaze: moderate");assert(edits[#edits]=="moderate")
click("File")
assert(m.pointer({event="down"},{x=1000,y=500}),"dismiss should consume click")
assert(m.pointer({event="up"},{x=1000,y=500}))
for _,size in ipairs({{640,360,1},{420,700,2},{1920,1080,2},{1280,720,1}}) do
  dims={w=size[1],h=size[2]}
  props["display-hidpi-scale"]=size[3]
  observers["osd-dimensions"]("osd-dimensions",dims)
  assert(overlay.res_x==dims.w and overlay.res_y==dims.h)
  click("Editing")
  local b=locate("Cancel editing export")
  assert(b.x>=0 and b.x<dims.w and b.y>=0 and b.y<dims.h,"menu item outside window")
  click("Editing")
end
click("Performance");click("Direct GPU decoding (fastest)")
assert(props.hwdec=="auto")
messages["editing-action"]("moderate")
assert(props.hwdec=="auto","GPU editing should not force a readback")
click("Performance");click("Standard audio sync")
assert(props["video-sync"]=="audio")
props.hwdec="auto-copy";props.vf={{label="videoediting"}}
messages["recording-menu-action"]("gpu_direct")
assert(props.hwdec=="auto-copy","direct decoding request is ignored with active CPU filter")
props.vf={}
messages["recording-menu-action"]("gpu_cpu")
assert(props.hwdec=="no")
messages["recording-menu-action"]("gpu_copy")
assert(props.hwdec=="auto-copy")
print("RECORDING_MENU_OK")
