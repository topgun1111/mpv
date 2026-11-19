@echo off
rem Takipli Oynat - GELISTIRME klasorunden canli mod: once Python takip programi (ayri pencere), sonra mpv.
rem Kullanim: video dosyasini bu dosyanin ustune surukle birak (ya da cift tikla, sonra mpv'de ac).
rem Sari nokta = tiklama alindi ama Python yanit vermiyor: Python penceresi acik ve hatasiz olmali.
chcp 65001 >nul
setlocal
set "TAKIPLI_DATA_DIR=E:\Tracking"
if not exist "%TAKIPLI_DATA_DIR%\" mkdir "%TAKIPLI_DATA_DIR%"
if not exist "%TAKIPLI_DATA_DIR%\" (echo HATA: E:\Tracking klasoru olusturulamadi. E: surucusunu kontrol edin. & pause & exit /b 1)
if exist "%~dp0tracker\__init__.py" (set "ROOT=%~dp0") else (set "ROOT=%~dp0..\")
cd /d "%ROOT%"
call "%~dp0_python.bat"
if errorlevel 1 (
  pause
  exit /b 1
)
set "HASMODEL="
for %%M in (yolov8n yolox_s yolox_m yolox_tiny yolox_nano) do if exist "models\%%M.onnx" set "HASMODEL=1"
if not defined HASMODEL (
  echo HATA: models klasorunde person modeli yok (yolox_s.onnx onerilir). models\MODELLER.txt dosyasini oku.
  pause
  exit /b 1
)
"%PY%" -c "import numpy, cv2, onnxruntime" 2>nul
if errorlevel 1 (
  echo Gerekli paketler yukleniyor...
  "%PY%" -m pip install -r requirements.txt
)
set "MPV=%ROOT%mpv\mpv.exe"
if not exist "%MPV%" set "MPV=mpv"
rem 1) Python takip programi: gorunur CMD penceresi (Takip.bat Python'u kendisi bulur); hatalar orada gorunur.
start "Takip (Python)" "%ROOT%launcher\Takip.bat"
rem 2) mpv: ayni anda ikinci Python acilmasin diye track.lua'ya haber verilir.
set "TAKIP_PY_STARTED=1"
start "" "%MPV%" --config-dir="%ROOT%mpv\portable_config" %*
