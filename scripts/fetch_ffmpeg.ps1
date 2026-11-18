# ffmpeg (BtbN, Windows x64, GPL derlemesi: libx264 icerir) indirip -Target klasorune koyar.
# E1 "takip kamerasi disa aktarma" libx264 kullanir; LGPL derlemesinde libx264 yoktur, bu yuzden GPL
# derlemesi secildi (mpv zaten GPL, paket GPL ile uyumlu). tracker/export.py find_ffmpeg
# <python klasoru>\..\ffmpeg\ffmpeg.exe yolunu arar -> Target = dist/TakipliOynat/ffmpeg.
# -Sha256 (ya da FFMPEG_SHA256 ortam degiskeni) verilirse arsiv ozeti dogrulanir; verilmezse ozet gunluge
# yazilir (dogrulayip workflow'a sabitle). Hata/bozuk indirmede derleme DURUR.
param(
  [string]$Target = "dist/TakipliOynat/ffmpeg",
  [string]$Url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
  [string]$Sha256 = $env:FFMPEG_SHA256
)
$ErrorActionPreference = "Stop"
$tmp = Join-Path ($(if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { $env:TEMP })) "ffdl"
Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $tmp, $Target | Out-Null
$zip = Join-Path $tmp "ffmpeg.zip"
Write-Host "Indiriliyor: $Url"
Invoke-WebRequest $Url -OutFile $zip -Headers @{ "User-Agent" = "takipli-oynat-ci" }
$size = (Get-Item $zip).Length
if ($size -lt 20MB) { throw "ffmpeg arsivi beklenenden kucuk ($size bayt): indirme bozuk ya da adres degismis ($Url)" }
$sha = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
Write-Host "SHA256 ffmpeg arsivi: $sha ($([math]::Round($size / 1MB, 1)) MB)"
if ($Sha256 -and $sha -ne $Sha256.ToLower()) { throw "ffmpeg SHA256 uyusmuyor (beklenen $Sha256, gelen $sha)" }
Expand-Archive $zip -DestinationPath $tmp -Force
$exe = Get-ChildItem $tmp -Recurse -Filter ffmpeg.exe | Select-Object -First 1
if (-not $exe) { throw "ffmpeg.exe arsivde bulunamadi" }
Copy-Item $exe.FullName (Join-Path $Target "ffmpeg.exe") -Force
# S13b: ffprobe disa aktarma dogrulamasi icin (yoksa dogrulama cv2 ile sinirli kalir; derlemeyi durdurmaz)
$probe = Get-ChildItem $tmp -Recurse -Filter ffprobe.exe | Select-Object -First 1
if ($probe) { Copy-Item $probe.FullName (Join-Path $Target "ffprobe.exe") -Force } else { Write-Host "UYARI: ffprobe.exe arsivde yok" }
$lic = Get-ChildItem $tmp -Recurse -Filter LICENSE.txt | Select-Object -First 1
if ($lic) { Copy-Item $lic.FullName (Join-Path $Target "FFMPEG_LICENSE.txt") -Force }
# libx264 gercekten var mi (LGPL derlemesi yanlislikla gelirse disa aktarma sessizce yedege duser)
$enc = & (Join-Path $Target "ffmpeg.exe") -hide_banner -encoders 2>&1 | Out-String
if ($enc -notmatch "libx264") { throw "ffmpeg derlemesinde libx264 yok (GPL derlemesi gerekli)" }
# S13b: bu derlemenin LISTELEDIGI kodlayici/hwaccel'ler (liste NVENC'in calistigini gostermez; GPU'da denenmeden iddia edilmez)
$listed = ($enc -split "`n" | Where-Object { $_ -match "libx264 |h264_nvenc|hevc_nvenc|av1_nvenc|h264_amf|h264_qsv" } | ForEach-Object { $_.Trim() })
$hw = (& (Join-Path $Target "ffmpeg.exe") -hide_banner -hwaccels 2>&1 | Out-String).Trim() -replace "\s+", " "
@(
  "ffmpeg derlemesi: BtbN/FFmpeg-Builds (GPL, win64)",
  "Listelenen kodlayicilar: $($listed -join ' | ')",
  "Listelenen hwaccel: $hw",
  "ffprobe: $(Test-Path (Join-Path $Target 'ffprobe.exe'))",
  "Kaynak/derleme: https://github.com/BtbN/FFmpeg-Builds",
  "ffmpeg kaynak kodu: https://ffmpeg.org/download.html (x264: https://www.videolan.org/developers/x264.html)",
  "Arsiv adresi: $Url",
  "SHA256: $sha"
) | Set-Content (Join-Path $Target "BUILD_INFO.txt") -Encoding UTF8
Write-Host "ffmpeg hazir: $Target"
