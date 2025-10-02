"""
Simple SocketClient replacement for hps.clients.SocketClient.

Protocol:
- Send: send_data(str) will send the provided string encoded as UTF-8
  and terminated with a newline `\n`.
- Receive: receive_data() will read from the socket until a newline `\n`
  is seen (the newline is stripped) and return the decoded string.

This mirrors the simple line-delimited JSON usage in your client.py.

Features:
- Automatic connect on construction.
- Optional timeout (default None = blocking).
- Context manager support.
- Thread-safe send/receive using a lock.
- graceful close().
"""

import socket
import threading
from typing import Optional


class SocketClient:
    def __init__(self, host: str, port: int, timeout: Optional[float] = 10.0):
        """
        Create and connect the socket.

        :param host: server hostname or IP
        :param port: server port (int)
        :param timeout: optional socket timeout in seconds. Default 10s.
                        Set to None for blocking sockets.
        """
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock = None
        self._lock = threading.Lock()  # protects send/recv concurrently
        self._recv_buffer = b""
        self._closed = False
        self._connect()

    def _connect(self):
        s = socket.create_connection((self.host, self.port))
        s.settimeout(self.timeout)
        self._sock = s

    def send_data(self, data: str) -> None:
        """
        Send a string to the server. Data will be encoded as UTF-8 and
        terminated with a newline if not already terminated.
        """
        if self._closed:
            raise RuntimeError("SocketClient is closed")

        if not isinstance(data, str):
            raise TypeError("send_data expects a string")

        # ensure a single newline at the end so receiver knows framing
        if not data.endswith("\n"):
            data_to_send = data + "\n"
        else:
            data_to_send = data

        payload = data_to_send.encode("utf-8")

        with self._lock:
            totalsent = 0
            while totalsent < len(payload):
                sent = self._sock.send(payload[totalsent:])
                if sent == 0:
                    raise RuntimeError("Socket connection broken while sending")
                totalsent += sent

    def receive_data(self) -> str:
        """
        Receive one message from the server. This reads until a newline is found.
        The returned string has the terminating newline stripped.

        Blocks until a newline is read or the socket is closed/timeout occurs.
        """
        if self._closed:
            raise RuntimeError("SocketClient is closed")

        with self._lock:
            while True:
                # If buffer already contains a newline, return the first line
                nl_index = self._recv_buffer.find(b"\n")
                if nl_index != -1:
                    line = self._recv_buffer[:nl_index]
                    self._recv_buffer = self._recv_buffer[nl_index + 1 :]
                    return line.decode("utf-8")

                # otherwise, read more from socket
                try:
                    chunk = self._sock.recv(4096)
                except socket.timeout:
                    # decide how you want to handle timeout: raise or return empty
                    raise
                except socket.error as e:
                    raise RuntimeError(f"Socket recv error: {e}")

                if not chunk:
                    # connection closed by the remote end
                    if self._recv_buffer:
                        # return what's left (no terminating newline)
                        leftover = self._recv_buffer
                        self._recv_buffer = b""
                        return leftover.decode("utf-8")
                    else:
                        raise RuntimeError("Server closed connection")

                self._recv_buffer += chunk

    def close(self) -> None:
        """Close the underlying socket."""
        if self._closed:
            return
        try:
            if self._sock:
                self._sock.shutdown(socket.SHUT_RDWR)
                self._sock.close()
        except Exception:
            pass
        self._closed = True

    # context manager support
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
