@echo off
rem Python takip programini GORUNUR CMD penceresinde calistirir (mpv'nin track.lua'si bunu acar; elle de calisir).
rem Pencereyi kapatma: kapanirsa takip durur. Hatalar burada gorunur.
chcp 65001 >nul
setlocal
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
set "CFG="
if exist "%APPDATA%\TakipliOynat\config.json" set "CFG=--config "%APPDATA%\TakipliOynat\config.json""
echo Takip programi basliyor; mpv acilinca baglanir...
"%PY%" -m tracker %CFG% live --wait 120
echo.
echo Takip programi durdu (yukaridaki hataya bak).
pause
