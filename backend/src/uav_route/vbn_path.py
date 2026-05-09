from __future__ import annotations

import math
from typing import Any


Point = tuple[float, float]


def simplified_route_lat_lon(fc: dict[str, Any] | None) -> list[Point] | None:
    if not fc:
        return None
    features = fc.get("features")
    if not isinstance(features, list):
        return None
    line = next(
        (f for f in features if isinstance(f, dict) and (f.get("geometry") or {}).get("type") == "LineString"),
        None,
    )
    if not isinstance(line, dict):
        return None
    geometry = line.get("geometry") or {}
    coords = geometry.get("coordinates")
    if not isinstance(coords, list) or len(coords) < 2:
        return None
    out: list[Point] = []
    for c in coords:
        if not isinstance(c, list) or len(c) < 2:
            continue
        lon = float(c[0])
        lat = float(c[1])
        out.append((lat, lon))
    return out if len(out) >= 2 else None


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    y = math.sin(dlon) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def init_playback(fc: dict[str, Any] | None) -> dict[str, Any] | None:
    fwd = simplified_route_lat_lon(fc)
    if not fwd:
        return None
    return {"points": list(reversed(fwd)), "seg_index": 0, "alpha": 0.0}


def step_playback(state: dict[str, Any], step: float) -> dict[str, Any]:
    points = state["points"]
    seg_index = int(state["seg_index"])
    alpha = float(state["alpha"])

    if seg_index >= len(points) - 1:
        lat, lon = points[-1]
        return {
            "playback": {"points": points, "seg_index": seg_index, "alpha": 1.0},
            "lat": lat,
            "lon": lon,
            "heading_deg": 0.0,
            "done": True,
        }

    alpha += step
    while alpha >= 1.0 and seg_index < len(points) - 1:
        alpha -= 1.0
        seg_index += 1

    if seg_index >= len(points) - 1:
        lat, lon = points[-1]
        return {
            "playback": {"points": points, "seg_index": len(points) - 1, "alpha": 1.0},
            "lat": lat,
            "lon": lon,
            "heading_deg": 0.0,
            "done": True,
        }

    la0, lo0 = points[seg_index]
    la1, lo1 = points[seg_index + 1]
    lat = la0 + (la1 - la0) * alpha
    lon = lo0 + (lo1 - lo0) * alpha
    return {
        "playback": {"points": points, "seg_index": seg_index, "alpha": alpha},
        "lat": lat,
        "lon": lon,
        "heading_deg": bearing_deg(lat, lon, la1, lo1),
        "done": False,
    }
