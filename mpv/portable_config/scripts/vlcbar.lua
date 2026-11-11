-- vlcbar.lua: OSC çubuğunun üstünde sağ altta Hız -/+, Altyazı (CC) ve Liste düğmeleri.
-- Fare hareketinde görünür, 2.5 sn sonra gizlenir. Sol tıkı YALNIZ düğme üstündeyken yakalar
-- (track.lua ile aynı yöntem), başka yerde mpv/track.lua davranışı bozulmaz.
local BAR_H = 95      -- OSC alt çubuğunun üstünde bırakılan boşluk (px, ölçeksiz); çakışırsa artır
local HIDE_S = 2.5
local ov = mp.create_osd_overlay("ass-events")
local st = { vis = false, hover = nil, rects = {}, list = {}, bound = false }

local function dims()
  local w = mp.get_property_number("osd-width", 0)
  local h = mp.get_property_number("osd-height", 0)
  if w <= 0 or h <= 0 then
    local d = mp.get_property_native("osd-dimensions") or {}
    w, h = d.w or 0, d.h or 0
  end
  return w, h
end

local function sub_on() local s = mp.get_property("sid"); return s ~= nil and s ~= "no" end
local function speed_step(d)
  local s = (mp.get_property_number("speed", 1) or 1) + d
  s = math.min(4, math.max(0.1, math.floor(s * 10 + 0.5) / 10))
  mp.set_property_number("speed", s)
  mp.osd_message(string.format("Hız: %.1fx", s), 1.5)
end

local function buttons()
  return {
    { w = 1,   label = "-", act = function() speed_step(-0.1) end },
    { w = 2,   label = string.format("%.1fx", mp.get_property_number("speed", 1) or 1),
      act = function() mp.set_property_number("speed", 1); mp.osd_message("Hız: 1.0x", 1.5) end },
    { w = 1,   label = "+", act = function() speed_step(0.1) end },
    { w = 1.4, label = "CC", dim = not sub_on(), act = function() mp.command("osd-auto cycle sub") end },
    { w = 2,   label = "Liste", act = function() mp.command("show-text ${playlist} 5000") end },
  }
end

local function layout()
  local W, H = dims()
  if W <= 0 or H <= 0 then st.rects, st.list = {}, {}; return W, H end
  local sc = mp.get_property_bool("fullscreen") and 1.4 or 1.2
  local bh = math.max(30, math.floor(H * 0.05))
  local gap = math.floor(bh * 0.2)
  local list, total = buttons(), -gap
  for _, b in ipairs(list) do b.pw = math.floor(bh * b.w); total = total + b.pw + gap end
  local x, y = W - 16 - total, H - math.floor(BAR_H * sc) - bh
  st.rects, st.list = {}, list
  for i, b in ipairs(list) do
    st.rects[i] = { x = x, y = y, w = b.pw, h = bh }
    x = x + b.pw + gap
  end
  return W, H
end

local function render()
  if not st.vis then ov:remove(); return end
  local W, H = layout()
  if W <= 0 then return end
  ov.res_x, ov.res_y = W, H
  local out = {}
  for i, r in ipairs(st.rects) do
    local b, on = st.list[i], (i == st.hover)
    out[#out + 1] = string.format(
      "{\\an7\\pos(%d,%d)\\bord0\\shad0\\1c&H%s&\\1a&H%s&\\p1}m 0 0 l %d 0 %d %d 0 %d{\\p0}",
      r.x, r.y, on and "0088FF" or "202020", on and "10" or "50", r.w, r.w, r.h, r.h)
    out[#out + 1] = string.format("{\\an5\\pos(%d,%d)\\bord0\\shad0\\fs%d\\1c&H%s&}%s",
      math.floor(r.x + r.w / 2), math.floor(r.y + r.h / 2), math.floor(r.h * 0.5), b.dim and "909090" or "FFFFFF", b.label)
  end
  ov.data = table.concat(out, "\n")
  ov:update()
end

local function press(ev)
  if ev and ev.event and ev.event ~= "down" and ev.event ~= "press" then return end
  local b = st.hover and st.list[st.hover]
  if b then b.act() end
  render()
end

local KEYS = { "MBTN_LEFT", "MBTN_LEFT_DBL" } -- çift tıkın 2. tıkı da aynı işi görsün (track/dblclick duraklatmasın)
local function sync()
  local want = st.vis and st.hover ~= nil
  if want and not st.bound then
    for _, k in ipairs(KEYS) do mp.add_forced_key_binding(k, "vlcbar-" .. k, press, { complex = true }) end
    st.bound = true
  elseif not want and st.bound then
    for _, k in ipairs(KEYS) do mp.remove_key_binding("vlcbar-" .. k) end
    st.bound = false
  end
end

local timer
timer = mp.add_timeout(HIDE_S, function()
  if st.hover then timer:resume(); return end -- düğme üstündeyken gizleme
  st.vis = false; render(); sync()
end)
timer:kill()

mp.observe_property("mouse-pos", "native", function(_, pos)
  if not pos or not pos.hover then
    st.vis, st.hover = false, nil
  else
    st.vis = true
    layout()
    st.hover = nil
    for i, r in ipairs(st.rects) do
      if pos.x >= r.x and pos.x <= r.x + r.w and pos.y >= r.y and pos.y <= r.y + r.h then st.hover = i end
    end
    timer:kill(); timer:resume()
  end
  render(); sync()
end)

for _, p in ipairs({ "speed", "sid", "fullscreen", "osd-width", "osd-height" }) do
  mp.observe_property(p, "native", function() if st.vis then render() end end)
end
