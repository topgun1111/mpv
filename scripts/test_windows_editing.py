"""Headless Windows integration checks against the actual packaged MPV/FFmpeg executables."""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(args, **kwargs):
    result = subprocess.run([str(a) for a in args], capture_output=True, timeout=90, **kwargs)
    if result.returncode:
        raise RuntimeError(
            f"{args[0]} failed ({result.returncode}): "
            + result.stderr.decode("utf-8", errors="replace")
            + result.stdout.decode("utf-8", errors="replace")
        )
    return result.stdout


def pixels(ffmpeg, raw, graph):
    return run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-filter_threads", "1",
        "-f", "rawvideo", "-pixel_format", "yuv420p", "-video_size", "160x120",
        "-framerate", "5", "-i", raw, "-vf", graph or "null",
        "-frames:v", "1", "-pix_fmt", "yuv420p", "-f", "rawvideo", "-",
    ])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--recording", action="store_true")
    args = parser.parse_args()
    pkg = args.package.resolve()
    mpv = pkg / "mpv/mpv.com"
    if not mpv.is_file():
        mpv = pkg / "mpv/mpv.exe"
    ffmpeg = pkg / "ffmpeg/ffmpeg.exe"
    modules = pkg / "mpv/portable_config/script-modules"
    env = dict(os.environ, EDITING_MODULES=str(modules))
    with tempfile.TemporaryDirectory() as tmp:
        temp = Path(tmp)
        clip = temp / "video.mp4"
        raw = temp / "frame.yuv"
        # Low contrast edges, gradient, fine noise and chroma variation; not a flat test card.
        y = bytes(
            65 + x // 3 + (25 if (x // 20 + yy // 20) % 2 else 0)
            + ((x * 17 + yy * 31) % 17) - 8
            for yy in range(120) for x in range(160)
        )
        u = bytes(95 + (x * 3 + yy) % 65 for yy in range(60) for x in range(80))
        v = bytes(100 + (x + yy * 3) % 60 for yy in range(60) for x in range(80))
        raw.write_bytes(y + u + v)
        run([
            ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
            "-i", "testsrc2=size=320x240:rate=10", "-t", "1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", clip,
        ])
        log = temp / "mpv.log"
        run([
            mpv, "--no-config", "--vo=null", "--ao=null", "--pause=yes", "--keep-open=yes",
            f"--log-file={log}", f"--script={ROOT / 'tests/editing_mpv_smoke.lua'}", clip,
        ], env=env)
        data = log.read_text(encoding="utf-8", errors="replace")
        assert "EDITING_MPV_SMOKE_OK" in data, data
        graphs = dict(re.findall(r"EDITING_GRAPH\|([^|\r\n]+)\|([^\r\n]+)", data))
        expected = {
            "haze", "contrast", "brightness", "gamma", "saturation", "shadows",
            "highlights", "warmth", "clarity", "sharpness", "denoise",
            "contrast_negative", "brightness_negative", "gamma_negative",
            "saturation_negative", "shadows_negative", "highlights_negative", "warmth_negative",
            "clarity_middle", "sharpness_middle",
        }
        assert set(graphs) == expected, set(graphs)
        baseline = pixels(ffmpeg, raw, "")
        differences = {}
        for name, graph in sorted(graphs.items()):
            changed = pixels(ffmpeg, raw, graph.strip())
            assert len(changed) == len(baseline)
            diff = sum(abs(a - b) for a, b in zip(baseline, changed)) / len(baseline)
            assert diff > 0.15, f"{name} had negligible effect: {diff:.3f}"
            differences[name] = diff
            print(f"PIXEL CHANGE {name}: mean absolute difference {diff:.3f}")
        for name in ("clarity", "sharpness"):
            assert differences[name] > differences[name + "_middle"] > 0.5
        # Execute real Lua mouse/resize regression in the shipped mpv interpreter.
        env["EDITING_HARNESS"] = str(ROOT / "tests/lua_harness_editing_ui.lua")
        log = temp / "ui.log"
        run([
            mpv, "--no-config", "--vo=null", "--ao=null", "--idle=yes",
            f"--log-file={log}", f"--script={ROOT / 'tests/editing_harness_mpv.lua'}",
        ], env=env, cwd=ROOT)
        assert "EDITING_UI_OK" in log.read_text(encoding="utf-8", errors="replace")
        if args.recording:
            env["EDITING_HARNESS"] = str(ROOT / "tests/lua_harness_recording_menu.lua")
            log = temp / "menu.log"
            run([
                mpv, "--no-config", "--vo=null", "--ao=null", "--idle=yes",
                f"--log-file={log}", f"--script={ROOT / 'tests/editing_harness_mpv.lua'}",
            ], env=env, cwd=ROOT)
            assert "EDITING_UI_OK" in log.read_text(encoding="utf-8", errors="replace")
            log = temp / "recording.log"
            run([
                mpv, f"--config-dir={pkg / 'mpv/portable_config'}", "--load-scripts=yes",
                "--input-ipc-server=", "--vo=null", "--ao=null", "--pause=yes",
                "--save-position-on-quit=no", "--resume-playback=no",
                "--keep-open=yes", f"--log-file={log}",
                f"--script={ROOT / 'tests/editing_recording_mpv.lua'}", clip,
            ], env=env)
            data = log.read_text(encoding="utf-8", errors="replace")
            assert "RECORDING_EDITING_OK" in data, data
            # Try a genuine native Windows video output using the software D3D11 renderer.
            if os.name == "nt":
                portrait = temp / "portrait.mp4"
                run([
                    ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                    "-i", "testsrc2=size=180x320:rate=5", "-t", "1",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", portrait,
                ])
                env.update(WINDOW_LANDSCAPE=str(clip), WINDOW_PORTRAIT=str(portrait),
                           WINDOW_SHOTS=str(temp))
                log = temp / "window.log"
                native_args = [
                    mpv, f"--config-dir={pkg / 'mpv/portable_config'}", "--load-scripts=yes",
                    "--input-ipc-server=", "--vo=gpu", "--gpu-api=d3d11", "--gpu-context=d3d11",
                    "--d3d11-warp=yes", "--ao=null", "--force-window=immediate", "--idle=yes",
                    "--save-position-on-quit=no", "--resume-playback=no",
                    "--geometry=800x500", "--pause=yes", f"--log-file={log}",
                    f"--script={ROOT / 'tests/recording_native_window.lua'}",
                ]
                result = subprocess.run(
                    [str(a) for a in native_args], capture_output=True, env=env, timeout=45,
                )
                data = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
                if "WINDOW_GEOMETRY_AVAILABLE" in data:
                    assert result.returncode == 0 and "WINDOW_GEOMETRY_OK" in data, data
                    assert "GPU_PREVIEW_OK" in data, data
                    # Compare actual rendered pixels, excluding HUD, subtitles and window edges.
                    def screenshot_pixels(name):
                        return run([
                            ffmpeg, "-hide_banner", "-loglevel", "error",
                            "-i", temp / name, "-vf", "crop=200:160:(iw-200)/2:(ih-160)/2",
                            "-pix_fmt", "rgb24", "-f", "rawvideo", "-",
                        ])
                    before, after, reset = (
                        screenshot_pixels(name) for name in ("before.png", "after.png", "reset.png")
                    )
                    assert len(before) == len(after) == len(reset) == 200 * 160 * 3
                    delta = sum(abs(a-b) for a, b in zip(before, after)) / len(before)
                    restored = sum(abs(a-b) for a, b in zip(before, reset)) / len(before)
                    assert delta > 2.0 and restored < 1.0, (delta, restored)
                    print(f"GPU_PREVIEW_PIXELS_OK: changed={delta:.3f}, reset={restored:.3f}")
                    print("NATIVE_WINDOWS_GEOMETRY_OK (WARP; not a physical GPU benchmark)")
                elif "WINDOW_GEOMETRY_UNAVAILABLE" in data:
                    print("NATIVE_WINDOWS_GEOMETRY_SKIPPED: runner has no usable native window")
                elif ("Error opening/initializing the selected video_out" in data
                      or "Failed to create D3D11 device" in data):
                    print("NATIVE_WINDOWS_GEOMETRY_SKIPPED: native renderer unavailable")
                    print(data[-4000:])
                else:
                    raise RuntimeError("Native window test failed to start: " + data)
    print("PACKAGED_EDITING_TESTS_OK")


if __name__ == "__main__":
    main()
