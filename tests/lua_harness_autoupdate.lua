-- Açılışta sessiz güncelleme denetimi (Ortam: TRACK_LUA, TRACK_MODULES, VIDEO, DATA_LUA, TRACK_STATE_DIR, TRACK_PYTHON).
-- track.lua gerçekten yüklenir; `subprocess` sahte: komut satırı yakalanır, stdout elle verilir.
local dir = (arg and arg[0] or ""):match("^(.*)[/\\]") or "."
local reg = dofile(dir .. "/lua_mp_stub.lua")
TRACK_SHOW_MENU = true
TRACK_FORCE_WIN = true
local mp = require("mp")
local out = function(...) print(table.concat({ ... }, "\t")) end
local info = {}
package.preload["mp.utils"] = function()
  return { parse_json = function() return info end, format_json = function() return "{}" end, file_info = function() return nil end }
end
local startup -- 8 sn'lik açılış zamanlayıcısı
local orig_timeout = mp.add_timeout
mp.add_timeout = function(sec, fn) if sec == 8 and not startup then startup = fn end; return orig_timeout(sec, fn) end
mp.command_native_async = function(t, cb) reg.async = { t = t, cb = cb } end
mp.command_native = function(t) reg.native = t; return nil end
dofile(os.getenv("TRACK_LUA"))

local function answer(stdout, status) local a = reg.async; reg.async = nil; a.cb(true, { status = status or 0, stdout = stdout }) end
local function last(t) return t.args[#t.args] end

out("SCHEDULED", tostring(startup ~= nil), tostring(reg.async == nil)) -- açılışta zamanlayıcı var; henüz denetim yok

-- 1) Güncel: denetim sessiz, ekrana hiçbir şey yazılmaz
local toast0 = reg.toast
startup()
out("CHECK_ARGS", last(reg.async.t), reg.async.t.args[#reg.async.t.args - 1])
info = { state = "uptodate", current = "1.0.0", latest = "1.0.0" }
answer("{}")
out("QUIET_UPTODATE", tostring(reg.async == nil), tostring(reg.toast == toast0))

-- 2) Denetim hatası (ağ yok): sessiz
startup()
info = { state = "error", message = "sürüm bilgisi alınamadı" }
answer("{}")
out("QUIET_ERROR", tostring(reg.async == nil), tostring(reg.toast == toast0))

-- 3) Yeni sürüm: Evet/Hayır sorulur (PowerShell), sürüm kaydedilir; Evet → kurulum başlar
startup()
info = { state = "available", current = "1.0.0", latest = "9.9.9", size = 104857600, notes = "yeni" }
answer("{}")
out("ASK", reg.async.t.args[1], tostring(last(reg.async.t):find("9.9.9", 1, true) ~= nil))
local f = io.open(os.getenv("TRACK_STATE_DIR") .. "/TakipliOynat/update_asked.txt", "rb")
out("ASKED_FILE", f and f:read("*a") or "-"); if f then f:close() end
answer("yes")
local n = reg.native and reg.native.args or {}
out("INSTALL", tostring(n[6]), tostring(n[7]), tostring(n[8])) -- tracker update install --progress

-- 4) Aynı sürüm için açılışta ikinci kez sorulmaz (Yardım menüsü hâlâ sorar)
reg.native = nil
local upd_ok = pcall(function() startup() end)
info = { state = "available", current = "1.0.0", latest = "9.9.9", size = 1, notes = "" }
if reg.async then answer("{}") end
out("NO_REPEAT", tostring(upd_ok), tostring(reg.async == nil))
