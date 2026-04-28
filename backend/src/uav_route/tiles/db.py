from __future__ import annotations

import base64
import os
import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class TileSource:
    """
    SQLite-backed tile store.

    Supports:
    - MBTiles schema (tiles table, zoom_level, tile_column, tile_row, tile_data)
    - QGC-like caches that reuse similar columns (best-effort detection)

    Note: QGC and Mission Planner caches vary by version/platform. This class
    attempts a few known layouts and fails with a clear error otherwise.
    """

    db_path: str
    mode: str  # "mbtiles" | "qgc" | "auto"

    def __post_init__(self) -> None:
        if not os.path.exists(self.db_path):
            raise FileNotFoundError(self.db_path)

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    def get_png(self, z: int, x: int, y: int) -> bytes | None:
        """
        Return raw tile bytes (png/jpg) as stored. Caller sets content-type.

        Leaflet uses XYZ where Y increases downward.
        MBTiles stores TMS Y (flipped): tms_y = (2^z - 1) - y
        """
        if self.mode not in ("auto", "mbtiles", "qgc"):
            raise ValueError("mode must be auto|mbtiles|qgc")

        with self._connect() as con:
            detected = self.mode
            if detected == "auto":
                detected = _detect_mode(con)

            if detected == "mbtiles":
                return _get_mbtiles(con, z, x, y)
            if detected == "qgc":
                return _get_qgc_like(con, z, x, y)

        return None


def _detect_mode(con: sqlite3.Connection) -> str:
    tables = {r["name"] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "tiles" in tables:
        cols = _table_columns(con, "tiles")
        if {"zoom_level", "tile_column", "tile_row", "tile_data"}.issubset(cols):
            return "mbtiles"
    # QGC caches vary; we try a loose match: tiles table with z/x/y + data
    if "Tiles" in tables:
        cols = _table_columns(con, "Tiles")
        if {"z", "x", "y"}.issubset(cols) and ("image" in cols or "tile" in cols or "data" in cols):
            return "qgc"
    if "tiles" in tables:
        cols = _table_columns(con, "tiles")
        if {"z", "x", "y"}.issubset(cols) and ("image" in cols or "tile" in cols or "data" in cols):
            return "qgc"
    raise RuntimeError(
        "Unrecognized tile cache schema. Provide an MBTiles file or set TILE_MODE and adapt."
    )


def _table_columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}


def _get_mbtiles(con: sqlite3.Connection, z: int, x: int, y: int) -> bytes | None:
    tms_y = (1 << z) - 1 - y
    row = con.execute(
        "SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
        (z, x, tms_y),
    ).fetchone()
    if not row:
        return None
    data = row["tile_data"]
    return bytes(data)


def _get_qgc_like(con: sqlite3.Connection, z: int, x: int, y: int) -> bytes | None:
    """
    Best-effort support for caches with z/x/y columns.

    Some caches store raw bytes in `image`/`tile`/`data` columns.
    Some store base64 in text columns.
    """
    # Try common table names first.
    candidates: list[tuple[str, str]] = []
    tables = {r["name"] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in ("Tiles", "tiles"):
        if table in tables:
            cols = _table_columns(con, table)
            for blob_col in ("image", "tile", "data", "tile_data"):
                if blob_col in cols and {"z", "x", "y"}.issubset(cols):
                    candidates.append((table, blob_col))

    for table, col in candidates:
        row = con.execute(
            f"SELECT {col} AS d FROM {table} WHERE z=? AND x=? AND y=?",
            (z, x, y),
        ).fetchone()
        if not row:
            continue
        d = row["d"]
        if d is None:
            continue
        if isinstance(d, (bytes, bytearray, memoryview)):
            return bytes(d)
        if isinstance(d, str):
            # base64-encoded
            try:
                return base64.b64decode(d)
            except Exception:
                continue
    return None

