from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .geo import LL, angle_diff_deg, bearing_deg, cross_track_distance_m, haversine_m
from .mission import MAV_CMD, MissionItem


@dataclass(frozen=True)
class SimplifyConfig:
    # Remove purely loiter navigation commands.
    remove_loiter: bool = True
    # Drop points closer than this to the previous kept point.
    min_separation_m: float = 2.0
    # If a candidate point does not change heading by at least this amount, it may be dropped.
    min_turn_deg: float = 6.0
    # RDP epsilon (meters). Larger => fewer points.
    rdp_epsilon_m: float = 5.0


ESSENTIAL_COMMANDS: set[int] = {
    int(MAV_CMD.NAV_TAKEOFF),
    int(MAV_CMD.NAV_LAND),
    int(MAV_CMD.NAV_RETURN_TO_LAUNCH),
}


def _is_essential(item: MissionItem) -> bool:
    return int(item.command) in ESSENTIAL_COMMANDS


def _rdp_indices(points: list[LL], epsilon_m: float) -> list[int]:
    if len(points) <= 2:
        return list(range(len(points)))

    keep: list[bool] = [False] * len(points)
    keep[0] = True
    keep[-1] = True

    stack: list[tuple[int, int]] = [(0, len(points) - 1)]
    while stack:
        i, j = stack.pop()
        a = points[i]
        b = points[j]
        max_d = -1.0
        max_k = None
        for k in range(i + 1, j):
            d = cross_track_distance_m(points[k], a, b)
            if d > max_d:
                max_d = d
                max_k = k
        if max_k is not None and max_d > epsilon_m:
            keep[max_k] = True
            stack.append((i, max_k))
            stack.append((max_k, j))

    return [i for i, v in enumerate(keep) if v]


def simplify_mission(items: Iterable[MissionItem], cfg: SimplifyConfig) -> list[MissionItem]:
    """
    Simplify a mission while keeping non-spatial/essential commands.

    Strategy:
    - optionally remove loiter commands
    - build a spatial polyline from remaining spatial items
    - prefilter: drop near-duplicates and tiny heading changes
    - run RDP on the remaining polyline
    - map kept polyline points back to mission items (by index)
    """
    items_list = list(items)

    filtered: list[MissionItem] = []
    for it in items_list:
        if cfg.remove_loiter and it.is_loiter and not _is_essential(it):
            continue
        filtered.append(it)

    spatial: list[MissionItem] = [it for it in filtered if it.is_spatial and not _is_essential(it)]
    essentials: list[MissionItem] = [it for it in filtered if _is_essential(it)]
    passthrough: list[MissionItem] = [it for it in filtered if (not it.is_spatial) and (not _is_essential(it))]

    if not spatial:
        out = essentials + passthrough
        return _resequenced(out)

    # Prefilter spatial points.
    pre: list[MissionItem] = [spatial[0]]
    for cand in spatial[1:]:
        last = pre[-1]
        a = LL(last.lat, last.lon)  # type: ignore[arg-type]
        b = LL(cand.lat, cand.lon)  # type: ignore[arg-type]
        if haversine_m(a, b) < cfg.min_separation_m:
            continue
        if len(pre) >= 2:
            prev = pre[-2]
            p = LL(prev.lat, prev.lon)  # type: ignore[arg-type]
            br1 = bearing_deg(p, a)
            br2 = bearing_deg(a, b)
            if angle_diff_deg(br1, br2) < cfg.min_turn_deg:
                continue
        pre.append(cand)

    pts = [LL(it.lat, it.lon) for it in pre]  # type: ignore[arg-type]
    keep_idx = _rdp_indices(pts, cfg.rdp_epsilon_m)
    kept_spatial = [pre[i] for i in keep_idx]

    # Merge back: keep original order among all remaining items.
    kept_set = {id(it) for it in kept_spatial}
    out: list[MissionItem] = []
    for it in filtered:
        if _is_essential(it) or (not it.is_spatial):
            out.append(it)
        else:
            if id(it) in kept_set:
                out.append(it)

    return _resequenced(out)


def _resequenced(items: list[MissionItem]) -> list[MissionItem]:
    out: list[MissionItem] = []
    for i, it in enumerate(items):
        raw = dict(it.raw)
        raw["seq"] = i
        out.append(
            MissionItem(
                seq=i,
                command=int(it.command),
                frame=it.frame,
                lat=it.lat,
                lon=it.lon,
                alt=it.alt,
                raw=raw,
            )
        )
    return out

