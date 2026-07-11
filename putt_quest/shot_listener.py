"""HTTP shot listener for Putt Quest.

The upstream tracker (ball_tracking.py) reports each detected putt to
http://localhost:8888/putting — normally consumed by a GSPro connector.
Putt Quest binds that same port so the tracker needs ZERO modification.

The real tracker posts a NESTED payload:
    {"ballData": {"BallSpeed": "4.20", "TotalSpin": 0,
                  "LaunchDirection": "-1.30"}}
so incoming JSON is flattened recursively before key matching. We also
accept shots liberally so different tracker versions all work:
  * GET  with query params:  /?ballspeed=4.2&hla=-1.3&...
  * POST with a JSON body:   {"ballspeed": 4.2, "hla": -1.3}
  * POST with form fields
Key names are matched case-insensitively; speed keys tried in order:
ballspeed, ball_speed, speed, mph. HLA keys: hla, launchdirection, angle.

Extras for debugging / setup UI:
  * POST /status with {"trackerStatus": {...}} updates a "tracker status"
    snapshot (ball detected? radius? fps?) the game can show live.
  * Every request (accepted or rejected) lands in a small event log the
    game's debug overlay can render.

Shots land in a thread-safe queue that the game loop drains. All
responses are JSON with a "result" key because the tracker calls
res.json()['result'] on the reply.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

SHOT_QUEUE: "queue.Queue[dict]" = queue.Queue()

_SPEED_KEYS = ("ballspeed", "ball_speed", "speed", "mph")
_HLA_KEYS = ("hla", "launchdirection", "launch_direction", "angle")

_LOCK = threading.Lock()
_TRACKER_STATUS: dict = {}
_TRACKER_STATUS_TIME: float = 0.0
_EVENTS: "deque[Tuple[float, str]]" = deque(maxlen=8)


def _log_event(msg: str) -> None:
    with _LOCK:
        _EVENTS.appendleft((time.time(), msg))


def _flatten(src: dict, out: dict) -> None:
    """Lowercase keys; recurse into nested dicts (tracker wraps its data
    in a 'ballData' object)."""
    for k, v in src.items():
        if isinstance(v, dict):
            _flatten(v, out)
        else:
            out[str(k).lower()] = v


def _extract(params: dict) -> dict | None:
    """params: lowercase-key -> value (str or number)."""
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
    server_version = "PuttQuest/0.2"

    def _ok(self) -> None:
        data = b'{"result": "success"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _params_from_query(self) -> dict:
        q = parse_qs(urlparse(self.path).query)
        return {k.lower(): v[0] for k, v in q.items() if v}

    def _handle(self, params: dict) -> None:
        global _TRACKER_STATUS_TIME
        path = urlparse(self.path).path
        if path.rstrip("/").endswith("status"):
            with _LOCK:
                _TRACKER_STATUS.update(params)
                _TRACKER_STATUS_TIME = time.time()
            return
        shot = _extract(params)
        if shot:
            SHOT_QUEUE.put(shot)
            _log_event(f"shot  {shot['speed_mph']:.2f} mph  "
                       f"hla {shot['hla_deg']:+.2f}")
        elif params:
            _log_event("rejected (no speed key): "
                       + json.dumps(params, default=str)[:80])

    def do_GET(self) -> None:          # noqa: N802
        self._handle(self._params_from_query())
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
                        _flatten(data, params)
                else:
                    form = parse_qs(body.decode(errors="replace"))
                    params.update({k.lower(): v[0]
                                   for k, v in form.items() if v})
            except (ValueError, UnicodeDecodeError):
                _log_event(f"unparseable body ({len(body)} bytes)")
        self._handle(params)
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

    @staticmethod
    def get_tracker_status() -> Tuple[Optional[float], dict]:
        """Returns (seconds since last /status ping or None, status dict)."""
        with _LOCK:
            if not _TRACKER_STATUS_TIME:
                return None, {}
            return time.time() - _TRACKER_STATUS_TIME, dict(_TRACKER_STATUS)

    @staticmethod
    def get_events() -> List[Tuple[float, str]]:
        with _LOCK:
            return list(_EVENTS)
