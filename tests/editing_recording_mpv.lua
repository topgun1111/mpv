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
        mp.msg.info("RECORDING_EDITING_OK");mp.commandv("quit",0)
      end)
    end)
  end)
end
mp.register_event("file-loaded",function() mp.add_timeout(.5,check) end)
