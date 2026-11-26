-- Fast SDR preview only. The export pipeline keeps the original full-resolution FFmpeg graph.
local mp=require "mp"
local utils=require "mp.utils"
local M={}
local prefix="takipli_grade/"
local names={"haze","contrast","brightness","gamma","saturation","shadows","highlights",
  "warmth","clarity","sharpness","denoise"}
local active_path,cached_path
local function shader_path()
  if cached_path then return cached_path end
  local path=mp.command_native({"expand-path","~~/script-modules/takipli_grade.glsl"})
  if type(path)=="string" then
    local info=utils.file_info(path)
    if info and info.is_file then cached_path=path;return path end
  end
end
function M.supported()
  local vo=mp.get_property("current-vo")
  return (vo=="gpu" or vo=="gpu-next") and
    mp.get_property_native("options/glsl-shader-opts")~=nil and shader_path()~=nil
end
local function read_opts()
  local old=mp.get_property_native("options/glsl-shader-opts") or {}
  local next={}
  for k,v in pairs(old) do if k:sub(1,#prefix)~=prefix then next[k]=v end end
  return next
end
local function write_opts(opts)
  if next(opts) then return mp.set_property_native("options/glsl-shader-opts",opts) end
  return mp.set_property("options/glsl-shader-opts","")
end
local function paths()
  return mp.get_property_native("options/glsl-shaders") or {}
end
local function contains(list,path)
  for _,p in ipairs(list) do if p==path then return true end end
  return false
end
function M.active()
  return active_path~=nil and contains(paths(),active_path)
end
function M.remove()
  if not active_path then return true end
  local keep={}
  for _,p in ipairs(paths()) do if p~=active_path then keep[#keep+1]=p end end
  local ok,err
  if #keep>0 then ok,err=mp.set_property_native("options/glsl-shaders",keep)
  else ok,err=mp.set_property("options/glsl-shaders","") end
  if not ok then return false,err end
  active_path=nil
  return write_opts(read_opts())
end
function M.apply(s)
  local path=active_path or shader_path()
  if not path then return false,"preview shader not found" end
  local previous=mp.get_property_native("options/glsl-shader-opts") or {}
  local opts=read_opts()
  for _,name in ipairs(names) do
    opts[prefix.."tg_"..name]=(string.format("%.4f",(s[name] or 0)/100):gsub(",","."))
  end
  local ok,err=write_opts(opts)
  if not ok then return false,err end
  local list=paths()
  if not contains(list,path) then
    local copy={}
    for _,p in ipairs(list) do copy[#copy+1]=p end
    copy[#copy+1]=path
    ok,err=mp.set_property_native("options/glsl-shaders",copy)
    if not ok then write_opts(previous);return false,err end
  end
  active_path=path
  return true
end
return M
