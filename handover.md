# handover.md — Takipli Oynat

Her parça sonunda güncellenir. Yeni oturumda önce bu dosyayı oku, sonra sıradaki parçayı yap.
Kurallar: (1) her parça sonunda `handover.md` güncelle → TÜM projeyi ZIP'le (`takipli-oynat-partNN.zip`; değişen dosyalar değil, tüm dosyalar). (2) Ücretsiz Claude hesabı: token'ı idareli ve akıllı kullan, israf yok.
Proje GitHub'a push edilip Actions ile derlenir (`ci.yml`: test+lint, `build.yml`: paket+installer). `build.yml` artık `main`'e her push'ta (yalnız .md değişikliği hariç), `v*` etiketinde ve elle çalışır; GitHub Release yalnız `v*` etiketinde oluşur. exe: çalışmanın sayfasında Artifacts → TakipliOynat.

## Durum
- Tamamlanan: **Parça 14/15**
- Sıradaki: **Parça 15**
- Sürüm: 0.14.0

## 15 Parçalık Plan
| # | Parça | Durum |
|---|-------|-------|
| 1 | İskelet: repo yapısı, CI/Build workflow, config, geometri (bbox→zoom/pan), EMA+dead-zone, mpv IPC istemcisi, CLI (ping/view), installer iskeleti, testler | ✅ |
| 2 | Lua: tıklama → video koordinatı, `script-message` ile Python'a iletme, OSD; Python'da olay okuma (`poll_event`) ve `listen` komutu | ✅ |
| 3 | Detector: YOLO ONNX (onnxruntime-directml), ön/son işleme, NMS, person sınıfı | ✅ |
| 4 | Tracker: ByteTrack (kalıcı ID), detector ile birleştirme | ✅ |
| 5 | Canlı mod `main.py`: kare okuma (mpv screenshot-raw/ffmpeg), time-pos senkronu, IPC çıkışı | ✅ |
| 6 | Hedef seçimi: tıklanan noktadaki bbox ID'si, hedef değiştirme/bırakma | ✅ |
| 7 | Kalman + hız yönünde lookahead (smooth.py genişletme) | ✅ |
| 8 | Kayıp yönetimi: son konumda bekle → kademeli zoom-out | ✅ |
| 9 | Offline mod: `offline.py` → `track.json` şeması ve üretimi | ✅ |
| 10 | Lua offline oynatma: `time-pos` ile JSON'dan zoom/pan, interpolasyon | ✅ |
| 11 | Re-ID (OSNet ONNX): embedding, ID kurtarma | ✅ |
| 12 | Takım rengi histogramı + forma numarası OCR | ✅ |
| 13 | Ayarlar (config UI/tuşlar) ve OSD iyileştirmeleri | ✅ |
| 14 | Gömülü Python (embeddable) + bağımlılık paketleme + Inno Setup tam installer, DirectML varsayılanı | ✅ |
| 15 | Lisans denetimi (AGPL/Apache alternatif, THIRD_PARTY_NOTICES), son testler, dokümantasyon, release | ⬜ |

## Parça 1'de yapılanlar (özet)
- `tracker/geometry.py`: `BBox`, `View`, `compute_view` (log2 zoom, pan = 0.5 − merkez, kenar kıstırma)
- `tracker/smooth.py`: `Ema`, `DeadZone`, `ViewSmoother`
- `tracker/ipc.py`: `MpvIpc` (Windows named pipe / Unix socket, `command/get/set_property/set_view`)
- `tracker/config.py`: `Config` (JSON yükle/kaydet), `tracker/main.py`: `ping`, `view` komutları
- `mpv/portable_config/`: `mpv.conf`, `input.conf` (t: aç/kapa, r: sıfırla), `scripts/track.lua` (iskelet)
- `.github/workflows/ci.yml` (ubuntu+windows, ruff+pytest), `build.yml` (tag `v*` veya elle: test → paket → mpv indir → portable ZIP → Inno Setup → artifact/release)
- `scripts/make_package.py`, `scripts/fetch_deps.ps1`, `installer.iss`, testler (13 test)

## Parça 2'de yapılanlar
- `track.lua`: `t` ile takip açılınca `MBTN_LEFT` zorunlu bağlanır (kapanınca kaldırılır). Tıklama → `osd-dimensions` (w,h,ml,mr,mt,mb) ile video-normalize (nx, ny) → `script-message track-click nx ny video_w video_h time-pos`. Video dışı tıklama yok sayılır. `track-toggle on|off` ve `track-reset` mesajları da gönderilir.
- `tracker/geometry.py`: `screen_to_video` (Lua'daki formülün Python eşi, testli; letterbox ve zoom'lu negatif margin durumları dahil).
- `tracker/clicks.py`: `ClickEvent` (nx, ny, vw, vh, time_pos; `px/py` piksel), `parse_click`, `message_name`.
- `tracker/ipc.py`: `command()` beklerken gelen olaylar kuyruğa alınır; `poll_event(timeout)` eklendi (Unix soketinde zaman aşımı destekli; Windows pipe'ında okuma bloklar → Parça 5'te olaylar ayrı bağlantı + iş parçacığına alındı).
- `tracker/main.py`: `listen [--follow-click] [--zoom Z]` komutu. Demo: tıklanan noktaya zoom yapar.
- Testler: 20 (yeni: ekran→video, clicks, IPC olay kuyruğu).

## Parça 3'te yapılanlar
- `tracker/detector.py`: `letterbox` (oran korur, gri 114 dolgu), `preprocess` (BGR→RGB, NCHW, 0..1, fp16 desteği), `nms` (numpy), `decode_yolo` (YOLOv8/YOLO11 `[1,4+nc,N]` ve `[1,N,4+nc]`; yalnızca person skoru; letterbox tersine çevirme, kare sınırına kırpma, <1 px kutuları atma, NMS, `max_det`), `select_providers` (auto: DirectML → CUDA → CPU; istenen yoksa CPU'ya düşer), `Detector` (ONNX Runtime oturumu; statik girdi boyutunu modelden okur, dinamikse `det_size`; DirectML için `enable_mem_pattern=False` + sıralı yürütme; model yoksa açıklayıcı `FileNotFoundError`; test için `session=` enjekte edilebilir), `Detection(bbox, score, cls)`.
- `tracker/config.py`: `model_path` (varsayılan `models/yolov8n.onnx`), `det_conf` 0.25, `det_iou` 0.45, `det_size` 640, `device` (auto|dml|cuda|cpu).
- `tracker/main.py`: `detect IMAGE [--model] [--conf] [--device] [--out]` komutu (mpv gerekmez; ısınma + süre + provider yazar, `--out` ile kutulu JPG). Ağır bağımlılıklar yalnızca bu komutta içe aktarılır, `ping/view/listen` numpy'siz çalışır.
- `requirements.txt`: numpy, opencv-python-headless, `onnxruntime-directml` (Windows) / `onnxruntime` (diğer platformlar).
- Testler: 45 (yeni: 25 — letterbox, preprocess, NMS, decode düzenleri/eşik/sınıf süzme/kırpma, provider seçimi, sahte oturumlu `Detector`).
- Sürüm 0.3.0.

## Elle deneme (Windows)
1. `dist\TakipliOynat\mpv\mpv.exe video.mp4` (IPC pipe: `\\.\pipe\mpv`)
2. Başka terminalde: `python -m tracker listen --follow-click`
3. mpv'de `t` → videoya sol tık → terminalde koordinat yazılır, görüntü o noktaya yakınlaşır. `r` sıfırlar.

## Kararlar / notlar
- mpv portable modda ayarları `mpv.exe` yanındaki **`portable_config/`** klasöründen okur; bu yüzden README'deki `mpv/mpv.conf` yerine `mpv/portable_config/mpv.conf` kullanıldı. Lua: `portable_config/scripts/`.
- pan matematiği: `video-pan` ölçeklenmiş video boyutunun oranı → hedefi ortalamak için `pan = 0.5 − c`, zoom'dan bağımsız. Merkez `[0.5/s, 1−0.5/s]` aralığına kıstırılır.
- Tıklama iletimi: mpv'nin `script-message` mekanizması; JSON IPC istemcileri bunu `client-message` olayı olarak alır (`args` string listesidir, sayılar Lua'da `string.format` ile gönderilir).
- Ağır bağımlılıklar (numpy, onnxruntime-directml, opencv) `requirements.txt`'e ilgili parçada eklenecek.
- mpv, shinchiro/mpv-winbuild-cmake son sürümünden indirilir (7z, runner'daki `7z` ile açılır).

## Doğrulama durumu
- Python testleri yerelde çalıştırıldı (45/45; pytest yüklenemediği için basit uyumluluk katmanıyla). `ruff` ve GitHub Actions hâlâ **gerçek ortamda çalıştırılmadı** (satır uzunluğu ≤100 elle kontrol edildi).
- Parça 3: gerçek onnxruntime (CPU) ile elle üretilmiş küçük ONNX modeliyle oturum açma, girdi boyutu okuma ve `detect` CLI akışı denendi. **Gerçek YOLOv8/YOLO11 modeliyle ve DirectML ile denenmedi** (ortamda model/GPU yok). Windows'ta ilk iş: `python -m tracker detect kare.jpg --model models/yolov8n.onnx --out sonuc.jpg` ile kutuların doğru yerde olduğunu ve `provider=DmlExecutionProvider` yazdığını doğrula. Çıktı `[1,84,8400]` değilse (ör. NMS gömülü / YOLOv10 `[1,300,6]`) `decode_yolo` uyarlanmalı.
- **`track.lua` çalıştırılmadı** (Parça 2'den kalan). Gerçek mpv'de doğrula: `osd-dimensions` alanlarının zoom/pan sonrası doğruluğu, `mp.get_mouse_pos()`, `script-message`'in IPC'de `client-message` olarak görünmesi.
- `fetch_deps.ps1` ve `installer.iss` Windows'ta denenmedi.
- Windows CI artık `onnxruntime-directml` kuruyor (GPU'suz runner'da CPU provider'a düşer); sorun çıkarsa `ci.yml`'de CPU `onnxruntime` kur.

## Parça 4'te yapılanlar
- `tracker/bytetrack.py`: `linear_assignment` (saf numpy Macar, dikdörtgen destekli; scipy eklenmedi), `iou_matrix`, `match`, `KalmanBox` (cx,cy,a,h + hızlar, sabit hız), `ByteTracker.update(list[Detection]) -> list[Track]` (yüksek skor → IoU eşleşme; kalan izler düşük skorlularla 2. aşama; yalnızca eşleşmeyen yüksek skorlu tespit yeni ID alır; `max_lost` sonrası silinir). `Track(id,bbox,score,age,lost)`. Dönüş yalnızca o karede görülenleri içerir; kayıp izler `lost_tracks` (tahmini konum, Parça 8 için).
- `tracker/pipeline.py`: `Pipeline(detector, tracker).step(frame_bgr) -> list[Track]`, `reset()`.
- Varsayılanlar: high 0.5, low 0.1, match_iou 0.3, second_iou 0.5, max_lost 30 (kare). Canlı modda detector `det_conf` (0.25) low_thr'den büyükse düşük skor aşaması çalışmaz → Parça 5'te `det_conf`'u ~0.1'e çek.
- Testler: `tests/test_bytetrack.py` (9: Macar, IoU, ID kalıcılığı, iki nesne, kısa/uzun kayıp, düşük skor, yeni ID, pipeline). Sürüm 0.4.0.
- Doğrulama: yalnızca sentetik kutularla; gerçek video/modelle denenmedi. `unconfirmed_iou`, `min_hits` parametreleri ayrılmış ama henüz kullanılmıyor (min_hits yalnızca çıktı süzer).

## Parça 5'te yapılanlar
- `tracker/frames.py`: `decode_raw` (screenshot-raw `{w,h,stride,format,data}` → BGR; base64 metni veya sayı listesi; `bgr0`/`bgra`; stride dolgusu atılır; bozuk/eksik veri → `ValueError`), `grab_frame(mpv)` (`screenshot-raw video bgr0`: altyazı/OSD'siz, zoom'suz tam çözünürlük kare).
- `tracker/live.py`: `LiveController` (IO'suz mantık: `handle_event`, `needs_frame`, `step`), `pick_track` (tıklanan noktayı içeren, merkezi en yakın iz; **basit**, Parça 6'da genişlet), `EventListener` (olayları AYRI IPC bağlantısında iş parçacığıyla okur), `run_live` (döngü).
  - Davranış: `track-toggle on|off`, `track-reset`, `track-click` işlenir; kapanınca/sıfırlanınca görünüm `View()` (1x) olur. Tıklama ilk işlenen karede hedef ID'ye çevrilir (OSD: "Hedef: ID n" / "Burada kişi yok"). Hedef görünürken `compute_view` → `ViewSmoother` → `set_view` (değişmediyse gönderilmez). Hedef kaybolursa son görünümde bekler ("Hedef kayboldu" bir kez; kayıp yönetimi Parça 8).
  - Senkron: her turda önce `time-pos` okunur, sonra kare alınır. Duraklatılmışken (time-pos değişmiyor) kare işlenmez; bekleyen tıklama varsa işlenir. Atlama (geri gitme veya `seek_jump` sn'den fazla ileri) → `pipeline.reset()`, hedef bırakılır, görünüm 1x, OSD "Atlama: hedefi yeniden seç". Dosya yokken `property unavailable` (`MpvCommandError`) döngüyü bozmaz; bağlantı kapanınca temiz çıkış.
  - Hız: `live_fps` (10) ile sınırlı; geride kalınırsa kuyruk birikmez (her tur o anki kareyi alır). `--stats SN` hız/gecikme yazar.
- `tracker/ipc.py`: **Windows pipe'ında okuma byte byte yapılıyordu** (büyük kare satırında çok yavaş) → 64 KB'lık parça okuma + `bytearray` tampon; Unix'te de her turda tamponu baştan taramak yerine kalan kısım taranır (MB'lık satırlar). `MpvCommandError(MpvIpcError)` eklendi; `MpvIpc(keep_events=False)` ile olay okumayan komut bağlantısında kuyruk şişmez.
- `tracker/config.py`: `live_det_conf` 0.1 (detector eşiği = ByteTrack `low_thr`; Parça 4 notu giderildi), `live_fps` 10, `seek_jump` 2.0.
- `tracker/main.py`: `live [--model] [--device] [--fps] [--stats SN]` komutu (Detector + ByteTracker + Pipeline + dinleyici + `run_live`). Sürüm 0.5.0.
- Testler: 68 (yeni 23: decode_raw, pick_track, denetleyici akışları, `run_live` uçtan uca sahte mpv ile, 1280x720 kareyle gerçek Unix soketi turu).
- Kasıtlı olarak yapılmayanlar: ffmpeg kare kaynağı (yalnız screenshot-raw), gecikme telafisi/lookahead (Parça 7), kayıp yönetimi (Parça 8), "her N karede bir tespit" (CPU modu; gerekirse Parça 7-8 ile).

## Parça 6'da yapılanlar
- `live.pick_track(tracks, px, py, tol=0)`: nokta kutu içindeyse kutu boyutuna göre normalize merkez uzaklığı en küçük olan (çakışan/iç içe kutuda küçük kutu seçilebilir; eşitlikte küçük alan); içinde değilse kenara `tol` px içindeki en yakın iz.
- `Config.pick_tol` (0.03): tolerans, kare yüksekliği oranı (`LiveController.step` px'e çevirir).
- Tıklama davranışı (`LiveController.step`): yeni kişi → hedef değişir (yumuşatıcı sıfırlanmaz: görünüm yeni hedefe kayar; ilk seçimde sıfırlanır); hedefin üstüne tekrar tıklama → bırak (OSD "Hedef bırakıldı", görünüm 1x, takip açık kalır); boş yere tıklama → mevcut hedef korunur, OSD "Burada kişi yok".
- Tuş: `x` → `track/release` (Lua) → `script-message track-release` → `clicks.RELEASE_MSG`; hedef yoksa OSD "Bırakılacak hedef yok"; bekleyen tıklama düşürülür.
- Testler: 76 (yeni 8). Sürüm 0.6.0.
- Kasıtlı olarak yapılmayanlar: tıklama anındaki kareye geri dönük eşleme (`click.time_pos` ile; canlıda gecikme küçük), çoklu hedef.

## Parça 6 sonrası düzeltme
- `scripts/make_package.py` 0 bayt (boş) çıkmıştı → yeniden yazıldı: `dist/TakipliOynat` içine `tracker/`, `mpv/portable_config/`, `models/`, `requirements.txt`, `README.md`, `VERSION` kopyalar (mpv.exe'yi `fetch_deps.ps1` ekler). Yerelde çalıştırıldı (20 dosya).
- Tüm dosyalar yeniden gözden geçirildi: `run_live.emit` artık `MpvCommandError`'da (set_view/show-text reddi) döngüyü bitirmiyor, loglayıp sürdürüyor (+1 test → 77/77); `bytetrack.py`'deki ölü `rest2` kodu silindi; README dosya yapısı/yol haritası gerçeğe göre güncellendi (`portable_config`, 15 parçalık plan).

## Parça 7'de yapılanlar
- `tracker/smooth.py`: `Kalman1D` (zaman tabanlı sabit hız süzgeci: durum konum+hız, `predict(dt)` sn, beyaz ivme süreç gürültüsü, saf Python) ve `BoxFilter` (hedef kutusunun cx, cy, w, h kanallarını süzer; `update(bbox, t) -> BBox`, `lookahead(ahead_s, max_lead) -> BBox` = merkez hızı × süre kadar ileri öteleme, eksen başına ±max_lead; boyut kanalları `size_ratio`=0.2 ile daha yumuşak; geri atlama veya `max_gap`=1 sn'den uzun boşlukta ölçümden yeniden başlar; `reset`, `velocity`, `active`). `ViewSmoother` (dead-zone + EMA) değişmedi, süzgeçten SONRA çalışır.
- `tracker/geometry.py`: `BBox.scaled(sx, sy)`.
- `tracker/live.py`: `LiveController` içinde hedef kutusu kareye göre normalize (0..1) edilip `BoxFilter`'dan geçer, lookahead'li kutu `compute_view`'a verilir. Süzgeç; yeni hedef seçilince, hedef bırakılınca, sıfırlama/kapatma/atlamada sıfırlanır (eski hedefin hızı taşınmaz). Hedef kayıpken güncellenmez (Parça 8 kayıp yönetimi bunu kullanacak).
- `tracker/config.py`: `lookahead_s` 0.15 (0 = kapalı), `max_lead` 0.15, `kf_accel` 0.5, `kf_meas` 0.01 (birimler kare boyutuna göre normalize).
- Testler: 89 (yeni 12: Kalman hız öğrenme/durağan/gürültü azaltma/dt≤0, BoxFilter geçiş-lookahead-sınır-yeniden başlatma, `scaled`, denetleyicide lookahead hareketli hedefi öne alır / durağanda etkisiz, hedef değişince-bırakınca süzgeç sıfırlanır). Sürüm 0.7.0.
- Kasıtlı olarak yapılmayanlar: ByteTrack içindeki `KalmanBox` yeniden kullanılmadı (o kare tabanlı ve piksel birimli; canlıda kare aralığı değişken olduğundan ayrı zaman tabanlı süzgeç yazıldı); kayıp hedef için tahmin/coast (Parça 8); lookahead süresinin gerçek gecikmeye göre otomatik ayarı.
- Doğrulama: yalnızca sentetik hareketle (yerelde 89/89, pytest yerine basit uyumluluk katmanı). Varsayılan değerler (`lookahead_s`, `kf_accel`, `kf_meas`) gerçek maç videosunda **ayarlanmadı**; Windows'ta `live --stats 2` ile gecikmeye bakıp `lookahead_s`'i ~ (ölçülen gecikme + EMA gecikmesi) civarına getir. Yüksek hızda görüntü hedefin önüne geçerse `lookahead_s`'i düşür.

## Parça 8'de yapılanlar
- `LiveController._on_lost(t, osd)` (hedef bu karede yok): kaybın ilk karesinde OSD "Hedef kayboldu" ve o anki görünüm (`_lost_from`) kaydedilir. `lost_hold_s` (1.0 sn) boyunca görünüm DEĞİŞMEZ (bekle); sonra `lost_zoomout_s` (2.0 sn) içinde `ease_view` (smoothstep) ile `View()` (1x, pan 0) değerine iner. Süre **video zamanıyla** (`t`) ölçülür: duraklatmada ilerlemez, kare hızına bağlı değildir. `lost_zoomout_s <= 0` → bekleme sonrası anında 1x.
- Zoom-out bitince hedef ID korunur (1x'te bekler); ByteTrack aynı ID'yi `max_lost` kare içinde geri getirirse (bekleme/zoom-out sırasında ya da sonrasında) takip kaldığı yerden sürer. Hedefi yeniden seçmek için tıkla; `x`/`r`/atlama durumu temizler.
- Sıçramasız dönüş: zoom-out başladıysa ve hedef geri gelirse (ya da zoom-out'tayken başka kişi seçilirse) `ViewSmoother.seed(self._view)` yumuşatıcıyı o anki görünüme kurar → görüntü eski yakın plana ışınlanmaz, kayarak gider. Bekleme sırasında geri gelirse görünüm zaten sabittir, seed gerekmez.
- `tracker/smooth.py`: `ease_view(a, b, p)` (zoom log2 uzayında doğrusal; pan doğrusal → 1x'e inerken kenar boşluğu görünmez, çünkü izinli pan aralığı zoom'un içbükey fonksiyonu), `ViewSmoother.seed(view)`.
- `tracker/live.py`: `_view` (son istenen görünüm), `_lost_t0/_lost_from/_zooming_out`, `_clear_lost()`; `_reset_tracking`/`_release` hepsini temizler.
- `tracker/config.py`: `lost_hold_s` 1.0, `lost_zoomout_s` 2.0.
- Testler: 97 (yeni 8: bekle→zoom-out→1x zaman çizelgesi, 0 süreli anında zoom-out, video zamanı/kare sayısı, zoom-out'ta geri dönüş sıçramaz, zoom-out'ta yeni hedef sıçramaz, release temizliği, `ease_view`, `seed`). `ruff check` temiz. Sürüm 0.8.0.
- Kasıtlı olarak yapılmayanlar: kayıp sırasında konum tahmini ("coast", Kalman ile ileri götürme) — bekleme sırasında görünüm sabit kalıyor (futbolda kısa örtüşmelerde kamera kaymasın diye); gerekirse `BoxFilter.update` zaten `max_gap` (1 sn) içinde hızla tahmin eder, yani geri dönüşte süzgeç tutarlıdır. Zoom-out sonrası hedefi otomatik bırakma yok (Parça 11 Re-ID ile birlikte düşünülecek). `lost_hold_s` + `lost_zoomout_s` (3 sn) varsayılan olarak ByteTrack `max_lost` (30 kare ≈ 3 sn @10 fps) ile aynı mertebede seçildi; `live_fps` değişirse ikisini birlikte ayarla.
- Doğrulama: yalnızca sentetik izlerle (yerelde 97/97, gerçek pytest ile — bu oturumda pytest kullanılabildi; ruff temiz). Gerçek videoda süreler (bekleme 1 sn, zoom-out 2 sn) **ayarlanmadı**.

## Parça 9'da yapılanlar
- `tracker/offline.py` (şema başında dokümante, sürüm 1): `{"version","video":{path,w,h,fps,duration},"sample_fps","samples":[{"t","d":[[id,x1,y1,x2,y2,skor]...]}],"target":{"id"}|null,"views":[[t,zoom,pan_x,pan_y]...]}`; koordinatlar kare boyutuna normalize, zaman video zamanı. `views` mpv `video-zoom`/`video-pan-x/y` değerleridir (Parça 10 Lua `time-pos`'a göre doğrusal interpole eder); sabit duran yinelenen anahtar kareler seyreltilir (ilk/son kare hep kalır).
- `VideoSource(path, fps)`: cv2.VideoCapture, `grab` ile atlayıp yalnızca örneklenen kareyi çözer (t = kare_no/kaynak_fps; **sabit kare hızı (CFR) varsayımı**). `run_detection(frames, pipeline)` → örnekler. `load_doc/save_doc` (sürüm doğrulamalı), `list_tracks`, `pick_target_id(doc, t, nx, ny)` (`pick_track` ile; en yakın örnek).
- `build_views(doc, id, cfg)` **nedensel değil**: (1) `offline_interp_s` (0.6 sn)'den kısa kayıplar doğrusal doldurulur; (2) kesintisiz parçalarda kutu (cx,cy,w,h) sıfır-faz (ileri+geri EMA, `smooth_zero_phase`) yumuşatılır → gecikme/lookahead gerekmez → `compute_view`; (3) uzun kayıpta Parça 8 mantığı: `lost_hold_s` bekle, `lost_zoomout_s` ile 1x'e in, hedef dönmeden `lost_zoomout_s` önce zoom-in'e başla (ease_view); başlangıç/bitiş boşlukları 1x. Hedef hiç yoksa 1x iki anahtar kare.
- CLI: `offline VIDEO [--out] [--model] [--device] [--fps] [--target-id N | --click SN NX NY]` (hedef verilmezse en uzun izleri listeler), `offline-view JSON [--list] [--target-id|--click] [--out]` (tespitsiz yeniden hedefleme: pahalı kısım bir kez).
- Config: `offline_fps` 10, `offline_interp_s` 0.6, `offline_alpha` 0.4.
- Testler: 109 (yeni 12: tespit normalizasyonu, şema gidiş-dönüş/doğrulama, list/pick, sıfır-faz gecikmesizliği, gecikmesiz takip, kısa/uzun kayıp zaman çizelgesi, zoom monotonluğu ve kenar boşluğu görünmemesi, hedef yok/başlangıç boşluğu, dedupe, CLI, gerçek AVI ile VideoSource). `ruff check` temiz. Sürüm 0.9.0.
- Kasıtlı olarak yapılmayanlar: `track.json`'u sıkıştırma/parçalama (2 saatlik video @10 örnek/sn × ~20 iz ≈ onlarca MB olabilir; Lua yalnızca `views`'i okuyacaksa ayrı küçük dosya `*.views.json` düşünülebilir → Parça 10'da karar ver); ByteTrack'in `max_lost`'u (30 örnek) ve `offline_fps` ilişkisi; değişken kare hızlı (VFR) videoda zaman kayması; ffmpeg kaynağı; çoklu hedef.
- Doğrulama: sentetik izler + küçük MJPG AVI; `offline` komutu gerçek YOLO modeliyle/DirectML'le ve gerçek maç videosuyla **denenmedi** (model yoksa `HATA` ile temiz çıkış denendi). Yumuşatma katsayıları (`offline_alpha`) ayarlanmadı.

## Parça 10'da yapılanlar
- Python: hedef seçilince `offline`/`offline-view` ayrıca küçük **`<video>.views.json`** yazar (`views_path`: `x.mp4.track.json` → `x.mp4.views.json`; `save_views`: yalnız version/video.path/target/views; `samples` yok → Lua büyük JSON ayrıştırmaz). `offline.view_at(views, t)` = Lua formülünün Python referansı.
- `track.lua`: `o` (`script-binding track/offline`) → `<video yolu>.views.json` (yoksa `.track.json`) okunur (`utils.parse_json`; sürüm/boş `views` denetimi, sebep OSD'de), anahtar kareler paralel dizilere alınır. `mp.observe_property("time-pos")` → ikili arama + doğrusal interpolasyon (`view_at`) → `video-zoom/pan-x/pan-y`; değişim <1e-4 ise atlanır. Duraklatmada seek'te de çalışır. URL/akışta devre dışı. `file-loaded`'da yan dosya varsa OSD ipucu; `end-file`'da offline kapanır.
- Canlı/offline karşılıklı dışlayıcı: `t` açılınca offline kapanır (`set_enabled` → `set_offline(false)`); `o` açılınca canlı kapanır ve Python'un async 1x sıfırlaması araya girmesin diye 0.5 sn sonra görünüm yeniden uygulanır. `r` her ikisini sıfırlar. Kod Lua 5.1/LuaJIT uyumlu (// ve goto yok).
- Testler: 114 (yeni 5). `tests/lua_harness.lua` + `tests/test_lua_offline.py`: `track.lua` sahte `mp` ile **gerçekten çalıştırılır** (texlua/lua/luajit varsa; yoksa atlanır) ve her `time-pos` için Lua çıktısı Python `view_at` ile birebir karşılaştırılır; canlı↔offline geçişi, zamanlayıcı, end-file, dosya yok durumu. `texluac -p` sözdizimi temiz. `ruff` temiz. Sürüm 0.10.0.
- Doğrulama: **gerçek mpv'de denenmedi**: `utils.parse_json`'ın büyük `.track.json`'da hızı/bellek tüketimi, `time-pos` gözlemcisinin oynatma sırasında gerçekten kare başı gelip gelmediği ve `video-pan` ayarının akıcılığı Windows'ta bakılmalı. Akıcı değilse: gözlemci yerine `mp.add_periodic_timer(1/60)` ya da anahtar kare yoğunluğunu artır (şu an `offline_fps`=10 örnek/sn; mpv iki anahtar kare arasında doğrusal ilerler).
- Kasıtlı olarak yapılmayanlar: Lua'da hedef seçimi/`--click` (hedef Python'da seçilir); birden çok hedef/profil dosyası; `.views.json`'u otomatik açma (yalnız ipucu); anahtar kareler arası easing (doğrusal yeterli: kareler zaten yumuşatılmış).

## Parça 11'de yapılanlar
- `tracker/reid.py`: `Embedder` (OSNet ONNX; 256x128, ImageNet ortalama/std, RGB; dinamik batch ya da sabit batch=1 → tek tek; sabit batch>1 → `ValueError`; model yoksa açıklayıcı `FileNotFoundError`; `session=` enjekte edilebilir; kırpılamayan kutu → sıfır satırı; çıktı L2-normalize), `crop_ok` (boyut ≥ `reid_min_h`, kare kenarında kesik değil, başka kutuyla IoU < `reid_max_iou`: kirli embedding'i engeller), `Gallery` (≤8 görünüm; ≥0.95 benzer olan EMA ile birleşir), `ReIdManager` (canlı), `TrackletBank` + `link_ids` (offline).
- **Canlı** (`live --reid`): hedef görünürken `observe` galeriyi besler (video zamanıyla `reid_every_s`=0.3 sn). Hedef ID'si yokken `_try_reid`: aday = hedef son görüldüğündeki en büyük ID'den (`_id_mark`; ByteTrack ID'leri artar) **büyük** ID'li, `age ≥ reid_min_age` izler → galeriye kosinüs ≥ `reid_thres` (0.6) ve ikinciye marj ≥ `reid_margin` (0.05) ise `target_id` yeni ID'ye taşınır, `BoxFilter` sıfırlanır, OSD "Hedef yeniden bulundu: ID n". Mevcut Parça 8 akışı devralır (zoom-out'tayken bulunursa yumuşatıcı seed'lenir → sıçrama yok). Yeni hedef seçimi/bırakma/sıfırlama/atlama galeriyi sıfırlar. Eski ID'li izler (ID switch değil, başka oyuncu) kasıtlı olarak aday değildir.
- **Offline** (`offline --reid`): `TrackletBank` her izin ilk 3 ve son 3 (uygun) görünümünün ortalama embedding'ini `doc["emb"]`'e yazar (`{id: {first,last}}`, ×100 tamsayı; kompakt). `offline-view` kayıtlı `emb` varsa `link_ids` ile hedef izi zincirler: sonraki iz hedef iz bittikten sonra doğmalı (≤ `reid_link_gap_s`=20 sn), son↔ilk kosinüs ≥ eşik + marj; geriye ve ileriye uzar. `doc["target"] = {"id", "linked": [...]}`; `build_views` artık ID kümesi alır (aynı örnekte birden çok kimlik → en yüksek skor). `--no-link` ile kapanır.
- Config: `reid_model` ("models/osnet_x0_25.onnx"), `reid_thres`, `reid_margin`, `reid_every_s`, `reid_gallery`, `reid_min_h`, `reid_max_iou`, `reid_min_age`, `reid_min_samples`, `reid_link_gap_s`.
- Testler: 133 (yeni 19, `tests/test_reid.py`): ön işleme, kırpma sınırları, Embedder (batch/sabit batch/normalizasyon/hata), Gallery, crop_ok, yönetici eşik/marj/hız sınırı/sıfırlama, canlı yeniden bağlama (Re-ID yok → bağlama yok; farklı görünüm → yok; eski ID → aday değil; zoom-out'ta sıçramasız), offline kompakt çıktı, zincirleme (ileri/geri/boşluk/belirsiz), `apply_target` + `build_views`, CLI `--no-link`. Sahte embedder ortalama renk kullanır. `ruff` temiz. Sürüm 0.11.0.
- Doğrulama: **gerçek OSNet modeliyle denenmedi** (ortamda model/ağ yok). Windows'ta: modeli `models/`'e koy, `live --reid --stats 2` ile gecikmeye bak; `reid_thres` OSNet x0.25 için tahminî (0.6) — gerçek maçta aynı formalı oyuncularla karışma/kaçırma oranına göre ayarla. Modelin çıktısı `[N, D]` olmalı (`[N, D, 1, 1]` gelirse `Embedder` reshape ile düzleştirir). Offline'da bağlı izlerin ardışık görünümü uzamsal makullük (hız/mesafe) denetlemez.
- Kasıtlı olarak yapılmayanlar: uzamsal kapı (yeni ID, hedefin son konumuna/hızına makul uzaklıkta mı); aynı ID içinde ID-switch düzeltmesi (hedefin ID'si başka oyuncuya geçerse); embedding'i takım rengi/forma ile birleştirme (Parça 12); OSNet modeli dağıtımı/lisansı (torchreid MIT; ağırlıklar için Parça 15'te denetle).

## Parça 12'de yapılanlar
- `tracker/team.py`: `team_feature` (kutunun üst gövdesi: y %18–52, x %25–75; HSV; saha yeşili H35–85/S≥50 maskeli; 12 ton kutusu + siyah/gri/beyaz = 15 boyut; karekök + L2), `kmeans2` (deterministik, MIN_SEP=0.15 altında "tek takım" → None), `assign` (marj < `team_margin` → belirsiz None), `TeamClassifier` (canlı; `team_min_samples`'ta ilk kez, sonra `team_refit` özellikte bir yeniden kümeler), `TeamBank` (offline; iz başına ortalama özellik → `doc["team"] = {centers, labels:{id: 0|1}}`, belirsiz iz etiketsiz).
- **Takım yalnızca eleme yapar**: hedef ve aday etiketi biliniyor ve farklıysa aday elenir; belirsiz/bilinmiyorsa elenmez. Hedefin takımı etiketle değil özelliğiyle (EMA) saklanır (yeniden kümelemede etiket 0/1 yer değiştirebilir). Takım modeli hedef değişince sıfırlanmaz (sahne özelliği); hedef özelliği ve numara oyları sıfırlanır.
- Forma numarası: ağır OCR bağımlılığı **eklenmedi**. `tracker/number.py`: `NumberReader` (isteğe bağlı küçük ONNX sınıflandırıcı; sözleşme: girdi [N,C,H,W] C=1/3, 0–1; çıktı [N,101]: 0–99 numara, 100 = yok; `models/jersey_number.onnx`; model dağıtılmaz, yoksa açıklayıcı `FileNotFoundError`), `NumberVoter` (güven ağırlıklı oy; `number_min_votes`=3, `number_share`=0.6). Hedefin numarası oylamayla kesinleşirse farklı numaralı aday elenir; aday numarası okunamıyorsa elenmez.
- Entegrasyon: `ReIdManager(embedder, cfg, team=None, numbers=None)`. `match` sırası: crop_ok → takım → numara → embedding/eşik+marj (marj artık elenmiş adaylar arasında ölçülür; yanlış takımdaki benzer oyuncu marjı bozmaz). Offline: `run_detection(..., team=TeamBank)`, `make_doc(..., team=)`, `link_ids` farklı takım etiketli adayı atlar.
- CLI: `live --reid --team [--number]` (`--team/--number` tek başına → hata kodu 2), `offline --team` (Re-ID'siz de etiket yazar; zincirleme için `--reid` de gerekir). Config: `team_min_samples`, `team_refit`, `team_margin`, `team_min_px`, `number_model`, `number_conf`, `number_min_votes`, `number_share`.
- Testler: 145 (yeni 12, `tests/test_team.py`; sahte `ConstEmbedder` Re-ID'yi kör eder, yalnız takım/numara ayırır). `ruff` temiz. pytest/ruff bu oturumda kuruldu ve gerçekten çalıştırıldı. Sürüm 0.12.0.
- Doğrulama: **gerçek maç görüntüsünde ve gerçek numara modeliyle denenmedi.** Windows'ta bak: `team_margin` (0.15) ve üst gövde bölgesi gerçek kamera açılarında/uzak planlarda yeterli mi; aynı renk forma + kaleci/hakem durumu (k=2 hakemi bir takıma katabilir → yalnız belirsizse elenmez, yani zarar değil kayıp fırsat); `team_min_px` (100) uzak oyuncuda sık None veriyor mu (küçük kutu → özellik yok → elemez). Numara modeli için sözleşme `number.py` başında; ayrı eğitilmesi gerekir.
- Kasıtlı olarak yapılmayanlar: hakem/kaleci için ayrı üçüncü küme; takım rengini embedding'e katmak (yalnız eleme); numara eşleşmesiyle `reid_thres`'i gevşetmek; `--list` çıktısında takım/numara gösterimi; ağır OCR bağımlılığı (installer boyutu; Parça 14'te model dağıtımı/lisansı ayrıca düşünülür).

## Parça 13'te yapılanlar
- **Canlı ayar tuşları** (`input.conf` → `track.lua` → `script-message track-setting <anahtar> <+1|-1|0>` → `LiveController._on_setting`): `Ctrl+↑/↓` doluluk (`target_fill`, ±0.05, 0.10–0.80), `Ctrl+→/←` tepki hızı (`alpha_pos` ve `alpha_zoom` birlikte ×1.25 / ÷1.25; `alpha_pos` 0.03–0.60), `Ctrl+PgUp/PgDn` öngörü (`lookahead_s` ±0.05, 0–0.6), `Ctrl+0` hepsini varsayılana, `Ctrl+S` ayarları config JSON'a kaydet (`track-save`; mpv'nin varsayılan Ctrl+S'sini geçersiz kılar), `h` durum özeti (tüm ayarlar + hedef), `Ctrl+H` etiketi gizle/göster. Mantık `tracker/settings.py` (`adjust`, `reset_all`, `status_text`); sınırda "(üst/alt sınır)" OSD'si. `ViewSmoother.set_alpha` durumu bozmadan katsayıyı değiştirir; `target_fill`/`lookahead_s` zaten her karede cfg'den okunur → bir sonraki karede etkili.
- **Kaydetme**: `run_live(..., cfg_path)`; CLI `--config` verildiyse oraya, yoksa çalışma klasöründeki `tracker_config.json`'a yazar. Yazma hatası OSD'de görünür, döngü durmaz.
- **HUD etiketi** (sağ üst, ASS overlay): Python durum değişince `script-message-to track track-hud <metin>` yollar ("Takip: hedef seç (tıkla)" / "Takip: ID n" / "Takip: hedef kayıp" / "... (uzaklaşıyor)"; takip kapalı → boş); yalnız metin değişince gönderilir. Lua offline açıkken kendisi "Takip: offline ID n" gösterir; canlı kapanınca/`end-file`'da temizlenir. ASS kaçış karakterleri ({ } \ satır sonu) temizlenir. `cfg.hud=False` ile kapanır. Kaydetmeden gelen yeni `hud` alanı config'e eklendi.
- Testler: 154 (yeni 9, `tests/test_settings.py`; Lua tarafı için ortak `tests/lua_mp_stub.lua` + `tests/lua_harness_hud.lua`; eski offline harness ortak stub'a taşındı, çıktısı değişmedi). `ruff` temiz. Sürüm 0.13.0.
- Doğrulama: **gerçek mpv'de denenmedi**: `create_osd_overlay` etiketinin yazı tipi/boyutu (`\\fs20`) akıllı tahtada okunaklı mı, `ctrl+up/down/left/right` ve `ctrl+pgup/pgdwn`'in Pardus/mpv sürümünde başka bir şeye bağlı olup olmadığı, `script-message-to track` istemci adının gerçekten "track" olduğu (`track.lua` dosya adından türer). Ayar tuşları yalnız Python canlı modu çalışırken etki eder (offline oynatmada yok; Lua bunu bilemez, geri bildirim vermez).
- Kasıtlı olarak yapılmayanlar: ayrı bir ayar penceresi/GUI (tuşlar + JSON yeterli sayıldı); offline oynatmada ayar; `det_conf`, `lost_hold_s`, Re-ID eşikleri gibi ince ayarların tuşları (config dosyasından); ayarın mpv yeniden başlatmada otomatik yüklenmesi (`--config tracker_config.json` ile).

## Parça 14'te yapılanlar
- `scripts/build_embedded.py` (CI'da, Windows): python.org 3.11.9 embeddable (amd64) indirilip `dist/TakipliOynat/python/`'a açılır; `pythonXY._pth` yamalanır (`import site` açık + `..` yola eklenir → `python -m tracker` uygulama kökünden çalışır; gömülü Python PYTHONPATH/cwd'yi yok sayar), get-pip ile pip kurulur, `requirements.txt` (Windows'ta **onnxruntime-directml**) içine kurulur, sonra `prune` (`__pycache__`, `tests`/`test`/`testing`, `.pyc`, pip/setuptools/wheel/pkg_resources) ile boyut düşürülür. `patch_pth` ve `prune` saf mantık, Linux'ta testli. `--no-install` yalnız Python'u açar.
- Başlatıcılar (`launcher/`, paketlenirken CRLF'ye çevrilir): `Baslat.bat` (mpv'yi `pseudo-gui` ile açar, `python -m tracker --config %APPDATA%\TakipliOynat\config.json live --wait 30 --stats 5`; `models\osnet_x0_25.onnx` varsa `--reid --team`, `jersey_number.onnx` de varsa `--number` eklenir; video sürükle-bırak çalışır; yolov8n.onnx yoksa anlaşılır hata), `Offline.bat` (video sürükle → `offline` → ID sor → `offline-view --target-id` → mpv; `o` ile aç). Config `%APPDATA%`'da: Program Files'a yazma sorunu yok, kaldırmada silinmez; `Ctrl+S` buraya yazar.
- Yeni: `tracker.ipc.wait_for_ipc` + `live --wait SN` (mpv'nin pipe'ı açılana kadar 0.5 sn arayla dener; başlatıcıda izleyici mpv'den önce açılırsa düşmesin). `Config` dosyası yoksa (`--config` verilse bile) varsayılanla başlar; `Config.save` üst klasörü oluşturur.
- `installer.iss` tam sürüm: `MinVersion=10.0.18362` (DirectML için Win10 1903+), x64, `lzma2/max`, Türkçe (`Turkish.isl`), `PrivilegesRequiredOverridesAllowed=dialog`, kısayollar (canlı / offline / modeller klasörü / masaüstü isteğe bağlı), `models\*.onnx` kurulumdan dışlanır (lisans: AGPL modeller dağıtılmaz) ve `models` kaldırmada silinmez, `MODELLER.txt` bilgi dosyası. `models/MODELLER.txt`: hangi modeller nereden/nasıl.
- `build.yml`: test → paket → **gömülü Python** → mpv → **duman testi** (`python -m tracker --version`; `import numpy, cv2, onnxruntime`; `DmlExecutionProvider` mevcut olmalı; `detect --help`) → zip → installer. DirectML varsayılanı: `device="auto"` zaten DirectML → CUDA → CPU sırasıyla seçer.
- Testler: 164 (yeni 10, `tests/test_packaging.py`: `_pth` yaması, prune, Python/DirectML sabitleri, `make_package` çıktısı + CRLF, başlatıcı içerikleri, installer'daki dosya referansları, workflow adım sırası, `wait_for_ipc`, eksik config, `--wait` hatası). `ruff` temiz. Sürüm 0.14.0.
- Doğrulama: **Windows'ta, CI'da ve gerçek installer'la hiç çalıştırılmadı** (bu ortam Linux; indirme/kurulum adımları, ISCC derlemesi, `Turkish.isl` varlığı, `.bat`'lerin cmd.exe'de davranışı, DirectML provider'ın runner'da listelenmesi doğrulanmadı). İlk CI koşusunda şunlara bak: embeddable Python'a pip kurulumu (`get-pip` + `_pth`), `opencv-python-headless`/`onnxruntime-directml` cp311 tekerlekleri, installer boyutu (tahmin: ~200–300 MB hedefi aşılabilir; aşılırsa opencv/onnxruntime paketlerini incele), `prune`'un çalışma zamanını bozup bozmadığı (duman testi yakalar). Kurulumdan sonra `Baslat.bat`'ı elle dene.
- Kasıtlı olarak yapılmayanlar: indirilen Python/get-pip/mpv için sağlama toplamı (SHA256) doğrulaması (Parça 15 tedarik zinciri denetimi); mpv sürümünü sabitleme (`fetch_deps.ps1` hâlâ "latest"); kod imzalama; modelleri installer içinde indirme; Python'a `tracker`'ı .pyc/zip olarak derleme.

## Doğrulama durumu (Parça 5; Parça 6-7 için de geçerli)
- Parça 6: testler yerelde 76/76 (aynı uyumluluk katmanı); `track.lua`'daki `release` bağı ve `x` tuşu gerçek mpv'de denenmedi.
- Testler yerelde 68/68 (pytest yüklenemediği için basit uyumluluk katmanıyla). `ruff` ve GitHub Actions yine **çalıştırılmadı** (satır ≤100 ve kullanılmayan import elle kontrol edildi). Yüklenen arşivde `.github/workflows/` (git'te kayıtlı) çalışma klasöründen silinmişti ve `pyproject.toml`'daki `pythonpath = ["."]` satırı eksikti (CI'da `import tracker` için gerekli); ikisi de git HEAD'den geri yüklendi.
- **Gerçek mpv ile denenmedi**: `screenshot-raw`'ın JSON IPC'de base64 `data` döndürdüğü, 1080p karede IPC hızı (kare başı ~8 MB bayt → ~11 MB base64) ve `live_fps` 10'un tutup tutmadığı Windows'ta doğrulanmalı. Yavaşsa: ffmpeg kare kaynağı veya mpv'de küçültülmüş kare (ör. `vf` ile) düşün.
- Windows'ta iki IPC bağlantısı (komut + olay) birlikte açılıyor; mpv'nin pipe sunucusunda çoklu istemci beklenen davranış ama denenmedi.
- Elle deneme: `dist\TakipliOynat\mpv\mpv.exe video.mp4` → ayrı terminalde `python -m tracker live --stats 2` → mpv'de `t`, oyuncuya sol tık; `r` sıfırlar.

## Notlar (devam)
- Lisans notu (Parça 15): Ultralytics YOLO modelleri AGPL-3.0; ONNX dışa aktarımı da buna tabidir. Kapalı dağıtım için YOLOX (Apache-2.0) ONNX'i düşün; `decode_yolo` YOLOX çıktısı (objectness'li) için ayrı bir çözücü gerektirir.
