-- Run from repository root: texlua tests/lua_harness_editing.lua
package.path = "mpv/portable_config/script-modules/?.lua;" .. package.path
assert(loadfile("mpv/portable_config/scripts/videoediting.lua"))
local E = require "editingcore"
assert(E.graph(E.defaults())=="")
assert(E.graph(nil)=="")
assert(E.normalize({haze=999,crf=-1,gamma=0/0}).haze==40)
assert(E.normalize({haze=999,crf=-1,gamma=0/0}).crf==14)
assert(E.normalize({haze=999,crf=-1,gamma=0/0}).gamma==0)
for _, p in ipairs({"light","moderate","strong"}) do
  local s=E.preset(p)
  local g=E.graph(s)
  assert(g:find("eq=",1,true) and g:find("unsharp=",1,true))
  local a=E.export_args("ffmpeg","a b.mp4","out.mp4",s,2)
  local found=false
  for i,v in ipairs(a) do if v=="-vf" then assert(a[i+1]:sub(1,#g)==g);found=true end end
  assert(found and a[#a]=="out.mp4" and a[6]=="-n")
  print(g)
end
assert(not pcall(E.export_args,"ffmpeg","a.mp4","a.mp4",{},nil))
print(E.graph({haze=40,contrast=30,brightness=-20,gamma=30,saturation=50,shadows=20,highlights=-20,warmth=-20,clarity=60,sharpness=60,denoise=40}))
