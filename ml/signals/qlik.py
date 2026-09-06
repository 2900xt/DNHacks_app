"""A minimal Qlik Sense engine client, over a hand-rolled websocket.

Why this exists: FDA's Inspection Classification data has no usable machine
route. The documented REST API (`api-datadashboard.fda.gov`) returns 401 and the
key is issued by email with no SLA; the "entire dataset" xlsx link 404s. What
*does* work is the public dashboard's own Qlik engine, which accepts anonymous
websocket connections — the same protocol the browser mashup uses. Nothing is
bypassed and no credential is involved; this is public government data served
over its own public endpoint.

⚠️ It is undocumented and the app id rotates. Treat the pinned CSV as the
artifact of record and do NOT call this live on stage. Classifications post
months after the inspection anyway, so liveness buys nothing.

Stdlib only — no `websockets` package, because the demo must not depend on a
`pip install` succeeding on venue wifi.
"""

from __future__ import annotations

import base64
import json
import os
import socket
import struct
from urllib.parse import urlparse

from .common import LoaderError, UA, ssl_context

TEXT, CLOSE, PING, PONG = 0x1, 0x8, 0x9, 0xA


class WebSocket:
    """Just enough RFC 6455 to speak Qlik JSON-RPC."""

    def __init__(self, url: str, *, timeout: int = 60):
        u = urlparse(url)
        host, port = u.hostname, u.port or 443
        raw = socket.create_connection((host, port), timeout=timeout)
        self.sock = ssl_context().wrap_socket(raw, server_hostname=host)
        key = base64.b64encode(os.urandom(16)).decode()
        path = u.path + (f"?{u.query}" if u.query else "")
        req = (
            f"GET {path} HTTP/1.1\r\nHost: {host}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
            f"Origin: https://{host}\r\nUser-Agent: {UA}\r\n\r\n"
        )
        self.sock.sendall(req.encode())
        head = self._read_until(b"\r\n\r\n")
        if b" 101 " not in head.split(b"\r\n")[0]:
            raise LoaderError(f"websocket upgrade refused:\n{head.decode(errors='replace')[:400]}")
        self.buf = b""
        self._id = 0

    def _read_until(self, marker: bytes) -> bytes:
        data = b""
        while marker not in data:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise LoaderError("connection closed during handshake")
            data += chunk
        return data

    def _recv_exact(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise LoaderError("connection closed mid-frame")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def send(self, payload: str) -> None:
        data = payload.encode()
        header = bytearray([0x80 | TEXT])
        n = len(data)
        if n < 126:
            header.append(0x80 | n)
        elif n < 1 << 16:
            header.append(0x80 | 126); header += struct.pack("!H", n)
        else:
            header.append(0x80 | 127); header += struct.pack("!Q", n)
        mask = os.urandom(4)
        header += mask
        self.sock.sendall(bytes(header) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def recv(self) -> str:
        """Return the next complete text message, handling ping and fragments."""
        parts: list[bytes] = []
        while True:
            b0, b1 = self._recv_exact(2)
            fin, opcode, length = b0 & 0x80, b0 & 0x0F, b1 & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._recv_exact(8))[0]
            payload = self._recv_exact(length) if length else b""

            if opcode == PING:
                self._control(PONG, payload); continue
            if opcode in (PONG,):
                continue
            if opcode == CLOSE:
                raise LoaderError("server closed the websocket")
            parts.append(payload)
            if fin:
                return b"".join(parts).decode(errors="replace")

    def _control(self, opcode: int, payload: bytes) -> None:
        mask = os.urandom(4)
        header = bytes([0x80 | opcode, 0x80 | len(payload)]) + mask
        self.sock.sendall(header + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def rpc(self, method: str, handle: int, params) -> dict:
        """One JSON-RPC call. Skips the engine's unsolicited change notifications."""
        self._id += 1
        self.send(json.dumps({"jsonrpc": "2.0", "id": self._id,
                              "method": method, "handle": handle, "params": params}))
        while True:
            msg = json.loads(self.recv())
            if msg.get("id") != self._id:
                continue                      # OnConnected / change notifications
            if "error" in msg:
                raise LoaderError(f"Qlik {method} failed: {msg['error']}")
            return msg.get("result", {})

    def close(self) -> None:
        try:
            self._control(CLOSE, b"")
            self.sock.close()
        except Exception:
            pass
