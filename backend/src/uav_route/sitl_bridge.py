from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from uav_route.geo import LL, haversine_m
from uav_route.geojson import mission_to_geojson
from uav_route.mission import MAV_CMD, MissionItem
from uav_route.simplify import SimplifyConfig, simplify_mission
from uav_route.track_library import save_track
from uav_route.vbn_path import init_playback, step_playback


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
        self.gimbal_preset = ""
        self.gps_disabled = False
        self.ekf_no_gps = False
        self.recording = False
        self.recording_name = ""
        self.recording_min_sep_m = 1.5
        self.recorded_points: list[MissionItem] = []
        self.error = ""
        self.master = None
        self.worker: threading.Thread | None = None
        self.vbn_playback: dict[str, Any] | None = None

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
                "gimbal_preset": self.gimbal_preset,
                "gps_disabled": self.gps_disabled,
                "ekf_no_gps": self.ekf_no_gps,
                "recording": self.recording,
                "recording_points": len(self.recorded_points),
                "recording_name": self.recording_name,
                "error": self.error,
                "vbn_ready": self.vbn_playback is not None,
            }


STATE = BridgeState()


def _set_error(msg: str) -> None:
    with STATE.lock:
        STATE.error = msg


def _pymavlink_import_error(exc: BaseException) -> str:
    return (
        f"pymavlink import failed ({type(exc).__name__}: {exc}). "
        f"This bridge is running as: {sys.executable}. "
        "Use the same environment: cd backend && source .venv/bin/activate && "
        "pip install -e . && PYTHONPATH=src python -m uav_route.sitl_bridge — then restart the bridge."
    )


def _telemetry_loop() -> None:
    try:
        from pymavlink import mavutil  # type: ignore
    except Exception as e:
        _set_error(_pymavlink_import_error(e))
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
                record_sample: tuple[float, float, float] | None = None
                with STATE.lock:
                    if t == "GLOBAL_POSITION_INT":
                        STATE.lat = msg.lat / 1e7
                        STATE.lon = msg.lon / 1e7
                        STATE.alt_m = msg.relative_alt / 1000.0
                        STATE.heading_deg = (msg.hdg / 100.0) if msg.hdg != 65535 else STATE.heading_deg
                        record_sample = (STATE.lat, STATE.lon, STATE.alt_m)
                    elif t == "VFR_HUD":
                        STATE.groundspeed = float(msg.groundspeed)
                    elif t == "HEARTBEAT":
                        STATE.armed = bool(
                            msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
                        )
                        STATE.mode = mavutil.mode_string_v10(msg)
                    elif t == "ATTITUDE":
                        pass
                if record_sample is not None:
                    _record_tick(*record_sample)
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
    except Exception as e:
        _set_error(_pymavlink_import_error(e))
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


def _apply_gimbal(payload: dict[str, Any]) -> None:
    try:
        from uav_route.gimbal_rc import apply_preset, send_gimbal_rc
    except Exception as e:
        _set_error(_pymavlink_import_error(e))
        return

    with STATE.lock:
        master = STATE.master
    if master is None:
        _set_error("Not connected to SITL yet")
        return

    try:
        if "roll_pwm" in payload or "pitch_pwm" in payload or "yaw_pwm" in payload:
            roll = payload.get("roll_pwm")
            pitch = payload.get("pitch_pwm")
            yaw = payload.get("yaw_pwm")
            send_gimbal_rc(
                master,
                int(roll) if roll is not None else None,
                int(pitch) if pitch is not None else None,
                int(yaw) if yaw is not None else None,
            )
            label = "custom_pwm"
        else:
            preset = str(payload.get("preset", "neutral"))
            apply_preset(master, preset)
            label = preset
        with STATE.lock:
            STATE.gimbal_preset = label
            STATE.error = ""
    except ValueError as e:
        _set_error(str(e))
    except Exception as e:
        _set_error(f"gimbal RC override failed: {e}")


def _set_param(master: Any, name: str, value: float) -> None:
    # Use a short timeout because this endpoint may set multiple params in sequence.
    master.mav.param_set_send(
        master.target_system,
        master.target_component,
        name.encode("ascii"),
        float(value),
        9,  # MAV_PARAM_TYPE_REAL32
    )
    master.recv_match(type="PARAM_VALUE", blocking=False, timeout=0.25)


def _set_gps_disabled(disabled: bool) -> None:
    with STATE.lock:
        master = STATE.master
    if master is None:
        _set_error("Not connected to SITL yet")
        return

    # Try common ArduPilot SIM GPS knobs. Not every build has every param.
    wanted = 0.0 if disabled else 1.0
    param_names = ("SIM_GPS1_ENABLE", "SIM_GPS2_ENABLE", "SIM_GPS_DISABLE")
    set_any = False
    for name in param_names:
        try:
            value = wanted if name != "SIM_GPS_DISABLE" else (1.0 if disabled else 0.0)
            _set_param(master, name, value)
            set_any = True
        except Exception:
            continue

    if not set_any:
        _set_error(
            "Could not set SIM GPS params (tried SIM_GPS1_ENABLE, SIM_GPS2_ENABLE, SIM_GPS_DISABLE)."
        )
        return

    with STATE.lock:
        STATE.gps_disabled = disabled
        STATE.error = ""


def _set_ekf_no_gps(disabled: bool) -> None:
    with STATE.lock:
        master = STATE.master
    if master is None:
        _set_error("Not connected to SITL yet")
        return

    disabled_values = {
        "EK3_SRC1_POSXY": 0.0,
        "EK3_SRC1_VELXY": 0.0,
        "EK3_SRC1_POSZ": 0.0,
        "EK3_SRC1_VELZ": 0.0,
    }
    enabled_values = {
        "EK3_SRC1_POSXY": 3.0,
        "EK3_SRC1_VELXY": 3.0,
        "EK3_SRC1_POSZ": 1.0,
        "EK3_SRC1_VELZ": 3.0,
    }
    values = disabled_values if disabled else enabled_values
    set_any = False
    for name, value in values.items():
        try:
            _set_param(master, name, value)
            set_any = True
        except Exception:
            continue
    if not set_any:
        _set_error("Could not set EKF params (tried EK3_SRC1_POSXY/VELXY/POSZ/VELZ).")
        return
    with STATE.lock:
        STATE.ekf_no_gps = disabled
        STATE.error = ""


def _record_tick(lat: float, lon: float, alt_m: float) -> None:
    with STATE.lock:
        if not STATE.recording:
            return
        last = STATE.recorded_points[-1] if STATE.recorded_points else None
        if last and last.lat is not None and last.lon is not None:
            if haversine_m(LL(last.lat, last.lon), LL(lat, lon)) < STATE.recording_min_sep_m:
                return
        seq = len(STATE.recorded_points)
        STATE.recorded_points.append(
            MissionItem(
                seq=seq,
                command=int(MAV_CMD.NAV_WAYPOINT),
                frame=3,
                lat=lat,
                lon=lon,
                alt=alt_m,
                raw={"source": "bridge_record"},
            )
        )


def _start_recording(payload: dict[str, Any]) -> None:
    name = str(payload.get("name", "")).strip() or f"sitl_record_{int(time.time())}"
    min_sep_m = max(0.1, min(20.0, float(payload.get("min_sep_m", 1.5))))
    with STATE.lock:
        STATE.recording = True
        STATE.recording_name = name
        STATE.recording_min_sep_m = min_sep_m
        STATE.recorded_points = []
        STATE.error = ""


def _stop_recording(payload: dict[str, Any]) -> dict[str, Any]:
    with STATE.lock:
        points = list(STATE.recorded_points)
        name = STATE.recording_name or f"sitl_record_{int(time.time())}"
        min_sep_m = STATE.recording_min_sep_m
        STATE.recording = False
    if len(points) < 2:
        raise RuntimeError("Recorded too few route points; fly longer before stopping")

    min_turn_deg = max(0.0, float(payload.get("min_turn_deg", 6.0)))
    rdp_epsilon_m = max(0.1, float(payload.get("rdp_epsilon_m", 8.0)))
    simplified = simplify_mission(
        points,
        SimplifyConfig(
            remove_loiter=True,
            min_separation_m=min_sep_m,
            min_turn_deg=min_turn_deg,
            rdp_epsilon_m=rdp_epsilon_m,
        ),
    )
    taught_fc = mission_to_geojson(points, "taught")
    simplified_fc = mission_to_geojson(simplified, "simplified")
    rec = save_track(taught_fc, simplified_fc, name=name)
    with STATE.lock:
        STATE.error = ""
    return {
        "ok": True,
        "id": rec.id,
        "name": rec.name,
        "points": len(points),
        "simplified_points": len(simplified),
        "taught_fc": taught_fc,
        "simplified_fc": simplified_fc,
    }


def _simplify_mission_payload(payload: dict[str, Any]) -> dict[str, Any]:
    mission_raw = payload.get("mission")
    if not isinstance(mission_raw, list):
        raise ValueError("mission must be an array")

    items: list[MissionItem] = []
    for idx, row_any in enumerate(mission_raw):
        if not isinstance(row_any, dict):
            continue
        row = row_any
        lat = row.get("lat")
        lon = row.get("lon")
        if lat is None or lon is None:
            continue
        items.append(
            MissionItem(
                seq=idx,
                command=int(row.get("command", int(MAV_CMD.NAV_WAYPOINT))),
                frame=int(row.get("frame", 3)),
                lat=float(lat),
                lon=float(lon),
                alt=float(row.get("alt", 25)),
                raw=dict(row),
            )
        )
    if len(items) < 2:
        raise ValueError("mission must include at least two spatial points")

    args = payload.get("args")
    args_obj = args if isinstance(args, dict) else {}
    fast_return = bool(args_obj.get("fast_return", False))
    max_shortcut = min(300.0, max(10.0, float(args_obj.get("max_shortcut_deviation_m", 300.0))))

    if fast_return:
        from uav_route.shortcut_return import mission_fast_return

        simplified = mission_fast_return(items, max_shortcut)
    else:
        cfg = SimplifyConfig(
            remove_loiter=bool(args_obj.get("remove_loiter", True)),
            min_separation_m=max(0.0, float(args_obj.get("min_separation_m", 2.0))),
            min_turn_deg=max(0.0, float(args_obj.get("min_turn_deg", 6.0))),
            rdp_epsilon_m=max(0.0, float(args_obj.get("rdp_epsilon_m", 8.0))),
        )
        simplified = simplify_mission(items, cfg)
    return {
        "ok": True,
        "source": "python-bridge",
        "points_in": len(items),
        "points_out": len(simplified),
        "taught_fc": mission_to_geojson(items, "taught"),
        "simplified_fc": mission_to_geojson(simplified, "simplified"),
    }


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
        if p == "/api/gimbal":
            _apply_gimbal(payload)
            with STATE.lock:
                gp = STATE.gimbal_preset
                err = STATE.error
            self._send_json(200, {"ok": not bool(err), "gimbal_preset": gp, "error": err})
            return
        if p == "/api/gps":
            disabled = bool(payload.get("disabled", False))
            _set_gps_disabled(disabled)
            with STATE.lock:
                err = STATE.error
                gps_disabled = STATE.gps_disabled
            self._send_json(200, {"ok": not bool(err), "gps_disabled": gps_disabled, "error": err})
            return
        if p == "/api/ekf_gps":
            disabled = bool(payload.get("disabled", False))
            _set_ekf_no_gps(disabled)
            with STATE.lock:
                err = STATE.error
                ekf_no_gps = STATE.ekf_no_gps
            self._send_json(200, {"ok": not bool(err), "ekf_no_gps": ekf_no_gps, "error": err})
            return
        if p == "/api/record/start":
            _start_recording(payload)
            with STATE.lock:
                name = STATE.recording_name
                min_sep_m = STATE.recording_min_sep_m
            self._send_json(200, {"ok": True, "recording": True, "name": name, "min_sep_m": min_sep_m})
            return
        if p == "/api/record/stop":
            try:
                result = _stop_recording(payload)
            except Exception as e:
                _set_error(str(e))
                with STATE.lock:
                    err = STATE.error
                self._send_json(400, {"ok": False, "error": err})
                return
            self._send_json(200, result)
            return
        if p == "/api/vbn/init":
            simplified_fc = payload.get("simplified_fc")
            if not isinstance(simplified_fc, dict):
                self._send_json(400, {"ok": False, "error": "simplified_fc must be a GeoJSON FeatureCollection"})
                return
            playback = init_playback(simplified_fc)
            if playback is None:
                self._send_json(400, {"ok": False, "error": "could not build playback from simplified route"})
                return
            with STATE.lock:
                STATE.vbn_playback = playback
                STATE.error = ""
            first = step_playback(playback, 0.0)
            with STATE.lock:
                STATE.vbn_playback = first["playback"]
            self._send_json(
                200,
                {
                    "ok": True,
                    "lat": first["lat"],
                    "lon": first["lon"],
                    "heading_deg": first["heading_deg"],
                    "done": bool(first.get("done")),
                },
            )
            return
        if p == "/api/vbn/step":
            step = float(payload.get("step", 0.11))
            step = max(0.001, min(1.0, step))
            with STATE.lock:
                playback = STATE.vbn_playback
            if playback is None:
                self._send_json(400, {"ok": False, "error": "vbn playback not initialized"})
                return
            frame = step_playback(playback, step)
            with STATE.lock:
                STATE.vbn_playback = frame["playback"]
            self._send_json(
                200,
                {
                    "ok": True,
                    "lat": frame["lat"],
                    "lon": frame["lon"],
                    "heading_deg": frame["heading_deg"],
                    "done": bool(frame.get("done")),
                },
            )
            return
        if p == "/api/simplify/mission":
            try:
                result = _simplify_mission_payload(payload)
            except Exception as e:
                self._send_json(400, {"ok": False, "error": str(e)})
                return
            self._send_json(200, result)
            return

        self._send_json(404, {"error": "not found"})

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


def main() -> None:
    try:
        import pymavlink  # noqa: F401
    except Exception as e:
        print(_pymavlink_import_error(e), file=sys.stderr, flush=True)

    host = "127.0.0.1"
    port = 8765
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"SITL bridge listening at http://{host}:{port}")
    print("POST /api/connect {\"connection\":\"udp:127.0.0.1:14550\"}")
    print('POST /api/gimbal {"preset":"nadir"}  # RC6/7/8 gimbal — see uav_route.gimbal_rc')
    server.serve_forever()


if __name__ == "__main__":
    main()

