-- Export notifications: independent foreground OSD, no input bindings or video filters.
local mp=require "mp"
local M={}
local ov,message,timer,serial,last
local watching=false
local function render()
  if not message or not ov then return end
  local d=mp.get_property_native("osd-dimensions") or {}
  local w,h=math.floor(d.w or 0),math.floor(d.h or 0)
  if w<=0 or h<=0 then
    if last~="" then ov.data="";ov:update();last="" end
    return
  end
  local dpi=math.max(.75,math.min(3,mp.get_property_number("display-hidpi-scale",1) or 1))
  local fs=math.max(12,math.min(42,math.floor(20*dpi),math.floor(w/16),math.floor(h/10)))
  local margin=math.max(8,math.floor(fs*.65))
  local y=math.max(math.floor(h*.5),h-math.max(36,math.floor(h*.075),math.floor(fs*1.9)))
  -- Keep text inside the client width; libass smart-wrap handles ordinary long messages.
  local escaped=mp.command_native({"escape-ass",message})
  if type(escaped)~="string" then return end
  -- Split extremely long filenames/paths so an unbroken token cannot run off the screen.
  local maxchars=math.max(10,math.floor((w-2*margin)/(fs*.68)))
  local parts={}
  local count=0
  for ch in message:gmatch("[%z\1-\127\194-\244][\128-\191]*") do
    if ch=="\n" then count=0;parts[#parts+1]="\n"
    else
      if count>=maxchars then parts[#parts+1]="\n";count=0 end
      parts[#parts+1]=ch;count=count+1
    end
  end
  local lines={}
  local wrapped=table.concat(parts)
  local maxlines=math.max(1,math.min(4,math.floor((y-h*.25)/(fs*1.3))))
  for line in (wrapped.."\n"):gmatch("(.-)\n") do
    if #lines>=maxlines then
      lines[#lines]=lines[#lines].."…"
      break
    end
    lines[#lines+1]=mp.command_native({"escape-ass",line}) or ""
  end
  escaped=table.concat(lines,"\\N")
  -- \an2 anchors the bottom of the message above the transport bar.
  -- Opaque dark outline provides contrast without a hit-testable panel.
  local data=string.format("{\\an2\\pos(%d,%d)\\fnSegoe UI\\fs%d\\q2\\bord%d\\shad0\\1c&HFFFFFF&\\3c&H202020&}%s",
    math.floor(w/2),y,fs,math.max(3,math.floor(fs*.22)),escaped)
  local key=w.."x"..h..":"..data
  if key~=last then
    last=key;ov.res_x,ov.res_y=w,h;ov.data=data;ov:update()
  end
end
function M.clear()
  serial=(serial or 0)+1
  if timer then timer:kill();timer=nil end
  message=nil
  if ov then ov.data="";ov:update();last="" end
end
function M.show(text,seconds)
  text=tostring(text or "")
  if text=="" then M.clear();return end
  local vo=mp.get_property("current-vo")
  -- Preserve native OSD in headless/non-graphical contexts.
  if not vo or vo=="null" then mp.osd_message(text,(seconds and seconds>0) and seconds or 3);return end
  if not ov then
    ov=mp.create_osd_overlay("ass-events");ov.z=40
  end
  if not watching then
    watching=true
    mp.observe_property("osd-dimensions","native",render)
    mp.observe_property("display-hidpi-scale","number",render)
  end
  if timer then timer:kill();timer=nil end
  serial=(serial or 0)+1
  local ticket=serial
  message=text:gsub("\r\n","\n"):gsub("\r","\n")
  render()
  seconds=seconds==nil and 3 or seconds
  if seconds>0 then
    timer=mp.add_timeout(seconds,function()
      if serial==ticket then timer=nil;M.clear() end
    end)
  end
end
return M
