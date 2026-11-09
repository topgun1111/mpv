-- Parça 16: ekran üstü panel (Ortam: TRACK_LUA, VIDEO, DATA_LUA). Tüm panel düğmelerini tarayıp tıklar.
local dir = (arg and arg[0] or ""):match("^(.*)[/\\]") or "."
local reg = dofile(dir .. "/lua_mp_stub.lua")
dofile(os.getenv("TRACK_LUA"))
local function out(...) print(table.concat({ ... }, "\t")) end
local W, H = 1280, 720
reg.props["osd-dimensions"] = { w = W, h = H, ml = 0, mr = 0, mt = 0, mb = 0 }
local function move(x, y) reg.obs["mouse-pos"]("mouse-pos", { x = x, y = y, hover = true }) end
local function over() return reg.bind["track-click-bind"] ~= nil end

out("BEFORE", tostring(#reg.hud), tostring(over()))
move(W - 5, H - 5) -- panel dışı: görünür ama hiçbir düğmenin üstünde değil
out("SHOWN", tostring(reg.hud[#reg.hud] ~= "" and reg.hud[#reg.hud] ~= nil), tostring(over()))
out("LABELS", tostring(reg.hud[#reg.hud]:find("Takip: KAPALI", 1, true) ~= nil),
  tostring(reg.hud[#reg.hud]:find("Offline: KAPALI", 1, true) ~= nil))

-- satırlar: soldaki ilk düğmenin x'inde dikey tarama
local rows, inrow = {}, nil
for y = 0, 300, 2 do
  move(12, y)
  if over() and not inrow then inrow = y elseif not over() and inrow then rows[#rows + 1] = { inrow, y - 2 }; inrow = nil end
end
out("ROWS", tostring(#rows))
local btns = {}
for _, r in ipairs(rows) do
  local ym = math.floor((r[1] + r[2]) / 2)
  local start
  for x = 0, W, 2 do
    move(x, ym)
    if over() and not start then start = x elseif not over() and start then btns[#btns + 1] = { math.floor((start + x - 2) / 2), ym }; start = nil end
  end
end
out("BTNS", tostring(#btns))
-- ters sırada tıkla (Takip düğmesi sona kalsın: durum zoom düğmelerini etkilemesin)
for i = #btns, 1, -1 do
  reg.cmds, reg.set = {}, {}
  move(btns[i][1], btns[i][2])
  reg.bind["track-click-bind"]()
  out("BTN", tostring(i), reg.cmds[1] or "-", tostring(reg.set["video-zoom"]))
end
-- Takip artık açık (Takip düğmesi en son tıklandı)
reg.cmds = {}
move(btns[6][1], btns[6][2]); reg.bind["track-click-bind"]()
out("ENABLED_ZOOM", reg.cmds[1] or "-")
move(btns[13][1], btns[13][2]); reg.bind["track-click-bind"]() -- sabitlemeyi kaldır
move(W - 5, H - 5)
out("ENABLED_BOUND", tostring(over())) -- hedef seçimi için bağ açık
reg.cmds = {}
reg.bind["track-click-bind"]() -- panel dışı tıklama = hedef seçimi (video-params yok: komut yok)
out("TARGET_CLICK", reg.cmds[1] or "-")
reg.timers[#reg.timers]() -- otomatik gizleme
out("HIDDEN", tostring(reg.hud[#reg.hud] == ""))
reg.bind.toggle() -- takip kapanınca sol tık bağı da kalkar
out("UNBOUND", tostring(not over()))
