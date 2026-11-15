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

Kodlama **üç parçaya** bölündü (aşağıda). **R1, R2, R3 yapıldı — kayıt varyantının kodlaması BİTTİ**; kalan iş yalnız Windows'ta gerçek doğrulama (aşağıda «Doğrulama»).

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
| R2 | Lua kayıt arayüzü: `scripts/kayit.lua` (+ `input.conf`), Lua↔Python eşlik testi | ✅ |
| R3 | Dışa aktarma akışı (`E` tuşu → `recorder export`), başlatıcılar, installer, CI workflow, README/lisans, son testler | ✅ |

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

### R2 — Yapıldı (2026-11-15): Lua kayıt arayüzü (`mpv/portable_config_recording/scripts/kayit.lua`, 269 satır)
- **Girdi**: sol tuş basılı + sürükle = kaydır; tekerlek = imleç etrafında zoom (adım 0.25 log2); sürüklerken tekerlek de çalışır (her olay `apply_gesture_at` ile, aynı imleç noktasında → nokta imleçle kalır). `+`/`-` (basılı tut = sürekli, `repeatable`) = zoom düzeyi (pencere ortası), `0` = sıfırla, `K` = döndür (kayıt sırasında reddedilir), `[`/`]` = hız (SPEED_PRESETS adımları), çift tık = `cycle pause` (input.conf), Space = mpv varsayılanı.
- **Geometri**: `clamp_view`/`apply_gesture_at`/`set_zoom_at`/`clamp_speed`/`key_dt`/`append_key` Python'dan birebir port. Görünüm doğrudan `video-zoom`/`video-pan-x`/`video-pan-y`'a yazılır (mpv pan = ölçekli genişlik oranı = kare oranı; işaret/merkez `0.5 − pan` Python ile aynı). İmleç oranı, zoom=1/pan=0'daki video dikdörtgenine göre (`box()`: osd boyutu + `video-params` dw/dh, 90/270 döndürmede yer değiştirir) → letterbox'ta da doğru.
- **Kayıt**: `R` → görünümü sıfırla, `seek 0 absolute exact`, oynat; anahtarlar **`playback-restart` gelince** başlar (seek bitmeden eski `time-pos` yazılmasın diye). Zamanlayıcı `add_timeout` (33 ms duvar saati, her tikte yeniden kurulur; `rec.id` ile eski zamanlayıcı etkisiz). `append_key` min_dt = `key_dt(speed)/2` → geri sarma/duraklatma anahtar üretmez. `R` tekrar / dosya sonu (`eof-reached`) / `end-file` = durdur: son anahtar eklenir, `<video>.rec.json` atomik yazılır (tmp + rename). Tek anahtar varsa 40 ms sonrasına kopyalanır.
- **KARAR (vsig)**: Lua `vsig` YAZMAZ (sha1 yok); `load_recording` `vsig` yoksa imza denetimini atlar → R3'te `recorder sig` alt komutu GEREKMİYOR. Video değişirse dışa aktarma bunu yakalamaz; kabul edilen ödünleşim (kayıt dosyası video yanında, adı `<video>.rec.json`).
- **HUD**: ASS katman z=5, sol üst: kayıtta `● KAYIT  3.2×  12.4 sn` (kırmızı ●), kayıt dışında yalnız `3.2×` (zoom her zaman görünür).
- **Testler**: `tests/lua_harness_kayit.lua` + `tests/test_lua_kayit.py` (6 test): Android referansı + 5 adımlı dizi Python ile birebir, imleç sabitleme değişmezi (zoom ve zoom+sürükleme, hata <1e-9), fare/tekerlek/tuş entegrasyonu (Python `geometry` ile karşılaştırma), kayıt akışı (seek komutu, playback-restart öncesi anahtar yok, duraklatma/geri sarma anahtarsız, HUD), `.rec.json` şeması + `load_recording` ile okunur, hız/döndürme, yazma hatası uyarısı, input.conf↔Lua bağ eşleşmesi, ≤350 satır, kodda onnx/yolo/tracker yok. `texlua` (Lua 5.3) ile yeşil; CI'da `REQUIRE_LUA=1`.
- Bu ortamda pytest/ruff kurulamadı (ağ yok): testler yerel mini koşucuyla yeşil (R1 testleri dahil, ffmpeg yedeği ile), satır uzunluğu ≤100 elle denetlendi → **CI'da ilk koşuda `ruff check .` + `pytest -q` doğrulanmalı**.
- **Bilinen riskler (gerçek Windows'ta elle denenmedi)**: (1) mpv'nin Lua'sında `io.open` Windows'ta UTF-8 olmayan/ANSI dışı karakterli yolları açamayabilir → yazma başarısız olursa OSD «dosya yazılamadı» der; R3'te dışa aktarma `--rec` ile elle yol verilebilir, gerekirse Python tarafı yazan bir `recorder save` yolu düşünülebilir. (2) mpv OSC `MBTN_LEFT`'i kendi düğmelerinde alır; boş alanda sürükleme `script-binding` ile çalışmalı (ana varyantta aynı kalıp) — gerçek mpv'de doğrulanacak. (3) `video-params.dw/dh` yoksa pencere oranı varsayılır.

### R3 — Yapıldı (2026-11-15): dışa aktarma akışı + dağıtım
- **Lua** (`kayit.lua`, 336 satır ≤350): `E` = `track`'teki kalıpla `~~exe_dir/../python/pythonw.exe` (yoksa `python.exe`) → `mp.command_native_async` ile `-m recorder export VIDEO --out <video>.kamera.mp4` (çıktı adı `recorder.keys.default_out` ile aynı; testle denetlenir). Ön koşullar: kayıt sürmüyor, yerel video, `<video>.rec.json` var (yoksa «önce kayıt yap (R)»), python bulundu. İlerleme 1 sn'de bir `<çıktı>.export.json`'dan OSD'ye «dışa aktarılıyor %NN (Esc: iptal)»; **Esc** yalnız dışa aktarma sürerken dinamik forced bağ (`export-cancel`) → `<çıktı>.export.cancel` dosyası (Python 1 sn'de bir bakar); bitince OSD «Kaydedildi: clip.kamera.mp4» / «iptal edildi» / «başarısız: <sebep>». Sonuç alt süreç çıkış koduyla belirlenir (0 ok, 3 iptal, diğer = hata), eski `.export.json` başta silinir (bayat «done» karışmaz). `R` ile kayıt bitince OSD ipucu «— E: dışa aktar». `input.conf`: `e script-binding kayit/export`.
- **Python** (`recorder/main.py`, `export.py`; küçük): konsolsuz `pythonw`'da hata görünsün diye `export` komutu her hatada (kayıt dosyası yok, video açılmıyor, ffmpeg hatası) `<çıktı>.export.json`'a `state: error` + sebep yazar (`_report_failure`); `_write_state` artık `ensure_ascii=False` (OSD'de «açılamadı», `\u0131` değil); `state_path()`; `main()` başında `_utf8_stdio()` (cp125x konsolunda Türkçe harf UnicodeEncodeError vermesin; akış yoksa sessiz geçer).
- **Dağıtım**: `launcher_recording/Disa-Aktar.bat` (video sürükle → `python\python.exe -m recorder export`; `if (` bloğu yok, etiket/goto; `chcp 65001` + `PYTHONUTF8=1`; her yolda `pause`), `installer-recording.iss` (YENİ AppId `B7E2D4A9-…`, «Takipli Oynat Kayit», `dist\TakipliOynatKayit`, çıktı `dist\installer-recording`, `MinVersion=10.0` — DirectML yok, model yok, `[InstallDelete]` python/recorder/ffmpeg/scripts; **ASCII** metinler: ana `installer.iss` gibi BOM'suz dosyada Türkçe harf ANSI sanılır → bilerek «Kayit», «Disa-Aktar»), `.github/workflows/build-recording.yml` (ana `build.yml` DEĞİŞMEDİ; tetik: `main` push + elle + **`kayit-v*`** etiketi → Release yalnız bu etikette; adımlar: ruff + yalnız kayıt testleri → `make_package --variant recording` → `build_embedded --out dist/TakipliOynatKayit --requirements requirements-recording.txt` → mpv → ffmpeg → duman testi → zip → Inno → artifact `TakipliOynatKayit-Setup`/`-Portable`). **Duman testi** (Windows runner): `recorder --version`, `import recorder, numpy, cv2`, **onnxruntime YOK** (`find_spec`), `tracker/` ve `models/` yok, `*.onnx` yok, gerekli dosyalar var, ffmpeg libx264 ile 2 sn test videosu → elle `.rec.json` yazılıp **gerçek `recorder export` uçtan uca** çalıştırılır.
- **Belgeler**: README «Kayıt varyantı (R1–R3)» (tuş tablosu + akış + CLI + CI) ve dosya yapısı; `THIRD_PARTY_NOTICES.md` Madde **3c** (kayıt paketi: mpv GPL, ffmpeg GPL, Python PSF, numpy BSD, opencv Apache-2.0; model satırları UYGULANMAZ).
- **Testler**: `tests/test_packaging_recording.py` (9: installer bağımsız/model yok/AppId farklı/Turkish.isl, workflow sırası + yasaklı adımlar (model, DirectML, `requirements.txt`) + `kayit-v*`, ana `build.yml`/`installer.iss`/`track.lua` kayıttan habersiz, bat yapısı, paket içeriği + CRLF, Lua↔Python sözleşmesi (komut, `.kamera.mp4`, `.export.json` alan desenleri Lua'nın okuyucusuyla), CLI hatası durum dosyasına yazılır, `_utf8_stdio`, belgeler); `tests/lua_harness_kayit.lua` bölüm 7 + `test_lua_kayit.py::test_export_flow_launches_recorder_and_reports` (sahte `mp`: komut satırı birebir, python.exe yedeği, python yok/kayıt yok/kayıt sürerken, ikinci E, %50 ilerleme, Esc → `.cancel`, iptal/başarı/hata (json'lu ve json'suz) OSD'leri, Esc bağı kalkar); `input.conf` bağ tablosuna `e`.
- **Bu ortamda doğrulanan**: pytest/ruff kurulamadı (ağ yok) → küçük pytest benzeri koşucuyla **tüm `tests/` (428 test; Lua testleri `texlua` ile gerçekten çalıştı)**: 427 geçti, 1 başarısız = **bu işten bağımsız, önceden var**: `tests/test_android_release.py::test_android_workflow_release_step` `android.yml`'de `secrets.ANDROID_KEYSTORE_B64/…` arıyor, workflow artık bunları kullanmıyor (imza anahtarı `android/app/stable.jks` depoda; yalnız yorum satırı eski). Android tarafına dokunulmadı: ya testi güncelle ya workflow'u eski haline getir. Satır ≤100, kullanılmayan import ve sondaki boşluk elle/betikle denetlendi; `texluac -p kayit.lua` temiz; zip'te `git grep '<<<<<<<'` temiz. **CI'da ilk koşuda gerçek `ruff check .` + `pytest -q` doğrulanmalı** (özellikle `ruff` import sırası `I001`).

### Doğrulama (yapılmadı — gerçek Windows gerekir)
1. `build-recording.yml` hiç çalışmadı: `get-pip`/cp311 tekerlekleri (opencv-python-headless, numpy), `fetch_ffmpeg.ps1` adresi, Inno derlemesi (`Turkish.isl`, `MinVersion=10.0`), duman testindeki PowerShell satırları (özellikle `Get-ChildItem -Recurse -Filter *.onnx` ve `find_spec` tek tırnak/çift tırnak kaçışı) ilk koşuda bakılacak.
2. `kayit.lua` gerçek mpv'de hiç denenmedi (R2 riskleri geçerli): sol sürükleme + OSC çakışması, `video-params` yokken oran, `io.open` ile Unicode yol. **R3 ek riskleri**: (a) `mp.command_native_async` alt süreci mpv kapanınca ÖLDÜRÜLÜR → dışa aktarma sürerken mpv kapatılırsa `<ad>.partial.mp4` yarım kalır (ana varyant `detached` kullanıyor ama durum kodunu alamıyor; burada sonuç/hata OSD'si için async seçildi) — istenirse `detached` + yalnız `.export.json` yoklaması; (b) `pythonw.exe` ile ffmpeg alt süreci ek konsol penceresi açabilir (`stderr=PIPE` kullanıldığı için görünmez olması beklenir, denenmedi); (c) `Esc` forced bağı yalnız dışa aktarma sürerken; tam ekrandan çıkış için `F`/çift tık kullan; (d) Windows'ta `os.remove(exp.prog)` eski dosya yoksa sessiz geçer; (e) `.kamera.mp4` zaten varsa üzerine yazılır (ffmpeg `-y`), uyarı yok.
3. Çıkış kriteri (kullanıcıda): temiz Windows'ta kayıt installer'ı → video aç → zoom + sürükle → `R` → `E` → `.kamera.mp4` açılır ve kamera hareketi kayıtla aynı.
4. Bilinen/devralınan: `vsig` Lua'da yazılmaz (R2 kararı) → video değişirse dışa aktarma bunu yakalamaz; `-shortest` sesli çıktıda son 1–2 kareyi kırpabilir.

## 4. Kurallar (bu varyant için)
- Yeni özellik EKLEME: yalnız «zoom düzeyi + sürükleme (aynı anda) → kaydet → dışa aktar». Poz/model/takip isteği gelirse ana varyanta.
- Ana varyant dosyalarını (`tracker/`, `track.lua`, `installer.iss`, `build.yml`) değiştirme; gerekirse küçük, testli ve `handover.md`'ye yazılı.
- Sürüm tek yerden: `VERSION` = `tracker.__version__` = `recorder.__version__` (test denetler; yükseltirken üçünü ve `tests/test_license.py`'ı birlikte güncelle).
