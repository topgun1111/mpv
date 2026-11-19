# Python startup integration

- `launcher/Baslat.bat` is the recommended application entry point.
- It calls `launcher/StartTracker.bat`, which checks the bundled Python, core packages,
  person-detection model, ONNX providers, starts the visible tracker console, and waits
  for the tracker IPC ping before mpv starts.
- If `mpv.exe` is opened directly, `track.lua` calls the same helper automatically.
- `TAKIP_PY_STARTED=1` prevents a duplicate Python service when mpv was opened through
  the main launcher.
- If the tracker is already running, the helper reuses it rather than starting another copy.

The uploaded `Baslat-Kontrol.bat` was adapted to the project's `launcher/` layout.
The old broad process-kill step was intentionally omitted: forcibly killing every
Python/mpv process matching an installation path could terminate another active session.
