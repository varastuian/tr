# Http vs ws usage and project README
_Exported on 5/4/2026 at 06:28:10 EDT from Cursor (3.1.17)_

---

**User**

why instead of ws here the http is ussed?
write complete readme for quick start from connecting to sitl to use camera and save the uav route and library and then use it to come back to home with gps disalbe 
add option in next to disable sitl gps

---

**Cursor**

I’ll inspect the project to find where `http` is used instead of `ws`, then I’ll update the docs with a full quick-start flow (SITL, camera, route save/load, GPS-disabled return-home) and add a Next.js option to disable SITL GPS. I’m starting by locating the relevant files and config paths.

I found the `http` usage: the frontend talks to the Python bridge over REST (`/api/*`), while `ws` isn’t implemented there yet. Next I’ll add a UI control and backend endpoint to toggle SITL GPS disable, then I’ll rewrite the README into a complete quick-start flow with that new option included.

I confirmed there was no existing SITL GPS toggle logic, so I’m now adding a backend `/api/gps` control plus a frontend checkbox to set MAVLink SIM GPS params on/off. After that I’ll replace the root README with a full end-to-end quick-start that includes this new GPS-disable flow.

Changed the project to match your request in three parts:

- Explained and documented why `http` is used instead of `ws`.
- Wrote a full root `README` quick-start from SITL connect -> camera -> route save/library -> GPS-disabled return flow.
- Added a new Next.js UI option to disable SITL GPS, with backend support.

### What I changed

- Updated `backend/src/uav_route/sitl_bridge.py`
  - Added bridge state flag: `gps_disabled`.
  - Added new endpoint: `POST /api/gps` with payload:
    - `{ "disabled": true }` to disable SITL GPS
    - `{ "disabled": false }` to re-enable
  - Endpoint tries common ArduPilot params:
    - `SIM_GPS1_ENABLE`
    - `SIM_GPS2_ENABLE`
    - fallback `SIM_GPS_DISABLE`
- Updated `frontend/app/page.tsx`
  - Added `gps_disabled` field to bridge state type.
  - Added checkbox in `SITL Live`:
    - **Disable SITL GPS (SIM params)**
  - Checkbox calls `/api/gps` and reflects current backend value.
- Rewrote `README.md`
  - Complete workflow from setup to GPS-disabled return testing.
  - Includes a dedicated section: **Why HTTP is used instead of WebSocket**.
  - Documents the new GPS toggle behavior and expected limitations.

### Direct answer to your first question

`http` is used here because the bridge is implemented as a simple REST/polling server (`GET /api/state` + `POST /api/*`). It’s easier to debug and good enough for the current telemetry rate. There is no WebSocket server implemented in `sitl_bridge.py` right now.

### Validation

- Python bridge file syntax check passed.
- Frontend lint command could not run in this environment because `npm` is not installed in shell (`npm: command not found`).

If you want, I can also add a true WebSocket telemetry stream (`/ws/state`) and keep HTTP only for command actions.

---

**User**

no need 
in addition to what you did , add not using gps in ekf too
add option to record uav route instead of importing waypoint 
in addition to corrrent option
then after taught while generating lib goes for repeat phase

---

**Cursor**

I’ll extend the bridge and UI so you can (1) disable GPS usage in EKF, and (2) teach by recording the UAV path directly (without importing waypoints), then automatically prepare the saved track for repeat. I’m checking existing backend route-recording code first so I can wire it into the current app cleanly.

I found a clean integration point in the bridge, so I’m now adding EKF no-GPS parameter toggling plus teach-record start/stop endpoints that generate taught/simplified GeoJSON and save them to the track library automatically.

I’m now wiring the frontend for “Teach by recording” in parallel with import, and auto-switching to repeat/demo phase once recording is saved and simplified.

