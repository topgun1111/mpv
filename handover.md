# handover.md — Takipli Oynat

Her parça sonunda güncellenir. Yeni oturumda önce bu dosyayı oku, sonra sıradaki parçayı yap.
Kurallar: (1) her parça sonunda `handover.md` güncelle → TÜM projeyi ZIP'le (`takipli-oynat-partNN.zip`; değişen dosyalar değil, tüm dosyalar). (2) Ücretsiz Claude hesabı: token'ı idareli ve akıllı kullan, israf yok.
Proje GitHub'a push edilip Actions ile derlenir (`ci.yml`: test+lint, `build.yml`: paket+installer). `build.yml` artık `main`'e her push'ta (yalnız .md değişikliği hariç), `v*` etiketinde ve elle çalışır; GitHub Release yalnız `v*` etiketinde oluşur. exe: çalışmanın sayfasında Artifacts → TakipliOynat.

## Durum
- Tamamlanan: **Parça 7/15**
- Sıradaki: **Parça 8**
- Sürüm: 0.7.0

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
| 8 | Kayıp yönetimi: son konumda bekle → kademeli zoom-out | ⬜ |
| 9 | Offline mod: `offline.py` → `track.json` şeması ve üretimi | ⬜ |
| 10 | Lua offline oynatma: `time-pos` ile JSON'dan zoom/pan, interpolasyon | ⬜ |
| 11 | Re-ID (OSNet ONNX): embedding, ID kurtarma | ⬜ |
| 12 | Takım rengi histogramı + forma numarası OCR | ⬜ |
| 13 | Ayarlar (config UI/tuşlar) ve OSD iyileştirmeleri | ⬜ |
| 14 | Gömülü Python (embeddable) + bağımlılık paketleme + Inno Setup tam installer, DirectML varsayılanı | ⬜ |
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

## Parça 8 için başlangıç
- Kayıp yönetimi: hedef görünmeyince son konumda bekle → kademeli zoom-out. `LiveController.step` içindeki `tr is None` dalı (şu an yalnız `_lost` sayar ve OSD verir) genişletilecek; `BoxFilter`'a kayıp için `predict`-only (coast) eklenebilir; `ByteTracker.lost_tracks` tahmini konum verir. Config'e `lost_hold_s` (bekleme) ve `lost_zoomout_s` (zoom-out süresi) benzeri ayarlar eklenmeli.

## Doğrulama durumu (Parça 5; Parça 6-7 için de geçerli)
- Parça 6: testler yerelde 76/76 (aynı uyumluluk katmanı); `track.lua`'daki `release` bağı ve `x` tuşu gerçek mpv'de denenmedi.
- Testler yerelde 68/68 (pytest yüklenemediği için basit uyumluluk katmanıyla). `ruff` ve GitHub Actions yine **çalıştırılmadı** (satır ≤100 ve kullanılmayan import elle kontrol edildi). Yüklenen arşivde `.github/workflows/` (git'te kayıtlı) çalışma klasöründen silinmişti ve `pyproject.toml`'daki `pythonpath = ["."]` satırı eksikti (CI'da `import tracker` için gerekli); ikisi de git HEAD'den geri yüklendi.
- **Gerçek mpv ile denenmedi**: `screenshot-raw`'ın JSON IPC'de base64 `data` döndürdüğü, 1080p karede IPC hızı (kare başı ~8 MB bayt → ~11 MB base64) ve `live_fps` 10'un tutup tutmadığı Windows'ta doğrulanmalı. Yavaşsa: ffmpeg kare kaynağı veya mpv'de küçültülmüş kare (ör. `vf` ile) düşün.
- Windows'ta iki IPC bağlantısı (komut + olay) birlikte açılıyor; mpv'nin pipe sunucusunda çoklu istemci beklenen davranış ama denenmedi.
- Elle deneme: `dist\TakipliOynat\mpv\mpv.exe video.mp4` → ayrı terminalde `python -m tracker live --stats 2` → mpv'de `t`, oyuncuya sol tık; `r` sıfırlar.

## Notlar (devam)
- Lisans notu (Parça 15): Ultralytics YOLO modelleri AGPL-3.0; ONNX dışa aktarımı da buna tabidir. Kapalı dağıtım için YOLOX (Apache-2.0) ONNX'i düşün; `decode_yolo` YOLOX çıktısı (objectness'li) için ayrı bir çözücü gerektirir.
