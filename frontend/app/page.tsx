 "use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";
import { parseQgcWpl110 } from "../lib/qgcWpl";
import { parseQgcPlan } from "../lib/qgcPlan";
import { missionToGeoJson } from "../lib/geojson";
import { simplifyMission } from "../lib/simplifyMission";
import type { AnyFC } from "../lib/geojson";

const MapClient = dynamic(() => import("../components/MapClient"), {
  ssr: false,
});

export default function Home() {
  const [taughtFc, setTaughtFc] = useState<AnyFC | null>(null);
  const [simplifiedFc, setSimplifiedFc] = useState<AnyFC | null>(null);
  const [importErr, setImportErr] = useState<string | null>(null);
  const [importName, setImportName] = useState<string | null>(null);
  const [demo, setDemo] = useState<"taught_mission" | "complex_mission">("taught_mission");
  const [sitlConn, setSitlConn] = useState("udp:127.0.0.1:14550");
  const [uavMapZoom, setUavMapZoom] = useState(17);
  const [autoPanMap, setAutoPanMap] = useState(true);
  const [showCameraOverlay, setShowCameraOverlay] = useState(true);
  const [cameraSource, setCameraSource] = useState<"sim_tile" | "gazebo">("sim_tile");
  const [gazeboCameraUrl, setGazeboCameraUrl] = useState(
    "http://127.0.0.1:8080/stream?topic=/camera/image_raw",
  );
  const [bridgeState, setBridgeState] = useState<{
    connected: boolean;
    armed: boolean;
    mode: string;
    lat: number;
    lon: number;
    alt_m: number;
    heading_deg: number;
    camera_zoom: number;
    error: string;
  } | null>(null);

  const mapEl = useMemo(
    () => (
      <MapClient
        taught={taughtFc}
        simplified={simplifiedFc}
        demoStem={demo}
        liveState={bridgeState}
        cameraZoom={bridgeState?.camera_zoom ?? 20}
        uavMapZoom={uavMapZoom}
        autoPan={autoPanMap}
        showCameraOverlay={showCameraOverlay}
        cameraSource={cameraSource}
        gazeboCameraUrl={gazeboCameraUrl}
      />
    ),
    [
      taughtFc,
      simplifiedFc,
      demo,
      bridgeState,
      uavMapZoom,
      autoPanMap,
      showCameraOverlay,
      cameraSource,
      gazeboCameraUrl,
    ],
  );

  useEffect(() => {
    const timer = setInterval(async () => {
      try {
        const res = await fetch("http://127.0.0.1:8765/api/state");
        if (!res.ok) return;
        const data = await res.json();
        setBridgeState(data);
      } catch {
        // bridge not running yet
      }
    }, 800);
    return () => clearInterval(timer);
  }, []);

  const sendBridge = async (path: string, payload: Record<string, unknown>) => {
    await fetch(`http://127.0.0.1:8765${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  };

  return (
    <div className="page">
      <div className="panel">
        <div className="h1">UAV Teach &amp; Repeat — Route Simplifier</div>
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
          <div className="small" style={{ marginTop: 8 }}>
            Generate demo files from the backend:
            <pre style={{ margin: "8px 0 0 0", whiteSpace: "pre-wrap" }}>
              cd backend{"\n"}uv run uav-route-demo
            </pre>
          </div>
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
            Mode: {bridgeState?.mode ?? "-"} | Alt: {bridgeState?.alt_m?.toFixed(1) ?? "-"} m |
            Hdg: {bridgeState?.heading_deg?.toFixed(0) ?? "-"}
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
              value={bridgeState?.camera_zoom ?? 20}
              onChange={(e) => sendBridge("/api/camera", { zoom: Number(e.target.value) })}
            />
          </div>
          <div className="small" style={{ marginTop: 6 }}>
            Camera view can be shown as sim tile imagery or a Gazebo stream URL.
          </div>
        </div>
      </div>

      <div className="map">
        {mapEl}
      </div>
    </div>
  );
}

