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
    filters[#filters+1] = "hqdn3d=" .. fmt(s.denoise/20) .. ":" .. fmt(s.denoise/15) .. ":0:0"
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
  if s.clarity > 0 then filters[#filters+1] = "unsharp=13:13:"..fmt(s.clarity/100)..":5:5:0" end
  if s.sharpness > 0 then filters[#filters+1] = "unsharp=5:5:"..fmt(s.sharpness/100)..":5:5:0" end
  return table.concat(filters,",")
end
function M.export_args(exe, source, dest, settings, stream)
  assert(type(exe)=="string" and exe~="" and type(source)=="string" and source~=""
    and type(dest)=="string" and dest~="" and source~=dest, "invalid export paths")
  local s = M.normalize(settings)
  local graph = M.graph(s)
  local args = {exe,"-hide_banner","-nostdin","-loglevel","error","-n","-i",source,
    "-map",stream and ("0:"..tostring(stream)) or "0:V:0","-map","0:a?","-map_metadata","0",
    "-vf",(graph~="" and graph.."," or "").."pad=ceil(iw/2)*2:ceil(ih/2)*2",
    "-c:v","libx264","-preset","fast","-crf",tostring(s.crf),"-pix_fmt","yuv420p",
    "-c:a","aac","-b:a","192k","-movflags","+faststart","-f","mp4",dest}
  return args
end
return M
