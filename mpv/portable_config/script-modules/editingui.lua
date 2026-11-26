-- Editing owns only @videoediting. Never calls tracking/recording services.
local mp = require "mp"
local utils = require "mp.utils"
local function load_module(name)
  local ok, mod = pcall(require,name)
  if ok then return mod end
  local path=mp.command_native({"expand-path","~~/script-modules/"..name..".lua"})
  assert(type(path)=="string","Missing "..name)
  return dofile(path)
end
local core=load_module("editingcore")
local files=load_module("trackfiles")
local M={}
local opened, overlay, drag, old_window_drag = false,nil,nil,nil
local rows, buttons, bounds = {},{},nil
local pending, pending_timer, shown_error
local render, close, flush

local state, bypass, generation = core.defaults(), false, 0
local dialog, job, timer = false, nil, nil
local label = "@videoediting"
local function notice(s, seconds) mp.osd_message("Editing: "..s, seconds or 3) end
local function local_source()
  local p = mp.get_property("path")
  if not p or files.is_url(p) then return nil end
  if not (p:match("^%a:[/\\]") or p:match("^[/\\]")) then
    p=utils.join_path(mp.get_property("working-directory","."),p)
  end
  local info = utils.file_info(p)
  return info and info.is_file and p or nil
end
local function video_ok()
  if not mp.get_property("path") or not mp.get_property_number("video-params/w") then
    notice("Open a local video first"); return false
  end
  local gamma = (mp.get_property("video-params/gamma") or ""):lower()
  if gamma == "pq" or gamma == "hlg" or gamma == "st2084" then
    notice("HDR is not supported by this SDR editor", 5); return false
  end
  return true
end
local function owns_filter()
  for _,f in ipairs(mp.get_property_native("vf") or {}) do
    if f.label=="videoediting" then return true end
  end
  return false
end
local function remove()
  if owns_filter() then return mp.commandv("vf","remove",label) end
  return true
end
local function install(graph)
  if graph=="" then return remove() end
  return mp.commandv("vf","add",label..":lavfi=graph=%"..#graph.."%"..graph)
end
local function apply(new,compare)
  new=core.normalize(new)
  local graph=compare and "" or core.graph(new)
  local prev=bypass and "" or core.graph(state)
  if graph~=prev or (graph~="" and not owns_filter()) then
    local ok,err=install(graph)
    if not ok or (graph~="" and not owns_filter()) then
      shown_error="Preview failed - see mpv log"
      mp.msg.error("Editing filter: "..tostring(err or "filter not present"))
      install(prev);notice(shown_error,5)
      if render then render() end
      return false
    end
  end
  state,bypass,shown_error=new,compare,nil
  if render then render() end
  return true
end
local function clamp(v,lo,hi) return math.max(lo,math.min(hi,v)) end
local function box(x,y,w,h)
  return {x=math.floor(x),y=math.floor(y),w=math.max(1,math.floor(w)),h=math.max(1,math.floor(h))}
end
local function inside(r,x,y)
  return r and x and y and x>=r.x and y>=r.y and x<r.x+r.w and y<r.y+r.h
end
local function rect(r,c)
  return string.format("{\\an7\\pos(%d,%d)\\bord0\\shad0\\1c&H%s&\\p1}m 0 0 l %d 0 l %d %d l 0 %d{\\p0}",r.x,r.y,c,r.w,r.w,r.h,r.h)
end
local function text(x,y,n,c,s)
  return string.format("{\\an4\\pos(%d,%d)\\fnSegoe UI\\fs%d\\bord0\\shad0\\1c&H%s&}%s",math.floor(x),math.floor(y),n,c,s)
end
local function layout()
  local d=mp.get_property_native("osd-dimensions") or {}
  local W,H=d.w or 0,d.h or 0
  rows,buttons={},{}
  if W<250 or H<220 then bounds=nil;return W,H end
  local top=math.max(42,math.floor(H*.08))
  local bottom=math.max(56,math.floor(H*.13))
  local available=H-top-bottom-8
  local cols=(available<430 and W>=640) and 2 or 1
  local width=math.min(W-16,cols==2 and 760 or math.max(340,math.min(520,W*.40)))
  local count=math.ceil(#core.controls/cols)
  local line=math.max(10,math.min(38,math.floor((available-82)/count)))
  local height=82+line*count
  local x,y=math.floor(W-width-8),top
  bounds=box(x,y,width,height)
  local colw=(width-16)/cols
  local names={haze="Dehaze",contrast="Contrast",brightness="Brightness",gamma="Gamma",saturation="Saturation",shadows="Shadows",highlights="Highlights",warmth="Warmth",clarity="Clarity",sharpness="Sharpness",denoise="Denoise",crf="Export CRF"}
  for i,c in ipairs(core.controls) do
    local rx=x+8+math.floor((i-1)/count)*colw
    local ry=y+46+((i-1)%count)*line
    local labelw=math.floor(colw*.40)
    rows[i]={control=c,name=names[c[1]],area=box(rx,ry,colw-6,line),rail=box(rx+labelw,ry+line/2-2,colw-labelw-44,4)}
  end
  local names2={{"light","Light"},{"moderate","Medium"},{"strong","Strong"},{"reset","Reset"},{"compare",bypass and "After" or "Before"},{"export","Export"},{"close","Close"}}
  local bw=(width-14)/#names2
  for i,v in ipairs(names2) do buttons[i]={action=v[1],name=v[2],area=box(x+7+(i-1)*bw,y+height-29,bw-3,23)} end
  return W,H
end
render=function()
  if not overlay then overlay=mp.create_osd_overlay("ass-events");overlay.z=6 end
  if not opened then overlay.data="";overlay:update();return end
  local W,H=layout()
  if not bounds then overlay.data="";overlay:update();return end
  overlay.res_x,overlay.res_y=W,H
  local o={rect(bounds,"252525"),rect(box(bounds.x,bounds.y,bounds.w,32),"353535"),
    text(bounds.x+10,bounds.y+14,18,"FFFFFF","Editing | Live preview"),
    text(bounds.x+10,bounds.y+37,12,shown_error and "8080FF" or "B8B8B8",shown_error or (bypass and "Original view - export uses edits" or "Drag sliders to grade video"))}
  local values=pending or state
  for _,r in ipairs(rows) do
    local c,a,t=r.control,r.area,r.rail
    local v=values[c[1]]
    local ratio=clamp((v-c[3])/(c[4]-c[3]),0,1)
    local cy=math.floor(a.y+a.h/2)
    local fs=math.max(9,math.min(15,a.h-3))
    o[#o+1]=text(a.x+2,cy,fs,"E0E0E0",r.name)
    o[#o+1]=rect(t,"606060")
    if ratio>0 then o[#o+1]=rect(box(t.x,t.y,t.w*ratio,t.h),"E8AE62") end
    o[#o+1]=rect(box(t.x+t.w*ratio-4,cy-6,8,12),"F5F5F5")
    o[#o+1]=text(t.x+t.w+10,cy,fs,"FFFFFF",tostring(v))
  end
  for _,v in ipairs(buttons) do
    local a=v.area
    o[#o+1]=rect(a,v.action=="export" and "986436" or "454545")
    o[#o+1]=text(a.x+3,a.y+a.h/2,math.max(9,math.min(13,math.floor(a.w/4))),"FFFFFF",v.name)
  end
  overlay.data=table.concat(o,"\n");overlay:update()
end
flush=function()
  if pending_timer then pending_timer:kill();pending_timer=nil end
  if not pending then return end
  local s=pending;pending=nil;apply(s,false)
end
local function queue(r,x)
  local c,t=r.control,r.rail
  local v=math.floor(c[3]+clamp((x-t.x)/t.w,0,1)*(c[4]-c[3])+.5)
  local s=core.normalize(pending or state)
  if s[c[1]]==v and not bypass then return end
  s[c[1]]=v;pending=s;render()
  if not pending_timer then pending_timer=mp.add_timeout(.10,flush) end
end
function M.over(x,y) return opened and (drag~=nil or inside(bounds,x,y)) end
function M.mouse(pos)
  if not opened or not drag then return end
  if not pos or pos.hover==false then drag=nil;flush()
  elseif pos.x then queue(drag,pos.x) end
end
function M.pointer(ev,pos)
  if not opened then return false end
  local e=ev and ev.event or "press"
  if e=="up" then
    if drag then if pos and pos.x then queue(drag,pos.x) end;drag=nil;flush();return true end
    return false
  end
  if not pos or not inside(bounds,pos.x,pos.y) then return false end
  if e~="press" and e~="down" then return true end
  for _,v in ipairs(buttons) do
    if inside(v.area,pos.x,pos.y) then M.action(v.action);return true end
  end
  for _,r in ipairs(rows) do
    if inside(r.area,pos.x,pos.y) and pos.x>=r.rail.x-8 then
      queue(r,pos.x)
      if e=="down" then drag=r else flush() end
      return true
    end
  end
  return true
end
close=function()
  flush();drag=nil;opened=false
  if old_window_drag~=nil then mp.set_property("options/window-dragging",old_window_drag);old_window_drag=nil end
  mp.remove_key_binding("editing-close");render()
end
function M.is_open() return opened end
function M.close() if opened then close() end end
local function choose()
  if opened then close();return end
  opened=true;old_window_drag=mp.get_property("options/window-dragging")
  if old_window_drag then mp.set_property("options/window-dragging","no") end
  mp.add_forced_key_binding("ESC","editing-close",close)
  render()
end
mp.observe_property("osd-dimensions","native",function() if opened then render() end end)
local function ffmpeg_path()
  local exe = mp.get_property("executable-path")
  if exe then
    local dir=files.parent_dir(exe)
    if dir then
      local p=utils.join_path(dir,"../ffmpeg/ffmpeg.exe")
      if utils.file_info(p) then return p end
    end
  end
  local p=mp.command_native({"expand-path","~~/../../ffmpeg/ffmpeg.exe"})
  if type(p)=="string" and utils.file_info(p) then return p end
  return nil
end
local function export()
  if job or dialog then notice("Export or save dialog already active"); return end
  if not video_ok() then return end
  flush()
  local source, exe, g = local_source(), ffmpeg_path(), generation
  if not source then notice("Export needs a local video file",5);return end
  if not exe then notice("Bundled FFmpeg not found",5); return end
  local snapshot=core.normalize(state)
  if core.graph(snapshot)=="" then notice("No color adjustments selected"); return end
  local stream
  for _, tr in ipairs(mp.get_property_native("track-list") or {}) do
    if tr.type=="video" and tr.selected then
      if tr.external or tr.albumart then notice("Select an internal video track first"); return end
      stream=tr["ff-index"]; break
    end
  end
  local dir=files.parent_dir(source)
  local name=(source:match("[^/\\]+$") or "video"):gsub("%.[^%.]+$","")..".edited.mp4"
  local ps="$ErrorActionPreference='Stop';[Console]::OutputEncoding=New-Object Text.UTF8Encoding $false;"
    .."Add-Type -AssemblyName System.Windows.Forms;$o=New-Object Windows.Forms.Form;$o.TopMost=$true;"
    .."$d=New-Object Windows.Forms.SaveFileDialog;$d.Title='Export edited video';$d.Filter='MP4 video|*.mp4';"
    .."$d.DefaultExt='mp4';$d.AddExtension=$true;$d.OverwritePrompt=$true;$d.FileName="..files.ps_quote(name)..";"
    ..(dir and ("$d.InitialDirectory="..files.ps_quote(dir)..";") or "")
    .."if($d.ShowDialog($o) -eq 'OK'){[Console]::Out.Write($d.FileName)};$d.Dispose();$o.Dispose();"
  dialog=true
  mp.command_native_async({name="subprocess",playback_only=false,capture_stdout=true,args=files.ps_args(ps)},function(ok,res)
    dialog=false
    if not ok or not res or res.status~=0 then notice("Save dialog failed",5);return end
    local dest=files.clean(res.stdout)
    if not dest then return end
    if generation~=g then notice("Video changed; export not started");return end
    if dest:lower():sub(-4)~=".mp4" then notice("Choose an MP4 filename");return end
    if utils.file_info(dest) then notice("Choose a new filename; existing files are never overwritten",6);return end
    local current={cancelled=false,started=mp.get_time(),dest=dest}
    job=current
    current.id=mp.command_native_async({name="subprocess",playback_only=false,capture_stderr=true,
      args=core.export_args(exe,source,dest,snapshot,stream)},function(success,result,err)
      if timer then timer:kill();timer=nil end
      job=nil
      if current.cancelled then notice("Export cancelled; incomplete output may remain",6)
      elseif success and result and result.status==0 then notice("Export finished: "..dest,8)
      else
        mp.msg.error("Editing export failed: "..tostring(result and result.stderr or err))
        notice("Export failed; see mpv log. Incomplete output may remain.",7)
      end
    end)
    if not current.id then job=nil;notice("Could not start FFmpeg",5);return end
    timer=mp.add_periodic_timer(2,function()
      notice(string.format("Exporting... %ds (Editing > Cancel editing export)",math.floor(mp.get_time()-current.started)),2.2)
    end)
    notice("Export started",3)
  end)
end
function M.action(action)
  if action=="close" then M.close();return end
  flush()
  if action=="cancel" then
    if job and job.id then job.cancelled=true;mp.abort_async_command(job.id) else notice("No export running") end
    return
  end
  if not video_ok() then return end
  if action=="adjust" then choose()
  elseif action=="light" or action=="moderate" or action=="strong" then
    local s=core.preset(action);s.crf=state.crf
    if apply(s,false) then notice("Dehaze: "..action) end
  elseif action=="compare" then
    if apply(state,not bypass) then notice(bypass and "Before (original)" or "After (edited)") end
  elseif action=="reset" then if apply(core.defaults(),false) then notice("Reset") end
  elseif action=="export" then export() end
end
local function reset_file()
  generation=generation+1
  if pending_timer then pending_timer:kill();pending_timer=nil end
  pending=nil;drag=nil;M.close();remove();state=core.defaults();bypass=false;shown_error=nil
end
mp.register_event("start-file",reset_file)
mp.register_event("end-file",reset_file)
mp.msg.info("Independent Editing module loaded")
return M
