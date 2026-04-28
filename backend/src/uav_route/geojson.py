from __future__ import annotations

from typing import Any, Iterable

from .mission import MissionItem


def _feature(geom: dict[str, Any], props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "Feature", "geometry": geom, "properties": props}


def mission_to_geojson(items: Iterable[MissionItem], name: str) -> dict[str, Any]:
    items_list = list(items)
    coords_line: list[list[float]] = []
    point_features: list[dict[str, Any]] = []

    for it in items_list:
        if it.lat is None or it.lon is None:
            continue
        coords_line.append([it.lon, it.lat])
        point_features.append(
            _feature(
                {"type": "Point", "coordinates": [it.lon, it.lat]},
                {
                    "seq": it.seq,
                    "command": int(it.command),
                    "alt": it.alt,
                },
            )
        )

    line = _feature(
        {"type": "LineString", "coordinates": coords_line},
        {"name": name, "kind": "route"},
    )

    return {
        "type": "FeatureCollection",
        "features": [line, *point_features],
        "properties": {"name": name},
    }

