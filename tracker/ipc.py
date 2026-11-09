"""mpv JSON IPC istemcisi (Windows named pipe + Unix socket)."""
from __future__ import annotations

import json
import os
import socket
from collections import deque
from typing import Any

from .geometry import View


class MpvIpcError(RuntimeError):
    pass


class MpvIpc:
    def __init__(self, path: str, timeout: float = 2.0):
        self.path = path
        self.timeout = timeout
        self._next_id = 1
        self._buf = b""
        self._sock: socket.socket | None = None
        self._pipe = None
        self._events: deque[dict[str, Any]] = deque()

    # --- bağlantı ---
    def connect(self) -> None:
        if os.name == "nt":
            try:
                self._pipe = open(self.path, "r+b", buffering=0)
            except OSError as e:
                raise MpvIpcError(f"mpv pipe açılamadı: {self.path}: {e}") from e
        else:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(self.timeout)
            try:
                s.connect(self.path)
            except OSError as e:
                s.close()
                raise MpvIpcError(f"mpv soketi açılamadı: {self.path}: {e}") from e
            self._sock = s

    def close(self) -> None:
        if self._sock:
            self._sock.close()
            self._sock = None
        if self._pipe:
            self._pipe.close()
            self._pipe = None

    def __enter__(self) -> MpvIpc:
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- düşük seviye ---
    def _write(self, data: bytes) -> None:
        if self._sock:
            self._sock.sendall(data)
        elif self._pipe:
            self._pipe.write(data)
        else:
            raise MpvIpcError("bağlı değil")

    def _readline(self, timeout: float | None = None) -> bytes | None:
        """Bir satır okur. `timeout` verilirse ve süre dolarsa None döner (yalnız Unix soketi;
        Windows pipe'ında okuma bloklar, canlı modda ayrı iş parçacığı kullanılacak)."""
        if self._pipe:
            line = self._pipe.readline()
            if not line:
                raise MpvIpcError("mpv bağlantısı kapandı")
            return line
        assert self._sock is not None
        wait = self.timeout if timeout is None else timeout
        self._sock.settimeout(wait)
        try:
            while b"\n" not in self._buf:
                try:
                    chunk = self._sock.recv(4096)
                except TimeoutError as e:
                    if timeout is not None:
                        return None
                    raise MpvIpcError("mpv yanıt zaman aşımı") from e
                if not chunk:
                    raise MpvIpcError("mpv bağlantısı kapandı")
                self._buf += chunk
        finally:
            self._sock.settimeout(self.timeout)
        line, self._buf = self._buf.split(b"\n", 1)
        return line

    # --- komutlar ---
    def command(self, *args: Any) -> Any:
        rid = self._next_id
        self._next_id += 1
        self._write(json.dumps({"command": list(args), "request_id": rid}).encode() + b"\n")
        while True:
            line = self._readline()
            assert line is not None
            msg = json.loads(line)
            if msg.get("request_id") != rid:
                if "event" in msg:
                    self._events.append(msg)  # komut beklerken gelen olayı kaybetme
                continue
            if msg.get("error") != "success":
                raise MpvIpcError(f"mpv hatası: {msg.get('error')}")
            return msg.get("data")

    def poll_event(self, timeout: float = 0.5) -> dict[str, Any] | None:
        """Sıradaki mpv olayını döndürür; `timeout` içinde olay yoksa None."""
        if self._events:
            return self._events.popleft()
        while True:
            line = self._readline(timeout)
            if line is None:
                return None
            msg = json.loads(line)
            if "event" in msg:
                return msg
            # request_id'li yanıtlar yalnız command() içinde işlenir; burada yok sayılır

    def set_property(self, name: str, value: Any) -> None:
        self.command("set_property", name, value)

    def get_property(self, name: str) -> Any:
        return self.command("get_property", name)

    def set_view(self, view: View) -> None:
        self.set_property("video-zoom", view.zoom)
        self.set_property("video-pan-x", view.pan_x)
        self.set_property("video-pan-y", view.pan_y)
