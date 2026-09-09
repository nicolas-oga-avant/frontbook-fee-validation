"""Minimal RFC 6455 WebSocket client - stdlib only, no pip dependency.

Exists because scripts/apply_harness.py and scripts/apply_driver.py were written against
browser-harness's pre-imported helpers (js, cdp, click_at_xy, ...), and browser-harness
itself only runs as an interactive daemon an LLM drives - there is no headless "just give me
a CDP socket" mode to import. This is the transport that replaces it (ROADMAP.md 2.1).

Text frames only - CDP speaks JSON over text frames exclusively, so a binary frame or a
frame this client cannot fully decode is a protocol error, not something to shrug past
(AGENTS.md: "assume silence means failure" applies to the transport too).
"""

import base64
import hashlib
import os
import socket
import struct
import threading
from urllib.parse import urlparse

_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class WebSocketError(Exception):
    pass


class WebSocket:
    def __init__(self, url, connect_timeout=10):
        self._url = url
        self._buf = b""
        self._sock = self._connect(url, connect_timeout)
        self._send_lock = threading.Lock()

    def _connect(self, url, timeout):
        parsed = urlparse(url)
        if parsed.scheme != "ws":
            raise WebSocketError(
                "unsupported scheme %r - CDP is always ws:// on localhost" % parsed.scheme)
        host = parsed.hostname
        port = parsed.port or 80
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query

        sock = socket.create_connection((host, port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            "GET %s HTTP/1.1\r\n"
            "Host: %s:%d\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Key: %s\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n" % (path, host, port, key)
        ).encode("ascii")
        sock.sendall(request)

        head, leftover = self._read_headers(sock)
        status_line = head[0]
        if " 101 " not in status_line:
            raise WebSocketError("handshake failed: %r" % status_line)
        accept = None
        for line in head[1:]:
            if line.lower().startswith("sec-websocket-accept:"):
                accept = line.split(":", 1)[1].strip()
        expected = base64.b64encode(hashlib.sha1((key + _GUID).encode()).digest()).decode()
        if accept != expected:
            raise WebSocketError("Sec-WebSocket-Accept mismatch - not a real WS server?")

        self._buf = leftover
        sock.settimeout(None)
        return sock

    @staticmethod
    def _read_headers(sock):
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                raise WebSocketError("connection closed during handshake")
            buf += chunk
        head, _, rest = buf.partition(b"\r\n\r\n")
        return head.decode("iso-8859-1").split("\r\n"), rest

    # --- sending -------------------------------------------------------------------------

    def send_text(self, data):
        payload = data.encode("utf-8")
        self._send_frame(0x1, payload)

    def _send_frame(self, opcode, payload):
        header = self._frame_header(len(payload), opcode, masked=True)
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        with self._send_lock:
            self._sock.sendall(header + mask + masked)

    @staticmethod
    def _frame_header(length, opcode, masked):
        b1 = 0x80 | opcode  # FIN=1, no extensions
        mask_bit = 0x80 if masked else 0x00
        if length < 126:
            return bytes([b1, mask_bit | length])
        elif length < 65536:
            return bytes([b1, mask_bit | 126]) + struct.pack(">H", length)
        return bytes([b1, mask_bit | 127]) + struct.pack(">Q", length)

    # --- receiving -----------------------------------------------------------------------

    def _recv_exact(self, n):
        while len(self._buf) < n:
            chunk = self._sock.recv(max(65536, n - len(self._buf)))
            if not chunk:
                raise WebSocketError("connection closed mid-frame")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def recv_message(self):
        """Block for one complete text message, joining continuation frames.

        Answers pings transparently. Raises WebSocketError on a close frame or on any
        frame type CDP never actually sends (binary) - never returns a partial/garbage
        decode silently.
        """
        parts = []
        first_opcode = None
        while True:
            b1, b2 = self._recv_exact(2)
            fin = b1 & 0x80
            opcode = b1 & 0x0F
            masked = b2 & 0x80
            length = b2 & 0x7F
            if length == 126:
                (length,) = struct.unpack(">H", self._recv_exact(2))
            elif length == 127:
                (length,) = struct.unpack(">Q", self._recv_exact(8))
            mask = self._recv_exact(4) if masked else None
            payload = self._recv_exact(length) if length else b""
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))

            if opcode == 0x8:
                raise WebSocketError("closed")
            if opcode == 0x9:
                self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue

            if opcode != 0x0:
                first_opcode = opcode
            parts.append(payload)
            if fin:
                break

        if first_opcode != 0x1:
            raise WebSocketError("unexpected non-text frame (opcode %r)" % first_opcode)
        return b"".join(parts).decode("utf-8")

    def close(self):
        try:
            self._send_frame(0x8, b"")
        except OSError:
            pass
        try:
            self._sock.close()
        except OSError:
            pass
