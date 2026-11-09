# Son mpv (shinchiro, Windows x86_64) sürümünü indirip -Target klasörüne açar.
param([string]$Target = "dist/TakipliOynat/mpv")
$ErrorActionPreference = "Stop"
$tmp = Join-Path $env:RUNNER_TEMP "mpvdl"
if (-not $env:RUNNER_TEMP) { $tmp = Join-Path $env:TEMP "mpvdl" }
New-Item -ItemType Directory -Force $tmp, $Target | Out-Null

$rel = Invoke-RestMethod "https://api.github.com/repos/shinchiro/mpv-winbuild-cmake/releases/latest" `
  -Headers @{ "User-Agent" = "takipli-oynat-ci" }
$asset = $rel.assets | Where-Object { $_.name -match '^mpv-x86_64-\d{8}.*\.7z$' } | Select-Object -First 1
if (-not $asset) { throw "mpv Windows arşivi bulunamadı" }
Write-Host "Indiriliyor: $($asset.name)"
$file = Join-Path $tmp $asset.name
Invoke-WebRequest $asset.browser_download_url -OutFile $file
& 7z x $file "-o$Target" -y | Out-Null
if (-not (Test-Path (Join-Path $Target "mpv.exe"))) { throw "mpv.exe açılamadı" }
Write-Host "mpv hazır: $Target"
