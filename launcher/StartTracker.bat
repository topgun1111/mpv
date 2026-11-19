@echo off
rem Takipli Oynat - Python takip servisini kontrol et ve gerekirse baslat.
rem Bu dosya hem Baslat.bat tarafindan hem mpv'nin track.lua otomatik baslatmasindan cagrilir.
chcp 65001 >nul
setlocal
rem E:\Tracking kullanilabiliyorsa veri klasoru orasi; degilse (E: yok) varsayilan %APPDATA%\TakipliOynat (hata vermez).
set "TAKIPLI_DATA_DIR=E:\Tracking"
if not exist "%TAKIPLI_DATA_DIR%\" mkdir "%TAKIPLI_DATA_DIR%" 2>nul
if not exist "%TAKIPLI_DATA_DIR%\" (
  echo [UYARI] E:\Tracking olusturulamadi; varsayilan veri klasoru kullanilacak.
  set "TAKIPLI_DATA_DIR="
)
set "ROOT=%~dp0.."
for %%F in ("%ROOT%") do set "ROOT=%%~fF"
cd /d "%ROOT%"
set "PY=%ROOT%\python\python.exe"
set "MPV=%ROOT%\mpv\mpv.exe"
set "CFG=%APPDATA%\TakipliOynat\config.json"
if defined TAKIPLI_DATA_DIR set "CFG=%TAKIPLI_DATA_DIR%\config.json"

if not exist "%PY%" (
  echo [UYARI] Paketli Python yok: "%PY%" - sistemdeki Python aranacak.
  call "%~dp0_python.bat"
  if not defined PY (
    set "WHY=Python bulunamadi. Python 3.11/3.12 kur (python.org, Add to PATH) ya da python\ klasorunu ekle."
    goto :fail
  )
  goto :havepy
)
:havepy
echo [OK] Python: "%PY%"
if not exist "%ROOT%\tracker\__init__.py" (
  set "WHY=tracker paketi bulunamadi: %ROOT%\tracker"
  goto :fail
)

rem Gerekli paketleri dogrula (hata metni gorunur; DLL hatasi = genelde VC++ Runtime eksik).
set "IMPERR=%TEMP%\takipli-import.txt"
"%PY%" -c "import numpy,cv2,onnxruntime" >nul 2>"%IMPERR%"
if errorlevel 1 (
  type "%IMPERR%"
  findstr /i /c:"DLL load failed" /c:"msvcp140" /c:"vcruntime" "%IMPERR%" >nul 2>nul
  if not errorlevel 1 (
    set "WHY=DLL yuklenemedi: Microsoft Visual C++ Runtime (x64) eksik. Kur: https://aka.ms/vs/17/release/vc_redist.x64.exe"
  ) else (
    set "WHY=Python paketleri eksik/bozuk: numpy / opencv / onnxruntime. Yukaridaki hata metnine bak."
  )
  goto :fail
)

rem Kisi algilama modeli olmadan takip baslatilamaz.
set "HASMODEL="
for %%M in (yolox_s yolov8n yolox_m yolox_tiny yolox_nano) do (
  if exist "%ROOT%\models\%%M.onnx" set "HASMODEL=1"
)
if not defined HASMODEL (
  set "WHY=models klasorunde kisi algilama modeli yok (yolox_s/yolov8n .onnx)."
  goto :fail
)

rem DirectML varsa kullanilir; yoksa CPU provider ile devam eder.
"%PY%" -c "import onnxruntime as o,sys;p=o.get_available_providers();print('ONNX providers:',', '.join(p));sys.exit(0 if 'DmlExecutionProvider' in p else 3)"
if errorlevel 1 echo [UYARI] DirectML bulunamadi; CPU kullanilabilir.

rem Servis zaten calisiyorsa ikinci kopyayi acma.
rem NOT: "tracker ping" burada KULLANILMAZ; ping mpv IPC ister, mpv ise henuz acilmadi (kilitlenme).
rem Bunun yerine bu kurulum klasorune ait calisan "tracker live" sureci aranir (yalniz okuma; hicbir surec sonlandirilmaz).
call :count_tracker
if not "%TRK_COUNT%"=="0" (
  echo [OK] Takip servisi zaten calisiyor (%TRK_COUNT% surec); yenisi baslatilmayacak.
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
set "WHY=Python takip sureci baslatilamadi. 'Takip (Python)' penceresindeki hatayi oku."
goto :fail

rem Bu kurulum klasorune ait "python -m tracker ... live" islemlerini sayar -> TRK_COUNT. Hicbir sureci sonlandirmaz.
:count_tracker
set "TRK_COUNT=0"
for /f "usebackq delims=" %%C in (`powershell -NoProfile -Command "(Get-CimInstance Win32_Process -Filter 'Name=''python.exe''' | Where-Object { $_.CommandLine -like ('*'+$env:ROOT+'*') -and $_.CommandLine -like '*-m tracker*live*' } | Measure-Object).Count" 2^>nul`) do set "TRK_COUNT=%%C"
exit /b 0

:fail
echo.
echo [HATA] %WHY%
>> "%TEMP%\takipli-start.log" echo %DATE% %TIME% [HATA] %WHY%
echo (Kayit: %TEMP%\takipli-start.log)
pause
exit /b 1
