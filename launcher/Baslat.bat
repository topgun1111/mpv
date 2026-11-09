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
set "HASMODEL="
for %%M in (yolov8n yolox_s yolox_m yolox_tiny yolox_nano) do if exist "models\%%M.onnx" set "HASMODEL=1"
if not defined HASMODEL (
  echo HATA: models klasorunde person modeli yok - yolox_s.onnx onerilir. models\MODELLER.txt dosyasini oku.
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
