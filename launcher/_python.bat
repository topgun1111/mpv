@echo off
rem Python'u bulur ve PY degiskenine yazar. Bulunamazsa mesaj yazar, errorlevel 1 doner (cagiran pause ile gosterir).
rem Sira: paketli python\ -> py launcher -> LOCALAPPDATA/ProgramFiles Python3* -> PATH
set "PY="
if defined ROOT if exist "%ROOT%python\python.exe" set "PY=%ROOT%python\python.exe"
if defined PY goto :found
for %%V in (3.12 3.13 3.11 3.10) do (
  if not defined PY (
    py -%%V -c "import sys" >nul 2>nul
    if not errorlevel 1 for /f "delims=" %%P in ('py -%%V -c "import sys;print(sys.executable)"') do set "PY=%%P"
  )
)
if defined PY goto :found
for %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*" "%LOCALAPPDATA%\Python\pythoncore-*" "%ProgramFiles%\Python3*") do (
  if exist "%%~D\python.exe" set "PY=%%~D\python.exe"
)
if defined PY goto :found
python -c "import sys" >nul 2>nul
if not errorlevel 1 set "PY=python"
if defined PY goto :found
echo HATA: Python bulunamadi. Python 3.12 kur ^(python.org, "Add to PATH" isaretli^) ya da python\ klasorunu ekle.
exit /b 1
:found
exit /b 0
