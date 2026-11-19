# mpv (shinchiro, Windows x86_64) sürümünü indirip -Target klasörüne açar.
# -Tag verilirse o sürüm sabitlenir (ör. 20260101); verilmezse son sürüm. Hangi derlemenin (ve
# SHA256'sının) paketlendiği Target\BUILD_INFO.txt'ye yazılır (GPL kaynak teklifi için gerekli).
param([string]$Target = "dist/TakipliOynat/mpv", [string]$Tag = "")
$ErrorActionPreference = "Stop"
$tmp = Join-Path $env:RUNNER_TEMP "mpvdl"
if (-not $env:RUNNER_TEMP) { $tmp = Join-Path $env:TEMP "mpvdl" }
New-Item -ItemType Directory -Force $tmp, $Target | Out-Null

$api = "https://api.github.com/repos/shinchiro/mpv-winbuild-cmake/releases/latest"
if ($Tag) { $api = "https://api.github.com/repos/shinchiro/mpv-winbuild-cmake/releases/tags/$Tag" }
# Anonim GitHub API istekleri paylasimli runner IP'sinde "rate limit exceeded" verir: GITHUB_TOKEN varsa
# kimlikli istek (5000/saat), ayrica gecici hatalarda 4 deneme (10, 20, 30 sn bekleyerek).
$headers = @{ "User-Agent" = "takipli-oynat-ci" }
if ($env:GITHUB_TOKEN) { $headers["Authorization"] = "Bearer $($env:GITHUB_TOKEN)" }
$rel = $null
for ($i = 1; $i -le 4; $i++) {
  try { $rel = Invoke-RestMethod $api -Headers $headers; break }
  catch {
    if ($i -eq 4) { throw }
    Write-Host "GitHub API hatasi (deneme $i/4): $($_.Exception.Message)"
    Start-Sleep -Seconds (10 * $i)
  }
}
$asset = $rel.assets | Where-Object { $_.name -match '^mpv-x86_64-\d{8}.*\.7z$' } | Select-Object -First 1
if (-not $asset) { throw "mpv Windows arşivi bulunamadı" }
Write-Host "Indiriliyor: $($asset.name)"
$file = Join-Path $tmp $asset.name
Invoke-WebRequest $asset.browser_download_url -OutFile $file
$sha = (Get-FileHash $file -Algorithm SHA256).Hash.ToLower()
Write-Host "SHA256 $($asset.name): $sha"
& 7z x $file "-o$Target" -y | Out-Null
if (-not (Test-Path (Join-Path $Target "mpv.exe"))) { throw "mpv.exe açılamadı" }
@(
  "mpv derlemesi: $($asset.name)",
  "Surum (etiket): $($rel.tag_name)",
  "Kaynak/derleme: https://github.com/shinchiro/mpv-winbuild-cmake/releases/tag/$($rel.tag_name)",
  "mpv kaynak kodu: https://github.com/mpv-player/mpv",
  "SHA256: $sha"
) | Set-Content (Join-Path $Target "BUILD_INFO.txt") -Encoding UTF8
Write-Host "mpv hazır: $Target"
