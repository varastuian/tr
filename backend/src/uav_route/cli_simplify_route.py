"""
CLI: simplify waypoint paths or ArduPilot-style mission JSON.

Windows examples (after ``pip install -e ./backend`` or ``pip install .`` from backend):

  uav-simplify-mission -i route.json -o simple.json
  python -m uav_route.cli_simplify_route -i track.json --rdp-epsilon-m 12

Plain coordinates JSON (lat, lon order by default):

  {"points": [[37.1, -122.0], [37.2, -122.05]]}

Or a top-level JSON array of coordinate pairs.

Single-file ``.exe`` (PyInstaller): on Windows, run
``backend\\packaging\\build_uav_simplify_exe.bat``, then use
``dist\\uav-simplify-mission.exe``. Exit codes: 0 success; 1 invalid input / IO error; 2 JSON parse error;
3 unexpected error.

From Python (same machine as the library): ``from uav_route.cli_simplify_route import main`` then ``main(["-i", "in.json", "-o", "out.json"])``.

From Python/C# via ``.exe``: run the executable with ``-i`` and ``-o`` paths
(UTF-8 JSON). Example Python:
``subprocess.run(["dist/uav-simplify-mission.exe","-i","a.json","-o","b.json"], check=True)``.
"""

from __future__ import annotations

import argparse
import copy
import importlib.metadata
import json
import sys
from pathlib import Path
from typing import Any


def _bootstrap_path() -> None:
    # PyInstaller one-file sets sys.frozen; imports are already on sys.path.
    if getattr(sys, "frozen", False):
        return
    if __package__ is None or __package__ == "":
        src = Path(__file__).resolve().parent.parent
        sys.path.insert(0, str(src))


def _parse_coord_pairs(raw: list[Any], lonlat: bool) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for item in raw:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            raise ValueError(f"Expected [lat, lon] pairs, got: {item!r}")
        a, b = float(item[0]), float(item[1])
        lat, lon = (b, a) if lonlat else (a, b)
        out.append((lat, lon))
    return out


def _load_geojson_points(data: dict[str, Any]) -> list[tuple[float, float]]:
    from uav_route.vbn_path import simplified_route_lat_lon

    pts = simplified_route_lat_lon(data)
    if not pts:
        raise ValueError(
            "GeoJSON must be a FeatureCollection containing one LineString feature."
        )
    return pts


def _load_input(path: Path | None, lonlat: bool) -> tuple[str, Any, dict[str, Any]]:
    text = path.read_text(encoding="utf-8") if path else sys.stdin.read()

    stripped = text.lstrip()
    if stripped.startswith("QGC WPL"):
        from uav_route.mission_io import load_mission_items_from_qgc_wpl

        return "mission", load_mission_items_from_qgc_wpl(text), {"source": "qgc-wpl"}

    data = json.loads(text)

    if isinstance(data, list):
        return "points", _parse_coord_pairs(data, lonlat), {"source": "json-array"}

    if not isinstance(data, dict):
        raise ValueError("JSON root must be an object or an array of coordinate pairs.")

    # QGroundControl plan JSON export.
    if data.get("fileType") == "Plan":
        from uav_route.mission_io import load_mission_items_from_qgc_plan

        return "mission", load_mission_items_from_qgc_plan(data), {
            "source": "qgc-plan",
            "plan_template": data,
        }

    # Internal mission JSON (`{"mission": [...]}`).
    if "mission" in data:
        from uav_route.mission import load_mission_json

        return "mission", load_mission_json(data), {"source": "mission-json"}

    if data.get("type") == "FeatureCollection" or "features" in data:
        return "points", _load_geojson_points(data), {"source": "geojson"}

    if "points" in data and isinstance(data["points"], list):
        return "points", _parse_coord_pairs(data["points"], lonlat), {"source": "points-json"}

    raise ValueError(
        "Unrecognized JSON: need "
        '{"mission": [...]}, '
        '{"points": [[lat,lon], ...]}, '
        "GeoJSON FeatureCollection with LineString, "
        "or a JSON array [[lat,lon], ...]."
    )


def _mission_items_to_json(items: list[Any]) -> dict[str, Any]:
    mission = []
    for it in items:
        row = dict(it.raw)
        row["seq"] = it.seq
        row["command"] = int(it.command)
        row["frame"] = it.frame
        row["lat"] = it.lat
        row["lon"] = it.lon
        row["alt"] = it.alt
        mission.append(row)
    return {"mission": mission}


def _points_to_geojson(points: list[tuple[float, float]]) -> dict[str, Any]:
    coords = [[lon, lat] for lat, lon in points]
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"simplified": True},
                "geometry": {"type": "LineString", "coordinates": coords},
            }
        ],
    }


def _to_qgc_plan_item(it: Any, do_jump_id: int) -> dict[str, Any]:
    row = dict(it.raw) if isinstance(it.raw, dict) else {}
    params = row.get("params")
    if not isinstance(params, list):
        params = [0.0] * 7
    elif len(params) < 7:
        params = list(params) + [0.0] * (7 - len(params))
    else:
        params = list(params[:7])

    if it.lat is not None:
        params[4] = float(it.lat)
    if it.lon is not None:
        params[5] = float(it.lon)
    if it.alt is not None:
        params[6] = float(it.alt)

    row.update(
        {
            "autoContinue": bool(row.get("autoContinue", True)),
            "command": int(it.command),
            "doJumpId": int(row.get("doJumpId", do_jump_id)),
            "frame": int(it.frame) if it.frame is not None else int(row.get("frame", 3)),
            "params": params,
            "type": str(row.get("type", "SimpleItem")),
        }
    )
    return row


def _mission_items_to_qgc_plan(
    items: list[Any], plan_template: dict[str, Any] | None = None
) -> dict[str, Any]:
    plan = copy.deepcopy(plan_template) if isinstance(plan_template, dict) else {}
    if not isinstance(plan.get("mission"), dict):
        plan["mission"] = {}

    mission = plan["mission"]
    mission["items"] = [_to_qgc_plan_item(it, idx + 1) for idx, it in enumerate(items)]

    plan.setdefault("fileType", "Plan")
    plan.setdefault("groundStation", "QGroundControl")
    plan.setdefault("version", 1)
    mission.setdefault("version", 2)
    return plan


def _app_version() -> str:
    try:
        return importlib.metadata.version("uav-route")
    except importlib.metadata.PackageNotFoundError:
        return "0.1.0+local"


def main(argv: list[str] | None = None) -> int:
    try:
        return _main_impl(argv)
    except json.JSONDecodeError as e:
        print(f"JSONDecodeError: {e}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as e:
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # pragma: no cover - defensive for bundled exe
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 3


def _main_impl(argv: list[str] | None = None) -> int:
    _bootstrap_path()

    from uav_route.simplify import SimplifyConfig, simplify_lat_lon_path, simplify_mission

    p = argparse.ArgumentParser(
        description="Simplify waypoint lists or mission JSON (same algorithm as uav-teach-repeat)."
    )
    p.add_argument(
        "-i",
        "--input",
        type=Path,
        help="Input JSON file (default: stdin)",
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output JSON file (default: stdout)",
    )
    p.add_argument(
        "--lonlat",
        action="store_true",
        help="Input coordinate pairs are [lon, lat] (default is [lat, lon]).",
    )
    p.add_argument(
        "--rdp-epsilon-m",
        type=float,
        default=8.0,
        help="RDP tolerance in meters (larger => fewer points). Default: 8",
    )
    p.add_argument(
        "--min-separation-m",
        type=float,
        default=2.0,
        help="Drop consecutive points closer than this (meters). Default: 2",
    )
    p.add_argument(
        "--min-turn-deg",
        type=float,
        default=6.0,
        help="Drop points that bend the path less than this (degrees). Default: 6",
    )
    p.add_argument(
        "--keep-loiter",
        action="store_true",
        help="Keep loiter NAV items (default: remove loiter commands when simplifying).",
    )
    p.add_argument(
        "--format",
        choices=("json", "json-array", "geojson", "qgc-plan"),
        default="json",
        help='Output shape. Use "qgc-plan" for QGroundControl .plan mission output.',
    )
    p.add_argument(
        "--version",
        action="version",
        version=f"uav-simplify-mission {_app_version()}",
        help="Show app version and exit.",
    )

    args = p.parse_args(argv)

    if args.input is not None and not args.input.is_file():
        raise FileNotFoundError(f"Input file not found: {args.input}")

    cfg = SimplifyConfig(
        remove_loiter=not args.keep_loiter,
        min_separation_m=args.min_separation_m,
        min_turn_deg=args.min_turn_deg,
        rdp_epsilon_m=args.rdp_epsilon_m,
    )

    kind, payload, meta = _load_input(args.input, args.lonlat)

    if kind == "mission":
        simplified = simplify_mission(payload, cfg)
        wants_qgc_plan = args.format == "qgc-plan" or (
            meta.get("source") == "qgc-plan"
            and args.output is not None
            and args.output.suffix.lower() == ".plan"
        )
        if wants_qgc_plan:
            template = meta.get("plan_template")
            out_obj = _mission_items_to_qgc_plan(simplified, template)
        else:
            out_obj = _mission_items_to_json(simplified)
    else:
        if args.format == "qgc-plan":
            raise ValueError("Output format 'qgc-plan' only supports mission-style input.")
        simplified_pts = simplify_lat_lon_path(payload, cfg)
        if args.format == "json-array":
            out_obj = [[lat, lon] for lat, lon in simplified_pts]
        elif args.format == "geojson":
            out_obj = _points_to_geojson(simplified_pts)
        else:
            out_obj = {
                "points": [[lat, lon] for lat, lon in simplified_pts],
                "count": len(simplified_pts),
            }

    dumped = json.dumps(out_obj, indent=2) + "\n"
    if args.output:
        args.output.write_text(dumped, encoding="utf-8")
    else:
        sys.stdout.write(dumped)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
