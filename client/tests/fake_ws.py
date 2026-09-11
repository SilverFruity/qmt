"""Tiny dependency-free RFC6455 server used to test the quote stream."""

from __future__ import annotations

import base64
import hashlib
import json
import socket
import socketserver
import struct
import threading

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _accept(key):
    digest = hashlib.sha1((key + GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


class _Connection:
    def __init__(self, sock):
        self.sock = sock
        self.headers = {}
        self._closed = False
        self._send_lock = threading.Lock()

    def send_frame(self, payload, opcode=1):
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        header = bytearray()
        header.append(0x80 | (opcode & 0x0F))
        length = len(payload)
        if length < 126:
            header.append(length)
        elif length < 65536:
            header.append(126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(127)
            header.extend(struct.pack("!Q", length))
        with self._send_lock:
            if not self._closed:
                self.sock.sendall(bytes(header) + payload)

    def send_json(self, payload):
        self.send_frame(json.dumps(payload), opcode=1)

    def _read(self, count):
        data = b""
        while len(data) < count:
            try:
                chunk = self.sock.recv(count - len(data))
            except OSError:
                return None
            if not chunk:
                return None
            data += chunk
        return data

    def recv_frame(self):
        header = self._read(2)
        if header is None:
            return None
        first, second = header[0], header[1]
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if length == 126:
            extended = self._read(2)
            if extended is None:
                return None
            length = struct.unpack("!H", extended)[0]
        elif length == 127:
            extended = self._read(8)
            if extended is None:
                return None
            length = struct.unpack("!Q", extended)[0]
        if masked:
            mask = self._read(4)
            if mask is None:
                return None
        else:
            mask = b"\x00\x00\x00\x00"
        data = self._read(length) if length else b""
        if data is None:
            return None
        if masked:
            data = bytes(item ^ mask[index % 4] for index, item in enumerate(data))
        return opcode, data

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        sock = self.request
        sock.settimeout(10)
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                return
            data += chunk
        head = data.split(b"\r\n\r\n", 1)[0].decode("latin-1")
        headers = {}
        for line in head.split("\r\n")[1:]:
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.strip().lower()] = value.strip()
        key = headers.get("sec-websocket-key")
        if not key:
            return
        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Accept: " + _accept(key) + "\r\n\r\n"
        )
        sock.sendall(response.encode("ascii"))
        connection = _Connection(sock)
        connection.headers = headers
        server = self.server
        with server.lock:
            server.connections.append(connection)
        reader = threading.Thread(target=self._reader, args=(connection,), daemon=True)
        reader.start()
        try:
            server.on_connect(connection)
        finally:
            connection.close()

    @staticmethod
    def _reader(connection):
        while True:
            frame = connection.recv_frame()
            if frame is None:
                return
            opcode, data = frame
            if opcode == 8:
                connection.close()
                return
            if opcode == 9:
                connection.send_frame(data, opcode=10)


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class FakeWSServer:
    def __init__(self, on_connect):
        self._server = _Server(("127.0.0.1", 0), _Handler)
        self._server.on_connect = on_connect
        self._server.connections = []
        self._server.lock = threading.Lock()
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        with self._server.lock:
            connections = list(self._server.connections)
        for connection in connections:
            connection.close()
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(5)
