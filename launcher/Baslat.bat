@echo off
rem Takipli Oynat - canli mod baslatici. Video dosyasini bu dosyanin ustune surukleyebilirsin.
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PY=%~dp0python\python.exe"
set "CFGDIR=%APPDATA%\TakipliOynat"
if not exist "%CFGDIR%" mkdir "%CFGDIR%"

if not exist "%PY%" (
  echo HATA: python\python.exe bulunamadi. Kurulum eksik.
  pause
  exit /b 1
)
if not exist "models\yolov8n.onnx" (
  echo HATA: models\yolov8n.onnx yok. models\MODELLER.txt dosyasini oku.
  pause
  exit /b 1
)

set "EXTRA="
if exist "models\osnet_x0_25.onnx" (
  set "EXTRA=--reid --team"
  if exist "models\jersey_number.onnx" set "EXTRA=%EXTRA% --number"
)

start "" "%~dp0mpv\mpv.exe" --player-operation-mode=pseudo-gui %*
echo Takipli Oynat canli mod. mpv'de t ile takibi ac, oyuncuya sol tikla.
echo Bu pencereyi kapatirsan takip durur. (mpv kapaninca kendiliginden biter.)
"%PY%" -m tracker --config "%CFGDIR%\config.json" live --wait 30 %EXTRA% --stats 5
if errorlevel 1 pause
