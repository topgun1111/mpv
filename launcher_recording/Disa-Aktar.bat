@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
rem Takipli Oynat Kayit: kayittaki kamera hareketini videoya uygular -> VIDEO.kamera.mp4
rem Kullanim: videoyu bu dosyanin ustune surukleyin (once mpv'de R ile kayit yapin).
if "%~1"=="" goto usage
if not exist "%~1.rec.json" goto norec
set "PY=%~dp0python\python.exe"
if not exist "%PY%" goto nopy
"%PY%" -m recorder export "%~1"
if errorlevel 1 goto fail
echo.
echo Tamam: video yaninda .kamera.mp4 olusturuldu.
pause
exit /b 0
:usage
echo Kullanim: bir videoyu Disa-Aktar.bat dosyasinin ustune surukleyin.
pause
exit /b 1
:norec
echo HATA: kayit dosyasi yok: %~1.rec.json
echo Once Kayit.bat ile videoyu acin, zoom ve surukleme yaparken R ile kaydi baslatip durdurun.
pause
exit /b 1
:nopy
echo HATA: python klasoru bulunamadi: %PY%
pause
exit /b 1
:fail
echo.
echo HATA: disa aktarma basarisiz (ayrintilar yukarida).
pause
exit /b 1
