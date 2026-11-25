"""Exercise the packaged Windows launcher, tracker, and mpv with a textured test clip."""
import os
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from tracker.config import default_ipc_path
from tracker.ipc import MpvIpc, MpvIpcError, wait_for_ipc


def main(root):
    clip = root / "target.avi"
    frame = np.random.default_rng(4).integers(0, 256, (240, 320, 3), dtype=np.uint8)
    writer = cv2.VideoWriter(str(clip), cv2.VideoWriter_fourcc(*"MJPG"), 25, (320, 240))
    assert writer.isOpened(), "VideoWriter failed"
    try:
        for _ in range(250):
            writer.write(frame)
    finally:
        writer.release()
    subprocess.Popen(["cmd.exe", "/d", "/c", "Baslat.bat", "--pause",
                      "--msg-level=ipc=trace", "--log-file=player.log", clip.name], cwd=root)
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
            player.command("script-message", "track-rect", ".4", ".4", ".5", ".5",
                           "320", "240", "0")
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                if player.get_property("video-zoom") > 0.01:
                    print("Live target selected and mpv zoom changed.")
                    return
                time.sleep(0.2)
            raise RuntimeError("No tracked zoom after rectangle selection")
        finally:
            try:
                player.command("quit")
            except MpvIpcError:
                pass


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
