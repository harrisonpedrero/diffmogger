from __future__ import annotations

from .common import *
from .html_render import render_html
from .snapshots import build_snapshot

class ObservatoryHandler(BaseHTTPRequestHandler):
    target: Path

    def _send(self, body: str | bytes, content_type: str, status: int = 200) -> None:
        payload = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
        path = urlparse(self.path).path
        if path in {"/", "/index.html"}:
            self._send(render_html(build_snapshot(self.target), live=True), "text/html; charset=utf-8")
            return
        if path == "/state.json":
            self._send(json.dumps(build_snapshot(self.target), indent=2, sort_keys=True) + "\n", "application/json; charset=utf-8")
            return
        self._send("Not found\n", "text/plain; charset=utf-8", status=404)

    def log_message(self, _format: str, *_args: Any) -> None:
        return

def run_server(target: Path, host: str, port: int, open_browser: bool) -> int:
    class Handler(ObservatoryHandler):
        pass

    Handler.target = target
    server = ThreadingHTTPServer((host, port), Handler)
    actual_host, actual_port = server.server_address
    url = f"http://{actual_host}:{actual_port}/"
    print(f"Diffmogger observatory: {url}", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    finally:
        server.server_close()
    return 0
