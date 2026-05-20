"""Fast return (end→start): shortest path with waypoint jumps inside a corridor of the traced route."""

from __future__ import annotations

import math

from uav_route.geo import LL, cross_track_distance_m, haversine_m
from uav_route.mission import MAV_CMD, MissionItem


def _max_deviation_on_subpath(points: list[LL], i: int, j: int) -> float:
    """Max cross-track distance from intermediate vertices to chord points[i]→points[j]."""
    if j - i <= 1:
        return 0.0
    a, b = points[i], points[j]
    m = 0.0
    for k in range(i + 1, j):
        m = max(m, cross_track_distance_m(points[k], a, b))
    return m


def shortest_reverse_vertex_indices(
    path_forward: list[LL], max_deviation_m: float
) -> list[int]:
    """
    Shortest end→start route on the reversed taught polyline.

    Any jump i→j is allowed when every skipped vertex stays within ``max_deviation_m``
    of the straight shortcut (corridor constraint). Edge cost is geodesic chord length.
    """
    rev = list(reversed(path_forward))
    n = len(rev)
    if n < 2:
        return list(range(n))

    max_dev = max(1.0, float(max_deviation_m))

    # Precompute valid jumps: i can shortcut to j>i when corridor is OK.
    valid_next: list[list[int]] = [[] for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            if _max_deviation_on_subpath(rev, i, j) <= max_dev:
                valid_next[i].append(j)

    best = [math.inf] * n
    prev = [-1] * n
    best[0] = 0.0

    for i in range(n):
        if not math.isfinite(best[i]):
            continue
        for j in valid_next[i]:
            direct = haversine_m(rev[i], rev[j])
            cand = best[i] + direct
            if cand < best[j]:
                best[j] = cand
                prev[j] = i

    last = n - 1
    if not math.isfinite(best[last]):
        # No corridor-feasible shortcuts — follow full reversed path.
        return list(range(n))

    idx: list[int] = []
    cur = last
    while cur >= 0:
        idx.append(cur)
        if cur == 0:
            break
        cur = prev[cur]
    idx.reverse()
    return idx


def mission_fast_return(items: list[MissionItem], max_shortcut_deviation_m: float) -> list[MissionItem]:
    """Build simplified mission: reversed path with corridor-limited shortcut jumps."""
    spatial_items = [it for it in items if it.lat is not None and it.lon is not None]
    if len(spatial_items) < 2:
        return list(items)

    pts_forward = [LL(float(it.lat), float(it.lon)) for it in spatial_items]
    pick = shortest_reverse_vertex_indices(pts_forward, max_shortcut_deviation_m)
    rev_spatial = list(reversed(spatial_items))

    out: list[MissionItem] = []
    for i, ri in enumerate(pick):
        src = rev_spatial[ri]
        raw = dict(src.raw) if isinstance(src.raw, dict) else {}
        raw["seq"] = i
        raw["source"] = "python_fast_return"
        out.append(
            MissionItem(
                seq=i,
                command=int(MAV_CMD.NAV_WAYPOINT),
                frame=src.frame,
                lat=float(src.lat) if src.lat is not None else None,
                lon=float(src.lon) if src.lon is not None else None,
                alt=src.alt,
                raw=raw,
            )
        )
    return out
