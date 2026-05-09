"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef, useState } from "react";
import { parseQgcWpl110 } from "../lib/qgcWpl";
import { parseQgcPlan } from "../lib/qgcPlan";
import { missionToGeoJson } from "../lib/geojson";
import { simplifyMission } from "../lib/simplifyMission";
import type { AnyFC } from "../lib/geojson";
import {
  deleteTrack,
  getTrack,
  listSavedTracks,
  saveTrack,
} from "../lib/trackLibrary";

type BridgeSnap = {
  connected: boolean;
  armed: boolean;
  mode: string;
  lat: number;
  lon: number;
  alt_m: number;
  heading_deg: number;
  camera_zoom: number;
  gimbal_preset?: string;
  gps_disabled?: boolean;
  ekf_no_gps?: boolean;
  recording?: boolean;
  recording_points?: number;
  recording_name?: string;
  vbn_ready?: boolean;
  error: string;
};

const MapClient = dynamic(() => import("../components/MapClient"), {
  ssr: false,
});

export default function Home() {
  const [taughtFc, setTaughtFc] = useState<AnyFC | null>(null);
  const [simplifiedFc, setSimplifiedFc] = useState<AnyFC | null>(null);
  const [importErr, setImportErr] = useState<string | null>(null);
  const [importName, setImportName] = useState<string | null>(null);
  const [routeSource, setRouteSource] = useState<"import" | "record">("import");
  const [demo, setDemo] = useState<"taught_mission" | "complex_mission">("taught_mission");
  const [sitlConn, setSitlConn] = useState("udp:127.0.0.1:14550");
  const [uavMapZoom, setUavMapZoom] = useState(17);
  const [autoPanMap, setAutoPanMap] = useState(true);
  const [showCameraOverlay, setShowCameraOverlay] = useState(true);
  const [cameraSource, setCameraSource] = useState<"sim_tile" | "gazebo">("gazebo");
  const [cameraSimMode, setCameraSimMode] = useState<"nadir" | "forward">("nadir");
  const [gazeboCameraUrl, setGazeboCameraUrl] = useState(
    "http://127.0.0.1:8080/stream",
  );
  const [bridgeState, setBridgeState] = useState<BridgeSnap | null>(null);
  const [libBump, setLibBump] = useState(0);
  const [trackSaveName, setTrackSaveName] = useState("");
  const [libraryPickId, setLibraryPickId] = useState("");
  const [vbnSimEnabled, setVbnSimEnabled] = useState(false);
  const [vbnFrame, setVbnFrame] = useState<{
    lat: number;
    lon: number;
    heading: number;
  } | null>(null);
  const [overlayCamZoom, setOverlayCamZoom] = useState(20);
  const [gimbalRoll, setGimbalRoll] = useState(1500);
  const [gimbalPitch, setGimbalPitch] = useState(1500);
  const [gimbalYaw, setGimbalYaw] = useState(1500);
  const [recordName, setRecordName] = useState("sitl_taught_route");
  const [recordBusy, setRecordBusy] = useState(false);

  const savedTracks = useMemo(() => listSavedTracks(), [libBump]);

  const displayLive = useMemo((): BridgeSnap | null => {
    if (!vbnSimEnabled || !vbnFrame || !simplifiedFc) return bridgeState;
    const base: BridgeSnap =
      bridgeState ?? {
        connected: true,
        armed: false,
        mode: "VBN_SIM",
        lat: vbnFrame.lat,
        lon: vbnFrame.lon,
        alt_m: 25,
        heading_deg: vbnFrame.heading,
        camera_zoom: overlayCamZoom,
        gimbal_preset: "",
        error: "",
      };
    return {
      ...base,
      lat: vbnFrame.lat,
      lon: vbnFrame.lon,
      heading_deg: vbnFrame.heading,
      camera_zoom: bridgeState?.camera_zoom ?? overlayCamZoom,
      mode: bridgeState?.connected ? `${bridgeState.mode} · VBN→home` : "VBN→home (map)",
    };
  }, [vbnSimEnabled, vbnFrame, simplifiedFc, bridgeState, overlayCamZoom]);

  const mapEl = useMemo(
    () => (
      <MapClient
        taught={taughtFc}
        simplified={simplifiedFc}
        demoStem={demo}
        liveState={displayLive}
        cameraZoom={displayLive?.camera_zoom ?? overlayCamZoom}
        uavMapZoom={uavMapZoom}
        autoPan={autoPanMap}
        showCameraOverlay={showCameraOverlay}
        cameraSource={cameraSource}
        gazeboCameraUrl={gazeboCameraUrl}
        cameraSimMode={cameraSimMode}
      />
    ),
    [
      taughtFc,
      simplifiedFc,
      demo,
      displayLive,
      overlayCamZoom,
      uavMapZoom,
      autoPanMap,
      showCameraOverlay,
      cameraSource,
      gazeboCameraUrl,
      cameraSimMode,
    ],
  );

  useEffect(() => {
    const timer = setInterval(async () => {
      try {
        const res = await fetch("http://127.0.0.1:8765/api/state");
        if (!res.ok) return;
        const data = (await res.json()) as BridgeSnap;
        setBridgeState(data);
        if (typeof data.camera_zoom === "number") {
          setOverlayCamZoom(data.camera_zoom);
        }
      } catch {
        // bridge not running yet
      }
    }, 800);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!vbnSimEnabled || !simplifiedFc) {
      setVbnFrame(null);
      return;
    }
    let active = true;
    const init = async () => {
      try {
        const res = await fetch("http://127.0.0.1:8765/api/vbn/init", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ simplified_fc: simplifiedFc }),
        });
        if (!res.ok) return;
        const first = (await res.json()) as { lat: number; lon: number; heading_deg: number };
        if (!active) return;
        setVbnFrame({ lat: first.lat, lon: first.lon, heading: first.heading_deg });
      } catch {
        // backend not ready
      }
    };
    void init();
    const id = window.setInterval(async () => {
      try {
        const res = await fetch("http://127.0.0.1:8765/api/vbn/step", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ step: 0.11 }),
        });
        if (!res.ok) return;
        const data = (await res.json()) as { lat: number; lon: number; heading_deg: number };
        if (!active) return;
        setVbnFrame({ lat: data.lat, lon: data.lon, heading: data.heading_deg });
      } catch {
        // backend not ready
      }
    }, 220);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [vbnSimEnabled, simplifiedFc]);

  const sendBridge = async (path: string, payload: Record<string, unknown>) => {
    await fetch(`http://127.0.0.1:8765${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  };

  useEffect(() => {
    const preset = cameraSimMode === "nadir" ? "nadir" : "forward";
    void fetch("http://127.0.0.1:8765/api/gimbal", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ preset }),
    });
  }, [cameraSimMode]);

  return (
    <div className="page">
      <div className="panel">
        <div className="h1">UAV VBN based Teach &amp; Repeat with Route Simplifier</div>
        <div className="small">
          This view overlays the taught route (raw mission) vs a simplified mission
          (loiter removed + redundant waypoints dropped + RDP).
        </div>

        <div className="section">
          <div className="row">
            <span className="pill">Data source</span>
            <span className="small">
              {importName ? `Imported: ${importName}` : "/public/demo/*.geojson"}
            </span>
          </div>
          <div className="row" style={{ marginTop: 8 }}>
            <span className="small">Teach source</span>
            <select
              value={routeSource}
              onChange={(e) => setRouteSource(e.target.value as "import" | "record")}
            >
              <option value="import">Import mission file</option>
              <option value="record">Record live UAV route</option>
            </select>
          </div>
          <div className="small" style={{ marginTop: 8 }}>
            Generate demo files from the backend:
            <pre style={{ margin: "8px 0 0 0", whiteSpace: "pre-wrap" }}>
              cd backend{"\n"}uv run uav-route-demo
            </pre>
          </div>
          {routeSource === "import" ? (
            <>
              <div className="row" style={{ marginTop: 10 }}>
                <span className="small">Demo route</span>
                <select
                  value={demo}
                  onChange={(e) => {
                    const v = e.target.value as "taught_mission" | "complex_mission";
                    setDemo(v);
                    setImportName(null);
                    setImportErr(null);
                    setTaughtFc(null);
                    setSimplifiedFc(null);
                  }}
                >
                  <option value="taught_mission">Simple demo</option>
                  <option value="complex_mission">Complex demo (loitering)</option>
                </select>
              </div>
              <div className="small" style={{ marginTop: 10 }}>
                Import a Mission Planner/QGC mission file (.waypoints / .plan):
                <div style={{ marginTop: 8 }}>
                  <input
                    type="file"
                    accept=".waypoints,.txt,.plan,application/json"
                    onChange={async (e) => {
                      const f = e.target.files?.[0];
                      if (!f) return;
                      setImportErr(null);
                      setImportName(f.name);
                      try {
                        const text = await f.text();
                        const taught =
                          f.name.toLowerCase().endsWith(".plan") || text.trim().startsWith("{")
                            ? parseQgcPlan(text)
                            : parseQgcWpl110(text);
                        const simplified = simplifyMission(taught, {
                          removeLoiter: true,
                          minSeparationM: 2,
                          minTurnDeg: 6,
                          rdpEpsilonM: 10,
                        });
                        setTaughtFc(missionToGeoJson(taught, "taught"));
                        setSimplifiedFc(missionToGeoJson(simplified, "simplified"));
                      } catch (err) {
                        setTaughtFc(null);
                        setSimplifiedFc(null);
                        setImportErr(err instanceof Error ? err.message : String(err));
                      }
                    }}
                  />
                </div>
                {importErr ? (
                  <div style={{ marginTop: 8, color: "#991b1b" }}>{importErr}</div>
                ) : null}
                <div className="small" style={{ marginTop: 8 }}>
                  Tip: In QGC, save a mission as <code>.waypoints</code>.
                </div>
              </div>
            </>
          ) : (
            <div className="small" style={{ marginTop: 10 }}>
              Teach by flying in SITL and recording <code>GLOBAL_POSITION_INT</code> route points:
              <div className="row" style={{ marginTop: 8, flexWrap: "wrap", gap: 8 }}>
                <input
                  value={recordName}
                  onChange={(e) => setRecordName(e.target.value)}
                  placeholder="Track name"
                  style={{ flex: "1 1 180px", minWidth: 140 }}
                />
                <button
                  type="button"
                  disabled={recordBusy || Boolean(bridgeState?.recording)}
                  onClick={async () => {
                    setRecordBusy(true);
                    try {
                      await sendBridge("/api/record/start", { name: recordName, min_sep_m: 1.5 });
                      setImportErr(null);
                    } catch (e) {
                      setImportErr(e instanceof Error ? e.message : String(e));
                    } finally {
                      setRecordBusy(false);
                    }
                  }}
                >
                  Start record
                </button>
                <button
                  type="button"
                  disabled={recordBusy || !bridgeState?.recording}
                  onClick={async () => {
                    setRecordBusy(true);
                    try {
                      const res = await fetch("http://127.0.0.1:8765/api/record/stop", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ min_turn_deg: 6, rdp_epsilon_m: 8 }),
                      });
                      const data = (await res.json()) as {
                        ok: boolean;
                        error?: string;
                        name?: string;
                        taught_fc?: AnyFC;
                        simplified_fc?: AnyFC;
                      };
                      if (!res.ok || !data.ok || !data.taught_fc || !data.simplified_fc) {
                        throw new Error(data.error || "failed to stop recording");
                      }
                      setTaughtFc(data.taught_fc);
                      setSimplifiedFc(data.simplified_fc);
                      setImportName(data.name ?? recordName);
                      setImportErr(null);
                      setLibBump((n) => n + 1);
                      // Move straight into repeat phase after teach+library generation.
                      setVbnSimEnabled(true);
                    } catch (e) {
                      setImportErr(e instanceof Error ? e.message : String(e));
                    } finally {
                      setRecordBusy(false);
                    }
                  }}
                >
                  Stop + save + repeat
                </button>
              </div>
              <div className="small" style={{ marginTop: 6 }}>
                Recording: {bridgeState?.recording ? "ON" : "OFF"} | points:{" "}
                {bridgeState?.recording_points ?? 0}
              </div>
              {importErr ? <div style={{ marginTop: 8, color: "#991b1b" }}>{importErr}</div> : null}
            </div>
          )}
          <div className="small" style={{ marginTop: 14 }}>
            <span className="pill">Track library</span> Save/load taught + simplified GeoJSON (feature map) in the
            browser.
          </div>
          <div className="row" style={{ marginTop: 8, flexWrap: "wrap", gap: 8 }}>
            <input
              value={trackSaveName}
              onChange={(e) => setTrackSaveName(e.target.value)}
              placeholder="Name for saved track"
              style={{ flex: "1 1 140px", minWidth: 120 }}
            />
            <button
              type="button"
              disabled={!taughtFc || !simplifiedFc}
              onClick={() => {
                if (!taughtFc || !simplifiedFc) return;
                saveTrack(trackSaveName, taughtFc, simplifiedFc);
                setTrackSaveName("");
                setLibBump((n) => n + 1);
              }}
            >
              Save
            </button>
          </div>
          <div className="row" style={{ marginTop: 8, flexWrap: "wrap", gap: 8 }}>
            <select
              value={libraryPickId}
              onChange={(e) => setLibraryPickId(e.target.value)}
              style={{ flex: "1 1 160px", minWidth: 140 }}
            >
              <option value="">Saved tracks…</option>
              {savedTracks.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
            <button
              type="button"
              disabled={!libraryPickId}
              onClick={() => {
                const t = getTrack(libraryPickId);
                if (!t) return;
                setTaughtFc(t.taught);
                setSimplifiedFc(t.simplified);
                setImportName(t.name);
                setImportErr(null);
                setDemo("taught_mission");
              }}
            >
              Load
            </button>
            <button
              type="button"
              disabled={!libraryPickId}
              onClick={() => {
                if (!libraryPickId) return;
                deleteTrack(libraryPickId);
                setLibraryPickId("");
                setLibBump((n) => n + 1);
              }}
            >
              Delete
            </button>
          </div>
        </div>

        <div className="section">
          <div className="small">
            Basemap can be switched from the map control (top-right). Includes:
            Esri satellite+labels, OpenStreetMap, and Google (unofficial) satellite/hybrid
            tiles (no key, may break anytime).
          </div>
        </div>

        <div className="section">
          <div className="h1" style={{ fontSize: 15, marginBottom: 8 }}>
            SITL Live
          </div>
          <div className="small">
            Bridge: <code>http://127.0.0.1:8765</code> status:{" "}
            {bridgeState?.connected ? "connected" : "disconnected"}
          </div>
          {bridgeState?.error ? (
            <div className="small" style={{ color: "#991b1b", marginTop: 6 }}>
              {bridgeState.error}
            </div>
          ) : null}
          <div className="row" style={{ marginTop: 8 }}>
            <input
              value={sitlConn}
              onChange={(e) => setSitlConn(e.target.value)}
              style={{ width: "100%" }}
            />
            <button onClick={() => sendBridge("/api/connect", { connection: sitlConn })}>
              Connect
            </button>
          </div>
          <div className="small" style={{ marginTop: 8 }}>
            Mode: {displayLive?.mode ?? "-"} | Alt: {displayLive?.alt_m?.toFixed(1) ?? "-"} m |
            Hdg: {displayLive?.heading_deg?.toFixed(0) ?? "-"}
          </div>
          <div className="small" style={{ marginTop: 4 }}>
            Gimbal RC (bridge): last preset{" "}
            <code>{bridgeState?.gimbal_preset || "—"}</code> — RC6 roll, RC7 pitch (low=nadir / high=up), RC8 yaw;
            see <code>uav_route/gimbal_rc.py</code>.
          </div>
          <div className="row" style={{ marginTop: 8 }}>
            <label className="small" style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
              <input
                type="checkbox"
                checked={vbnSimEnabled}
                disabled={!simplifiedFc}
                onChange={(e) => setVbnSimEnabled(e.target.checked)}
              />
              <span>
                VBN return demo (map-only): move the UAV icon along the <strong>simplified</strong> route reversed
                toward home, as if GPS were off and features guided the path. This does{" "}
                <strong>not</strong> change ArduPilot/Gazebo GPS; use MAV params + real vision for that. Combine with{" "}
                <strong>RTL</strong> for an actual SITL return when connected.
              </span>
            </label>
          </div>
          <div className="row" style={{ marginTop: 8 }}>
            <label className="small" style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
              <input
                type="checkbox"
                checked={Boolean(bridgeState?.gps_disabled)}
                onChange={(e) => void sendBridge("/api/gps", { disabled: e.target.checked })}
              />
              <span>
                Disable SITL GPS (SIM params): toggles <code>SIM_GPS1_ENABLE</code>/<code>SIM_GPS2_ENABLE</code> (and
                fallback <code>SIM_GPS_DISABLE</code> when present). Use this for GPS-denied tests, then run return
                logic from your saved track/feature map.
              </span>
            </label>
          </div>
          <div className="row" style={{ marginTop: 8 }}>
            <label className="small" style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
              <input
                type="checkbox"
                checked={Boolean(bridgeState?.ekf_no_gps)}
                onChange={(e) => void sendBridge("/api/ekf_gps", { disabled: e.target.checked })}
              />
              <span>
                Disable GPS usage in EKF: toggles EKF3 source params (<code>EK3_SRC1_POSXY</code>,{" "}
                <code>EK3_SRC1_VELXY</code>, <code>EK3_SRC1_POSZ</code>, <code>EK3_SRC1_VELZ</code>).
              </span>
            </label>
          </div>
          <div className="row" style={{ marginTop: 8, flexWrap: "wrap" }}>
            <button onClick={() => sendBridge("/api/command", { action: "arm" })}>Arm</button>
            <button onClick={() => sendBridge("/api/command", { action: "takeoff" })}>
              Takeoff
            </button>
            <button onClick={() => sendBridge("/api/command", { action: "guided" })}>
              GUIDED
            </button>
            <button onClick={() => sendBridge("/api/command", { action: "auto" })}>AUTO</button>
            <button onClick={() => sendBridge("/api/command", { action: "rtl" })}>RTL</button>
            <button onClick={() => sendBridge("/api/command", { action: "land" })}>LAND</button>
          </div>
          <div className="row" style={{ marginTop: 8 }}>
            <span className="small">UAV map zoom</span>
            <input
              type="range"
              min={13}
              max={21}
              value={uavMapZoom}
              onChange={(e) => setUavMapZoom(Number(e.target.value))}
            />
            <span className="small">{uavMapZoom}</span>
          </div>
          <div className="row" style={{ marginTop: 8 }}>
            <label className="small" style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <input
                type="checkbox"
                checked={autoPanMap}
                onChange={(e) => setAutoPanMap(e.target.checked)}
              />
              Auto-pan map with UAV
            </label>
          </div>
          <div className="row" style={{ marginTop: 8 }}>
            <label className="small" style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <input
                type="checkbox"
                checked={showCameraOverlay}
                onChange={(e) => setShowCameraOverlay(e.target.checked)}
              />
              Show camera overlay
            </label>
          </div>
          <div className="row" style={{ marginTop: 8 }}>
            <span className="small">Camera source</span>
            <select
              value={cameraSource}
              onChange={(e) => setCameraSource(e.target.value as "sim_tile" | "gazebo")}
            >
              <option value="sim_tile">Sim tile camera</option>
              <option value="gazebo">Gazebo camera</option>
            </select>
          </div>
          <div className="row" style={{ marginTop: 8 }}>
            <span className="small">Sim camera framing</span>
            <select
              value={cameraSimMode}
              onChange={(e) => setCameraSimMode(e.target.value as "nadir" | "forward")}
            >
              <option value="nadir">Nadir (top-down + crosshair)</option>
              <option value="forward">Forward cue (heading line)</option>
            </select>
          </div>
          <div className="small" style={{ marginTop: 4 }}>
            <strong>Sim tile</strong> inset uses nadir vs forward drawing; with SITL connected the same choice sends
            MAVLink <code>RC_CHANNELS_OVERRIDE</code> on RC6–RC8 (nadir → RC7 low / forward → RC7 high per your mount
            doc). Tune in <code>gimbal_rc.py</code> if endpoints differ.
          </div>
          <div className="small" style={{ marginTop: 8 }}>
            Manual camera angle (PWM): adjust roll/pitch/yaw then send custom RC override.
          </div>
          <div className="row" style={{ marginTop: 6 }}>
            <span className="small">Roll</span>
            <input
              type="range"
              min={1100}
              max={1900}
              value={gimbalRoll}
              onChange={(e) => setGimbalRoll(Number(e.target.value))}
            />
            <span className="small">{gimbalRoll}</span>
          </div>
          <div className="row" style={{ marginTop: 6 }}>
            <span className="small">Pitch</span>
            <input
              type="range"
              min={1100}
              max={1900}
              value={gimbalPitch}
              onChange={(e) => setGimbalPitch(Number(e.target.value))}
            />
            <span className="small">{gimbalPitch}</span>
          </div>
          <div className="row" style={{ marginTop: 6 }}>
            <span className="small">Yaw</span>
            <input
              type="range"
              min={1100}
              max={1900}
              value={gimbalYaw}
              onChange={(e) => setGimbalYaw(Number(e.target.value))}
            />
            <span className="small">{gimbalYaw}</span>
            <button
              onClick={() =>
                sendBridge("/api/gimbal", {
                  roll_pwm: gimbalRoll,
                  pitch_pwm: gimbalPitch,
                  yaw_pwm: gimbalYaw,
                })
              }
            >
              Send angle
            </button>
          </div>
          {cameraSource === "gazebo" ? (
            <div className="row" style={{ marginTop: 8 }}>
              <input
                value={gazeboCameraUrl}
                onChange={(e) => setGazeboCameraUrl(e.target.value)}
                style={{ width: "100%" }}
                placeholder="Gazebo camera URL"
              />
            </div>
          ) : null}
          <div className="row" style={{ marginTop: 8 }}>
            <span className="small">Camera zoom</span>
            <input
              type="range"
              min={15}
              max={22}
              value={displayLive?.camera_zoom ?? overlayCamZoom}
              onChange={(e) => {
                const z = Number(e.target.value);
                setOverlayCamZoom(z);
                void sendBridge("/api/camera", { zoom: z });
              }}
            />
          </div>
          <div className="small" style={{ marginTop: 6 }}>
            gz RTP UDP: run scripts/gazebo_mjpeg_bridge.py (python3-gi + GStreamer plugins); URL should end with
            /stream.
          </div>
        </div>
      </div>

      <div className="map">
        {mapEl}
      </div>
    </div>
  );
}

