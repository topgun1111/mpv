-- GPU option routing, preservation of other shaders/options and neutral reset.
package.path="mpv/portable_config/script-modules/?.lua;"..package.path
local props={
  ["current-vo"]="gpu",
  ["options/glsl-shaders"]={"other.glsl"},
  ["options/glsl-shader-opts"]={["other/value"]="7"},
}
local writes=0
local mp={
  get_property=function(k) return props[k] end,
  get_property_native=function(k) return props[k] end,
  set_property_native=function(k,v) props[k]=v;writes=writes+1;return true end,
  set_property=function(k,v) assert(v=="");props[k]={};return true end,
  command_native=function() return "takipli_grade.glsl" end,
}
package.loaded.mp=mp
package.loaded["mp.utils"]={file_info=function() return {is_file=true} end}
local G=require "editinggpu"
local C=require "editingcore"
assert(G.supported())
assert(G.apply(C.preset("moderate")) and G.active())
assert(#props["options/glsl-shaders"]==2)
local opts=props["options/glsl-shader-opts"]
assert(tonumber(opts["takipli_grade/tg_haze"])==.16 and opts["other/value"]=="7")
local old=writes
assert(G.apply(C.preset("strong")) and G.active())
assert(writes==old+1,"changing uniforms should not reload shader list")
assert(tonumber(props["options/glsl-shader-opts"]["takipli_grade/tg_haze"])==.28)
assert(G.remove() and not G.active())
assert(#props["options/glsl-shaders"]==1 and props["options/glsl-shaders"][1]=="other.glsl")
assert(props["options/glsl-shader-opts"]["other/value"]=="7")
assert(props["options/glsl-shader-opts"]["takipli_grade/tg_haze"]==nil)
props["current-vo"]="null";assert(not G.supported())
print("EDITING_GPU_OK")
