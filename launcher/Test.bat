@echo off
rem Takipli Oynat - tek dosyayi otomatik test et, gunlugu MASAUSTUNE yaz.
rem Kullanim: video dosyasini bu dosyanin ustune surukle birak (ya da Sag-Tik-Ekle.bat ile sag tik menusune ekle).
rem Alt vucut kutusu otomatik secilir; elle vermek icin video.mp4.test.json (rect) yanina koy.
chcp 65001 >nul
setlocal
if exist "%~dp0tracker\__init__.py" (set "ROOT=%~dp0") else (set "ROOT=%~dp0..\")
cd /d "%ROOT%"
set "VID=%~1"
set "PY=%ROOT%python\python.exe"
if not exist "%PY%" set "PY=python"
if "%VID%"=="" (
  echo Kullanim: video dosyasini Test.bat uzerine surukle birak.
  pause
  exit /b 1
)
"%PY%" -c "import numpy, cv2, onnxruntime" 2>nul
if errorlevel 1 (
  echo Gerekli paketler yukleniyor: numpy, opencv, onnxruntime...
  "%PY%" -m pip install -r requirements.txt
  "%PY%" -c "import numpy, cv2, onnxruntime" 2>nul
  if errorlevel 1 (
    echo HATA: paketler yuklenemedi. Python surumu: 
    "%PY%" --version
    echo onnxruntime-directml Python 3.14 icin henuz olmayabilir; Python 3.12 kur ve tekrar dene.
    pause
    exit /b 1
  )
)
"%PY%" -m tracker.autotest --file "%VID%" --device dml %2 %3 %4
echo.
echo Bitti. Gunluk masaustunde: Takipli-Test-... klasoru ve .md dosyasi (hata varsa yukaridaki yazilara bak).
pause
