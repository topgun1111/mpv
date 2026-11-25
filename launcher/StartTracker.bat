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
if exist "%~dp0tracker\__init__.py" (set "ROOT=%~dp0.") else (set "ROOT=%~dp0..")
for %%F in ("%ROOT%") do set "ROOT=%%~fF"
cd /d "%ROOT%"
set "TRACKER=%ROOT%\tracker.exe"
set "MPV=%ROOT%\mpv\mpv.exe"
set "CFG=%APPDATA%\TakipliOynat\config.json"
if defined TAKIPLI_DATA_DIR set "CFG=%TAKIPLI_DATA_DIR%\config.json"

if not exist "%TRACKER%" (
  set "WHY=tracker.exe bulunamadi. Paket eksik; uygulamayi yeniden indir/kur."
  goto :fail
)
echo [OK] Tracker: "%TRACKER%"

rem Servis zaten calisiyorsa ikinci kopyayi acma.
rem NOT: "tracker ping" burada KULLANILMAZ; ping mpv IPC ister, mpv ise henuz acilmadi (kilitlenme).
rem Bunun yerine bu kurulum klasorune ait calisan "tracker live" sureci aranir (yalniz okuma; hicbir surec sonlandirilmaz).
call :count_tracker
if not "%TRK_COUNT%"=="0" (
  echo [OK] Takip servisi zaten calisiyor - %TRK_COUNT% surec, yenisi baslatilmayacak.
  exit /b 0
)

if exist "%CFG%" (
  start "Takip" "%TRACKER%" --config "%CFG%" live --wait 120
) else (
  start "Takip" "%TRACKER%" live --wait 120
)

if errorlevel 1 (
  set "WHY=Takip servisi baslatilamadi."
  goto :fail
)
echo [OK] Takip servisi baslatildi; mpv baglantisi bekleniyor.
exit /b 0

rem Bu kurulum klasorune ait "tracker.exe ... live" islemlerini sayar -> TRK_COUNT. Hicbir sureci sonlandirmaz.
:count_tracker
set "TRK_COUNT=0"
for /f "usebackq delims=" %%C in (`powershell -NoProfile -Command "(Get-CimInstance Win32_Process -Filter 'Name=''tracker.exe''' | Where-Object { $_.ExecutablePath -eq $env:TRACKER -and $_.CommandLine -like '*live*' } | Measure-Object).Count" 2^>nul`) do set "TRK_COUNT=%%C"
exit /b 0

:fail
echo.
echo [HATA] %WHY%
>> "%TEMP%\takipli-start.log" echo %DATE% %TIME% [HATA] %WHY%
echo (Kayit: %TEMP%\takipli-start.log)
pause
exit /b 1
