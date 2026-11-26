-- Run from repository root: texlua tests/lua_harness_editing.lua
package.path = "mpv/portable_config/script-modules/?.lua;" .. package.path
assert(loadfile("mpv/portable_config/script-modules/editingui.lua"))
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

-- Encoder selection is independent from the tracking GPU and the color graph.
local function value(args,key)
  for i,v in ipairs(args) do if v==key then return args[i+1] end end
end
local settings=E.preset("moderate")
local options=E.export_settings({encoder="nvenc",gpu=1,crf=14})
assert(options.encoder=="nvenc" and options.gpu==1 and options.crf==14)
local nv=E.export_args("ffmpeg","source.mp4","out.mp4",settings,0,"nvenc",options)
assert(value(nv,"-c:v")=="h264_nvenc" and value(nv,"-gpu")=="1" and value(nv,"-cq")=="14")
assert(value(nv,"-crf")==nil and value(nv,"-vf"):find(E.graph(settings),1,true)==1)
local qsv=E.encoder_args("qsv",{crf=22})
assert(value(qsv,"-c:v")=="h264_qsv" and value(qsv,"-global_quality")=="22")
local amf=E.encoder_args("amf",{crf=26})
assert(value(amf,"-c:v")=="h264_amf" and value(amf,"-qp_i")=="26")
local cpu=E.encoder_args("cpu",{crf=18})
assert(value(cpu,"-c:v")=="libx264" and value(cpu,"-crf")=="18")
assert(table.concat(E.candidates({encoder="auto"}),",")=="nvenc,qsv,amf,cpu")
assert(table.concat(E.candidates({encoder="nvenc"}),",")=="nvenc")
assert(E.export_settings({encoder="garbage",gpu=99,crf=-1}).encoder=="auto")
assert(E.export_settings({encoder="nvenc",gpu=99,crf=-1}).gpu==-1)
assert(E.export_settings({encoder="cpu",gpu=0,crf=99}).crf==28)
assert(E.export_settings({encoder="cpu",gpu=0}).gpu==-1)
local probe=E.probe_args("ffmpeg","source.mp4",settings,0,"nvenc",options)
assert(value(probe,"-frames:v")=="3" and probe[#probe]=="-" and value(probe,"-gpu")=="1")
