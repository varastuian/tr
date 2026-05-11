from __future__ import annotations

"""
Mission file importers.

This module converts common mission formats into the internal `MissionItem`
representation used by `uav_route.simplify`.

Supported inputs:
- QGroundControl `.plan` (JSON "Plan" format)
- QGroundControl / ArduPilot "QGC WPL" waypoint files (text)
- Existing internal mission JSON (`{"mission": [...]}`) via `load_mission_json`
"""

import json
from pathlib import Path
from typing import Any

from .mission import MissionItem, load_mission_json

_MAV_CMD_NAME_TO_ID: dict[str, int] | None = None


def _coerce_int(v: Any) -> int | None:
    if v is None:
        return None
    if isinstance(v, bool):  # pragma: no cover (defensive)
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
            return int(s)
    return None


def _coerce_float(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _ensure_mav_cmd_name_to_id() -> dict[str, int]:
    global _MAV_CMD_NAME_TO_ID
    if _MAV_CMD_NAME_TO_ID is not None:
        return _MAV_CMD_NAME_TO_ID

    # `pymavlink` exposes MAV_CMD enums via `mavutil.mavlink.enums['MAV_CMD']`.
    # We invert it to map "MAV_CMD_NAV_WAYPOINT" -> 16, etc.
    from pymavlink import mavutil

    enums = mavutil.mavlink.enums.get("MAV_CMD")
    name_to_id: dict[str, int] = {}
    if enums:
        for cmd_id_str, variants in enums.items():
            try:
                cmd_id = int(cmd_id_str)
            except ValueError:  # pragma: no cover (defensive)
                continue
            if not isinstance(variants, dict):
                continue
            name = variants.get("name")
            if name:
                name_to_id[str(name)] = cmd_id
    _MAV_CMD_NAME_TO_ID = name_to_id
    return name_to_id


def _mav_cmd_from_any(v: Any) -> int:
    """
    Convert QGC / waypoint command representations to MAV_CMD numeric id.
    """
    if v is None:
        raise ValueError("Mission item missing command")
    if isinstance(v, bool):  # pragma: no cover (defensive)
        raise ValueError("Invalid mission command type")
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            raise ValueError("Mission item command is empty")
        if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
            return int(s)

        # Common QGC spellings.
        # Examples seen in exports:
        # - "MAV_CMD_NAV_WAYPOINT"
        # - "NAV_WAYPOINT"
        # - "MAV_CMD_NAV_TAKEOFF"
        if s.startswith("NAV_") and not s.startswith("MAV_CMD_"):
            s = f"MAV_CMD_{s}"
        elif s.startswith("MAV_CMD") and not s.startswith("MAV_CMD_"):
            # E.g. "MAV_CMDNAV_WAYPOINT" -> "MAV_CMD_NAV_WAYPOINT"
            s = s.replace("MAV_CMD", "MAV_CMD_", 1)

        name_to_id = _ensure_mav_cmd_name_to_id()
        if s in name_to_id:
            return name_to_id[s]

        # Try a last-resort normalization.
        s_norm = s.replace("mav_cmd_", "MAV_CMD_").replace("MAVCMD_", "MAV_CMD_")
        if s_norm in name_to_id:
            return name_to_id[s_norm]

    raise ValueError(f"Unrecognized mission command: {v!r}")


def load_mission_items_from_qgc_plan(data: dict[str, Any]) -> list[MissionItem]:
    """
    Load a QGroundControl `.plan` file into `MissionItem`s.

    QGC plan structure is version-dependent; this parser focuses on the common
    "mission" -> "items" array where each item has:
    - `command`: MAV_CMD id or name
    - `frame`: MAV_FRAME id (often 3 for global)
    - `params`: list of 7 params (for waypoints params[4..6] are lat/lon/alt)
    """
    if not isinstance(data, dict):
        raise ValueError("QGC plan root must be a JSON object")

    mission = data.get("mission", None)
    items: list[Any] | None = None
    if isinstance(mission, dict) and isinstance(mission.get("items"), list):
        items = mission["items"]
    elif isinstance(data.get("items"), list):
        items = data["items"]  # non-standard but seen in the wild

    if items is None:
        raise ValueError("Unrecognized QGC plan: missing mission.items array")

    out: list[MissionItem] = []
    for idx, raw_item in enumerate(items):
        if not isinstance(raw_item, dict):
            continue

        command = _mav_cmd_from_any(raw_item.get("command"))
        frame = _coerce_int(raw_item.get("frame"))

        params = raw_item.get("params", None)
        lat = lon = alt = None
        if isinstance(params, list) and len(params) >= 7:
            lat = _coerce_float(params[4])
            lon = _coerce_float(params[5])
            alt = _coerce_float(params[6])

        out.append(
            MissionItem(
                seq=idx,
                command=command,
                frame=frame,
                lat=lat,
                lon=lon,
                alt=alt,
                raw=dict(raw_item),
            )
        )

    return out


def load_mission_items_from_qgc_wpl(text: str) -> list[MissionItem]:
    """
    Load a "QGC WPL" waypoint text file.

    Format (12 whitespace-separated columns):
      seq current frame command param1 param2 param3 param4 x y z autocontinue

    Where (x, y, z) are (lat, lon, alt) for global waypoint commands.
    """
    # Normalize line endings and strip empty lines.
    lines = [ln.strip() for ln in text.replace("\r\n", "\n").split("\n") if ln.strip()]
    if not lines:
        return []

    header = lines[0]
    if "QGC WPL" not in header:
        raise ValueError("Not a QGC WPL waypoint file (missing 'QGC WPL' header)")

    out: list[MissionItem] = []
    for line in lines[1:]:
        # Allow comments at end of line.
        if "#" in line:
            line = line.split("#", 1)[0].strip()
        if not line:
            continue

        parts = line.split()
        if len(parts) < 12:
            raise ValueError(f"Invalid QGC WPL line (expected 12 fields): {line!r}")

        seq = _coerce_int(parts[0])
        frame = _coerce_int(parts[2])
        command = _coerce_int(parts[3])
        if seq is None or command is None or frame is None:
            raise ValueError(f"Invalid QGC WPL numeric fields: {line!r}")

        # QGC WPL:
        #   param1..param4 are strings/floats
        #   x y z are latitude, longitude, altitude
        raw = {
            "seq": seq,
            "current": _coerce_int(parts[1]),
            "frame": frame,
            "command": command,
            "param1": _coerce_float(parts[4]),
            "param2": _coerce_float(parts[5]),
            "param3": _coerce_float(parts[6]),
            "param4": _coerce_float(parts[7]),
            "x": _coerce_float(parts[8]),
            "y": _coerce_float(parts[9]),
            "z": _coerce_float(parts[10]),
            "autocontinue": _coerce_int(parts[11]),
        }

        lat = raw["x"]
        lon = raw["y"]
        alt = raw["z"]

        out.append(
            MissionItem(
                seq=seq,
                command=command,
                frame=frame,
                lat=lat,
                lon=lon,
                alt=alt,
                raw=raw,
            )
        )

    return out


def load_mission_items_file(path: Path) -> list[MissionItem]:
    """
    Load a mission from a file, supporting:
    - `.plan` (QGroundControl plan JSON)
    - QGC WPL waypoint text files
    - internal JSON mission files (`{"mission": [...]}`)
    """
    if not path.is_file():
        raise FileNotFoundError(str(path))

    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8")

    # Waypoint text.
    if suffix in {".waypoints", ".wpl", ".txt"} or text.lstrip().startswith("QGC WPL"):
        return load_mission_items_from_qgc_wpl(text)

    # JSON (QGC plan or internal mission JSON).
    data: Any = json.loads(text)
    if isinstance(data, dict):
        if data.get("fileType") == "Plan" or isinstance(data.get("mission"), dict):
            # QGC plan.
            return load_mission_items_from_qgc_plan(data)
        if "mission" in data:
            return load_mission_json(data)

    raise ValueError(
        f"Unsupported mission file format for {path.name!r} "
        "(expected QGroundControl `.plan`, QGC WPL `.waypoints`, or internal JSON mission)."
    )


__all__ = ["load_mission_items_from_qgc_plan", "load_mission_items_from_qgc_wpl", "load_mission_items_file"]

