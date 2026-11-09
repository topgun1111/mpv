# Üçüncü taraf bileşenler ve lisanslar — Takipli Oynat

Bu belge, Takipli Oynat paketinde **dağıtılan** ve kullanıcının **ayrıca edinmesi gereken**
bileşenleri ve lisans yükümlülüklerini özetler. Hukuki görüş değildir; dağıtmadan önce her
bileşenin kendi lisans metnini kontrol et. Takipli Oynat kodunun kendi lisansı proje sahibi
tarafından belirlenir (depoda `LICENSE` dosyası yoksa tüm haklar saklıdır).

## 1. Pakette dağıtılanlar

| Bileşen | Lisans | Nasıl dahil | Yükümlülük |
|---|---|---|---|
| **mpv** (`mpv\mpv.exe`, shinchiro Windows derlemesi) | GPL-2.0+ (derlemeye göre GPL-3.0 olabilir; LGPL derlemesi de vardır) | Değiştirilmeden, ayrı çalıştırılabilir; Python ile IPC/Lua üzerinden konuşur (bağlama yok) | Lisans metni ve **kaynak koduna erişim**: bkz. Madde 3. Derleme kimliği `mpv\BUILD_INFO.txt` |
| **Python 3.11** (embeddable, `python\`) | PSF License 2.0 | Değiştirilmeden (yalnız `_pth` yapılandırması) | `python\LICENSE.txt` kalmalı |
| **NumPy** | BSD-3-Clause (tekerlekteki OpenBLAS BSD-3, libgfortran GPL-3 + GCC Runtime Exception) | pip ile `python\Lib\site-packages` | Tekerlekteki `LICENSE.txt` kalmalı |
| **opencv-python-headless** | Sarmalayıcı MIT; OpenCV Apache-2.0; tekerlek FFmpeg (LGPL-2.1+) ve başka kütüphaneler içerir (`LICENSE-3RD-PARTY.txt`) | pip ile | Lisans dosyaları kalmalı; FFmpeg DLL'leri değiştirilebilir (dinamik) bırakılmalı |
| **ONNX Runtime — DirectML** (`onnxruntime-directml`) | MIT; `DirectML.dll` Microsoft yeniden dağıtılabilir bileşeni (tekerlekte `ThirdPartyNotices.txt`) | pip ile | Tekerlekteki bildirimler kalmalı |
| **YOLOX-S modeli** (`models\yolox_s.onnx`, Megvii-BaseDetection/YOLOX) | Apache-2.0 | Derlemede (`scripts/fetch_model.ps1`) resmî sürümden indirilir, değiştirilmeden kurulumla birlikte gelir; böylece kurulumdan sonra elle model kopyalamak gerekmez | Lisans metni `models\YOLOX_LICENSE.txt` olarak pakette kalmalı. COCO verisinin kendi koşulları ayrıca geçerlidir |
| **Inno Setup** (yalnız derleme aracı) | Inno Setup License (serbest) | Kurulum programına küçük çalışma zamanı gömülür | Ek yükümlülük yok |

Python paketlerinin tam lisans listesi için paketlenmiş ortamda:
`python\python.exe -m pip list` ve her paketin `*.dist-info\LICENSE*` dosyalarına bak
(`build_embedded.py` bu dosyaları silmez; yalnız önbellek/test/pip kısımlarını ayıklar).

## 2. Diğer modeller (pakette DAĞITILMAZ; kullanıcı isterse kendisi ekler)

Pakette yalnız YOLOX-S (Apache-2.0) bulunur. Aşağıdakiler kurulum paketine **konmaz**
(`installer.iss` → `models\yolov8*.onnx` hariç; Re-ID/numara modelleri depoda yoktur); lisans sorumluluğu
modeli edinen/dağıtana aittir.

| Model | Lisans | Not |
|---|---|---|
| **YOLOX** (`yolox_s.onnx`, Megvii) — **önerilen, pakette gelir** | Apache-2.0 | Takipli Oynat'ta desteklenir (`model_type=yolox`, dosya adında "yolox" varsa otomatik). Ticari/kapalı dağıtım için uygun yol. COCO verisinin kendi koşulları ayrıca geçerlidir |
| **YOLOv8 / YOLO11** (Ultralytics) | **AGPL-3.0** (ya da ücretli Ultralytics Enterprise lisansı) | Takipli Oynat `ultralytics` paketini kullanmaz/içermez; yalnız dışa aktarılmış ONNX çıktısını okur. Modeli (ve türevlerini) **dağıtırsan** AGPL şartları (kaynak açma) devreye girer; kişisel/okul içi kullanım dağıtım sayılmaz — emin değilsen YOLOX kullan |
| **OSNet** (Re-ID, `osnet_x0_25.onnx`; torchreid) | Kod MIT; **ağırlıklar eğitim verisine bağlıdır** | Market-1501/MSMT17 gibi veri kümeleri araştırma amaçlı/ticari olmayan koşullar taşıyabilir. Dağıtmadan önce ağırlığın kaynağını ve veri lisansını doğrula |
| **Forma numarası modeli** (`jersey_number.onnx`) | Eğiten kişiye bağlı | Projede hazır model yoktur (`tracker/number.py` sözleşmesi) |

## 3. GPL (mpv) kaynak kodu teklifi

mpv, `mpv\mpv.exe` olarak **değiştirilmeden** dağıtılır. Kaynak kodu ve derleme betikleri:
- mpv: https://github.com/mpv-player/mpv
- Derleme: https://github.com/shinchiro/mpv-winbuild-cmake (tam sürüm/etiket `mpv\BUILD_INFO.txt`'de)

Bu paketi dağıtan kişi, paketle birlikte aldığı mpv ikilisinin karşılık gelen kaynak kodunu,
paketi aldıktan sonra **en az üç yıl** boyunca, dağıtım maliyetini aşmayan bir bedelle isteyen
herkese sağlamayı yazılı olarak taahhüt eder (GPL-2.0 madde 3(b)); kolaylık için yukarıdaki
bağlantılar ve BUILD_INFO.txt'deki sürüm bilgisi bu teklifin parçasıdır. Daha güvenli yol: indirilen
mpv sürümünü sabitleyip (`fetch_deps.ps1 -Tag <sürüm>`) kaynak arşivini paketle birlikte yayımlamak.

## 4. Takipli Oynat kodu ile ilişki

- `tracker/` içindeki kod bu projeye özgüdür; Ultralytics/YOLOX/torchreid kodu **kopyalanmamıştır**
  (çözücüler yalnızca modellerin belgelenmiş çıktı biçimini okur).
- AGPL bileşen (Ultralytics modeli) yalnız kullanıcının kendi sağladığı dosyadır; ağ üzerinden
  hizmet olarak sunulmaz.
- Üçüncü taraf ticari markalar (mpv, Python, OpenCV, ONNX, YOLO) ilgili sahiplerine aittir.
