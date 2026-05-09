# Gazebo: iris runway + aerial tile ground + visual feature map

This folder adds a **copy** of the ArduPilot **`iris_runway`** world with an extra **satellite-style ground plane**, plus scripts to build the texture. For **OpenCV feature maps** (ORB library along the flight path and “toward home” hints), use the Python package in `backend/src/uav_route/feature_map/` (see below).

## Legal / third-party

- **`worlds/iris_runway_ardupilot_upstream.sdf`** — verbatim reference from [ArduPilot/ardupilot_gazebo](https://github.com/ArduPilot/ardupilot_gazebo) (GPL-3.0).
- **`worlds/iris_runway_google_tile.sdf`** — same world + `model://tile_ground`.
- **Map tiles:** `scripts/build_aerial_mosaic.py` can use **unofficial Google** tile URLs (same pattern as many research tools) or **Esri World Imagery**. You must comply with the provider’s terms.

## 1. Build the aerial mosaic texture

```bash
cd sim
python3 -m venv .venv-mosaic
source .venv-mosaic/bin/activate
pip install -r requirements-mosaic.txt
python3 scripts/build_aerial_mosaic.py --zoom 17 --radius 2 --provider google_hybrid
# or: --provider esri_world
```

This writes:

- `models/tile_ground/materials/textures/mosaic.png`
- `mosaic_meta.json` (tile bounds / zoom)

Tune **`--zoom`** (detail) and **`--radius`** (coverage). Defaults center on the WGS84 origin in the world file (Canberra area).

## 2. Point Gazebo at this `sim` directory

```bash
export GZ_SIM_RESOURCE_PATH=/absolute/path/to/tr/sim:$GZ_SIM_RESOURCE_PATH
```

You still need **ArduPilot Gazebo** models on the path (`model://runway`, `model://iris_with_gimbal`) — install/configure [ardupilot_gazebo](https://github.com/ArduPilot/ardupilot_gazebo) as usual.

## 3. Launch the world

From the repo root (or `sim`):

```bash
gz sim -r /absolute/path/to/tr/sim/worlds/iris_runway_google_tile.sdf
```

The **`tile_ground`** plane is included at a slight **+Z** offset so the mosaic shows above the mathematical ground; adjust the `<pose>` of that `<include>` in `iris_runway_google_tile.sdf` if it fights the stock runway mesh.

## 4. OpenCV feature map (teach → library → hint toward home)

Install backend extras:

```bash
cd backend
source .venv/bin/activate
pip install -e ".[feature_map]"
```

**Build a library** from an ordered folder of down-looking images (e.g. exported camera frames while flying):

```bash
uav-feature-map ingest ./my_flight_frames/ --out-dir ./feature_maps/run1
```

**Query** a live frame against the map (greedy step toward keyframe index `0` = start / “home”):

```bash
uav-feature-map query ./feature_maps/run1 ./query.png --step 3
```

The JSON-like dict printed includes `target_index` (earlier along the path). This is a **research scaffold**: wire it to your estimator, GPS dropout tests, or logging; it is not a certified navigation filter.

### Hooking to gz camera / RTP

Export frames from your bridge (e.g. MJPEG or PNG sequence), or add a small subscriber in Python to your gz transport / OpenCV `VideoCapture` on the decoded stream, and call `FeatureMapLibrary.add_image` in a loop.

---

## Files

| Path | Purpose |
|------|---------|
| `worlds/iris_runway_google_tile.sdf` | Run this world |
| `worlds/iris_runway_ardupilot_upstream.sdf` | Pristine upstream copy |
| `models/tile_ground/` | Textured plane model |
| `scripts/build_aerial_mosaic.py` | Tile download + stitch |
