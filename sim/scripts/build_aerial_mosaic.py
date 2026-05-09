#!/usr/bin/env python3
"""
Download map tiles around the iris_runway WGS84 origin and stitch into
``sim/models/tile_ground/materials/textures/mosaic.png`` for the Gazebo plane.

Providers
---------
- ``google_hybrid`` — same unofficial pattern as the web UI (lyrs=y). **You** are
  responsible for complying with Google Maps terms of use.
- ``esri_world`` — Esri World Imagery (often usable for research; check their terms).

Example (matches world spherical_coordinates in iris_runway_google_tile.sdf):

  cd sim
  python3 scripts/build_aerial_mosaic.py --zoom 17 --radius 2 --provider google_hybrid

Requires: pip install -r requirements-mosaic.txt
"""

from __future__ import annotations

import argparse
import io
import json
import math
import time
from pathlib import Path

import requests
from PIL import Image

# Default = Canberra area from ArduPilot iris_runway world
DEFAULT_LAT = -35.363262
DEFAULT_LON = 149.165237

USER_AGENT = "uav-route-mosaic-builder/1.0 (research; contact: local)"


def latlon_to_tile(lat_deg: float, lon_deg: float, zoom: int) -> tuple[float, float]:
    lat_rad = math.radians(lat_deg)
    n = 2.0**zoom
    x = (lon_deg + 180.0) / 360.0 * n
    y = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n
    return x, y


def tile_url(provider: str, x: int, y: int, z: int, subdomain: int) -> str:
    s = subdomain % 4
    if provider == "google_hybrid":
        return f"https://mt{s}.google.com/vt/lyrs=y&x={x}&y={y}&z={z}"
    if provider == "google_sat":
        return f"https://mt{s}.google.com/vt/lyrs=s&x={x}&y={y}&z={z}"
    if provider == "esri_world":
        return (
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            f"World_Imagery/MapServer/tile/{z}/{y}/{x}"
        )
    raise ValueError(f"Unknown provider {provider}")


def fetch_tile(session: requests.Session, url: str) -> Image.Image:
    r = session.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content)).convert("RGB")


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    out_png = root / "models" / "tile_ground" / "materials" / "textures" / "mosaic.png"

    p = argparse.ArgumentParser(description="Stitch aerial tiles for Gazebo tile_ground model")
    p.add_argument("--lat", type=float, default=DEFAULT_LAT)
    p.add_argument("--lon", type=float, default=DEFAULT_LON)
    p.add_argument("--zoom", type=int, default=17, help="Tile zoom level (higher = more detail, smaller area)")
    p.add_argument(
        "--radius",
        type=int,
        default=2,
        help="How many tiles to extend in +/− x and y from center tile (e.g. 2 → 5×5 grid)",
    )
    p.add_argument(
        "--provider",
        choices=("google_hybrid", "google_sat", "esri_world"),
        default="google_hybrid",
    )
    p.add_argument("--sleep", type=float, default=0.15, help="Seconds between tile requests")
    args = p.parse_args()

    cx, cy = latlon_to_tile(args.lat, args.lon, args.zoom)
    xc, yc = int(cx), int(cy)

    tiles: list[list[Image.Image | None]] = []
    session = requests.Session()
    n = 0
    total = (2 * args.radius + 1) ** 2

    for row, dy in enumerate(range(-args.radius, args.radius + 1)):
        row_imgs: list[Image.Image | None] = []
        for col, dx in enumerate(range(-args.radius, args.radius + 1)):
            tx, ty = xc + dx, yc + dy
            url = tile_url(args.provider, tx, ty, args.zoom, col + row)
            n += 1
            print(f"[{n}/{total}] z={args.zoom} tile {tx},{ty}", flush=True)
            try:
                img = fetch_tile(session, url)
                row_imgs.append(img)
            except Exception as e:
                print(f"  failed: {e}", flush=True)
                row_imgs.append(None)
            time.sleep(args.sleep)
        tiles.append(row_imgs)

    # Use first good tile size
    tw = th = 256
    for row in tiles:
        for im in row:
            if im is not None:
                tw, th = im.size
                break
        else:
            continue
        break

    w, h = (2 * args.radius + 1) * tw, (2 * args.radius + 1) * th
    mosaic = Image.new("RGB", (w, h), (40, 40, 48))

    for row_idx, row in enumerate(tiles):
        for col_idx, im in enumerate(row):
            if im is None:
                continue
            if im.size != (tw, th):
                im = im.resize((tw, th), Image.Resampling.LANCZOS)
            mosaic.paste(im, (col_idx * tw, row_idx * th))

    out_png.parent.mkdir(parents=True, exist_ok=True)
    mosaic.save(out_png, "PNG", optimize=True)
    print(f"Wrote {out_png} ({mosaic.size[0]}×{mosaic.size[1]} px)", flush=True)
    meta = root / "models" / "tile_ground" / "materials" / "textures" / "mosaic_meta.json"
    meta.write_text(
        json.dumps(
            {
                "lat": args.lat,
                "lon": args.lon,
                "zoom": args.zoom,
                "radius": args.radius,
                "provider": args.provider,
                "tiles_x": (xc - args.radius, xc + args.radius),
                "tiles_y": (yc - args.radius, yc + args.radius),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
