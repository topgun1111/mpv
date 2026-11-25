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


def main(root):
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
    subprocess.Popen(["cmd.exe", "/d", "/c", "Baslat.bat", "--pause",
                      "--msg-level=cplayer=debug", "--log-file=player.log", clip.name], cwd=root)
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
            player.command("script-message", "track-toggle", "on")
            player.command("script-message", "track-rect", ".4", ".2", ".5", ".3",
                           "360", "480", "0")
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                log = (root / "player.log").read_text("utf-8", errors="replace")
                skeleton = any("track-skel" in line and ";" in line for line in log.splitlines())
                if player.get_property("video-zoom") > 0.01 and skeleton:
                    print("Live target selected, camera zoom applied, pose keypoints sent to Lua.")
                    break
                time.sleep(0.2)
            else:
                raise RuntimeError("Missing live zoom or pose keypoints after target selection")
        finally:
            try:
                player.command("quit")
            except MpvIpcError:
                pass


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
    main(Path(sys.argv[1]).resolve())
