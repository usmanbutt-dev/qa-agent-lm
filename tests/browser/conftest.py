from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


class SiteHandler(BaseHTTPRequestHandler):
    redirect_target = ""

    def do_GET(self) -> None:
        if self.path == "/form":
            body = b"""<!doctype html>
<html><title>Form</title><body>
  <form id="profile">
    <label>Name <input name="name" placeholder="Full name"></label>
    <label>Notes <textarea name="notes"></textarea></label>
    <button type="submit">Save profile</button>
  </form>
  <p id="result" hidden></p>
  <script>
    document.querySelector('#profile').addEventListener('submit', event => {
      event.preventDefault();
      const data = new FormData(event.target);
      const result = document.querySelector('#result');
      result.textContent = `${data.get('name')}|${data.get('notes')}`;
      result.hidden = false;
      event.submitter.textContent = `Saved ${result.textContent}`;
    });
  </script>
</body></html>"""
            self._html(body)
            return
        if self.path == "/unsafe":
            self._html(b'<html><a href="mailto:test@example.com">Email support</a></html>')
            return
        if self.path == "/diagnostics":
            body = b"""<html><body>
  <button>super-secret</button>
  <script>
    console.error('first super-secret');
    console.error('second super-secret');
    const request = new XMLHttpRequest();
    request.open('GET', '/missing?token=super-secret', false);
    request.send();
  </script>
</body></html>"""
            self._html(body)
            return
        if self.path == "/ok":
            self._html(b"<html><title>Allowed page</title><body>ok</body></html>")
            return
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", self.redirect_target)
            self.end_headers()
            return
        if self.path == "/download":
            body = b"not allowed"
            self.send_response(200)
            self.send_header("Content-Disposition", 'attachment; filename="blocked.txt"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def _html(self, body: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


@contextmanager
def serve(handler: type[BaseHTTPRequestHandler]) -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host = str(server.server_address[0])
    port = int(server.server_address[1])
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture
def origins() -> Iterator[tuple[str, str]]:
    with serve(SiteHandler) as allowed, serve(SiteHandler) as denied:
        SiteHandler.redirect_target = f"{denied}/ok"
        yield allowed, denied
