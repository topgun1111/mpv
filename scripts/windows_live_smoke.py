"""Exercise the packaged Windows launcher, tracker, and mpv with a textured test clip."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import cv2

from tracker.config import default_ipc_path
from tracker.ipc import MpvCommandError, MpvIpc, MpvIpcError, wait_for_ipc


def check_scan(player, root, frame):
    video = root / "scan.avi"
    # Center the test person so the input lands on a person even at the initial window size.
    frame = cv2.copyMakeBorder(frame, 0, 0, 55, 0, cv2.BORDER_REPLICATE)[:, :360]

    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 25, (360, 480))
    assert writer.isOpened()
    try:
        for _ in range(25):
            writer.write(frame)
    finally:
        writer.release()
    player.command("loadfile", str(video), "replace")
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if Path(player.get_property("path")) == video and player.get_property("pause"):
            break
        time.sleep(0.2)
    time.sleep(0.5)
    player.command("script-binding", "track/tracker")
    player.command("script-binding", "track/reset")
    time.sleep(0.4)
    d = player.get_property("osd-dimensions")
    x = round(d["ml"] + 0.5 * (d["w"] - d["ml"] - d["mr"]))
    y = round(d["mt"] + 0.5 * (d["h"] - d["mt"] - d["mb"]))
    player.command("mouse", x, y)
    time.sleep(0.3)
    player.command("mouse", x, y, 2, "single")
    time.sleep(0.4)
    player.set_property("pause", False)
    views = Path(str(video) + ".views.json")
    deadline = time.monotonic() + 75
    while time.monotonic() < deadline:
        if views.exists() and json.loads(views.read_text(encoding="utf-8"))["views"]:
            print("A real right-click and Play produced the offline camera path.")
            return
        time.sleep(0.5)
    raise RuntimeError("Missing offline camera path after right-click and Play")


def main(root, direct=False):
    clip = root / "target.avi"
    frame = cv2.resize(cv2.imread(str(root / "bus.jpg")), (360, 480))
    writer = cv2.VideoWriter(str(clip), cv2.VideoWriter_fourcc(*"MJPG"), 25, (360, 480))
    assert writer.isOpened(), "VideoWriter failed"
    try:
        for _ in range(250):
            writer.write(frame)
    finally:
        writer.release()
    (root / "player.log").unlink(missing_ok=True)
    launcher = [str(root / "mpv/mpv.exe")] if direct else ["cmd.exe", "/d", "/c", "Baslat.bat"]
    subprocess.Popen([*launcher, "--pause", "--msg-level=cplayer=debug",
                      "--log-file=player.log", clip.name], cwd=root)
    pipe = default_ipc_path()
    assert wait_for_ipc(pipe, 60), "Baslat.bat did not open mpv IPC"
    with MpvIpc(pipe) as player:
        try:
            deadline = time.monotonic() + 60
            folders = (Path("E:/Tracking"), Path(os.environ["APPDATA"]) / "TakipliOynat")
            while not any((folder / "tracker.lock").is_file() for folder in folders):
                if time.monotonic() >= deadline:
                    raise RuntimeError("The packaged tracker did not acquire its session lock")
                time.sleep(0.25)
            player.command("script-binding", "track/tracker")
            player.command("script-message-to", "track", "track-mode", "rect")
            time.sleep(0.5)  # allow Lua mode and enable messages to reach Python
            player.command("script-message", "track-rect", ".29", ".46", ".42", ".59",
                           "360", "480", "0")
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if player.get_property("video-zoom") > 0.01:
                    time.sleep(0.5)
                    snapshot = root / "tracked.png"
                    player.command("screenshot-to-file", str(snapshot), "window")
                    pixels = cv2.imread(str(snapshot))
                    assert pixels is not None
                    bgr = (64, 255, 64)
                    low = tuple(max(0, v - 22) for v in bgr)
                    high = tuple(min(255, v + 22) for v in bgr)
                    count = cv2.countNonZero(cv2.inRange(pixels, low, high))
                    if count >= 12:
                        print(f"Verified camera zoom and rectangle ({count} pixels).")
                        break  # wait for actual overlay, not only for zoom
                time.sleep(0.2)
            else:
                raise RuntimeError("Missing live zoom or rendered rectangle after selection")
            for old in root.glob("target.avi.recorded-*.views.json"):
                old.unlink()
            player.command("script-binding", "track/record-toggle")
            time.sleep(2)
            player.command("script-binding", "track/record-toggle")
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                recordings = list(root.glob("target.avi.recorded-*.views.json"))
                if recordings:
                    keys = json.loads(recordings[-1].read_text(encoding="utf-8"))["views"]
                    if len(keys) > 1 and keys[-1][0] > keys[0][0]:
                        break
                time.sleep(0.2)
            else:
                raise RuntimeError("Recording did not produce camera keyframes")
            print("Verified main application recording keyframes.")
            player.command("script-message-to", "track", "track-mode", "auto")
            if not direct:
                check_scan(player, root, frame)
        finally:
            try:
                player.command("quit")
            except MpvIpcError:
                pass

    if direct:
        return

    recording_pipe = r"\\.\pipe\mpv-recording-smoke"
    config = Path("mpv/portable_config_recording").resolve()
    proc = subprocess.Popen([root / "mpv/mpv.exe", f"--config-dir={config}",
                             f"--input-ipc-server={recording_pipe}", str(clip)], cwd=root)
    try:
        assert wait_for_ipc(recording_pipe, 30), "Recorder IPC did not open"
        with MpvIpc(recording_pipe) as player:
            deadline = time.monotonic() + 20
            while True:
                try:
                    if player.get_property("video-params"):
                        break
                except MpvCommandError:
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError("Recorder did not load test clip")
                time.sleep(0.2)
            player.command("script-binding", "kayit/record")
            time.sleep(0.5)
            player.command("script-binding", "kayit/space")
            time.sleep(2)
            assert player.get_property("time-pos") > 0.2, "Recorder did not start playback"
            player.command("script-binding", "kayit/record")
            result = Path(str(clip) + ".rec.json")
            for _ in range(50):
                if result.is_file():
                    break
                time.sleep(0.1)
            views = json.loads(result.read_text(encoding="utf-8"))["views"]
            assert views[-1][0] - views[0][0] > 0.2, "No recorded camera timeline"
            print(f"Recorder wrote {len(views)} camera samples.")
    finally:
        proc.terminate()
        proc.wait(timeout=10)


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve(), "--direct" in sys.argv[2:])
