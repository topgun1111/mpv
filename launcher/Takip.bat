@echo off
rem Python takip programini GORUNUR CMD penceresinde calistirir (mpv'nin track.lua'si bunu acar; elle de calisir).
rem Pencereyi kapatma: kapanirsa takip durur. Hatalar burada gorunur.
chcp 65001 >nul
setlocal
set "TAKIPLI_DATA_DIR=E:\Tracking"
if not exist "%TAKIPLI_DATA_DIR%\" mkdir "%TAKIPLI_DATA_DIR%"
if not exist "%TAKIPLI_DATA_DIR%\" (echo HATA: E:\Tracking klasoru olusturulamadi. E: surucusunu kontrol edin. & pause & exit /b 1)
title Takip (Python)
if exist "%~dp0tracker\__init__.py" (set "ROOT=%~dp0") else (set "ROOT=%~dp0..\")
cd /d "%ROOT%"
call "%~dp0_python.bat"
if errorlevel 1 (
  pause
  exit /b 1
)
"%PY%" -c "import numpy, cv2, onnxruntime" 2>nul
if errorlevel 1 (
  echo Gerekli paketler yukleniyor...
  "%PY%" -m pip install -r requirements.txt
)
echo Takip programi basliyor; mpv acilinca baglanir...
"%PY%" -m tracker --config "%TAKIPLI_DATA_DIR%\config.json" live --wait 120
echo.
echo Takip programi durdu (yukaridaki hataya bak).
pause
