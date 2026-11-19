@echo off
rem Takipli Oynat Kayit: videoyu bu dosyanin ustune suruklemek de olur.
start "" "%~dp0mpv\mpv.exe" --player-operation-mode=pseudo-gui %*
