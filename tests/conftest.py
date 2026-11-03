import functools
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
HITS: list[str] = []  # every GET path the server saw


class _Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        HITS.append(self.path)
        if self.path == "/redirect-metadata":
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/")
            self.end_headers()
        elif self.path == "/slow":
            time.sleep(10)
            self.send_error(504)
        elif self.path == "/csp.html":
            body = (FIXTURES / "broken.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Security-Policy", "script-src 'none'")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            super().do_GET()

    def log_message(self, *a):
        pass


@pytest.fixture
def http_server():
    handler = functools.partial(_Handler, directory=str(FIXTURES))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()
