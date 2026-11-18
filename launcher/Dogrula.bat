@echo off
rem Takipli Oynat - otomatik dogrulama. Klipleri "klipler" klasorune koy, bu dosyaya cift tikla.
rem Istege bagli: klip.mp4.test.json (rect, start, expect). Rapor: validation\<zaman>\report.md
chcp 65001 >nul
setlocal
if exist "%~dp0tracker\__init__.py" (set "ROOT=%~dp0") else (set "ROOT=%~dp0..\")
cd /d "%ROOT%"
set "PY=%ROOT%python\python.exe"
if not exist "%PY%" set "PY=python"
if not exist "klipler" mkdir "klipler"
"%PY%" -c "import numpy, cv2, onnxruntime" 2>nul
if errorlevel 1 (
  echo Gerekli paketler yukleniyor...
  "%PY%" -m pip install -r requirements.txt
)
"%PY%" -m tracker.autotest --clips klipler --device dml %*
echo.
pause
