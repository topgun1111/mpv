@echo off
rem Ana baslatici: once Python takip servisini hazirla, sonra mpv'yi ac.
chcp 65001 >nul
setlocal
set "ROOT=%~dp0.."
for %%F in ("%ROOT%") do set "ROOT=%%~fF"
cd /d "%ROOT%"
if not exist "%ROOT%\mpv\mpv.exe" (
  echo [HATA] mpv\mpv.exe bulunamadi.
  pause
  exit /b 1
)
rem 1) Python hazirligi + surecin baslatilmasi (IPC beklenmez). 2) mpv hemen acilir; Python baglantiyi kendisi kurar.
call "%ROOT%\launcher\StartTracker.bat"
if errorlevel 1 (
  echo.
  echo [UYARI] Takip servisi baslatilamadi. mpv yine de acilsin mi?
  choice /c EH /n /m "Evet / Hayir (E/H): "
  if errorlevel 2 exit /b 1
)
set "TAKIP_PY_STARTED=1"
start "" "%ROOT%\mpv\mpv.exe" --config-dir="%ROOT%\mpv\portable_config" --player-operation-mode=pseudo-gui %*
exit /b 0
