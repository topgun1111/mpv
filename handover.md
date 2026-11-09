# handover.md — Takipli Oynat

Her parça sonunda güncellenir. Yeni oturumda önce bu dosyayı oku, sonra sıradaki parçayı yap.
Kurallar: her parça sonunda `handover.md` güncelle → tüm proje ZIP'le (`takipli-oynat-partNN.zip`).
Proje GitHub'a push edilip Actions ile derlenir (`ci.yml`: test+lint, `build.yml`: paket+installer).

## Durum
- Tamamlanan: **Parça 3/15**
- Sıradaki: **Parça 4**
- Sürüm: 0.3.0

## 15 Parçalık Plan
| # | Parça | Durum |
|---|-------|-------|
| 1 | İskelet: repo yapısı, CI/Build workflow, config, geometri (bbox→zoom/pan), EMA+dead-zone, mpv IPC istemcisi, CLI (ping/view), installer iskeleti, testler | ✅ |
| 2 | Lua: tıklama → video koordinatı, `script-message` ile Python'a iletme, OSD; Python'da olay okuma (`poll_event`) ve `listen` komutu | ✅ |
| 3 | Detector: YOLO ONNX (onnxruntime-directml), ön/son işleme, NMS, person sınıfı | ✅ |
| 4 | Tracker: ByteTrack (kalıcı ID), detector ile birleştirme | ⬜ |
| 5 | Canlı mod `main.py`: kare okuma (mpv screenshot-raw/ffmpeg), time-pos senkronu, IPC çıkışı | ⬜ |
| 6 | Hedef seçimi: tıklanan noktadaki bbox ID'si, hedef değiştirme/bırakma | ⬜ |
| 7 | Kalman + hız yönünde lookahead (smooth.py genişletme) | ⬜ |
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
- `tracker/ipc.py`: `command()` beklerken gelen olaylar kuyruğa alınır; `poll_event(timeout)` eklendi (Unix soketinde zaman aşımı destekli; Windows pipe'ında okuma bloklar → Parça 5'te okuma iş parçacığına alınacak).
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

## Parça 4 için başlangıç
- `tracker/bytetrack.py`: Kalman (cx,cy,a,h) + IoU ile ByteTrack (yüksek/düşük skor iki aşamalı eşleştirme, `lap`/`scipy` yerine saf numpy Macar algoritması veya `scipy.optimize.linear_sum_assignment`), kalıcı `track_id`, `Track(id, bbox, score, age, lost)`.
- Detector çıktısı (`list[Detection]`) → tracker `update(detections)` → `list[Track]`. Birleştirme için `tracker/pipeline.py` (detector + tracker, kare başına `step(frame)`).
- Testler: sentetik hareketli kutularla ID kalıcılığı, kısa kayıpta ID korunması, yeni nesne = yeni ID. `requirements.txt`'e `scipy` eklenecekse onayla (boyut).
- Lisans notu (Parça 15): Ultralytics YOLO modelleri AGPL-3.0; ONNX dışa aktarımı da buna tabidir. Kapalı dağıtım için YOLOX (Apache-2.0) ONNX'i düşün; `decode_yolo` YOLOX çıktısı (objectness'li) için ayrı bir çözücü gerektirir.
