@echo off
rem Takipli Oynat - Python takip servisini kontrol et ve gerekirse baslat.
rem Bu dosya hem Baslat.bat tarafindan hem mpv'nin track.lua otomatik baslatmasindan cagrilir.
chcp 65001 >nul
setlocal
set "ROOT=%~dp0.."
for %%F in ("%ROOT%") do set "ROOT=%%~fF"
cd /d "%ROOT%"
set "PY=%ROOT%\python\python.exe"
set "MPV=%ROOT%\mpv\mpv.exe"
set "CFG=%APPDATA%\TakipliOynat\config.json"

if not exist "%PY%" (
  echo [HATA] Paketli Python bulunamadi: "%PY%"
  echo Gelistirme kurulumu icin launcher\Takip.bat kullanin.
  exit /b 1
)
if not exist "%ROOT%\tracker\__init__.py" (
  echo [HATA] tracker paketi bulunamadi.
  exit /b 1
)

rem Gerekli paketleri dogrula.
"%PY%" -c "import numpy,cv2,onnxruntime" >nul 2>nul
if errorlevel 1 (
  echo [HATA] Python paketleri eksik: numpy / opencv / onnxruntime.
  echo requirements.txt dosyasini kontrol edin.
  exit /b 1
)

rem Kisi algilama modeli olmadan takip baslatilamaz.
set "HASMODEL="
for %%M in (yolox_s yolov8n yolox_m yolox_tiny yolox_nano) do (
  if exist "%ROOT%\models\%%M.onnx" set "HASMODEL=1"
)
if not defined HASMODEL (
  echo [HATA] models klasorunde kisi algilama modeli bulunamadi.
  exit /b 1
)

rem DirectML varsa kullanilir; yoksa CPU provider ile devam eder.
"%PY%" -c "import onnxruntime as o,sys;p=o.get_available_providers();print('ONNX providers:',', '.join(p));sys.exit(0 if 'DmlExecutionProvider' in p else 3)"
if errorlevel 1 echo [UYARI] DirectML bulunamadi; CPU kullanilabilir.

rem Servis zaten calisiyorsa ikinci kopyayi acma.
"%PY%" -m tracker ping >nul 2>nul
if not errorlevel 1 (
  echo [OK] Takip servisi zaten calisiyor.
  exit /b 0
)

rem Model dosyalarini ONNX Runtime ile yukleme testinden gecir.
for %%M in (yolox_s yolov8n) do (
  if exist "%ROOT%\models\%%M.onnx" (
    "%PY%" -c "import sys,onnxruntime as o;s=o.InferenceSession(sys.argv[1],providers=['DmlExecutionProvider','CPUExecutionProvider']);print('[OK] %%M:',s.get_providers()[0])" "%ROOT%\models\%%M.onnx" >nul 2>nul
    if errorlevel 1 echo [UYARI] %%M modeli yuklenemedi; takip servisi yine de baslatilacak.
  )
)

if exist "%CFG%" (
  start "Takip (Python)" cmd /d /k ""%PY%" -m tracker --config "%CFG%" live --wait 120"
) else (
  start "Takip (Python)" cmd /d /k ""%PY%" -m tracker live --wait 120"
)

rem IPC hazir olana kadar bekle.
set "N=0"
:wait_ping
timeout /t 2 /nobreak >nul
"%PY%" -m tracker ping >nul 2>nul
if not errorlevel 1 (
  echo [OK] Python takip servisi hazir.
  exit /b 0
)
set /a N+=1
if %N% LSS 20 goto wait_ping
echo [HATA] Python takip servisi 40 saniye icinde hazir olmadi.
echo Takip (Python) penceresindeki hata mesajlarini kontrol edin.
exit /b 1
