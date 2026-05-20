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

### Simplification HTTP API (`uav-sitl-bridge`, no SITL required)

The map page can call **Python-only** simplification on **`http://127.0.0.1:8765`**. You do **not** need a MAVLink connection for this — only the bridge process:

```bash
cd backend
source .venv/bin/activate   # if you use a venv
pip install -e .
PYTHONPATH=src python -m uav_route.sitl_bridge
```

- **`POST /api/simplify/mission`** — body: `{ "mission": [ { "lat", "lon", "alt", "command", "frame", ... }, ... ], "args": { "fast_return": true|false, "max_shortcut_deviation_m": 25, "remove_loiter": true, "min_separation_m": 2, "min_turn_deg": 6, "rdp_epsilon_m": 8 } }`
- With **`fast_return: true`**, the backend runs the end→start shortcut algorithm in **`uav_route/shortcut_return.py`**. With **`fast_return: false`**, it uses **`simplify_mission`** (RDP + filters).

### Python-only teach & repeat (no frontend logic)

Record taught route from SITL telemetry and save into track library:

```bash
uav-teach-repeat record --connection udp:127.0.0.1:14550 --seconds 120 --name sitl_path_1
```

Repeat the simplified route in GUIDED mode (reverse for return-to-home style):

```bash
uav-teach-repeat repeat --connection udp:127.0.0.1:14550 --track sitl_path_1 --reverse --rtl-end
```

Notes:
- `record` samples `GLOBAL_POSITION_INT` and stores taught + simplified GeoJSON via `track_library.py`.
- `repeat` sends GUIDED position targets waypoint-by-waypoint and waits for arrival radius.

