-- track.lua'yı sahte `mp` ile çalıştırır (texlua/lua 5.1+). Ortam: TRACK_LUA, VIDEO, DATA_LUA, TIMES.
local dir = (arg and arg[0] or ""):match("^(.*)[/\\]") or "."
local reg = dofile(dir .. "/lua_mp_stub.lua")
dofile(os.getenv("TRACK_LUA"))

local function last_osd() return reg.osd[#reg.osd] or "" end
local function out(...) print(table.concat({ ... }, "\t")) end

reg.ev["file-loaded"]()
out("HINT", last_osd())
reg.bind.offline()
out("ON", last_osd())
for t in os.getenv("TIMES"):gmatch("[^,]+") do
  reg.set = {}
  reg.obs["time-pos"](nil, tonumber(t))
  out("T", t, tostring(reg.set["video-zoom"]), tostring(reg.set["video-pan-x"]),
    tostring(reg.set["video-pan-y"]))
end
-- offline açıkken + / - zoom'u değiştirmez (görünümü anahtar kareler sürer), uyarı verir
reg.set = {}
reg.bind["zoom-in"]()
out("OFF_ZOOM", tostring(reg.set["video-zoom"]), last_osd())
-- canlı mod açılınca offline kapanır ve görünüm sıfırlanır
reg.bind.toggle()
out("LIVE", last_osd(), tostring(reg.set["video-zoom"]))
reg.set = {}
reg.obs["time-pos"](nil, 1.0)
out("AFTER_LIVE_SET", tostring(reg.set["video-zoom"])) -- nil: offline kapalı, görünüm değişmez
-- offline tekrar açılınca canlı kapanır; gecikmeli yeniden uygulama zamanlayıcısı kurulur
reg.props["time-pos"] = 1.0
reg.bind.offline()
out("REON", last_osd(), tostring(#reg.timers))
reg.set = {}
reg.timers[1]()
out("TIMER", tostring(reg.set["video-zoom"]))
-- video değişince offline kapanır
reg.ev["end-file"]()
reg.set = {}
reg.obs["time-pos"](nil, 1.0)
out("ENDFILE", tostring(reg.set["video-zoom"]))
-- veri dosyası yoksa
reg.props.path = os.getenv("VIDEO") .. ".yok"
reg.bind.offline()
out("MISSING", last_osd())
