-- Real packaged recording script, not a separate instance of the editor.
local mp=require "mp"
local function owns()
  for _,f in ipairs(mp.get_property_native("vf") or {}) do
    if f.label=="videoediting" then return true end
  end
  return false
end
local function fail(msg) mp.msg.error(msg);mp.commandv("quit",1) end
local function check()
  mp.commandv("script-message-to","kayit","editing-action","moderate")
  mp.add_timeout(.5,function()
    if not owns() then fail("Recording editing menu did not install preset");return end
    mp.commandv("script-message-to","kayit","editing-action","adjust")
    mp.add_timeout(.3,function()
      mp.commandv("script-message-to","kayit","editing-action","reset")
      mp.add_timeout(.4,function()
        if owns() then fail("Recording editor reset failed");return end
        mp.commandv("script-message-to","kayit","recording-menu-action","zoom_in")
        mp.add_timeout(.2,function()
          if (mp.get_property_number("video-zoom",0) or 0)<=0 then
            fail("Recording View menu zoom failed");return
          end
          mp.commandv("script-message-to","kayit","recording-menu-action","reset")
          mp.add_timeout(.2,function()
            if mp.get_property_number("video-zoom",0)~=0 then fail("View reset failed");return end
            mp.commandv("script-message-to","kayit","recording-menu-action","rotate_right")
            mp.add_timeout(.2,function()
              if mp.get_property_number("video-rotate",0)~=90 then fail("Rotate failed");return end
              mp.commandv("script-message-to","kayit","recording-menu-action","mute")
              mp.add_timeout(.2,function()
                if not mp.get_property_native("mute") then fail("Mute failed");return end
                mp.msg.info("RECORDING_EDITING_OK");mp.commandv("quit",0)
              end)
            end)
          end)
        end)
      end)
    end)
  end)
end
mp.register_event("file-loaded",function() mp.add_timeout(.5,check) end)
