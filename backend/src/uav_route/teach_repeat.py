from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from uav_route.geo import LL, haversine_m
from uav_route.geojson import mission_to_geojson
from uav_route.mission import MAV_CMD, MissionItem
from uav_route.simplify import SimplifyConfig, simplify_mission
from uav_route.track_library import SavedTrack, list_tracks, save_track


def _connect(connection: str):
    from pymavlink import mavutil  # type: ignore

    m = mavutil.mavlink_connection(connection)
    hb = m.wait_heartbeat(timeout=15)
    if hb is None:
        raise RuntimeError(f"No heartbeat on {connection}")
    return m


def _record_path(connection: str, seconds: float, hz: float, min_sep_m: float) -> list[MissionItem]:
    master = _connect(connection)
    timeout_s = max(0.2, 1.0 / max(0.5, hz))
    deadline = time.monotonic() + max(1.0, seconds)
    points: list[MissionItem] = []
    last_ll: LL | None = None
    seq = 0

    while time.monotonic() < deadline:
        msg = master.recv_match(type="GLOBAL_POSITION_INT", blocking=True, timeout=timeout_s)
        if msg is None:
            continue
        lat = float(msg.lat) / 1e7
        lon = float(msg.lon) / 1e7
        alt = float(msg.relative_alt) / 1000.0
        cur = LL(lat, lon)
        if last_ll is not None and haversine_m(last_ll, cur) < min_sep_m:
            continue
        points.append(
            MissionItem(
                seq=seq,
                command=int(MAV_CMD.NAV_WAYPOINT),
                frame=3,  # MAV_FRAME_GLOBAL_RELATIVE_ALT
                lat=lat,
                lon=lon,
                alt=alt,
                raw={"source": "sitl_record"},
            )
        )
        seq += 1
        last_ll = cur
    if len(points) < 2:
        raise RuntimeError("Recorded too few route points; increase --seconds or lower --min-sep-m")
    return points


def _mode_guided(master) -> None:
    mode_id = master.mode_mapping().get("GUIDED")
    if mode_id is None:
        raise RuntimeError("GUIDED mode not supported by this vehicle")
    master.set_mode(mode_id)
    time.sleep(0.7)


def _goto(master, lat: float, lon: float, alt_m: float, speed_mps: float) -> None:
    from pymavlink import mavutil  # type: ignore

    master.mav.command_long_send(
        master.target_system,
        master.target_component,
        mavutil.mavlink.MAV_CMD_DO_CHANGE_SPEED,
        0,
        1,  # ground speed
        float(speed_mps),
        -1,
        0,
        0,
        0,
        0,
    )
    master.mav.set_position_target_global_int_send(
        0,
        master.target_system,
        master.target_component,
        mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
        int(0b0000111111111000),  # position only
        int(lat * 1e7),
        int(lon * 1e7),
        float(alt_m),
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
    )


def _wait_arrival(master, target: LL, radius_m: float, timeout_s: float) -> bool:
    end = time.monotonic() + max(1.0, timeout_s)
    while time.monotonic() < end:
        msg = master.recv_match(type="GLOBAL_POSITION_INT", blocking=True, timeout=1.0)
        if msg is None:
            continue
        cur = LL(float(msg.lat) / 1e7, float(msg.lon) / 1e7)
        if haversine_m(cur, target) <= radius_m:
            return True
    return False


def _pick_track(track_ref: str | None) -> SavedTrack:
    tracks = list_tracks()
    if not tracks:
        raise RuntimeError("No saved tracks found in track library")
    if not track_ref:
        return tracks[0]
    for t in tracks:
        if t.id == track_ref or t.id.startswith(track_ref) or t.name == track_ref:
            return t
    raise RuntimeError(f"Track not found: {track_ref}")


def _line_points(fc: dict[str, Any]) -> list[tuple[float, float, float | None]]:
    feats = fc.get("features") or []
    line = next((f for f in feats if (f.get("geometry") or {}).get("type") == "LineString"), None)
    if line is None:
        return []
    coords = (line.get("geometry") or {}).get("coordinates") or []
    out: list[tuple[float, float, float | None]] = []
    for c in coords:
        if not isinstance(c, list) or len(c) < 2:
            continue
        lon = float(c[0])
        lat = float(c[1])
        alt = float(c[2]) if len(c) > 2 and c[2] is not None else None
        out.append((lat, lon, alt))
    return out


def cmd_record(args: argparse.Namespace) -> None:
    points = _record_path(args.connection, args.seconds, args.hz, args.min_sep_m)
    simplified = simplify_mission(
        points,
        SimplifyConfig(
            remove_loiter=True,
            min_separation_m=args.min_sep_m,
            min_turn_deg=args.min_turn_deg,
            rdp_epsilon_m=args.rdp_epsilon_m,
        ),
    )
    taught_fc = mission_to_geojson(points, "taught")
    simplified_fc = mission_to_geojson(simplified, "simplified")
    rec = save_track(taught_fc, simplified_fc, name=args.name)
    print(json.dumps({"ok": True, "id": rec.id, "name": rec.name, "points": len(points)}))


def cmd_repeat(args: argparse.Namespace) -> None:
    master = _connect(args.connection)
    _mode_guided(master)
    tr = _pick_track(args.track)
    pts = _line_points(tr.simplified)
    if len(pts) < 2:
        raise RuntimeError("Selected track has too few simplified points")
    route = list(reversed(pts)) if args.reverse else pts
    print(f"repeating track: {tr.name} ({tr.id}) with {len(route)} waypoints", flush=True)
    for idx, (lat, lon, alt) in enumerate(route):
        goal_alt = args.alt_m if alt is None else alt
        _goto(master, lat, lon, goal_alt, args.speed_mps)
        ok = _wait_arrival(master, LL(lat, lon), args.arrival_radius_m, args.wp_timeout_s)
        status = "arrived" if ok else "timeout"
        print(f"wp {idx + 1}/{len(route)} {status}", flush=True)
        if not ok and args.stop_on_timeout:
            raise RuntimeError(f"Timeout reaching waypoint {idx + 1}")
    if args.rtl_end:
        mode_id = master.mode_mapping().get("RTL")
        if mode_id is not None:
            master.set_mode(mode_id)
            print("set mode RTL", flush=True)


def main() -> None:
    p = argparse.ArgumentParser(description="Python-only SITL teach & repeat")
    sub = p.add_subparsers(dest="cmd", required=True)

    rec = sub.add_parser("record", help="Record taught route from SITL telemetry")
    rec.add_argument("--connection", default="udp:127.0.0.1:14550")
    rec.add_argument("--seconds", type=float, default=120.0)
    rec.add_argument("--hz", type=float, default=5.0)
    rec.add_argument("--min-sep-m", type=float, default=1.5)
    rec.add_argument("--min-turn-deg", type=float, default=6.0)
    rec.add_argument("--rdp-epsilon-m", type=float, default=8.0)
    rec.add_argument("--name", default="sitl_taught_route")
    rec.set_defaults(func=cmd_record)

    rep = sub.add_parser("repeat", help="Repeat saved route in GUIDED mode")
    rep.add_argument("--connection", default="udp:127.0.0.1:14550")
    rep.add_argument("--track", default=None, help="Track id prefix or exact name; default latest")
    rep.add_argument("--reverse", action="store_true", help="Fly simplified route in reverse (return to home)")
    rep.add_argument("--speed-mps", type=float, default=4.0)
    rep.add_argument("--alt-m", type=float, default=25.0)
    rep.add_argument("--arrival-radius-m", type=float, default=3.0)
    rep.add_argument("--wp-timeout-s", type=float, default=35.0)
    rep.add_argument("--stop-on-timeout", action="store_true")
    rep.add_argument("--rtl-end", action="store_true")
    rep.set_defaults(func=cmd_repeat)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
