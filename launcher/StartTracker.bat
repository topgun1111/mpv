@echo off
rem Takipli Oynat - Python takip servisini kontrol et ve gerekirse baslat.
rem Bu dosya hem Baslat.bat tarafindan hem mpv'nin track.lua otomatik baslatmasindan cagrilir.
chcp 65001 >nul
setlocal
set "TAKIPLI_DATA_DIR=E:\Tracking"
if not exist "%TAKIPLI_DATA_DIR%\" mkdir "%TAKIPLI_DATA_DIR%"
if not exist "%TAKIPLI_DATA_DIR%\" (echo HATA: E:\Tracking klasoru olusturulamadi. E: surucusunu kontrol edin. & pause & exit /b 1)
set "ROOT=%~dp0.."
for %%F in ("%ROOT%") do set "ROOT=%%~fF"
cd /d "%ROOT%"
set "PY=%ROOT%\python\python.exe"
set "MPV=%ROOT%\mpv\mpv.exe"
set "CFG=%TAKIPLI_DATA_DIR%\config.json"

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
rem NOT: "tracker ping" burada KULLANILMAZ; ping mpv IPC ister, mpv ise henuz acilmadi (kilitlenme).
rem Bunun yerine bu kurulum klasorune ait calisan "tracker live" sureci aranir (yalniz okuma; hicbir surec sonlandirilmaz).
call :count_tracker
if not "%TRK_COUNT%"=="0" (
  echo [OK] Takip servisi zaten calisiyor ^(%TRK_COUNT% surec^); yenisi baslatilmayacak.
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

rem Python SURECININ baslatildigini dogrula (IPC'nin hazir olmasi BEKLENMEZ).
rem Python, mpv acilana kadar kendi icinde bekler ve baglantiyi kendisi kurar.
set "N=0"
:wait_started
timeout /t 1 /nobreak >nul
call :count_tracker
if not "%TRK_COUNT%"=="0" (
  echo [OK] Python takip servisi baslatildi; mpv'ye baglanmasi bekleniyor.
  exit /b 0
)
set /a N+=1
if %N% LSS 10 goto wait_started
echo [HATA] Python takip sureci baslatilamadi.
echo Takip (Python) penceresindeki hata mesajlarini kontrol edin.
exit /b 1

rem Bu kurulum klasorune ait "python -m tracker ... live" islemlerini sayar -> TRK_COUNT. Hicbir sureci sonlandirmaz.
:count_tracker
set "TRK_COUNT=0"
for /f "usebackq delims=" %%C in (`powershell -NoProfile -Command "(Get-CimInstance Win32_Process -Filter 'Name=''python.exe''' | Where-Object { $_.CommandLine -like ('*'+$env:ROOT+'*') -and $_.CommandLine -like '*-m tracker*live*' } | Measure-Object).Count" 2^>nul`) do set "TRK_COUNT=%%C"
exit /b 0
