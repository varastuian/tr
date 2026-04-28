from __future__ import annotations

import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
import threading

from .db import TileSource


_src_lock = threading.Lock()
_src: TileSource | None = None


def _get_src() -> TileSource:
    global _src
    with _src_lock:
        if _src is not None:
            return _src
        db_path = os.environ.get("TILE_DB_PATH", "").strip()
        if not db_path:
            raise RuntimeError("Set TILE_DB_PATH to your cache .mbtiles/.sqlite file path")
        mode = os.environ.get("TILE_MODE", "auto").strip().lower()
        _src = TileSource(db_path=db_path, mode=mode)
        return _src


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            if not path.startswith("/tiles/") or not path.endswith(".png"):
                self.send_response(404)
                self.end_headers()
                return

            # /tiles/{z}/{x}/{y}.png
            parts = path.split("/")
            if len(parts) != 5:
                self.send_response(404)
                self.end_headers()
                return
            z = int(parts[2])
            x = int(parts[3])
            y_str = parts[4]
            if y_str.endswith(".png"):
                y_str = y_str[: -len(".png")]
            y = int(y_str)

            data = _get_src().get_png(z=z, x=x, y=y)
            if data is None:
                self.send_response(404)
                self.end_headers()
                return

            # Many caches store JPG tiles. We still set image/png for simplicity.
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Cache-Control", "public, max-age=86400")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(str(e).encode("utf-8"))

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        # Keep output quiet.
        return


def main() -> None:
    host = os.environ.get("TILE_HOST", "127.0.0.1")
    port = int(os.environ.get("TILE_PORT", "8000"))
    # Validate configuration early (fail fast).
    _get_src()
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Serving tiles on http://{host}:{port}/tiles/{{z}}/{{x}}/{{y}}.png")
    server.serve_forever()


if __name__ == "__main__":
    main()

