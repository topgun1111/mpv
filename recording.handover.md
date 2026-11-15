# recording.handover.md — Takipli Oynat KAYIT (PC varyantı)

Yeni oturumda önce bu dosyayı, sonra ana `handover.md`'nin «Kurallar» satırını oku; sıradaki ⬜ parçayı yap.
Her parça sonunda bu dosyayı güncelle → TÜM projeyi ZIP'le (`takipli-oynat-recording-partN.zip`; değişen dosyalar değil, hepsi).
Ücretsiz Claude hesabı: token'ı idareli kullan. Bir parça = bir oturum; yarım bırakma, son yeşil testte dur ve buraya yaz.

## 1. Amaç (kullanıcı isteği, bağlayıcı)
PC tarafı **iki varyanta** ayrılır:
1. **Ana varyant (`main`)** — mevcut uygulama (takip, modeller, offline). **Değişmez**; testleri aynen geçmeli.
2. **Kayıt varyantı (`recording`)** — **tek özellik**: video oynarken kullanıcı **zoom düzeyini ayarlar ve videoyu aynı anda sürükler**
   (Android `RecordScreen` ile aynı özellik); kamera hareketi kaydedilir, sonra yeni video olarak dışa aktarılır.
   **Poz, YOLO, Re-ID, takip, model YOK ve eklenmeyecek.** `onnxruntime`, `tracker/`, `models/` pakete girmez.

Kodlama **üç parçaya** bölündü (aşağıda). Parça R1 yapıldı.

## 2. Tasarım kararları
- Yeni, bağımsız Python paketi **`recorder/`** (ana `tracker/`'ı içe aktarmaz; test AST ile denetler). Geometri/dışa aktarma
  formülleri ana varyantla **birebir aynı** (testte `tracker.export`/`tracker.offline` ile eşlik testi) → çıktı tutarlı.
- Anahtar kare biçimi her yerde aynı: `[t, zoom(log2), pan_x, pan_y]`, `t` = videonun kendi saati (`time-pos`).
  Önizleme hızı (0.25×–2×) kaydı etkilemez; dışa aktarma özgün hızda (Android ile aynı kural).
- Kayıt dosyası: `<video>.rec.json` = `{version:1, kind:"manual-camera", video, vsig, rotate, speed, views}`.
  `vsig` = ana varyanttaki `cache.file_sig` ile aynı imza; video değişmişse dışa aktarma reddeder.
- Zoom + sürükleme **aynı anda**: `apply_gesture_at` (Android `applyGestureAt` portu) imlecin altındaki kare noktasını imleçle
  birlikte tutar; zoom imleç etrafındadır, kare ortası etrafında değil. Zoom 0..4 (log2, 1×–16×), pan ±(0.5−0.5/2^z) ile kıstırılır.
- Ayrı mpv IPC borusu (`\\.\pipe\mpv-kayit`) ve ayrı paket klasörü (`dist/TakipliOynatKayit`) → iki varyant yan yana çalışabilir.
- Dışa aktarma ffmpeg ile (ana varyanttaki gibi `ffmpeg\ffmpeg.exe`; yoksa sessiz cv2 yedeği). `requirements-recording.txt` =
  numpy + opencv-python-headless (kare okuma/kırpma için); ONNX çalışma zamanı yok.
- mpv `video-rotate` (K tuşu) kayda yazılır; dışa aktarma önce kareyi döndürür, sonra kırpar (çıktı boyutu 90/270'te yer değiştirir).

## 3. Parçalar
| # | Parça | Durum |
|---|-------|-------|
| R1 | Python çekirdek + varyant paketleme (`recorder/`, `make_package --variant`, testler) | ✅ |
| R2 | Lua kayıt arayüzü: `scripts/kayit.lua` (+ `input.conf`), Lua↔Python eşlik testi | ⬜ |
| R3 | Dışa aktarma akışı (menü/tuş → `recorder export`), başlatıcılar, installer, CI workflow, README/lisans, son testler | ⬜ |

### R1 — Yapıldı (2026-11-15)
- `recorder/geometry.py`: `clamp_view`, `apply_gesture_at`, `set_zoom_at`, `view_at`, `crop_rect` (+ `MAX_ZOOM=4`).
- `recorder/keys.py`: `append_key`, `normalize_keys`, hız (`clamp_speed`, `key_dt`, `SPEED_PRESETS`), `save_recording`/`load_recording`, `rec_path`, `default_out` (`<video>.kamera.mp4`), `file_sig`.
- `recorder/export.py`: `export_video(video, views, out, rotate=…)` (ffmpeg libx264 + özgün ses; ilerleme `<out>.export.json`, iptal `<out>.export.cancel`).
- `recorder/main.py` CLI: `python -m recorder export VIDEO [--rec F] [--out F] [--no-audio] [--crf N] [--ffmpeg P]`, `info REC`, `--version`.
- `scripts/make_package.py --variant main|recording [--out DİZİN]` (varsayılan main = eski davranış; `main()` argümansız çağrılabilir),
  `scripts/build_embedded.py --requirements <dosya>`, `requirements-recording.txt`.
- Kayıt paketi iskeleti: `mpv/portable_config_recording/{mpv.conf,input.conf}` (şimdilik düz oynatıcı), `launcher_recording/Kayit.bat`.
- Testler: `tests/test_recorder.py` (25 test: zoom+sürükleme aynı anda, imleç sabitleme, ana varyantla eşlik, kayıt dosyası, uçtan uca dışa aktarma,
  döndürme, iptal, CLI, `recorder` içinde tracker/onnx/torch içe aktarımı yok, kayıt paketinde model/tracker yok, ana paket değişmedi).
  Gerçek ffmpeg ile (sesli test klibi) elle doğrulandı: sesli, 640x360 çıktı. Bu ortamda pytest/ruff kurulamadı (ağ yok); testler yerel
  mini koşucuyla yeşil, satır uzunluğu (≤100) ve kullanılmayan içe aktarma elle denetlendi → **CI'da ilk koşuda `ruff check .` + `pytest -q` doğrulanmalı**.
- Bilinen/devralınan: `-shortest` nedeniyle ffmpeg sesli çıktıda son 1–2 kareyi kırpabilir (ana varyantla aynı davranış).

### R2 — Sıradaki: Lua kayıt arayüzü (`mpv/portable_config_recording/scripts/kayit.lua`, ≤ ~350 satır)
Ana `track.lua`'ya DOKUNMA; sıfırdan, küçük, tek amaçlı betik (mpcbar/vlcbar yok; `osc=yes` ya da basit OSD yeter).
- **Girdi (fare)**: sol tuş basılı tut + sürükle = kaydır; **tekerlek = imleç etrafında zoom**; ikisi birlikte (sürüklerken tekerlek) aynı karede uygulanır
  (`apply_gesture_at` Lua portu; Python ile **aynı sayısal referans değerleri** `test_recorder.py::test_android_parity_apply_gesture_at_reference_values` ve
  imleç-sabitleme invariantı Lua harness'te). Klavye: `+`/`-` (basılı tutunca sürekli) = zoom düzeyi, ok tuşları yerine fare sürüklemesi; `0` = görünümü sıfırla.
  Çift tık = oynat/duraklat (ana varyantta olduğu gibi); `Space` = oynat/duraklat.
- **Kayıt**: `R` = kaydı başlat/durdur (başlarken `seek 0`, oynat, görünümü sıfırla; Android ile aynı). Kayıt sırasında zamanlayıcı (≈33 ms duvar saati,
  `key_dt(speed)` ile) `time-pos`'a anahtar yazar (`append_key`: geri sarma/duraklatma anahtar üretmez). Durunca son anahtar eklenir, `<video>.rec.json` yazılır
  (JSON'u Lua yazar; şema R1 ile aynı: `version, kind, video, vsig, rotate, speed, views`).
  **`vsig` sorunu**: Lua `file_sig` (sha1) hesaplayamaz → `vsig` boş yazılsın, dışa aktarma `load_recording` `vsig` yoksa kabul eder (R1'de yok = kabul);
  alternatif: Lua `recorder sig` alt komutunu (R3'e bırakılan küçük CLI eki) çağırsın. Kararı R2 başında ver, buraya yaz.
- **Hız**: `[`/`]` ile 0.25–2× (önizleme); kayıt video saatinde, hızdan bağımsız.
- **HUD**: sol üstte `● KAYIT  3.2×  12.4 sn` (ASS/OSD), zoom değeri her zaman görünür; kayıt dışında zoom/sürükleme önizleme olarak serbest (kaydedilmez).
- **Sınır**: `video-zoom`/`video-pan-*` yalnız `clamp_view` sınırları içinde; pencere boyutu/`video-align` varsayımı için ana `track.lua::pan_apply` mantığına bak.
- Test: `tests/lua_harness_kayit.lua` + `tests/test_lua_kayit.py` (mevcut `lua_mp_stub.lua` kalıbıyla; `REQUIRE_LUA=1` CI'da zorunlu).
- Çıkış: kayıt varyantı paketinde fare ile zoom+sürükle çalışır, `R` ile `.rec.json` yazılır (dışa aktarma el ile `python -m recorder export`).

### R3 — Son: dışa aktarma akışı + dağıtım
- Lua: `E` = dışa aktar (`mp.command_native_async` ile `pythonw.exe -m recorder export <video>`; durum çubuğu/OSD'de ilerleme `.export.json`'dan, `Esc` iptal = `.export.cancel`),
  bitince OSD «Kaydedildi: …kamera.mp4». Kayıt yoksa uyarı.
- `launcher_recording/`: `Kayit.bat` (var), `Disa-Aktar.bat` (video sürükle → `recorder export`).
- `installer-recording.iss` (yeni AppId, ad «Takipli Oynat Kayıt», `dist\TakipliOynatKayit`; model/ONNX yok; `MinVersion` gerekirse düşür — DirectML gerekmiyor).
- `.github/workflows/build-recording.yml`: test → `make_package.py --variant recording` → `build_embedded.py --requirements requirements-recording.txt`
  → mpv + ffmpeg indir → duman testi (`python -m recorder --version`, cv2 import, **onnxruntime YOK** doğrulaması) → zip + Inno Setup. Ana `build.yml`'ye dokunma.
- `README.md` «Kayıt varyantı» bölümü, `THIRD_PARTY_NOTICES.md` (kayıt paketi: mpv GPL/LGPL, ffmpeg GPL, opencv Apache-2.0, numpy BSD; model yok).
- `tests/test_packaging_recording.py`: installer/workflow/launcher tutarlılığı (test_packaging.py kalıbı), kayıt paketinde ONNX/model yok.
- Çıkış: temiz Windows'ta kayıt installer'ı: video aç → zoom+sürükle → R → E → mp4.

## 4. Kurallar (bu varyant için)
- Yeni özellik EKLEME: yalnız «zoom düzeyi + sürükleme (aynı anda) → kaydet → dışa aktar». Poz/model/takip isteği gelirse ana varyanta.
- Ana varyant dosyalarını (`tracker/`, `track.lua`, `installer.iss`, `build.yml`) değiştirme; gerekirse küçük, testli ve `handover.md`'ye yazılı.
- Sürüm tek yerden: `VERSION` = `tracker.__version__` = `recorder.__version__` (test denetler; yükseltirken üçünü ve `tests/test_license.py`'ı birlikte güncelle).
