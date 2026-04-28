from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Iterable


class MAV_CMD(IntEnum):
    # Minimal subset; ArduPilot uses MAVLink command ids.
    NAV_WAYPOINT = 16
    NAV_LOITER_UNLIM = 17
    NAV_LOITER_TURNS = 18
    NAV_LOITER_TIME = 19
    NAV_RETURN_TO_LAUNCH = 20
    NAV_LAND = 21
    NAV_TAKEOFF = 22
    NAV_LOITER_TO_ALT = 31


LOITER_COMMANDS: set[int] = {
    int(MAV_CMD.NAV_LOITER_UNLIM),
    int(MAV_CMD.NAV_LOITER_TURNS),
    int(MAV_CMD.NAV_LOITER_TIME),
    int(MAV_CMD.NAV_LOITER_TO_ALT),
}


@dataclass(frozen=True)
class MissionItem:
    """
    MAVLink-like mission item (lat/lon in degrees, alt in meters).

    We intentionally keep an extensible `raw` payload so you can preserve
    non-navigation mission actions in the future.
    """

    seq: int
    command: int
    frame: int | None
    lat: float | None
    lon: float | None
    alt: float | None
    raw: dict[str, Any]

    @property
    def is_spatial(self) -> bool:
        return self.lat is not None and self.lon is not None

    @property
    def is_loiter(self) -> bool:
        return int(self.command) in LOITER_COMMANDS


def load_mission_json(data: dict[str, Any]) -> list[MissionItem]:
    """
    Load a mission from a simple JSON format:

    {
      "mission": [
        {"seq": 0, "command": 22, "frame": 3, "lat": ..., "lon": ..., "alt": ...},
        ...
      ]
    }
    """
    items: list[MissionItem] = []
    for idx, obj in enumerate(data.get("mission", [])):
        seq = int(obj.get("seq", idx))
        cmd = int(obj["command"])
        frame = obj.get("frame", None)
        frame_i = int(frame) if frame is not None else None
        lat = obj.get("lat", None)
        lon = obj.get("lon", None)
        alt = obj.get("alt", None)
        items.append(
            MissionItem(
                seq=seq,
                command=cmd,
                frame=frame_i,
                lat=float(lat) if lat is not None else None,
                lon=float(lon) if lon is not None else None,
                alt=float(alt) if alt is not None else None,
                raw=dict(obj),
            )
        )
    return items


def iter_spatial_items(items: Iterable[MissionItem]) -> Iterable[MissionItem]:
    for it in items:
        if it.is_spatial:
            yield it

