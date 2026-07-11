"""HTTP shot listener for Putt Quest.

The upstream tracker (ball_tracking.py) reports each detected putt to
http://localhost:8888/ — normally consumed by a GSPro connector. Putt
Quest binds that same port so the tracker needs ZERO modification.

We accept shots liberally so different tracker versions all work:
  * GET  with query params:  /?ballspeed=4.2&hla=-1.3&...
  * POST with a JSON body:   {"ballspeed": 4.2, "hla": -1.3}
  * POST with form fields
Key names are matched case-insensitively; speed keys tried in order:
ballspeed, ball_speed, speed, mph. HLA keys: hla, launchdirection, angle.

Shots land in a thread-safe queue that the game loop drains.
"""

from __future__ import annotations

import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

SHOT_QUEUE: "queue.Queue[dict]" = queue.Queue()

_SPEED_KEYS = ("ballspeed", "ball_speed", "speed", "mph")
_HLA_KEYS = ("hla", "launchdirection", "launch_direction", "angle")


def _extract(params: dict) -> dict | None:
    """params: lowercase-key -> first value (str or number)."""
    def pick(keys):
        for k in keys:
            if k in params and params[k] not in (None, ""):
                try:
                    return float(params[k])
                except (TypeError, ValueError):
                    pass
        return None

    speed = pick(_SPEED_KEYS)
    if speed is None:
        return None
    hla = pick(_HLA_KEYS) or 0.0
    return {"speed_mph": speed, "hla_deg": hla, "raw": dict(params)}


class _Handler(BaseHTTPRequestHandler):
    server_version = "PuttQuest/0.1"

    def _ok(self, body: str = "OK") -> None:
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _params_from_query(self) -> dict:
        q = parse_qs(urlparse(self.path).query)
        return {k.lower(): v[0] for k, v in q.items() if v}

    def do_GET(self) -> None:          # noqa: N802
        shot = _extract(self._params_from_query())
        if shot:
            SHOT_QUEUE.put(shot)
        self._ok()

    def do_POST(self) -> None:         # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        params = self._params_from_query()
        if body:
            ctype = (self.headers.get("Content-Type") or "").lower()
            try:
                if "json" in ctype or body.lstrip()[:1] in (b"{", b"["):
                    data = json.loads(body)
                    if isinstance(data, dict):
                        params.update({str(k).lower(): v
                                       for k, v in data.items()})
                else:
                    form = parse_qs(body.decode(errors="replace"))
                    params.update({k.lower(): v[0]
                                   for k, v in form.items() if v})
            except (ValueError, UnicodeDecodeError):
                pass
        shot = _extract(params)
        if shot:
            SHOT_QUEUE.put(shot)
        self._ok()

    def log_message(self, *args) -> None:  # silence per-request stderr spam
        pass


class ShotListener:
    def __init__(self, host: str = "127.0.0.1", port: int = 8888):
        self.host, self.port = host, port
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.error: str | None = None

    def start(self) -> bool:
        try:
            self._server = ThreadingHTTPServer((self.host, self.port),
                                               _Handler)
        except OSError as exc:
            self.error = (f"Could not bind {self.host}:{self.port} ({exc}). "
                          "Is a GSPro connector still running?")
            return False
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        daemon=True, name="shot-listener")
        self._thread.start()
        return True

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()

    @staticmethod
    def get_shot() -> dict | None:
        try:
            return SHOT_QUEUE.get_nowait()
        except queue.Empty:
            return None
