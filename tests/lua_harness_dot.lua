-- Beyaz takip noktası (Ortam: TRACK_LUA, VIDEO, DATA_LUA).
local dir = (arg and arg[0] or ""):match("^(.*)[/\\]") or "."
local reg = dofile(dir .. "/lua_mp_stub.lua")
dofile(os.getenv("TRACK_LUA"))
local function out(...) print(table.concat({ ... }, "\t")) end
local function dot() return reg.ov[3] or "<yok>" end -- nokta katmanı (z=3)

-- pencere 1000x500, video zoom'suz tam kaplıyor
reg.props["osd-dimensions"] = { w = 1000, h = 500, ml = 0, mr = 0, mt = 0, mb = 0 }
reg.msgs["track-dot"]("0.5", "0.5")
out("OFF_WHEN_DISABLED", dot()) -- takip kapalıyken çizilmez
reg.bind.toggle() -- takibi aç
reg.msgs["track-dot"]("0.5", "0.5")
out("CENTER", dot())
-- zoom/pan: video pencerenin dışına taşmış (ml negatif) → nokta ekran koordinatına çevrilir
reg.props["osd-dimensions"] = { w = 1000, h = 500, ml = -500, mr = -500, mt = -250, mb = -250 }
reg.obs["osd-dimensions"]()
out("ZOOMED", dot()) -- 0.5,0.5 → x=-500+0.5*2000=500, y=-250+0.5*1000=250: merkez
reg.msgs["track-dot"]("0.9", "0.5")
out("OUT", dot()) -- x=1300: ekran dışı → gizli
reg.msgs["track-dot"]("off")
out("HIDE", dot())
