from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class LL:
    lat: float
    lon: float


EARTH_RADIUS_M = 6371008.8


def haversine_m(a: LL, b: LL) -> float:
    lat1 = math.radians(a.lat)
    lat2 = math.radians(b.lat)
    dlat = lat2 - lat1
    dlon = math.radians(b.lon - a.lon)
    s = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(s)))


def bearing_deg(a: LL, b: LL) -> float:
    lat1 = math.radians(a.lat)
    lat2 = math.radians(b.lat)
    dlon = math.radians(b.lon - a.lon)
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(
        dlon
    )
    brng = math.degrees(math.atan2(y, x))
    return (brng + 360.0) % 360.0


def angle_diff_deg(a: float, b: float) -> float:
    d = (b - a + 180.0) % 360.0 - 180.0
    return abs(d)


def cross_track_distance_m(p: LL, a: LL, b: LL) -> float:
    """
    Approx cross-track distance from point p to segment a-b.
    Uses an equirectangular projection (good for local route simplification).
    """
    lat0 = math.radians((a.lat + b.lat) / 2.0)
    ax = math.radians(a.lon) * math.cos(lat0)
    ay = math.radians(a.lat)
    bx = math.radians(b.lon) * math.cos(lat0)
    by = math.radians(b.lat)
    px = math.radians(p.lon) * math.cos(lat0)
    py = math.radians(p.lat)

    vx = bx - ax
    vy = by - ay
    wx = px - ax
    wy = py - ay

    vv = vx * vx + vy * vy
    if vv == 0:
        dx = px - ax
        dy = py - ay
        return math.hypot(dx, dy) * EARTH_RADIUS_M

    t = max(0.0, min(1.0, (wx * vx + wy * vy) / vv))
    cx = ax + t * vx
    cy = ay + t * vy
    return math.hypot(px - cx, py - cy) * EARTH_RADIUS_M

