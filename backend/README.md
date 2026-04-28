## Backend (`uav-route`)

### Run the demo

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync
uv run uav-route-demo
```

Outputs GeoJSON to `../frontend/public/demo/`.

### Run offline tile cache server (MBTiles / QGC cache)

This serves tiles at:

- `http://127.0.0.1:8000/tiles/{z}/{x}/{y}.png`

Example with an **MBTiles** file:

```bash
TILE_DB_PATH="/absolute/path/to/your.mbtiles" TILE_MODE=mbtiles python3 -m uav_route.tiles.server
```

Example with a **QGC-like SQLite cache** (best-effort detection):

```bash
TILE_DB_PATH="/absolute/path/to/qgc-cache.sqlite" TILE_MODE=auto python3 -m uav_route.tiles.server
```

Then in the frontend, pick the basemap:

- `Local cache (offline) — http://127.0.0.1:8000`

