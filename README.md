# UAV Teach & Repeat - Quick Start and Full Workflow

This project gives you:

- A Next.js UI to view taught vs simplified routes.
- A Python SITL bridge (`/api/*`) to control ArduPilot and read telemetry.
- Camera overlay support (Gazebo stream or simulated map camera).
- Route library support (browser + Python disk library).
- A VBN-style return demo on the map, plus a new UI option to disable SITL GPS params.

## Why HTTP is used instead of WebSocket

The frontend currently communicates with the bridge using HTTP polling and POST endpoints:

- `GET /api/state` every ~800ms for telemetry/state.
- `POST /api/*` for commands (`connect`, `command`, `camera`, `gimbal`, `gps`, `vbn/*`).

This was chosen because it is simple, debuggable (easy `curl`), and enough for current update rates.
There is no WebSocket server implemented in `sitl_bridge.py` yet.

## 1) Requirements

- Node.js 18+ and npm
- Python 3.10+
- Optional but recommended:
  - ArduPilot SITL + MAVLink output (for example `udp:127.0.0.1:14550`)
  - Gazebo (`gz`) for camera simulation
  - GStreamer runtime (`python3-gi`, plugins) for RTP -> MJPEG bridge

## 2) Install

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Frontend

```bash
cd frontend
npm install
```

## 3) Start the app

Use 3 terminals.

### Terminal A - Frontend

```bash
cd frontend
npm run dev
```

Open `http://localhost:3000`.

### Terminal B - SITL bridge

```bash
cd backend
source .venv/bin/activate
PYTHONPATH=src python -m uav_route.sitl_bridge
```

Bridge default listen URL: `http://127.0.0.1:8765`.

### Terminal C - SITL (example)

Start your preferred ArduPilot SITL setup so MAVLink is available at `udp:127.0.0.1:14550`.

## 4) Connect SITL from the UI

In `SITL Live` panel:

1. Keep connection string as `udp:127.0.0.1:14550` (or your own).
2. Click `Connect`.
3. Verify mode/altitude/heading update.
4. Use `Arm`, `Takeoff`, `GUIDED`, `AUTO`, `RTL`, `LAND` as needed.

## 5) Camera setup

### Option A: Gazebo camera (real stream in overlay)

1. Enable camera streaming in Gazebo topic.
2. Run MJPEG bridge:

```bash
cd /path/to/tr
python3 scripts/gazebo_mjpeg_bridge.py --udp-port 5600
```

3. In UI:
   - Camera source = `Gazebo camera`
   - Stream URL = `http://127.0.0.1:8080/stream`

Because browser cannot consume raw RTP directly, the bridge converts RTP/UDP to HTTP MJPEG.

### Option B: Sim tile camera

In UI, select `Sim tile camera`.
This renders an inset map around UAV location (no Gazebo video needed).

## 6) Teach route, simplify, and save

1. In `Data source`, import mission file:
   - `.waypoints` / `.txt` (Mission Planner style), or
   - `.plan` (QGroundControl JSON).
2. App generates:
   - `taught` route
   - `simplified` route (loiter removal + thinning + RDP)
3. In `Track library`, set a name and click `Save`.
4. Later use `Load` or `Delete`.

Browser track library is stored in localStorage.

## 7) Python track library (disk)

Use backend CLI:

```bash
cd backend
source .venv/bin/activate
uav-track-lib path
uav-track-lib list
```

Default folder is `~/.uav_route/tracks` (override with `UAV_TRACK_LIBRARY_DIR`).

## 8) Disable SITL GPS (new option)

In `SITL Live`, enable:

- `Disable SITL GPS (SIM params)`

This calls `POST /api/gps` and attempts:

- `SIM_GPS1_ENABLE=0`
- `SIM_GPS2_ENABLE=0`
- fallback `SIM_GPS_DISABLE=1` if supported

When unchecked it restores:

- `SIM_GPS1_ENABLE=1`
- `SIM_GPS2_ENABLE=1`
- fallback `SIM_GPS_DISABLE=0`

Note: available params depend on your ArduPilot build.

## 9) Come back home with GPS disabled

There are 2 related flows:

1. **Real autopilot return mode**: use `RTL`/`LAND` command buttons (depends on your estimator/nav configuration; pure GPS-off RTL may not be viable unless you have alternative aiding).
2. **VBN return demo (map-only)**: enable `VBN return demo (map-only)` after loading a simplified route. This replays the UAV marker from route end toward home as a visual feature-guided return concept.

Recommended test sequence:

1. Connect SITL and take off.
2. Import mission and save simplified route to library.
3. Toggle `Disable SITL GPS`.
4. Enable `VBN return demo (map-only)` to validate route-to-home logic in UI.
5. If your nav stack supports it, test `RTL`/guided return behavior separately.

## 10) Optional offline tile server

```bash
cd backend
source .venv/bin/activate
TILE_DB_PATH="/absolute/path/to/cache.sqlite" TILE_MODE=auto PYTHONPATH=src python -m uav_route.tiles.server
```

Then choose base layer `Local cache (offline) - http://127.0.0.1:8000`.

## 11) Troubleshooting

- Bridge says disconnected:
  - verify SITL MAVLink output is on expected UDP endpoint
  - click `Connect` again after SITL heartbeat starts
- `pymavlink` import error:
  - run bridge from same backend venv used for `pip install -e .`
- Gazebo camera panel blank:
  - check MJPEG bridge is running and URL ends with `/stream`
- GPS toggle has no effect:
  - your SITL build may use different SIM params; inspect available params in MAVProxy/Mission Planner

## 12) Main paths

- `frontend/app/page.tsx` - controls UI actions and bridge API calls
- `frontend/components/MapClient.tsx` - map rendering and camera overlay
- `backend/src/uav_route/sitl_bridge.py` - HTTP bridge, commands, telemetry, VBN playback, GPS toggle
- `backend/src/uav_route/track_library.py` - disk track persistence
- `scripts/gazebo_mjpeg_bridge.py` - RTP to HTTP MJPEG bridge
