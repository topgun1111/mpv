@echo off
rem Takipli Oynat - tracker.exe servis surecini kontrol et ve gerekirse baslat.
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
set "TRACKER=%ROOT%\tracker.exe"
set "MPV=%ROOT%\mpv\mpv.exe"
set "CFG=%APPDATA%\TakipliOynat\config.json"
if defined TAKIPLI_DATA_DIR set "CFG=%TAKIPLI_DATA_DIR%\config.json"

if not exist "%TRACKER%" (
  set "WHY=tracker.exe bulunamadi. Nuitka paket derlemesi eksik; uygulamayi yeniden indir/kur."
  goto :fail
)
echo [OK] Tracker: "%TRACKER%"

rem Kisi algilama modeli olmadan takip baslatilamaz.
set "HASMODEL="
for %%M in (yolox_s yolov8n yolox_m yolox_tiny yolox_nano) do (
  if exist "%ROOT%\models\%%M.onnx" set "HASMODEL=1"
)
if not defined HASMODEL (
  set "WHY=models klasorunde kisi algilama modeli yok (yolox_s/yolov8n .onnx)."
  goto :fail
)

rem DirectML provider ve DLL butunlugu CI duman testinde dogrulanir.

rem Servis zaten calisiyorsa ikinci kopyayi acma.
rem NOT: "tracker ping" burada KULLANILMAZ; ping mpv IPC ister, mpv ise henuz acilmadi (kilitlenme).
rem Bunun yerine bu kurulum klasorune ait calisan "tracker live" sureci aranir (yalniz okuma; hicbir surec sonlandirilmaz).
call :count_tracker
if not "%TRK_COUNT%"=="0" (
  echo [OK] Takip servisi zaten calisiyor (%TRK_COUNT% surec); yenisi baslatilmayacak.
  exit /b 0
)

if exist "%CFG%" (
  start "Takip" cmd /d /k ""%TRACKER%" --config "%CFG%" live --wait 120"
) else (
  start "Takip" cmd /d /k ""%TRACKER%" live --wait 120"
)

rem tracker.exe SURECININ baslatildigini dogrula (IPC'nin hazir olmasi BEKLENMEZ).
rem Tracker, mpv acilana kadar kendi icinde bekler ve baglantiyi kendisi kurar.
set "N=0"
:wait_started
timeout /t 1 /nobreak >nul
call :count_tracker
if not "%TRK_COUNT%"=="0" (
  echo [OK] Takip servisi baslatildi; mpv'ye baglanmasi bekleniyor.
  exit /b 0
)
set /a N+=1
if %N% LSS 10 goto wait_started
set "WHY=Python takip sureci baslatilamadi. 'Takip' penceresindeki hatayi oku."
goto :fail

rem Bu kurulum klasorune ait "tracker.exe ... live" islemlerini sayar -> TRK_COUNT. Hicbir sureci sonlandirmaz.
:count_tracker
set "TRK_COUNT=0"
for /f "usebackq delims=" %%C in (`powershell -NoProfile -Command "(Get-CimInstance Win32_Process -Filter 'Name=''tracker.exe''' | Where-Object { $_.ExecutablePath -like ($env:ROOT+'*') -and $_.CommandLine -like '*live*' } | Measure-Object).Count" 2^>nul`) do set "TRK_COUNT=%%C"
exit /b 0

:fail
echo.
echo [HATA] %WHY%
>> "%TEMP%\takipli-start.log" echo %DATE% %TIME% [HATA] %WHY%
echo (Kayit: %TEMP%\takipli-start.log)
pause
exit /b 1
