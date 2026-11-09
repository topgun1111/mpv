# Takipli Oynat — mpv Tabanlı Nesne Takipli Otomatik Zoom

Oynatma sırasında seçilen bir nesneyi (ör. futbolcu) takip edip `video-zoom` / `video-pan` ile otomatik yakınlaştıran Windows video oynatıcı paketi.

## Hedef
- Ekranda tıklanan oyuncuyu takip et, kameraman hissiyle zoom/pan uygula
- Tek `setup.exe` ile kurulum, internetsiz çalışma
- Açık kaynak bileşenler üzerine kurulu, mpv çekirdeğine dokunmadan

## Neden mpv (VLC değil)
- Runtime property'ler: `video-zoom` (log2), `video-pan-x`, `video-pan-y`
- IPC (Windows named pipe) + Lua + JSON ile derlemesiz genişletme
- VLC'de aynı iş C/C++ `video_filter` modülü + OpenCV contrib build gerektirir; ağır inference video thread'ini bloklar, A/V senkronu bozulur

## Mimari
- **Detector**: YOLOv8/YOLO11 (person), tam çözünürlük, ONNX
- **Tracker**: ByteTrack / BoT-SORT, kalıcı ID
- **Re-ID**: OSNet embedding ile örtüşme sonrası ID kurtarma
- **Ek sinyaller**: forma numarası OCR, takım rengi histogramı
- **Smoothing**: EMA/Kalman, dead-zone, hız yönünde lookahead
- **Kayıp yönetimi**: son konumda bekle → kademeli zoom-out
- **Hedef seçimi**: Lua `mouse_btn0` → `mouse-pos` → tıklanan noktadaki bbox ID'si
- **Çıkış**: IPC ile `set_property video-zoom/pan-x/pan-y`

## Çalışma Modları
- **Offline (önerilen)**: video bir kez taranır → `track.json` (frame → bbox, ID) → Lua `time-pos` ile JSON'dan zoom/pan uygular. A/V senkronu bozulmaz, hedef sonradan düzeltilebilir
- **Canlı**: Python süreci videoyu okur, `model.track(persist=True, tracker="bytetrack.yaml")`, sonucu IPC ile gönderir. Gecikme `time-pos` ile ileri kare tahminiyle telafi edilir. CPU'da detector her 3–5 karede bir, aralarda KCF/optical flow

## Dosya Yapısı
```
TakipliOynat/
├─ mpv/                          # portable mpv (mpv.exe + portable_config/)
│  └─ portable_config/
│     ├─ mpv.conf                # input-ipc-server=\\.\pipe\mpv
│     ├─ input.conf              # t: aç/kapa, r: sıfırla, x: hedefi bırak
│     └─ scripts/track.lua       # tıklama seçimi, OSD, tuşlar
├─ tracker/                      # Python paketi (python -m tracker ...)
│  ├─ main.py                    # CLI: ping, view, listen, detect, live
│  ├─ ipc.py, clicks.py, frames.py, geometry.py, smooth.py, config.py
│  ├─ detector.py                # YOLO ONNX
│  ├─ bytetrack.py, pipeline.py  # ByteTrack + birleşim
│  └─ live.py                    # canlı mod (hedef seçimi dahil)
├─ models/                       # YOLO ONNX buraya
├─ scripts/                      # make_package.py, fetch_deps.ps1
├─ installer.iss                 # Inno Setup
└─ handover.md                   # parça parça ilerleme notu (15 parçalık plan)
```
(Planlanan, henüz yok: `offline.py`, Re-ID, forma OCR, gömülü Python.)

## Paketleme
- **Installer**: Inno Setup / NSIS → tek `setup.exe`, kısayol "Takipli Oynat" (mpv + Python süreci birlikte)
- **Boyut**: PyTorch ~2–3 GB; ONNX Runtime + ONNX model ~300–500 MB
- **GPU**: `onnxruntime-directml` (NVIDIA/AMD/Intel evrensel); NVIDIA için `onnxruntime-gpu` (+~1 GB CUDA/cuDNN)
- **Alternatif**: Python → PyInstaller tek `.exe`, mpv klasörüne

## Lisans
- mpv: GPLv2+ (LGPLv2.1+ derlenebilir); değiştirilmiş sürüm dağıtılırsa kaynak açılır
- Ultralytics (YOLO): **AGPL-3.0** → dağıtımda kaynak açma zorunlu veya ticari lisans
- Kapalı dağıtım için alternatif: YOLOX / RT-DETR (Apache-2.0)
- Telif/lisans bildirimleri korunmalı

## Kod Tahmini
- Python tracker (detector + ByteTrack + Re-ID + smoothing + IPC): ~400–600 satır
- Lua script: ~100–150
- Offline mod: ~150–250
- Config/CLI/hata yönetimi: ~100
- Installer: ~80–120
- **Toplam**: ~800–1200 satır
- **Minimum prototip** (YOLO + ByteTrack + EMA + IPC + tıklama): ~150–250 satır
- Re-ID + forma OCR: +300–500 satır

## Bilinen Riskler
- Aynı formalı oyuncuların kesişmesinde ID kayması → Re-ID + renk/numara sinyali
- Küçük hedef (30–60 px) → tam çözünürlük inference
- Ani kamera pan'ı → bbox sıçraması → Kalman + dead-zone
- CPU-only makinelerde canlı mod düşük fps → offline mod

## Yol Haritası
Ayrıntılı 15 parçalık plan ve durum `handover.md` içindedir. Tamamlanan: Parça 1–10 (iskelet, tıklama, detector, ByteTrack, canlı mod, hedef seçimi, Kalman + lookahead, kayıp yönetimi, offline mod, Lua offline oynatma). Sıradaki: Parça 11 (Re-ID).

## Offline mod (Parça 9)
```
python -m tracker offline video.mp4                       # tespit+izleme → video.mp4.track.json, en uzun izleri listeler
python -m tracker offline video.mp4 --target-id 7         # hedefle birlikte görünüm anahtar karelerini de yazar
python -m tracker offline video.mp4 --click 12.5 0.43 0.61  # 12.5. sn'de (nx, ny) noktasındaki kişi
python -m tracker offline-view video.mp4.track.json --list
python -m tracker offline-view video.mp4.track.json --target-id 3   # tespit YOK, saniyeler sürer
```
Şema `tracker/offline.py` başındadır (`views`: `[t, zoom, pan_x, pan_y]`).

### Offline oynatma (Parça 10)
`offline ... --target-id N` (veya `offline-view`) `video.mp4.views.json` dosyasını da yazar. Bu dosya
videonun yanında dururken mpv'de **`o`** tuşu görünümü Python olmadan, `time-pos`'a göre sürer
(seek/duraklatmada da çalışır). `t` (canlı) açılınca offline kapanır ve tersi; `r` ikisini de sıfırlar.
`--out` ile farklı yola yazdıysan `*.views.json` dosyasını `<video dosya adı>.views.json` yap.
