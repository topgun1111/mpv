# Toast notification placement fix

- Replaced tracker/update/error notifications that used mpv's default OSD with a dedicated ASS overlay.
- Notifications now appear centered near the bottom of the video, above the playback controls, rather than in the area immediately below the top menu.
- The toast layer is placed above the tracker/menu overlays, uses a readable dark outline, scales with window height, and clears itself after the requested duration.
- Python live-tracking status messages and playback-bar speed/volume feedback are routed through `script-message-to track track-toast`, so they use the same placement.
- The diagnostic message also uses the toast layer.

Validation: `compileall` succeeded. Focused tests for tracker Lua, playback-bar notifications, update flow, and live tracking passed (54 tests). A full test-suite run exceeded the 120-second execution limit; it had several unrelated existing failures before timeout. Actual Windows/mpv visual verification is still required.
