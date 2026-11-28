#!/usr/bin/env python3
"""Create a byte-exact delta of signed APKs, copying unchanged raw ZIP payloads.
Never unzip/repack an APK: its signing block must survive byte for byte.
"""
import argparse
import gzip
import hashlib
import io
import json
import os
import re
import struct
import subprocess
import tempfile
import zipfile
from pathlib import Path

MAGIC = b"PCDELTA1"
MAX_APK = 512 * 1024 * 1024

def sha(data):
    return hashlib.sha256(data).digest()

def entries(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        result = {}
        for item in archive.infolist():
            offset = item.header_offset
            if data[offset:offset+4] != b"PK\x03\x04":
                raise ValueError("invalid local ZIP header")
            name_len, extra_len = struct.unpack_from("<HH", data, offset + 26)
            start = offset + 30 + name_len + extra_len
            end = start + item.compress_size
            if end > len(data):
                raise ValueError("invalid ZIP payload bounds")
            result[item.filename] = (start, end)
        return result

def create(base, target):
    if not 0 < len(target) <= MAX_APK:
        raise ValueError("invalid target size")
    old = entries(base)
    matches = []
    for name, (start, end) in entries(target).items():
        if name in old and end - start >= 64:
            a, b = old[name]
            if b-a == end-start and base[a:b] == target[start:end]:
                matches.append((start, end, a))
    stream = io.BytesIO()
    with gzip.GzipFile(fileobj=stream, mode="wb", mtime=0) as out:
        out.write(MAGIC + sha(base) + sha(target) + struct.pack(">Q", len(target)))
        cursor = 0
        for start, end, source in sorted(matches):
            if start < cursor:
                continue
            if start > cursor:
                out.write(struct.pack(">BI", 1, start-cursor))
                out.write(target[cursor:start])
            out.write(struct.pack(">BQI", 0, source, end-start))
            cursor = end
        if cursor < len(target):
            out.write(struct.pack(">BI", 1, len(target)-cursor))
            out.write(target[cursor:])
        out.write(b"\x02")
    return stream.getvalue()

def reconstruct(base, patch):
    """Independent CI round-trip verification of the generated patch."""
    with gzip.GzipFile(fileobj=io.BytesIO(patch)) as inp:
        if inp.read(8) != MAGIC or inp.read(32) != sha(base):
            raise ValueError("base mismatch")
        target_hash = inp.read(32)
        size, = struct.unpack(">Q", inp.read(8))
        if not 0 < size <= MAX_APK:
            raise ValueError("invalid output size")
        out = bytearray()
        while True:
            op = inp.read(1)
            if op == b"\x02":
                break
            if op == b"\x00":
                offset, length = struct.unpack(">QI", inp.read(12))
                if offset + length > len(base):
                    raise ValueError("invalid copy")
                chunk = base[offset:offset+length]
            elif op == b"\x01":
                length, = struct.unpack(">I", inp.read(4))
                chunk = inp.read(length)
            else:
                raise ValueError("invalid record")
            if not length or len(chunk) != length or len(out)+length > size:
                raise ValueError("invalid length")
            out.extend(chunk)
        if inp.read(1) or len(out) != size or sha(out) != target_hash:
            raise ValueError("target mismatch")
        return bytes(out)

def self_test():
    def apk(changed, order):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for name in order:
                z.writestr(name, changed if name == "classes.dex" else bytes(range(256))*400)
        return data.getvalue()
    a = apk(b"old code", ["classes.dex", "assets/font"])
    b = apk(b"new longer code", ["assets/font", "classes.dex"])
    patch = create(a, b)
    assert reconstruct(a, patch) == b
    assert len(patch) < len(b)
    try:
        reconstruct(b, patch)
    except ValueError:
        pass
    else:
        raise AssertionError("wrong base accepted")
    print("APK delta self-test passed")

RECORD_APK = re.compile(r"TakipliKayit-Android-(\d+)\.(\d+)\.(\d+)-b(\d+)\.apk")


def record_version(name):
    match = RECORD_APK.fullmatch(name)
    if not match:
        return None
    return tuple(map(int, match.groups()))


def make_patch(base, target, target_path):
    patch = create(base, target)
    if reconstruct(base, patch) != target:
        raise RuntimeError("round-trip failed")
    if len(patch) >= len(target) * 0.85:
        return None
    version = target_path.stem.removeprefix("TakipliKayit-Android-")
    name = f"TakipliKayit-Patch-{sha(base).hex()}-{sha(target).hex()}-{version}.patch"
    print(f"{name}: {len(patch):,} / {len(target):,} bytes")
    return name, patch


def from_releases(target_path):
    target_version = record_version(target_path.name)
    if target_version is None:
        raise ValueError("not a versioned recorder APK")
    target = target_path.read_bytes()
    repo = os.environ["GITHUB_REPOSITORY"]
    releases = json.loads(subprocess.check_output(
        ["gh", "api", f"repos/{repo}/releases?per_page=30"], text=True,
    ))
    candidates = []
    for release in releases:
        if release["draft"]:
            continue
        for asset in release["assets"]:
            version = record_version(asset["name"])
            if version is not None and version < target_version:
                candidates.append((version, release["tag_name"], asset["name"]))
    for _, tag, name in sorted(candidates, reverse=True)[:8]:
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(
                ["gh", "release", "download", tag, "--pattern", name, "--dir", tmp], check=True,
            )
            result = make_patch((Path(tmp) / name).read_bytes(), target, target_path)
        if result:
            patch_name, patch = result
            (target_path.parent / patch_name).write_bytes(patch)


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--from-releases", action="store_true")
    parser.add_argument("target", type=Path, nargs="?")
    parser.add_argument("--base", type=Path)
    args = parser.parse_args()
    if args.self_test:
        self_test()
    elif args.from_releases and args.target:
        from_releases(args.target)
    elif args.target and args.base:
        result = make_patch(args.base.read_bytes(), args.target.read_bytes(), args.target)
        if result:
            name, patch = result
            (args.target.parent / name).write_bytes(patch)
        else:
            print("Delta would be at least 85% of the full APK")
    else:
        parser.error("provide --self-test, --from-releases TARGET, or TARGET --base BASE")


if __name__ == "__main__":
    main()
