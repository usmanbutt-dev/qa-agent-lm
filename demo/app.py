"""Deterministic local application used by the v0.1 browser benchmark."""

from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEMO_PAGE = b"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>QA-AgentLM Demo</title></head>
<body>
  <main>
    <h1>Deployment check</h1>
    <label>Environment <input name="environment" placeholder="e.g. staging"></label>
    <button id="success" type="button">Run successful check</button>
    <button id="failure" type="button">Run failing check</button>
    <button id="ambiguous" type="button">Delete shared test data</button>
    <p id="status" aria-live="polite">Not run</p>
  </main>
  <script>
    const environment = document.querySelector('[name=environment]');
    const status = document.querySelector('#status');
    document.querySelector('#success').addEventListener('click', event => {
      status.textContent = `Passed for ${environment.value}`;
      event.target.textContent = `Passed ${environment.value}`;
    });
    document.querySelector('#failure').addEventListener('click', event => {
      const request = new XMLHttpRequest();
      request.open('GET', '/api/failure?environment=' + encodeURIComponent(environment.value), false);
      request.send();
      console.error(`Deployment check failed with HTTP ${request.status}`);
      status.textContent = `Failed for ${environment.value}`;
      event.target.textContent = `Failed ${environment.value}`;
    });
  </script>
</body>
</html>"""


class DemoRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/":
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(DEMO_PAGE)))
            self.end_headers()
            self.wfile.write(DEMO_PAGE)
            return
        if self.path.startswith("/api/failure"):
            body = b'{"error":"intentional demo failure"}'
            self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: object) -> None:
        return


def create_server(host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), DemoRequestHandler)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = create_server(args.host, args.port)
    print(f"QA-AgentLM demo running at http://{args.host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
