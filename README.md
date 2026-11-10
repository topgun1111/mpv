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
- **Detector**: YOLOX (Apache-2.0, önerilen) veya YOLOv8/YOLO11 (AGPL-3.0) person modeli, ONNX
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
│     ├─ input.conf              # t: aç/kapa, r: sıfırla, x: hedefi bırak, F10: menü
│     ├─ script-modules/trackmenu.lua  # üst menü çubuğu motoru (M1; saf mantık)
│     └─ scripts/track.lua       # tıklama seçimi, OSD, tuşlar, menü bağlama
├─ tracker/                      # Python paketi (python -m tracker ...)
│  ├─ main.py                    # CLI: ping, view, listen, detect, live
│  ├─ ipc.py, clicks.py, frames.py, geometry.py, smooth.py, config.py
│  ├─ detector.py                # YOLO ONNX
│  ├─ point.py                   # sınıfsız nesne izleyici (sağ tık; optik akış + şablon)
│  ├─ bytetrack.py, pipeline.py  # ByteTrack + birleşim
│  └─ live.py                    # canlı mod (hedef seçimi dahil)
├─ models/                       # YOLOX/YOLO ONNX buraya (MODELLER.txt)
├─ scripts/                      # make_package.py, fetch_deps.ps1
├─ installer.iss                 # Inno Setup
├─ THIRD_PARTY_NOTICES.md        # üçüncü taraf lisanslar + GPL kaynak teklifi
├─ project.md                    # yol haritası (P23…O3; her parça = 1 oturum)
└─ handover.md                   # parça parça ilerleme notu
```
(Parça 14: `launcher/`, `scripts/build_embedded.py` da pakete dahildir.)

## Paketleme
- **Installer**: Inno Setup / NSIS → tek `setup.exe`, kısayol "Takipli Oynat" (mpv + Python süreci birlikte)
- **Boyut**: PyTorch ~2–3 GB; ONNX Runtime + ONNX model ~300–500 MB
- **GPU**: `onnxruntime-directml` (NVIDIA/AMD/Intel evrensel); NVIDIA için `onnxruntime-gpu` (+~1 GB CUDA/cuDNN)
- **Alternatif**: Python → PyInstaller tek `.exe`, mpv klasörüne

## Lisans
Ayrıntılı denetim: **`THIRD_PARTY_NOTICES.md`** (pakete ve Başlat menüsüne de konur; hukuki görüş değildir).
- **Dağıtılanlar**: mpv (GPL-2.0+, değiştirilmeden; kaynak teklifi + `mpv\BUILD_INFO.txt`), Python (PSF), NumPy (BSD), OpenCV (Apache-2.0; FFmpeg LGPL), ONNX Runtime-DirectML (MIT; DirectML Microsoft bileşeni).
- **Modeller dağıtılmaz** (`installer.iss` `models\*.onnx` hariç):
  - **YOLOX** (Apache-2.0) — önerilen, dağıtıma uygun; **kurulum paketine CI'da (`scripts/fetch_model.ps1`) konur**. Dosya adında "yolox" varsa otomatik seçilir (`model_type`: auto | yolov8 | yolox).
  - **YOLOv8/YOLO11** (Ultralytics, AGPL-3.0) — kişisel/okul içi kullanımda sorun yok; modeli başkalarına dağıtırsan AGPL şartları geçerli.
  - **OSNet** ağırlıkları eğitim verisinin (Market-1501 vb.) koşullarına tabidir; dağıtmadan önce doğrula.
- Takipli Oynat kodunun kendi lisansını proje sahibi seçer (depoda `LICENSE` yoksa tüm haklar saklıdır; `make_package.py` `LICENSE` varsa pakete koyar).
- Kodda `ultralytics` içe aktarılmaz; çözücüler yalnız ONNX çıktı biçimini okur.

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
Ayrıntılı plan ve durum `handover.md`, sonraki parçalar (M2…O3) `project.md` içindedir. Tamamlanan: **Parça 1–15 (1.0.0)** (iskelet, tıklama, detector, ByteTrack, canlı mod, hedef seçimi, Kalman + lookahead, kayıp yönetimi, offline mod, Lua offline oynatma, Re-ID, takım rengi + isteğe bağlı forma numarası, canlı ayar tuşları + durum etiketi,  Python + tam installer, lisans denetimi + YOLOX alternatifi + release).

### Sağ tık: herhangi bir nesneyi takip (Parça 18)
`tracker/point.py`: sağ tıklanan nokta için kutu çıkarılır (aynı renkteki bitişik bölge; olmazsa karenin %6'sı kadar kare), sonra her karede Lucas-Kanade optik akışı kutuyu taşır, şablon benzerliği (NCC) yanlış şeye kaymayı yakalar, tutmazsa son konum çevresinde şablon aranır; bulunamazsa "hedef kayıp" (bekle → kademeli zoom-out) ve nesne geri gelirse takip sürer. Detector çalışmaz (CPU'da daha hızlı); `models\` boşsa bile sağ tık çalışır. Ayarlar (`config.json`): `point_box` (0.06), `point_refine` (true), `point_min_score` (0.55; yükselirse kayıp daha erken ilan edilir), `point_max_side` (640). Zoom miktarı `+`/`−` (doluluk) ile ayarlanır. Takip edilen noktanın üstünde **beyaz nokta** gösterilir (Python her karede merkezi `track-dot` ile yollar, Lua mpv'nin anlık zoom/pan'ına göre çizer); hedef kayıpsa ya da bırakılınca nokta kaybolur — çalışıp çalışmadığını buradan görürsün.
Sınırlar: tek tıklamadan nesnenin boyutu kesin bilinemez (küçük/dokusuz nesnede kutu fazla büyük ya da küçük olabilir → `+`/`−`, `point_box`); çok benzer nesnelerin iç içe geçtiği, nesnenin tamamen örtüldüğü ya da kareyi terk ettiği durumlarda kayıp ilan edilir (yeniden sağ tık). Offline mod (`offline --click`) hâlâ yalnız oyuncu içindir.

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

### Re-ID (Parça 11)
OSNet ONNX modelini `models/osnet_x0_25.onnx` olarak koy (torchreid ile dışa aktarılır; girdi 1x3x256x128 veya dinamik batch).
```
python -m tracker live --reid                      # hedef kaybolup ByteTrack yeni ID verirse görünüme göre geri bağlar
python -m tracker offline video.mp4 --reid         # izlerin ilk/son embedding'ini track.json'a yazar
python -m tracker offline-view video.mp4.track.json --target-id 7          # kayıtlı embedding varsa ID değişimlerini zincirler
python -m tracker offline-view video.mp4.track.json --target-id 7 --no-link
```
Ayarlar: `reid_thres` (0.6), `reid_margin` (0.05), `reid_link_gap_s` (20). Benzer formalı oyuncular karışabilir; belirsizse (marj yetmezse) bağlama yapılmaz.

### Takım rengi ve forma numarası (Parça 12)
```
python -m tracker live --reid --team                 # farklı takım renkli adaylar Re-ID'de elenir
python -m tracker live --reid --team --number        # + hedefle farklı numaralı adaylar elenir
python -m tracker offline video.mp4 --reid --team    # izlerin takımı track.json'a yazılır, zincirleme takımı gözetir
```
Takım yalnızca eleme yapar; etiket belirsizse aday elenmez. `--number` için `models/jersey_number.onnx` gerekir (girdi [N,C,H,W], çıktı [N,101]: 0–99 numara, 100 = yok; ayrıntı `tracker/number.py`). Ayarlar: `team_margin` (0.15), `team_min_samples` (40), `number_min_votes` (3).

### Canlı ayarlar ve durum etiketi (Parça 13)
Canlı mod çalışırken mpv'de: `Ctrl+↑/↓` doluluk, `Ctrl+→/←` tepki hızı, `Ctrl+PgUp/PgDn` öngörü, `Ctrl+0` varsayılanlar, `Ctrl+S` ayarları kaydet (`--config` ya da `tracker_config.json`), `h` durum özeti, `Ctrl+H` sağ üst etiketi gizle/göster. Kayıtlı ayarla başlamak için: `python -m tracker --config tracker_config.json live ...`.

### Üst menü çubuğu (M1)
Fareyi pencerenin üst kenarına götürünce ya da **F10** ile menü çubuğu açılır: **Dosya · Görünüm · Takip · Araçlar · Ayarlar · Yardım**. Çalışan işlevler (takip, bırak, sıfırla, offline, zoom, HUD, tepki/öngörü/doluluk, kaydet, durum, çıkış) menüden de kullanılır; kısayolları yanında yazar, açık olanlar • ile işaretlidir. Henüz yazılmamış öğeler (Video aç, Dışa aktar, Tarama…) gri görünür ve sonraki parçalarda (`project.md`) açılır. Açıkken ←/→/↑/↓, Enter, Esc ile gezilir; dışarı tıklamak kapatır.

### Ekran üstü düğmeler (Parça 16)
mpv penceresinde fareyi/parmağı oynatınca sol üstte düğme paneli çıkar (3 sn sonra gizlenir; **Sabit** düğmesi ya da `Ctrl+B` ile sabitlenir): **Takip AÇIK/KAPALI**, **Bırak**, **Sıfırla**, **Offline**, **Zoom -/+**, **Tepki -/+**, **Öngörü -/+**, **Kaydet**, **Durum**. Zoom düğmeleri artık ayrı bir **ekran üstü zoom kontrolüne** taşındı (aşağıda). Takip açıkken düğmelerin dışında bir oyuncuya sol tıklamak da hedef seçer. Klavye kısayolları aynen çalışır.

### Sağ tık ile takip noktası ve ekran üstü zoom kontrolü (Parça 17)
- **Sağ tık**: tıklanan nokta/**nesne** takip edilir — oyuncu olmak zorunda değil (top, araba, tahtadaki bir şekil...); takip kapalıysa kendiliğinden açılır (önce `t` basmak gerekmez). Nesnenin üstüne tekrar sağ tık bırakır, başka yere sağ tık hedefi değiştirir. (mpv'nin sağ tık = duraklat davranışı yerine geçer; duraklatma Boşluk tuşuyla.) Bu mod YOLO'ya ihtiyaç duymaz (bkz. Parça 18); oyuncu kimliği/Re-ID için **sol tık** (takip açıkken) eskisi gibi çalışır.
- **Zoom kontrolü**: pencerenin sağ kenarında ortada **+** / anlık zoom (ör. `x1.5`) / **−**. Fare/dokunma hareketinde, takip açıkken ya da zoom yapılmışken görünür (zoom varken panel gizlense de kalır). `+` ve `-` tuşları aynı işi yapar.
  - Hedef kilitliyken +/− hedefin kareyi doldurma oranını ayarlar (zoom'u takip sürer; değer etiketi canlı güncellenir).
  - Hedef yokken ya da takip kapalıyken +/− doğrudan video zoom'unu 1x–16x arasında 0.25 (log2) adımla değiştirir.
  - Offline oynatma açıkken zoom sabittir (uyarı verir).

### Kurulum ve başlatıcılar (Parça 14)
Installer (`TakipliOynat-Setup-x.y.z.exe`, Windows 10 1903+) gömülü Python, mpv, DirectML ve **YOLOX-S modeliyle (Apache-2.0)** gelir: kurduktan sonra elle bir şey kurmak ya da kopyalamak gerekmez, kurulum bitince "şimdi başlat" ile çalışır. Eklem (vücut parçası) takibi için `yolov8s-pose.onnx` (AGPL, yalnız kişisel kullanım) de pakete CI'da konur; sağ tık bir eklemin (ayak bileği, diz, bilek...) yakınına yapılırsa o eklem izlenir, uzaksa nesne izlenir. Re-ID/numara modelleri isteğe bağlıdır (`models\MODELLER.txt`).

**Güncelleme**: yeni `setup.exe`'yi çalıştırmak yeter; AppId aynı olduğundan eski kurulumun üstüne (aynı klasör/yetki) sorusuz kurulur, açık mpv/python kapatılır, eski artıklar (`python\`, `tracker\`, Lua betikleri) temizlenip yenisi yazılır. Ayarlar (`%APPDATA%\TakipliOynat\config.json`) ve `models\` içine kendi eklediğin dosyalar korunur. Sessiz: `TakipliOynat-Setup-x.y.z.exe /VERYSILENT /NORESTART`.
- **Takipli Oynat (canlı)** kısayolu / `Baslat.bat`: mpv'yi ve izleyiciyi birlikte açar (video sürükleyebilirsin). Re-ID/takım/numara modelleri `models\`'te varsa otomatik açılır.
- **Offline** kısayolu / `Offline.bat`: videoyu üstüne sürükle → işlenir → oyuncu ID'sini yaz → mpv'de `o`.
- Ayarlar `%APPDATA%\TakipliOynat\config.json` dosyasına kaydedilir.
Paket derleme (CI): `python scripts/make_package.py` → `python scripts/build_embedded.py` → `scripts/fetch_deps.ps1` → `iscc installer.iss`.

### Release (Parça 15)
1. `main`'e push → CI (`ci.yml`) ve `build.yml` (artifact: portable ZIP + `TakipliOynat-Setup-x.y.z.exe`).
2. Derleme günlüğündeki `SHA256 python-...` ve `SHA256 mpv-...` satırlarını doğrulayıp `scripts/build_embedded.py` (`PY_SHA256`) içine yaz; mpv için `fetch_deps.ps1 -Tag <sürüm>` ile sürümü sabitle.
3. Temiz Windows'ta kur (model pakette gelir) → `Baslat.bat` ile dene. Üzerine yeni sürüm kurup ayarların/kısayolların korunduğunu da dene.
4. `git tag v1.0.0 && git push origin v1.0.0` → GitHub Release otomatik oluşur (`generate_release_notes`).

İlk gerçek denemede kontrol: `python -m tracker detect kare.jpg --model models\yolox_s.onnx --out sonuc.jpg` (kutular doğru yerde mi, `provider=DmlExecutionProvider`); `live --stats 2` (fps/gecikme); `o` ile offline oynatma; Ctrl+S ayar kaydı.
