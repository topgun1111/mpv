-- Takipli Oynat: «Tracker» paneli (L tuşu / üst menüde «Tracker» sekmesi). SAF mantık: `mp`'ye dokunmaz,
-- texlua ile test edilir. track.lua şunu verir:
--   ctx = { state = function() -> st, run = function(act, a, b) }
--   st  = { enabled, mode, part, source, add_mode, offline, hud, cfg }   (cfg: Python `track-cfg` özeti ya da nil)
-- Modlar: auto (tık = nesne/eklem, sürükle = alan) | point (yalnız tık) | rect (yalnız alan) | body (vücut parçası).
-- Çizim: ASS (libass) yuvarlak köşeli kartlar; yerleşim tasarım birimiyle (u) yapılıp pencereye ölçeklenir.
local M = {}

local DW, PAD, COLW, COLGAP = 918, 18, 430, 22 -- kart genişliği (u), kenar boşluğu, sütun genişliği, sütun arası

M.MODES = {
  { id = "auto", label = "Otomatik", sub = "tık + sürükle", icon = "spark",
    desc = "Sağ tık nesne/eklem, sağ tuşla sürükle alan seçer." },
  { id = "point", label = "Nokta", sub = "tek tık", icon = "ring",
    desc = "Sağ tık: tıklanan noktadaki nesneyi takip eder." },
  { id = "rect", label = "Dikdörtgen", sub = "alan çiz", icon = "frame",
    desc = "Sağ tuşu basılı tutup sürükle: seçilen alanı takip eder." },
  { id = "body", label = "Vücut", sub = "parça", icon = "person",
    desc = "Kişiye sağ tık: aşağıda seçili vücut parçası takip edilir." },
}
-- Sıra/adlar track.lua PARTS ile aynı (testle denetlenir)
M.PARTS = {
  { "person", "Tüm kişi" }, { "head", "Baş" }, { "torso", "Gövde" },
  { "left_arm", "Sol kol" }, { "right_arm", "Sağ kol" }, { "left_leg", "Sol bacak" },
  { "right_leg", "Sağ bacak" }, { "legs", "Bacaklar" }, { "left_foot", "Sol ayak" },
  { "right_foot", "Sağ ayak" }, { "feet", "Ayaklar" }, { "hands", "Eller" },
}
-- Sayısal ayarlar: anahtar Python settings.py ile aynı (fill/speed/lead = track-setting; diğerleri track-option)
M.STEPS = {
  { "fill", "Doluluk" }, { "speed", "Tepki hızı" }, { "lead", "Öngörü" },
  { "hold", "Kayıp bekleme" }, { "zoomout", "Zoom-out süresi" }, { "memory", "Kare dışı hafıza" },
  { "pbox", "Nokta kutusu" }, { "pscore", "Nokta hassasiyeti" }, { "kpconf", "Eklem güveni" },
}
M.FLAGS = {
  { "kp_world", "Kamera telafisi" }, { "kp_filter", "Eklem süzgeci" },
  { "kp_robust", "Sağlam parça kutusu" }, { "kp_reacq_single", "Tek kişide yeniden bağla" },
  { "cut_detect", "Çekim kesmesi" }, { "ui_hud", "Durum etiketi" },
}
M.SOURCES = { { "auto", "Otomatik" }, { "live", "Canlı" }, { "scanned", "Taranmış iz" } }

local function nchars(s)
  local n = 0
  for _ in s:gmatch("[^\128-\191]") do n = n + 1 end
  return n
end
M.nchars = nchars

local function inside(r, x, y) return r and x >= r.x and x < r.x + r.w and y >= r.y and y < r.y + r.h end

-- ---- Saf yerleşim -----------------------------------------------------------------------------
-- W,H pencere pikseli; top: üstteki menü çubuğu yüksekliği. Döner { s, card, items, widgets }.
-- items: çizim listesi (sıralı); widgets: tıklanabilir öğeler (items'ın alt kümesi, klavye sırası).
function M.layout(W, H, st, top)
  st = st or {}
  local cfg = st.cfg
  top = top or 0
  local s = math.min(1.6, (W - 24) / DW, (H - top - 16) / 560)
  local items, widgets = {}, {}
  local ox, oy -- kart başlangıcı (hesaplama sonunda yerleşir)
  local function add(it, widget)
    items[#items + 1] = it
    if widget then it.wi = #widgets + 1; widgets[#widgets + 1] = it end
    return it
  end
  -- tasarım birimi koordinatı (kart içi) -> kayıt; piksele sonra çevrilir
  local function rect(k, x, y, w, h, f) f = f or {}; f.k, f.x, f.y, f.w, f.h = k, x, y, w, h; return f end

  -- Başlık
  add(rect("text", PAD, PAD + 18, 0, 0, { s = "Tracker", fs = 22, bold = true, col = "text", an = 4 }))
  add(rect("text", PAD + 96, PAD + 21, 0, 0, { s = "izleme modları ve ayarları", fs = 12, col = "dim", an = 4 }))
  add(rect("pill", DW - PAD - 28 - 10 - 104, PAD + 4, 104, 28,
    { act = "toggle", on = st.enabled, s = st.enabled and "Takip AÇIK" or "Takip KAPALI" }), true)
  add(rect("btn", DW - PAD - 28, PAD + 4, 28, 28, { act = "close", s = "✕", variant = "ghost" }), true)
  add(rect("line", PAD, PAD + 46, DW - PAD * 2, 1))

  local y0 = PAD + 60
  -- ---- Sol sütun: mod, parça, takip, kısayol
  local x, y = PAD, y0
  add(rect("label", x, y, 0, 0, { s = "MOD" }))
  y = y + 22
  local cw, gap = math.floor((COLW - 3 * 8) / 4), 8
  for i, m in ipairs(M.MODES) do
    add(rect("mode", x + (i - 1) * (cw + gap), y, cw, 92,
      { act = "mode", a = m.id, sel = (st.mode == m.id), s = m.label, sub = m.sub, icon = m.icon }), true)
  end
  y = y + 92 + 8
  local cur = st.mode or "auto"
  for _, m in ipairs(M.MODES) do
    if m.id == cur then add(rect("text", x + 2, y + 8, 0, 0, { s = m.desc, fs = 12, col = "dim", an = 4 })) end
  end
  y = y + 26 + 10
  add(rect("label", x, y, 0, 0, { s = "VÜCUT PARÇASI" }))
  y = y + 22
  local cx, cy = x, y
  for _, p in ipairs(M.PARTS) do
    local w = math.floor(nchars(p[2]) * 12 * 0.58 + 22)
    if cx > x and cx + w > x + COLW then cx, cy = x, cy + 26 + 6 end
    add(rect("chip", cx, cy, w, 26,
      { act = "part", a = p[1], sel = (st.mode == "body" and st.part == p[1]), s = p[2] }), true)
    cx = cx + w + 6
  end
  y = cy + 26 + 12
  add(rect("label", x, y, 0, 0, { s = "TAKİP" }))
  y = y + 22
  local bw = math.floor((COLW - 2 * 8) / 3)
  add(rect("btn", x, y, bw, 30, { act = "add", on = st.add_mode, s = "Hedef ekle" }), true)
  add(rect("btn", x + bw + 8, y, bw, 30, { act = "release", s = "Hedefi bırak", disabled = not st.enabled }), true)
  add(rect("btn", x + (bw + 8) * 2, y, bw, 30, { act = "offline", on = st.offline, s = "Offline oynat" }), true)
  y = y + 30 + 8
  local sw = math.floor((COLW - 2 * 4) / 3)
  for i, so in ipairs(M.SOURCES) do
    add(rect("btn", x + (i - 1) * (sw + 4), y, sw, 28,
      { act = "source", a = so[1], on = (st.source == so[1]), s = "Kaynak: " .. so[2], variant = "seg" }), true)
  end
  y = y + 28 + 12
  add(rect("text", x + 2, y + 2, 0, 0, { s = "L panel  ·  G sonraki parça  ·  A hedef ekle", fs = 11, col = "dim", an = 4 }))
  add(rect("text", x + 2, y + 20, 0, 0, { s = "X hedefi bırak  ·  T takip aç/kapa  ·  Esc kapat", fs = 11, col = "dim", an = 4 }))
  local left_end = y + 34

  -- ---- Sağ sütun: sayısal ayarlar, seçenekler
  x, y = PAD + COLW + COLGAP, y0
  add(rect("label", x, y, 0, 0, { s = "AYARLAR" }))
  y = y + 22
  for _, sp in ipairs(M.STEPS) do
    local c = cfg and cfg[sp[1]]
    local frac = 0
    if c and c[3] > c[2] then frac = math.max(0, math.min(1, (c[1] - c[2]) / (c[3] - c[2]))) end
    add(rect("text", x + 2, y + 11, 0, 0, { s = sp[2], fs = 13, col = cfg and "text" or "dim", an = 4 }))
    add(rect("bar", x + 2, y + 24, COLW - 130, 3, { frac = frac, disabled = not c }))
    local bx = x + COLW - 24
    add(rect("btn", bx, y + 1, 24, 24, { act = "step", a = sp[1], b = 1, s = "+", variant = "step", disabled = not c }), true)
    add(rect("text", bx - 36, y + 12, 0, 0, { s = c and c[4] or "—", fs = 13, col = "text", an = 5, bold = true }))
    add(rect("btn", bx - 96, y + 1, 24, 24, { act = "step", a = sp[1], b = -1, s = "−", variant = "step", disabled = not c }), true)
    y = y + 29
  end
  y = y + 6
  add(rect("label", x, y, 0, 0, { s = "SEÇENEKLER" }))
  y = y + 22
  local fw = math.floor((COLW - 10) / 2)
  for i, f in ipairs(M.FLAGS) do
    local col, row = (i - 1) % 2, math.floor((i - 1) / 2)
    local on
    if f[1] == "ui_hud" then on = st.hud else on = cfg and cfg.flags and cfg.flags[f[1]] end
    add(rect("switch", x + col * (fw + 10), y + row * 30, fw, 26,
      { act = "flag", a = f[1], on = on and true or false, s = f[2], disabled = (f[1] ~= "ui_hud" and not cfg) }), true)
  end
  y = y + 3 * 30 + 6
  local fy = math.max(y, left_end) + 4
  local hw = math.floor((COLW - 8) / 2)
  add(rect("btn", x, fy, hw, 32, { act = "save", s = "Ayarları kaydet", variant = "primary" }), true)
  add(rect("btn", x + hw + 8, fy, hw, 32, { act = "defaults", s = "Varsayılanlar" }), true)
  local DH = fy + 32 + PAD

  s = math.max(0.35, math.min(1.6, (W - 24) / DW, (H - top - 16) / DH))
  ox = math.floor((W - DW * s) / 2)
  oy = top + 8
  local function px(v) return math.floor(v * s + 0.5) end
  for _, it in ipairs(items) do -- tasarım birimi -> piksel
    it.x, it.y, it.w, it.h = ox + px(it.x), oy + px(it.y), px(it.w), px(it.h)
    if it.fs then it.fs = math.max(7, px(it.fs)) end
  end
  return { s = s, card = { x = ox, y = oy, w = px(DW), h = px(DH) }, items = items, widgets = widgets,
    fs = math.max(8, px(12)), u = s }
end

-- ---- ASS çizim yardımcıları -------------------------------------------------------------------
local PAL = { -- RRGGBB
  card = "14171D", surface = "212733", hover = "2D3544", border = "343C4D", text = "EDF1F8", dim = "8E99AE",
  accent = "4F8CFF", accent_soft = "22365E", green = "35D08A", green_soft = "173A2D", red = "FF6B6B", off = "485064",
  white = "FFFFFF",
}
local function bgr(hex) return hex:sub(5, 6) .. hex:sub(3, 4) .. hex:sub(1, 2) end
local function C(name) return bgr(PAL[name] or name) end

local function rpath(w, h, r, ox, oy, ccw)
  r = math.max(0, math.min(r, math.floor(math.min(w, h) / 2)))
  ox, oy = ox or 0, oy or 0
  local function P(x, y) return string.format("%d %d", ox + x, oy + y) end
  if not ccw then
    return string.format("m %s l %s b %s %s %s l %s b %s %s %s l %s b %s %s %s l %s b %s %s %s",
      P(r, 0), P(w - r, 0), P(w, 0), P(w, 0), P(w, r), P(w, h - r), P(w, h), P(w, h), P(w - r, h),
      P(r, h), P(0, h), P(0, h), P(0, h - r), P(0, r), P(0, 0), P(0, 0), P(r, 0))
  end
  return string.format("m %s b %s %s %s l %s b %s %s %s l %s b %s %s %s l %s b %s %s %s",
    P(r, 0), P(0, 0), P(0, 0), P(0, r), P(0, h - r), P(0, h), P(0, h), P(r, h),
    P(w - r, h), P(w, h), P(w, h), P(w, h - r), P(w, r), P(w, 0), P(w, 0), P(w - r, 0))
end
local function cpath(cx, cy, r, ccw) -- daire (4 Bezier)
  local k = math.floor(r * 0.5523 + 0.5)
  local function P(x, y) return string.format("%d %d", x, y) end
  if not ccw then
    return string.format("m %s b %s %s %s b %s %s %s b %s %s %s b %s %s %s", P(cx - r, cy),
      P(cx - r, cy - k), P(cx - k, cy - r), P(cx, cy - r), P(cx + k, cy - r), P(cx + r, cy - k), P(cx + r, cy),
      P(cx + r, cy + k), P(cx + k, cy + r), P(cx, cy + r), P(cx - k, cy + r), P(cx - r, cy + k), P(cx - r, cy))
  end
  return string.format("m %s b %s %s %s b %s %s %s b %s %s %s b %s %s %s", P(cx - r, cy),
    P(cx - r, cy + k), P(cx - k, cy + r), P(cx, cy + r), P(cx + k, cy + r), P(cx + r, cy + k), P(cx + r, cy),
    P(cx + r, cy - k), P(cx + k, cy - r), P(cx, cy - r), P(cx - k, cy - r), P(cx - r, cy - k), P(cx - r, cy))
end

function M.render_layout(L, st, hover, focus)
  local ev = {}
  local function shape(x, y, col, alpha, path)
    ev[#ev + 1] = string.format("{\\an7\\pos(%d,%d)\\bord0\\shad0\\1c&H%s&\\1a&H%s&\\p1}%s{\\p0}", x, y, C(col), alpha, path)
  end
  local function fill(x, y, w, h, r, col, alpha) shape(x, y, col, alpha or "00", rpath(w, h, r)) end
  local function stroke(x, y, w, h, r, t, col, alpha)
    shape(x, y, col, alpha or "00", rpath(w, h, r) .. " " .. rpath(w - 2 * t, h - 2 * t, math.max(0, r - t), t, t, true))
  end
  local function text(x, y, an, col, fs, s, bold, sp)
    ev[#ev + 1] = string.format("{\\an%d\\pos(%d,%d)\\fnSegoe UI\\fs%d\\b%d\\fsp%s\\bord0\\shad0\\1c&H%s&}%s",
      an, x, y, fs, bold and 1 or 0, sp or "0", C(col), s)
  end
  local u = L.u
  local cd = L.card
  local rad = math.floor(14 * u)
  fill(cd.x + math.floor(4 * u), cd.y + math.floor(6 * u), cd.w, cd.h, rad, "000000", "B0") -- gölge
  fill(cd.x, cd.y, cd.w, cd.h, rad, "card", "08")
  stroke(cd.x, cd.y, cd.w, cd.h, rad, math.max(1, math.floor(u + 0.5)), "border", "00")

  local function widget_bg(it, base, base_alpha)
    local over = (hover == it.wi)
    local col = over and "hover" or base
    fill(it.x, it.y, it.w, it.h, math.floor(8 * u), col, base_alpha or "00")
    if focus == it.wi then stroke(it.x, it.y, it.w, it.h, math.floor(8 * u), math.max(2, math.floor(1.5 * u)), "accent", "00") end
  end

  local function icon(kind, cx, cy, col)
    local r = math.floor(13 * u + 0.5)
    if kind == "spark" then
      local a, b = r, math.floor(r * 0.28)
      local function P(dx, dy) return string.format("%d %d", a + dx, a + dy) end
      shape(cx - a, cy - a, col, "00", string.format("m %s l %s l %s l %s l %s l %s l %s l %s",
        P(0, -a), P(b, -b), P(a, 0), P(b, b), P(0, a), P(-b, b), P(-a, 0), P(-b, -b)))
    elseif kind == "ring" then
      shape(cx - r, cy - r, col, "00", cpath(r, r, r, false) .. " " .. cpath(r, r, math.floor(r * 0.68), true))
      local d = math.max(2, math.floor(r * 0.26))
      shape(cx - d, cy - d, col, "00", cpath(d, d, d, false))
    elseif kind == "frame" then
      local w, h = math.floor(r * 2.1), math.floor(r * 1.5)
      local t = math.max(2, math.floor(r * 0.2))
      shape(cx - math.floor(w / 2), cy - math.floor(h / 2), col, "00",
        rpath(w, h, math.floor(r * 0.25)) .. " " .. rpath(w - 2 * t, h - 2 * t, math.floor(r * 0.1), t, t, true))
    elseif kind == "person" then
      local hr = math.floor(r * 0.36)
      shape(cx - hr, cy - r, col, "00", cpath(hr, hr, hr, false))
      local bw, bh = math.floor(r * 1.5), math.floor(r * 0.9)
      shape(cx - math.floor(bw / 2), cy + math.floor(r * 0.12), col, "00", rpath(bw, bh, math.floor(bh * 0.5)))
    end
  end

  for _, it in ipairs(L.items) do
    local k = it.k
    if k == "text" then
      text(it.x, it.y, it.an or 4, it.col or "text", it.fs, it.s, it.bold)
    elseif k == "label" then
      text(it.x + 2, it.y + 6, 4, "dim", math.max(7, math.floor(11 * u + 0.5)), it.s, true, "1.2")
    elseif k == "line" then
      fill(it.x, it.y, it.w, math.max(1, math.floor(u)), 0, "border", "20")
    elseif k == "mode" then
      local on = it.sel
      widget_bg(it, on and "accent_soft" or "surface")
      if on then stroke(it.x, it.y, it.w, it.h, math.floor(8 * u), math.max(1, math.floor(1.5 * u)), "accent", "00") end
      icon(it.icon, it.x + math.floor(it.w / 2), it.y + math.floor(it.h * 0.36), on and "accent" or "dim")
      text(it.x + math.floor(it.w / 2), it.y + math.floor(it.h * 0.70), 5, on and "white" or "text",
        math.max(8, math.floor(13 * u + 0.5)), it.s, true)
      text(it.x + math.floor(it.w / 2), it.y + math.floor(it.h * 0.88), 5, "dim", math.max(7, math.floor(10 * u + 0.5)), it.sub)
    elseif k == "chip" then
      widget_bg(it, it.sel and "accent" or "surface")
      text(it.x + math.floor(it.w / 2), it.y + math.floor(it.h / 2), 5, it.sel and "white" or "text",
        math.max(7, math.floor(12 * u + 0.5)), it.s, it.sel)
    elseif k == "pill" then
      widget_bg(it, it.on and "green_soft" or "surface")
      local dot = math.floor(5 * u + 0.5)
      shape(it.x + math.floor(12 * u), it.y + math.floor(it.h / 2) - dot, it.on and "green" or "off", "00",
        cpath(dot, dot, dot, false))
      text(it.x + math.floor(24 * u), it.y + math.floor(it.h / 2), 4, it.on and "green" or "dim",
        math.max(7, math.floor(12 * u + 0.5)), it.s, true)
    elseif k == "btn" then
      local v = it.variant
      local base = it.on and "accent_soft" or (v == "primary" and "accent" or "surface")
      if v == "ghost" then base = "card" end
      if it.disabled then
        fill(it.x, it.y, it.w, it.h, math.floor(8 * u), "surface", "60")
        text(it.x + math.floor(it.w / 2), it.y + math.floor(it.h / 2), 5, "off", math.max(7, math.floor(12 * u + 0.5)), it.s)
      else
        widget_bg(it, base, v == "ghost" and "FF" or "00")
        if it.on then stroke(it.x, it.y, it.w, it.h, math.floor(8 * u), math.max(1, math.floor(1.5 * u)), "accent", "00") end
        local fs = (v == "step") and math.floor(16 * u + 0.5) or math.floor(12 * u + 0.5)
        text(it.x + math.floor(it.w / 2), it.y + math.floor(it.h / 2), 5, (v == "primary") and "white" or (it.on and "accent" or "text"),
          math.max(7, fs), it.s, v == "primary" or v == "step")
      end
    elseif k == "bar" then
      local h = math.max(2, it.h)
      fill(it.x, it.y, it.w, h, math.floor(h / 2), "surface", "00")
      if not it.disabled and it.frac > 0 then
        fill(it.x, it.y, math.max(h, math.floor(it.w * it.frac)), h, math.floor(h / 2), "accent", "00")
      end
    elseif k == "switch" then
      if hover == it.wi then fill(it.x, it.y, it.w, it.h, math.floor(8 * u), "hover", "A0") end
      if focus == it.wi then stroke(it.x, it.y, it.w, it.h, math.floor(8 * u), math.max(2, math.floor(1.5 * u)), "accent", "00") end
      text(it.x + math.floor(8 * u), it.y + math.floor(it.h / 2), 4, it.disabled and "off" or "text",
        math.max(7, math.floor(12 * u + 0.5)), it.s)
      local tw, th = math.floor(34 * u), math.floor(18 * u)
      local tx, ty = it.x + it.w - tw - math.floor(6 * u), it.y + math.floor((it.h - th) / 2)
      fill(tx, ty, tw, th, math.floor(th / 2), (it.on and not it.disabled) and "green" or "off", it.disabled and "60" or "00")
      local kr = math.floor(th / 2) - math.max(1, math.floor(2 * u))
      local kx = it.on and (tx + tw - kr * 2 - math.max(1, math.floor(2 * u))) or (tx + math.max(1, math.floor(2 * u)))
      shape(kx, ty + math.floor((th - kr * 2) / 2), "white", "00", cpath(kr, kr, kr, false))
    end
  end
  return table.concat(ev, "\n")
end

-- ---- Durum + etkileşim ------------------------------------------------------------------------
function M.new(ctx)
  local p = { is_shown = false, hover = nil, focus = nil, W = 0, H = 0, top = 0, lay = nil }

  function p:refresh(W, H, top)
    self.W, self.H, self.top = W or self.W, H or self.H, top or self.top
    self.lay = M.layout(self.W, self.H, ctx.state(), self.top)
    local n = #self.lay.widgets
    if self.hover and self.hover > n then self.hover = nil end
    if self.focus and self.focus > n then self.focus = nil end
  end
  function p:is_open() return self.is_shown end
  function p:open(W, H, top) self.is_shown = true; self.hover, self.focus = nil, nil; self:refresh(W, H, top) end
  function p:close() local was = self.is_shown; self.is_shown, self.hover, self.focus = false, nil, nil; return was end
  function p:toggle(W, H, top) if self.is_shown then self:close() else self:open(W, H, top) end return self.is_shown end
  function p:over(x, y) return self.is_shown and self.lay ~= nil and inside(self.lay.card, x, y) end

  local function widget_at(self, x, y)
    for i, w in ipairs(self.lay.widgets) do if inside(w, x, y) then return i end end
  end
  function p:mouse(x, y) -- döner: çizim değişti mi
    if not (self.is_shown and self.lay) then return false end
    local h = widget_at(self, x, y)
    if h ~= self.hover then self.hover = h; return true end
    return false
  end
  local function activate(self, i)
    local w = self.lay.widgets[i]
    if not w or w.disabled then return false end
    if w.act == "close" then self:close() else ctx.run(w.act, w.a, w.b) end
    if self.is_shown then self:refresh() end
    return true
  end
  function p:click(x, y) -- döner: tık tüketildi mi (kart üstündeki her tık tüketilir)
    if not (self.is_shown and self.lay) then return false end
    if not inside(self.lay.card, x, y) then return false end
    local i = widget_at(self, x, y)
    if i then activate(self, i) end
    return true
  end
  -- Klavye: "up","down","left","right","enter","esc". Döner: tüketildi mi.
  function p:key(k)
    if not self.is_shown then return false end
    if k == "esc" then self:close() return true end
    local n = #self.lay.widgets
    if n == 0 then return false end
    local f = self.focus
    if k == "down" or k == "up" or ((k == "left" or k == "right") and not (f and self.lay.widgets[f].act == "step")) then
      local dir = (k == "down" or k == "right") and 1 or -1
      self.focus = f and ((f - 1 + dir) % n + 1) or (dir > 0 and 1 or n)
      return true
    end
    if (k == "left" or k == "right") and f then -- adım düğmesinde sol/sağ = −/+
      local w = self.lay.widgets[f]
      for i, o in ipairs(self.lay.widgets) do
        if o.act == "step" and o.a == w.a and o.b == (k == "right" and 1 or -1) then activate(self, i) break end
      end
      return true
    end
    if k == "enter" then return (f and activate(self, f)) or true end
    return false
  end
  function p:render()
    if not (self.is_shown and self.lay) then return "" end
    return M.render_layout(self.lay, ctx.state(), self.hover, self.focus)
  end
  return p
end

return M
