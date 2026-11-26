-- Independent SDR grading model. No mpv/tracker dependency.
local M = {}
M.controls = {
  {"haze", "Dehaze", 0, 40, 2, 0},
  {"contrast", "Contrast", -30, 30, 5, 0},
  {"brightness", "Brightness", -20, 20, 2, 0},
  {"gamma", "Midtone gamma", -30, 30, 5, 0},
  {"saturation", "Saturation", -50, 50, 5, 0},
  {"shadows", "Shadows", -20, 20, 5, 0},
  {"highlights", "Highlights", -20, 20, 5, 0},
  {"warmth", "Warmth", -20, 20, 5, 0},
  {"clarity", "Local contrast / clarity", 0, 60, 5, 0},
  {"sharpness", "Sharpness", 0, 60, 5, 0},
  {"denoise", "Noise reduction", 0, 40, 5, 0},
  {"crf", "Export quality (lower CRF = better)", 14, 28, 1, 18},
}
function M.defaults()
  local s = {}
  for _, c in ipairs(M.controls) do s[c[1]] = c[6] end
  return s
end
function M.normalize(s)
  local out = M.defaults()
  if type(s) ~= "table" then return out end
  for _, c in ipairs(M.controls) do
    local n = tonumber(s[c[1]])
    if n and n == n and n ~= math.huge and n ~= -math.huge then
      out[c[1]] = math.floor(math.max(c[3], math.min(c[4], n)) + 0.5)
    end
  end
  return out
end
function M.preset(name)
  local s = M.defaults()
  if name == "light" then s.haze,s.saturation,s.clarity,s.sharpness=8,5,15,10
  elseif name == "moderate" then s.haze,s.saturation,s.clarity,s.sharpness,s.highlights=16,10,25,15,-5
  elseif name == "strong" then s.haze,s.saturation,s.clarity,s.sharpness,s.highlights=28,15,35,20,-10 end
  return s
end
local function fmt(n) return (string.format("%.4f", n):gsub(",", ".")) end
function M.graph(settings)
  local s = M.normalize(settings)
  local filters = {}
  if s.denoise > 0 then
    filters[#filters+1] = "hqdn3d=" .. fmt(s.denoise/8) .. ":" .. fmt(s.denoise/6) .. ":0:0"
  end
  -- Approximate neutral veiling light inversion, then independently grade.
  -- FFmpeg eq pivots contrast at middle grey. A negative brightness term
  -- offsets the raised black point instead of merely making highlights brighter.
  local t = 1 - s.haze/100
  local contrast = (1/t)*(1+s.contrast/100)
  local brightness = -0.5*(1/t-1)+s.brightness/100
  if s.haze ~= 0 or s.contrast ~= 0 or s.brightness ~= 0 or s.gamma ~= 0 or s.saturation ~= 0 then
    filters[#filters+1] = "eq=contrast="..fmt(contrast)..":brightness="..fmt(brightness)
      ..":gamma="..fmt(1+s.gamma/100)..":saturation="..fmt(1+s.saturation/100)
  end
  if s.shadows ~= 0 or s.highlights ~= 0 then
    filters[#filters+1] = "curves=all='0/0 0.25/"..fmt(0.25+s.shadows/100)
      .." 0.75/"..fmt(0.75+s.highlights/100).." 1/1'"
  end
  if s.warmth ~= 0 then
    local w = s.warmth/100
    filters[#filters+1] = "colorbalance=rs="..fmt(w/2)..":bs="..fmt(-w/2)
      ..":rm="..fmt(w)..":bm="..fmt(-w)..":rh="..fmt(w/2)..":bh="..fmt(-w/2)..":pl=1"
  end
  if s.clarity > 0 then filters[#filters+1] = "unsharp=13:13:"..fmt(s.clarity/40)..":5:5:0" end
  if s.sharpness > 0 then filters[#filters+1] = "unsharp=5:5:"..fmt(s.sharpness/30)..":5:5:0" end
  return table.concat(filters,",")
end
-- Separate output settings: the grading graph never depends on encoder selection.
M.quality_presets={
  {name="Maximum",value=14},{name="High",value=18},
  {name="Balanced",value=22},{name="Small file",value=26}
}
M.encoder_options={"auto","nvenc","qsv","amf","cpu"}
function M.export_settings(s)
  s=type(s)=="table" and s or {}
  local enc="auto"
  for _,v in ipairs(M.encoder_options) do if s.encoder==v then enc=v end end
  local gpu=tonumber(s.gpu)
  if not gpu or gpu~=gpu or gpu<0 or gpu>15 or gpu%1~=0 or enc~="nvenc" then gpu=-1 end
  return {encoder=enc,gpu=gpu,crf=M.normalize(s).crf}
end
function M.candidates(options)
  local s=M.export_settings(options)
  if s.encoder=="auto" then return {"nvenc","qsv","amf","cpu"} end
  return {s.encoder}
end
local function append(dst,src)
  for _,v in ipairs(src) do dst[#dst+1]=v end
end
function M.encoder_args(encoder,settings)
  local s=M.export_settings(settings)
  local q=tostring(s.crf)
  if encoder=="nvenc" then
    local a={"-c:v","h264_nvenc","-preset","p5","-rc","vbr","-cq",q,"-b:v","0"}
    if s.gpu>=0 then append(a,{"-gpu",tostring(s.gpu)}) end
    return a
  elseif encoder=="qsv" then
    return {"-c:v","h264_qsv","-preset","medium","-global_quality",q}
  elseif encoder=="amf" then
    return {"-c:v","h264_amf","-quality","quality","-rc","cqp","-qp_i",q,"-qp_p",q,"-qp_b",q}
  elseif encoder=="cpu" then
    return {"-c:v","libx264","-preset","fast","-crf",q}
  end
  error("Unknown editing encoder: "..tostring(encoder))
end
local function video_args(exe,source,settings,stream,encoder)
  local graph=M.graph(settings)
  return {exe,"-hide_banner","-nostdin","-loglevel","error","-n","-i",source,
    "-map",stream and ("0:"..tostring(stream)) or "0:V:0",
    "-vf",(graph~="" and graph.."," or "").."pad=ceil(iw/2)*2:ceil(ih/2)*2",
    "-pix_fmt",(encoder=="qsv" or encoder=="amf") and "nv12" or "yuv420p"}
end
function M.probe_args(exe,source,settings,stream,encoder,options)
  local args=video_args(exe,source,settings,stream,encoder)
  append(args,M.encoder_args(encoder,options))
  append(args,{"-an","-sn","-dn","-frames:v","3","-f","null","-"})
  return args
end
function M.export_args(exe,source,dest,settings,stream,encoder,options)
  assert(type(exe)=="string" and exe~="" and type(source)=="string" and source~=""
    and type(dest)=="string" and dest~="" and source~=dest,"invalid export paths")
  -- Preserve old callers' CPU default and CRF; UI always passes resolved options.
  options=options or {encoder="cpu",crf=M.normalize(settings).crf}
  local args=video_args(exe,source,settings,stream,encoder or "cpu")
  append(args,M.encoder_args(encoder or "cpu",options))
  append(args,{"-map","0:a?","-map_metadata","0","-c:a","aac","-b:a","192k",
    "-movflags","+faststart","-f","mp4",dest})
  return args
end
return M
