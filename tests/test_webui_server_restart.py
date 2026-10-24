"""Linux 服务处理请求后应可立即重启，且仍拒绝同端口双实例。"""
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler

import pytest

from webui import _Srv


class _EmptyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.mark.skipif(os.name == "nt", reason="POSIX TIME_WAIT 重绑行为")
def test_server_restarts_after_serving_request():
    with _Srv(("127.0.0.1", 0), _EmptyHandler) as server:
        address = server.server_address
        worker = threading.Thread(target=server.handle_request, daemon=True)
        worker.start()
        with socket.create_connection(address, timeout=5) as client:
            client.sendall(b"GET / HTTP/1.0\r\nHost: localhost\r\n\r\n")
            response = b""
            while data := client.recv(4096):
                response += data
        worker.join(timeout=5)
        assert b"200 OK" in response
        assert not worker.is_alive()
    with _Srv(address, _EmptyHandler) as restarted:
        assert restarted.server_address[1] == address[1]
