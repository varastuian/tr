"""
Filesystem **track library**: save/load taught + simplified missions as GeoJSON FeatureCollections.

Each entry is one JSON file (portable with the browser ``trackLibrary.ts`` shape).

Default directory: ``$UAV_TRACK_LIBRARY_DIR`` or ``~/.uav_route/tracks``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


@dataclass
class SavedTrack:
    id: str
    name: str
    savedAt: str
    taught: dict[str, Any]
    simplified: dict[str, Any]

    def to_json_obj(self) -> dict[str, Any]:
        return asdict(self)


def default_library_dir() -> Path:
    env = os.environ.get("UAV_TRACK_LIBRARY_DIR", "").strip()
    if env:
        return Path(env).expanduser()
    return Path.home() / ".uav_route" / "tracks"


def _safe_slug(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "_", name.strip())[:80]
    return s or "track"


def save_track(
    taught: dict[str, Any],
    simplified: dict[str, Any],
    *,
    name: str,
    library_dir: Path | None = None,
) -> SavedTrack:
    """Write a new track file; returns the saved record."""
    if taught.get("type") != "FeatureCollection" or simplified.get("type") != "FeatureCollection":
        raise ValueError("taught and simplified must be GeoJSON FeatureCollections")

    d = library_dir or default_library_dir()
    d.mkdir(parents=True, exist_ok=True)

    tid = str(uuid.uuid4())
    saved_at = datetime.now(timezone.utc).isoformat()
    label = name.strip() or saved_at[:19]
    rec = SavedTrack(
        id=tid,
        name=label,
        savedAt=saved_at,
        taught=taught,
        simplified=simplified,
    )

    fname = f"{_safe_slug(label)}_{tid[:8]}.json"
    path = d / fname
    path.write_text(json.dumps(rec.to_json_obj(), indent=2), encoding="utf-8")
    return rec


def load_track_file(path: Path) -> SavedTrack:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return SavedTrack(
        id=str(raw["id"]),
        name=str(raw["name"]),
        savedAt=str(raw["savedAt"]),
        taught=raw["taught"],
        simplified=raw["simplified"],
    )


def iter_tracks(library_dir: Path | None = None) -> Iterator[SavedTrack]:
    d = library_dir or default_library_dir()
    if not d.is_dir():
        return
    for p in sorted(d.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            yield load_track_file(p)
        except (OSError, json.JSONDecodeError, KeyError):
            continue


def list_tracks(library_dir: Path | None = None) -> list[SavedTrack]:
    return list(iter_tracks(library_dir))


def main() -> None:
    p = argparse.ArgumentParser(description="UAV track library (GeoJSON on disk)")
    p.add_argument("--dir", type=Path, default=None, help="Library directory (default: ~/.uav_route/tracks)")
    sub = p.add_subparsers(dest="cmd", required=True)

    ls = sub.add_parser("list", help="List saved tracks")
    sub.add_parser("path", help="Print default library directory")

    args = p.parse_args()
    lib = args.dir
    if args.cmd == "path":
        print(default_library_dir() if lib is None else lib)
        return
    if args.cmd == "list":
        for t in list_tracks(lib):
            print(f"{t.savedAt}  {t.id}  {t.name}")
        return


if __name__ == "__main__":
    main()
