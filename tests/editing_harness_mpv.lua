local real=require "mp"
local ok,err=pcall(dofile,assert(os.getenv("EDITING_HARNESS")))
if not ok then real.msg.error(tostring(err));real.commandv("quit",1)
else real.msg.info("EDITING_UI_OK");real.commandv("quit",0) end
