-- Editing owns only @videoediting. Never calls tracking/recording services.
local mp = require "mp"
local utils = require "mp.utils"
local core = require "editingcore"
local files = require "trackfiles"
local input_ok, input = pcall(require, "mp.input")
local state, bypass, generation = core.defaults(), false, 0
local dialog, job, timer = false, nil, nil
local label = "@videoediting"
local function notice(s, seconds) mp.osd_message("Editing: "..s, seconds or 3) end
local function local_source()
  local p = mp.get_property("path")
  if not p or files.is_url(p) then return nil end
  p = utils.join_path(mp.get_property("working-directory", "."), p)
  local info = utils.file_info(p)
  return info and info.is_file and p or nil
end
local function video_ok()
  if not local_source() or not mp.get_property("video-params/w") then
    notice("Open a local video first"); return false
  end
  local gamma = mp.get_property("video-params/gamma", ""):lower()
  if gamma == "pq" or gamma == "hlg" or gamma == "st2084" then
    notice("HDR is not supported by this SDR editor", 5); return false
  end
  return true
end
local function remove()
  for _, f in ipairs(mp.get_property_native("vf") or {}) do
    if f.label == "videoediting" then mp.commandv("vf", "remove", label); return end
  end
end
local function apply(new, compare)
  local graph = core.graph(new)
  remove()
  if not compare and graph ~= "" then
    local ok, err = mp.commandv("vf", "add", label..":lavfi=["..graph.."]")
    if not ok then
      mp.msg.error(tostring(err))
      -- Restore last working preview, not other scripts' filters.
      local prev = core.graph(state)
      if not bypass and prev ~= "" then mp.commandv("vf","add",label..":lavfi=["..prev.."]") end
      notice("Filter unavailable; previous settings retained",5)
      return false
    end
  end
  state, bypass = new, compare
  return true
end
local function choose()
  if not input_ok or not input.select then notice("This mpv version does not support adjustment lists",5); return end
  local g = generation
  local items = {}
  for i,c in ipairs(core.controls) do items[i] = c[2]..": "..state[c[1]] end
  input.select({prompt="Editing - select adjustment",items=items,submit=function(i)
    if generation ~= g or not video_ok() then return end
    local c=core.controls[i]
    if not c then return end
    local values, names, selected = {}, {}, 1
    for n=c[3],c[4],c[5] do
      values[#values+1]=n; names[#names+1]=tostring(n)
      if math.abs(n-state[c[1]])<math.abs(values[selected]-state[c[1]]) then selected=#values end
    end
    input.select({prompt=c[2],items=names,default_item=selected,submit=function(j)
      if generation ~= g or not values[j] then return end
      local next_state=core.normalize(state); next_state[c[1]]=values[j]
      if apply(next_state,false) then notice(c[2]..": "..values[j]) end
    end})
  end})
end
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
  local source, exe, g = local_source(), ffmpeg_path(), generation
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
mp.register_script_message("editing-action",function(action)
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
  elseif action=="reset" then apply(core.defaults(),false);notice("Reset")
  elseif action=="export" then export() end
end)
mp.register_event("start-file",function()
  generation=generation+1
  remove();state=core.defaults();bypass=false
end)
mp.register_event("end-file",function() generation=generation+1;remove() end)
