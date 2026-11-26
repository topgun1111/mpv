-- Native Windows VO integration: keep an existing window across replacement clips and rotation.
local mp=require "mp"
local first=assert(os.getenv("WINDOW_LANDSCAPE"))
local second=assert(os.getenv("WINDOW_PORTRAIT"))
local initial
local phase=0
local shotdir=assert(os.getenv("WINDOW_SHOTS"))
local function shader_active()
  for _,p in ipairs(mp.get_property_native("options/glsl-shaders") or {}) do
    if p:find("takipli_grade.glsl",1,true) then return true end
  end
  return false
end
local function cpu_active()
  for _,f in ipairs(mp.get_property_native("vf") or {}) do if f.label=="videoediting" then return true end end
  return false
end
local function dims()
  local d=mp.get_property_native("osd-dimensions") or {}
  if d.w and d.h and d.w>0 and d.h>0 then return {w=d.w,h=d.h} end
end
local function fail(msg) mp.msg.error("WINDOW_GEOMETRY_FAILED "..msg);mp.commandv("quit",1) end
local function same(tag)
  local d=dims()
  if not d or math.abs(d.w-initial.w)>2 or math.abs(d.h-initial.h)>2 then
    fail(tag.." changed viewport from "..initial.w.."x"..initial.h.." to "..(d and d.w.."x"..d.h or "nil"))
    return false
  end
  mp.msg.info("WINDOW_GEOMETRY_STABLE "..tag.." "..d.w.."x"..d.h)
  return true
end
mp.register_event("file-loaded",function()
  mp.add_timeout(.8,function()
    if phase==1 then
      if not same("landscape") then return end
      if mp.get_property_number("video-rotate",0)~=0 then fail("landscape inherited rotation");return end
      local function rotate_first()
        mp.commandv("script-message-to","kayit","recording-menu-action","rotate_right")
        mp.add_timeout(.8,function()
          if mp.get_property_number("video-rotate",0)~=90 then fail("first rotation");return end
          if not same("first rotation") then return end
          phase=2;mp.commandv("loadfile",second,"replace")
        end)
      end
      local presets={{"light",.08,"light"},{"moderate",.16,"after"},{"strong",.28,"strong"}}
      local function shot(name)
        if not mp.commandv("screenshot-to-file",shotdir.."/"..name..".png","window") then
          fail("screenshot failed: "..name);return false
        end
        return true
      end
      local function preset(i)
        local p=presets[i]
        mp.commandv("script-message-to","kayit","editing-action",p[1])
        mp.add_timeout(1.2,function()
          if not shader_active() or cpu_active() then fail(p[1].." GPU preview not active");return end
          local opts=mp.get_property_native("options/glsl-shader-opts") or {}
          if tonumber(opts["takipli_grade/tg_haze"])~=p[2] then
            fail(p[1].." GPU parameters missing");return
          end
          if mp.get_property("options/hwdec")~="auto" then fail("GPU preview changed decoder");return end
          if not shot(p[3]) then return end
          if i<#presets then preset(i+1);return end
          -- Compare and reset before playback so all screenshots show the identical source frame.
          mp.commandv("script-message-to","kayit","editing-action","reset")
          mp.add_timeout(.8,function()
            if shader_active() or cpu_active() then fail("GPU preview reset failed");return end
            if not shot("reset") then return end
            mp.msg.info("GPU_PREVIEW_OK")
            mp.commandv("script-message-to","kayit","editing-action","strong")
            mp.add_timeout(.8,function()
              if not shader_active() or cpu_active() then fail("strong GPU preview missing");return end
              local t=mp.get_property_number("time-pos",0) or 0
              mp.set_property("pause","no")
              mp.add_timeout(.6,function()
                if (mp.get_property_number("time-pos",0) or 0)-t<.2 then
                  fail("GPU preview playback did not advance");return
                end
                mp.set_property("pause","yes")
                mp.commandv("script-message-to","kayit","editing-action","reset")
                mp.add_timeout(.4,rotate_first)
              end)
            end)
          end)
        end)
      end
      if shot("before") then preset(1) end
    elseif phase==2 then
      if not same("portrait") then return end
      if mp.get_property_number("video-rotate",0)~=0 then fail("portrait inherited rotation");return end
      mp.commandv("script-message-to","kayit","recording-menu-action","rotate_right")
      mp.add_timeout(.8,function()
        if mp.get_property_number("video-rotate",0)~=90 then fail("rotation action");return end
        if not same("rotation") then return end
        phase=3;mp.commandv("loadfile",first,"replace")
      end)
    elseif phase==3 and same("reopen") then
      if mp.get_property_number("video-rotate",0)~=0 then fail("reopen inherited rotation");return end
      mp.msg.info("WINDOW_GEOMETRY_OK");mp.commandv("quit",0)
    end
  end)
end)
local attempts=0
local function wait_window()
  local d=dims()
  if d then
    initial=d
    mp.msg.info("WINDOW_GEOMETRY_AVAILABLE "..d.w.."x"..d.h)
    phase=1;mp.commandv("loadfile",first,"replace")
  else
    attempts=attempts+1
    if attempts>=50 then mp.msg.warn("WINDOW_GEOMETRY_UNAVAILABLE");mp.commandv("quit",2)
    else mp.add_timeout(.2,wait_window) end
  end
end
mp.add_timeout(.2,wait_window)
