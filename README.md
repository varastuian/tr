## UAV Teach & Repeat (Vision-ready) — Route Simplifier + Map UI

This repo contains:

- **Python backend** (`backend/`): load a taught route (mission + optional track), **remove loitering + redundant waypoints**, run polyline simplification (RDP), and export **GeoJSON** for visualization.
- **Next.js frontend** (`frontend/`): **Leaflet** map UI that overlays **taught vs simplified** routes on a **satellite + labels** basemap.
- Optional: **Google Maps Satellite/Hybrid** view (official JS API).

### Quick start

#### 1) Backend (Python)

Install `uv` (recommended) and run the demo generator:

```bash
cd backend
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync
uv run python -m uav_route.demo.generate_demo
```

This writes GeoJSON outputs into `frontend/public/demo/`.

#### 2) Frontend (Next.js)

```bash
cd frontend
npm install
npm run dev
```

If you want the **Google Satellite/Hybrid** view, add an API key:

```bash
cd frontend
printf "NEXT_PUBLIC_GOOGLE_MAPS_API_KEY=YOUR_KEY_HERE\n" > .env.local
```

Open the dev server URL and you’ll see:

- taught mission polyline + waypoints
- simplified mission polyline + waypoints

### Inputs / outputs

- **Input (demo)**: `backend/sample_data/taught_mission.json`
- **Output (demo)**: `frontend/public/demo/*.geojson`

### ArduPilot integration notes

The backend is structured so you can later add a live MAVLink source (e.g. via `pymavlink`) to pull:

- mission items from the vehicle
- live GPS track for “teach”

The simplifier already understands loiter-style commands and keeps non-navigation commands intact.

### SITL live telemetry + commands + camera-view simulation

1) Start ArduPilot SITL (example: UDP out on `14550`).

2) Start the bridge server:

```bash
cd backend
source .venv/bin/activate  # or your existing venv
pip install pymavlink
PYTHONPATH=src python3 -m uav_route.sitl_bridge
```

3) Start frontend (`npm run dev`) and use **SITL Live** panel:

- connect string: `udp:127.0.0.1:14550`
- commands: Arm / Takeoff / GUIDED / AUTO / RTL / LAND
- live UAV marker and heading are shown on map
- mini-map overlay simulates camera tile view around UAV position

### Offline tiles (read QGC / Mission Planner cache)

If you have an **MBTiles** file or a **QGroundControl/Mission Planner tile cache SQLite DB**, you can serve it locally and use it as a basemap in Leaflet.

1) Start the tile server:

```bash
cd backend
TILE_DB_PATH="/absolute/path/to/cache.sqlite" TILE_MODE=auto PYTHONPATH=src python3 -m uav_route.tiles.server
```

2) In the web UI, open the layers control (top-right) and select:

- **Local cache (offline) — http://127.0.0.1:8000**

Notes:
- Cache schemas vary by version/platform; `TILE_MODE=auto` tries common layouts.
- If you have a standard `.mbtiles`, use `TILE_MODE=mbtiles`.

