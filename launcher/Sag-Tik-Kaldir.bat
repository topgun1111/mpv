@echo off
chcp 65001 >nul
for %%E in (.mp4 .mkv .mov .avi .webm) do reg delete "HKCU\Software\Classes\SystemFileAssociations\%%E\shell\TakipliTest" /f >nul 2>&1
echo Kaldirildi.
pause
