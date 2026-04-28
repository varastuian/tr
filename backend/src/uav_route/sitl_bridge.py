from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse


class BridgeState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.connection = "udp:127.0.0.1:14550"
        self.connected = False
        self.armed = False
        self.mode = "UNKNOWN"
        self.lat = 37.4221
        self.lon = -122.0841
        self.alt_m = 0.0
        self.heading_deg = 0.0
        self.groundspeed = 0.0
        self.last_command = ""
        self.camera_zoom = 20
        self.error = ""
        self.master = None
        self.worker: threading.Thread | None = None

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "connection": self.connection,
                "connected": self.connected,
                "armed": self.armed,
                "mode": self.mode,
                "lat": self.lat,
                "lon": self.lon,
                "alt_m": self.alt_m,
                "heading_deg": self.heading_deg,
                "groundspeed": self.groundspeed,
                "last_command": self.last_command,
                "camera_zoom": self.camera_zoom,
                "error": self.error,
            }


STATE = BridgeState()


def _set_error(msg: str) -> None:
    with STATE.lock:
        STATE.error = msg


def _telemetry_loop() -> None:
    try:
        from pymavlink import mavutil  # type: ignore
    except Exception:
        _set_error("pymavlink not installed. Install in your venv: pip install pymavlink")
        return

    while True:
        with STATE.lock:
            conn = STATE.connection
        try:
            master = mavutil.mavlink_connection(conn)
            hb = master.wait_heartbeat(timeout=8)
            if hb is None:
                raise RuntimeError("No heartbeat from SITL")
            with STATE.lock:
                STATE.master = master
                STATE.connected = True
                STATE.error = ""

            while True:
                msg = master.recv_match(
                    type=["GLOBAL_POSITION_INT", "VFR_HUD", "HEARTBEAT", "ATTITUDE"],
                    blocking=True,
                    timeout=1.0,
                )
                if msg is None:
                    continue
                t = msg.get_type()
                with STATE.lock:
                    if t == "GLOBAL_POSITION_INT":
                        STATE.lat = msg.lat / 1e7
                        STATE.lon = msg.lon / 1e7
                        STATE.alt_m = msg.relative_alt / 1000.0
                        STATE.heading_deg = (msg.hdg / 100.0) if msg.hdg != 65535 else STATE.heading_deg
                    elif t == "VFR_HUD":
                        STATE.groundspeed = float(msg.groundspeed)
                    elif t == "HEARTBEAT":
                        STATE.armed = bool(
                            msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
                        )
                        STATE.mode = mavutil.mode_string_v10(msg)
                    elif t == "ATTITUDE":
                        pass
        except Exception as e:
            with STATE.lock:
                STATE.connected = False
                STATE.master = None
                STATE.error = f"SITL connect/read error: {e}"
            time.sleep(2.0)


def _ensure_worker() -> None:
    if STATE.worker and STATE.worker.is_alive():
        return
    t = threading.Thread(target=_telemetry_loop, daemon=True)
    STATE.worker = t
    t.start()


def _send_command(action: str) -> None:
    try:
        from pymavlink import mavutil  # type: ignore
    except Exception:
        _set_error("pymavlink not installed. Install in your venv: pip install pymavlink")
        return

    with STATE.lock:
        master = STATE.master
        STATE.last_command = action
    if master is None:
        _set_error("Not connected to SITL yet")
        return

    if action == "arm":
        master.arducopter_arm()
    elif action == "disarm":
        master.arducopter_disarm()
    elif action == "takeoff":
        master.mav.command_long_send(
            master.target_system,
            master.target_component,
            mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            20,
        )
    elif action in {"rtl", "land", "guided", "auto", "loiter"}:
        mode_map = {
            "rtl": "RTL",
            "land": "LAND",
            "guided": "GUIDED",
            "auto": "AUTO",
            "loiter": "LOITER",
        }
        mode = mode_map[action]
        mode_id = master.mode_mapping().get(mode)
        if mode_id is None:
            _set_error(f"Mode {mode} not supported")
            return
        master.set_mode(mode_id)
    else:
        _set_error(f"Unknown command: {action}")


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, data: dict[str, Any]) -> None:
        raw = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        p = urlparse(self.path).path
        if p == "/api/state":
            self._send_json(200, STATE.snapshot())
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        p = urlparse(self.path).path
        n = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(n) if n > 0 else b"{}"
        payload = json.loads(body.decode("utf-8"))

        if p == "/api/connect":
            conn = str(payload.get("connection", "udp:127.0.0.1:14550"))
            with STATE.lock:
                STATE.connection = conn
                STATE.error = ""
            _ensure_worker()
            self._send_json(200, {"ok": True, "connection": conn})
            return
        if p == "/api/command":
            action = str(payload.get("action", ""))
            _send_command(action)
            self._send_json(200, {"ok": True, "action": action})
            return
        if p == "/api/camera":
            zoom = int(payload.get("zoom", 20))
            with STATE.lock:
                STATE.camera_zoom = max(15, min(22, zoom))
            self._send_json(200, {"ok": True, "camera_zoom": STATE.camera_zoom})
            return

        self._send_json(404, {"error": "not found"})

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


def main() -> None:
    host = "127.0.0.1"
    port = 8765
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"SITL bridge listening at http://{host}:{port}")
    print("POST /api/connect {\"connection\":\"udp:127.0.0.1:14550\"}")
    server.serve_forever()


if __name__ == "__main__":
    main()

