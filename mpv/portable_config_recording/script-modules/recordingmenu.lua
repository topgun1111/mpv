-- Recording top bar: shared Editing definitions and menu engine; no AI controls.
local mp=require "mp"
local utils=require "mp.utils"
local function shared(name)
  local ok,mod=pcall(require,name)
  if ok then return mod end
  return dofile(mp.command_native({"expand-path","~~/script-modules/"..name..".lua"}))
end
local menus=shared("trackmenu")
local editor=shared("editingui")
local files=shared("trackfiles")
local M={}
local editing
for _,m in ipairs(menus.MENUS) do if m.id=="editing" then editing=m;break end end
assert(editing,"Missing shared Editing menu")
-- Each mpv script has its own Lua VM.
menus.MENUS={
  {id="file",label="File",items={
    {cmd="open",label="Open file…",key="Ctrl+O"},
    {cmd="recent",label="Recent files…"},
    {sep=true},
    {cmd="close",label="Close video"},
    {cmd="quit",label="Exit",key="Q"},
  }},
  {id="view",label="View",items={
    {cmd="zoom_in",label="Zoom in",key="+"},
    {cmd="zoom_out",label="Zoom out",key="-"},
    {cmd="reset",label="Reset zoom / pan",key="0"},
    {sep=true},
    {cmd="rotate_left",label="Rotate left 90°"},
    {cmd="rotate_right",label="Rotate right 90°",key="K"},
    {cmd="fullscreen",label="Fullscreen",key="F"},
  }},
  {id="playback",label="Playback",items={
    {cmd="play_pause",label="Play / pause"},
    {cmd="slower",label="Slower",key="["},
    {cmd="faster",label="Faster",key="]"},
    {cmd="mute",label="Mute"},
  }},
  {id="record",label="Recording",items={
    {cmd="record",label="Prepare recording",key="R"},
    {cmd="record_pause",label="Start / pause / resume",key="Space"},
    {sep=true},
    {cmd="camera_export",label="Export camera recording…",key="S"},
  }},
  editing,
  {id="performance",label="Performance",items={
    {cmd="gpu_copy",label="GPU decoding (copy-back)"},
    {cmd="gpu_direct",label="Direct GPU decoding (fastest)"},
    {cmd="gpu_cpu",label="Software decoding"},
    {sep=true},
    {cmd="edit_preview_gpu",label="GPU editing preview (fast)"},
    {cmd="edit_preview_cpu",label="CPU editing preview (reduced)"},
    {sep=true},
    {cmd="sync_display",label="Smooth display sync"},
    {cmd="sync_audio",label="Standard audio sync"},
    {cmd="playback_stats",label="Playback diagnostics",key="I"},
  }},
}
function M.new(ctx)
  local self={}
  local ov=mp.create_osd_overlay("ass-events");ov.z=8
  local captured,dialog=false,false
  local recent={recent={}}
  local render,keys
  local function has_edit_filter()
    for _,filter in ipairs(mp.get_property_native("vf") or {}) do
      if filter.label=="videoediting" then return true end
    end
    return false
  end
  local function status(cmd)
    local s=ctx.state()
    local video=(mp.get_property_number("video-params/w",0) or 0)>0
    local busy=s.exporting or editor.busy() or dialog
    local idle=not s.recording and not busy
    if cmd=="open" or cmd=="quit" then return {enabled=idle} end
    if cmd=="recent" then return {enabled=idle and #recent.recent>0} end
    if cmd=="close" then return {enabled=idle and mp.get_property("path")~=nil} end
    if cmd=="fullscreen" then return {enabled=true,checked=mp.get_property_native("fullscreen")==true} end
    if cmd=="mute" then return {enabled=video,checked=mp.get_property_native("mute")==true} end
    if cmd=="gpu_copy" or cmd=="gpu_direct" or cmd=="gpu_cpu" then
      local mode=mp.get_property("hwdec","auto-copy")
      local target=({gpu_copy="auto-copy",gpu_direct="auto",gpu_cpu="no"})[cmd]
      return {enabled=idle and (cmd~="gpu_direct" or not has_edit_filter()),checked=mode==target}
    end
    if cmd=="sync_display" or cmd=="sync_audio" then
      local target=cmd=="sync_display" and "display-resample" or "audio"
      return {enabled=idle,checked=mp.get_property("video-sync")==target}
    end
    if cmd=="playback_stats" then return {enabled=video} end
    if cmd=="edit_cancel" then return {enabled=editor.busy()} end
    if cmd:match("^edit_") then return {enabled=video and idle} end
    if cmd=="record" then
      return {enabled=s.local_video and not busy,label=s.recording and "Stop recording" or "Prepare recording"}
    end
    if cmd=="record_pause" then
      return {enabled=s.recording and not busy,
        label=not s.started and "Start recording" or (s.running and "Pause recording" or "Resume recording")}
    end
    if cmd=="camera_export" then return {enabled=idle and s.saved} end
    if cmd=="rotate_left" or cmd=="rotate_right" then
      return {enabled=video and not busy and not (s.recording and s.started)}
    end
    if cmd=="play_pause" then
      return {enabled=video and not busy,label=mp.get_property_native("pause") and "Play" or "Pause"}
    end
    return {enabled=video and not busy}
  end
  local function remember()
    local path=mp.get_property("path")
    if not path or path=="" or files.is_url(path) then return end
    if not (path:match("^%a:[/\\]") or path:match("^[/\\]")) then
      path=utils.join_path(mp.get_property("working-directory","."),path)
    end
    local info=utils.file_info(path)
    if info and info.is_file then recent=files.add_recent(recent,path,false) end
    if render then render() end
  end
  local function choose(script)
    if dialog then return end
    dialog=true
    mp.command_native_async({name="subprocess",playback_only=false,capture_stdout=true,
      capture_stderr=true,args=files.ps_args(script)},function(ok,result)
      dialog=false
      if not ok or not result or result.status~=0 then
        mp.osd_message("File dialog failed",4)
      elseif status("open").enabled then
        local path=files.clean(result.stdout)
        if path then
          local info=utils.file_info(path)
          if info and info.is_file then mp.commandv("loadfile",path,"replace")
          else mp.osd_message("File no longer exists",4) end
        end
      end
      render()
    end)
  end
  local function action(cmd)
    if status(cmd).enabled==false then return end
    local name=cmd:match("^edit_(.+)$")
    if name then
      editor.action(name)
    elseif cmd=="gpu_copy" or cmd=="gpu_direct" or cmd=="gpu_cpu" then
      local target=({gpu_copy="auto-copy",gpu_direct="auto",gpu_cpu="no"})[cmd]
      if mp.get_property("hwdec")~=target then mp.set_property("hwdec",target) end
    elseif cmd=="sync_display" or cmd=="sync_audio" then
      mp.set_property("video-sync",cmd=="sync_display" and "display-resample" or "audio")
    elseif cmd=="playback_stats" then
      mp.commandv("script-binding","stats/display-stats-toggle")
      local dec=mp.get_property("hwdec-current","no")
      local drops=mp.get_property_number("frame-drop-count",0) or 0
      mp.osd_message("Decoder: "..dec.." | Dropped frames: "..drops,4)
    elseif cmd=="open" then choose(files.open_script(recent.dir))
    elseif cmd=="recent" then choose(files.recent_script(recent.recent))
    elseif cmd=="close" then editor.close();mp.commandv("stop")
    elseif cmd=="quit" then mp.commandv("quit")
    elseif cmd=="fullscreen" or cmd=="mute" then mp.commandv("cycle",cmd)
    else ctx.run(cmd) end
  end
  local engine=menus.new({run=action,state=status,responsive=true})
  local last_data,last_w,last_h
  render=function()
    local d=mp.get_property_native("osd-dimensions") or {}
    local w,h=d.w or 0,d.h or 0
    if w<=0 or h<=0 then
      if last_data~="" then ov.data="";ov:update();last_data="" end
      return
    end
    local hd=mp.get_property_number("display-hidpi-scale",1) or 1
    if hd~=engine.hd then engine.hd=hd;engine.W=0 end
    engine:resize(w,h);engine:relayout()
    local data=engine:render()
    if data~=last_data or w~=last_w or h~=last_h then
      last_data,last_w,last_h=data,w,h
      ov.res_x,ov.res_y=w,h;ov.data=data;ov:update()
    end
  end
  -- Only capture navigation keys while a drop-down is open.
  local keymap={LEFT="left",RIGHT="right",UP="up",DOWN="down",ENTER="enter",ESC="esc"}
  local key_open=false
  keys=function()
    local opened=engine:is_open()
    if key_open==opened then return end
    key_open=opened
    for key,cmd in pairs(keymap) do
      local id="rec-menu-"..key
      if opened then
        local k=cmd
        mp.add_forced_key_binding(key,id,function()
          engine:key(k);render();keys()
        end)
      else mp.remove_key_binding(id) end
    end
  end
  function self.hud_top()
    return engine.bh+math.max(4,math.floor(8*engine.hd))
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
    if not pos or not pos.x or (e~="down" and e~="press") then return false end
    if engine:over(pos.x,pos.y) or engine:is_open() then
      if engine:click(pos.x,pos.y) then
        captured=e=="down";render();keys();return true
      end
      -- Dismissing a dropdown must not start an unintended camera drag.
      captured=e=="down";render();keys();return true
    end
    if editor.pointer(ev,pos) then captured=e=="down";return true end
    return false
  end
  function self.busy() return dialog or editor.busy() end
  function self.close_editor() editor.close();engine:close();render();keys() end
  local vw,vh
  mp.observe_property("osd-dimensions","native",function(_,d)
    d=d or {}
    if d.w~=vw or d.h~=vh then vw,vh=d.w,d.h;render() end
  end)
  mp.observe_property("display-hidpi-scale","number",render)
  mp.observe_property("pause","native",render)
  mp.observe_property("fullscreen","native",render)
  mp.observe_property("mute","native",render)
  mp.register_event("file-loaded",remember)
  mp.register_event("end-file",function() engine:close();render();keys() end)
  mp.add_key_binding("F10","editing-menu",function() engine:key("f10");render();keys() end)
  mp.add_key_binding("Ctrl+o","rec-open-file",function() action("open");render() end)
  mp.register_script_message("editing-action",function(name) action("edit_"..name);render() end)
  mp.register_script_message("recording-menu-action",function(cmd)
    -- Dispatch only declared commands, so unknown names cannot reach camera callbacks.
    for _,m in ipairs(menus.MENUS) do
      for _,it in ipairs(m.items) do
        if it.cmd==cmd then action(cmd);render();return end
      end
    end
  end)
  render()
  return self
end
return M
