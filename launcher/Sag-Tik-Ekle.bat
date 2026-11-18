@echo off
rem Video dosyalarinin sag tik menusune "Takipli Oynat ile test et" ekler (yalnizca bu kullanici, yonetici gerekmez).
rem Kaldirmak icin: Sag-Tik-Kaldir.bat
chcp 65001 >nul
setlocal
set "T=%~dp0Test.bat"
for %%E in (.mp4 .mkv .mov .avi .webm) do (
  reg add "HKCU\Software\Classes\SystemFileAssociations\%%E\shell\TakipliTest" /ve /d "Takipli Oynat ile test et" /f >nul
  reg add "HKCU\Software\Classes\SystemFileAssociations\%%E\shell\TakipliTest\command" /ve /d "\"%T%\" \"%%1\"" /f >nul
)
echo Eklendi. Bir videoya sag tikla: "Takipli Oynat ile test et".
pause
