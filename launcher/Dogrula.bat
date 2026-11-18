@echo off
rem Takipli Oynat - otomatik dogrulama. Klipleri "klipler" klasorune koy, bu dosyaya cift tikla.
rem Istege bagli: klip.mp4.test.json (rect, start, expect). Rapor: validation\<zaman>\report.md
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PY=%~dp0python\python.exe"
if not exist "%PY%" set "PY=python"
if not exist "klipler" mkdir "klipler"
"%PY%" -m tracker.autotest --clips klipler --device dml %*
echo.
pause
