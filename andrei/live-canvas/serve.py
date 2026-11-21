"""Serve the judge's canvas and stream local TM_LIVE events by byte offset."""

from __future__ import annotations

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent
SYSTEM = HERE.parents[1] / "system"
RUNS = SYSTEM / "traces" / "live"
RUN_ID = re.compile(r"[a-f0-9]{32}")
ASSETS = {"/": ("index.html", "text/html"), "/styles.css": ("styles.css", "text/css"),
          "/app.js": ("app.js", "text/javascript"), "/examples.json": ("examples.json", "application/json")}


class Handler(BaseHTTPRequestHandler):
    def reply(self, body: bytes, kind: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", kind + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                         "object-src 'none'; base-uri 'none'; frame-ancestors 'self'")
        self.end_headers()
        self.wfile.write(body)

    def json(self, value) -> None:
        self.reply(json.dumps(value, ensure_ascii=False).encode(), "application/json")

    def log_request(self, code="-", size="-"):
        if not self.path.startswith("/api/") or str(code) != "200":
            super().log_request(code, size)

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        if url.path in ASSETS:
            file, kind = ASSETS[url.path]
            return self.reply((HERE / file).read_bytes(), kind)
        if url.path == "/api/runs":
            runs = []
            for path in RUNS.glob("*.jsonl"):
                if not RUN_ID.fullmatch(path.stem):
                    continue
                try:
                    with path.open(encoding="utf-8") as file:
                        event = json.loads(file.readline())
                    if event["stage"] == "run" and event["state"] == "start":
                        runs.append({"id": path.stem, "institution": event["data"]["institution"], "at": event["at"]})
                except (OSError, ValueError, KeyError):
                    continue
            return self.json(sorted(runs, key=lambda x: x["at"], reverse=True))
        target = url.path.removeprefix("/api/runs/")
        if url.path.startswith("/api/runs/") and RUN_ID.fullmatch(target):
            try:
                cursor = int(parse_qs(url.query).get("after", ["0"])[0])
                if cursor < 0:
                    raise ValueError
            except ValueError:
                return self.send_error(400, "Expected a nonnegative byte offset")
            try:
                with (RUNS / f"{target}.jsonl").open("rb") as file:
                    file.seek(cursor)
                    events = []
                    for _ in range(450):
                        line = file.readline()
                        if not line.endswith(b"\n"):  # wait for a complete event from the writer
                            break
                        events.append(json.loads(line))
                        cursor += len(line)
            except FileNotFoundError:
                return self.send_error(404, "Run unavailable")
            except (OSError, ValueError):
                return self.send_error(500, "Run could not be read")
            return self.json({"events": events, "cursor": cursor})
        self.send_error(404)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print(f"Payper Trail case canvas: http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
