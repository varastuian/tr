"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  CircleMarker,
  GeoJSON,
  LayersControl,
  MapContainer,
  Marker,
  Pane,
  Polyline,
  TileLayer,
  Tooltip,
  useMap,
  useMapEvents,
} from "react-leaflet";
import type { Feature, FeatureCollection, GeoJsonObject, Geometry } from "geojson";
import L from "leaflet";
import type { DrawNode } from "../lib/drawRoute";

type AnyFC = FeatureCollection<Geometry, Record<string, unknown>>;

/** ~1.5e-5° lat ≈ 1.7 m — ignore smaller jitter from MAVLink so we do not re-pan every poll. */
const FOLLOW_EPS_DEG = 1.5e-5;

function isFeatureCollection(x: unknown): x is AnyFC {
  return (
    typeof x === "object" &&
    x !== null &&
    (x as { type?: unknown }).type === "FeatureCollection" &&
    Array.isArray((x as { features?: unknown }).features)
  );
}

async function loadGeoJson(path: string): Promise<AnyFC> {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to fetch ${path}: ${res.status}`);
  const data = (await res.json()) as unknown;
  if (!isFeatureCollection(data)) throw new Error(`Invalid GeoJSON at ${path}`);
  return data;
}

export default function MapClient({
  taught: taughtProp,
  simplified: simplifiedProp,
  demoStem = "taught_mission",
  liveState,
  cameraZoom = 20,
  uavMapZoom = 17,
  autoPan = false,
  showCameraOverlay = true,
  cameraSource = "gazebo",
  gazeboCameraUrl = "http://127.0.0.1:8080/stream",
  /** Sim tile overlay only: nadir = top-down map + crosshair; forward = heading cue line. */
  cameraSimMode = "forward",
  drawMode = false,
  drawNodes = [],
  drawSelectedIndex = null,
  placeLoiter = false,
  onDrawMapClick,
  onDrawSelect,
  onDrawMove,
  suppressDemo = false,
  fitRouteTrigger = 0,
  showLiveFollow = false,
  showDrawLayer = true,
  showTaughtLayer = true,
  showSimplifiedLayer = true,
}: {
  taught?: AnyFC | null;
  simplified?: AnyFC | null;
  demoStem?: "taught_mission" | "complex_mission";
  liveState?: {
    lat: number;
    lon: number;
    heading_deg: number;
    alt_m: number;
    mode: string;
    armed: boolean;
  } | null;
  cameraZoom?: number;
  uavMapZoom?: number;
  autoPan?: boolean;
  showCameraOverlay?: boolean;
  cameraSource?: "sim_tile" | "gazebo";
  gazeboCameraUrl?: string;
  cameraSimMode?: "nadir" | "forward";
  drawMode?: boolean;
  drawNodes?: DrawNode[];
  drawSelectedIndex?: number | null;
  placeLoiter?: boolean;
  onDrawMapClick?: (lat: number, lon: number) => void;
  onDrawSelect?: (index: number | null) => void;
  onDrawMove?: (index: number, lat: number, lon: number) => void;
  suppressDemo?: boolean;
  fitRouteTrigger?: number;
  showLiveFollow?: boolean;
  showDrawLayer?: boolean;
  showTaughtLayer?: boolean;
  showSimplifiedLayer?: boolean;
}) {
  const [taught, setTaught] = useState<AnyFC | null>(taughtProp ?? null);
  const [simplified, setSimplified] = useState<AnyFC | null>(simplifiedProp ?? null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    // If caller provides data, do not fetch demo.
    if (taughtProp || simplifiedProp || suppressDemo) {
      setTaught(taughtProp ?? null);
      setSimplified(simplifiedProp ?? null);
      return;
    }

    (async () => {
      try {
        const [a, b] = await Promise.all([
          loadGeoJson(`/demo/${demoStem}.taught.geojson`),
          loadGeoJson(`/demo/${demoStem}.simplified.geojson`),
        ]);
        setTaught(a);
        setSimplified(b);
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
      }
    })();
  }, [taughtProp, simplifiedProp, demoStem, suppressDemo]);

  function DrawClickCapture({
    enabled,
    onClick,
  }: {
    enabled: boolean;
    onClick?: (lat: number, lon: number) => void;
  }) {
    useMapEvents({
      click(e) {
        if (!enabled || !onClick) return;
        onClick(e.latlng.lat, e.latlng.lng);
      },
    });
    return null;
  }

  function FitRoute({
    trigger,
    taughtFc,
    simplifiedFc,
  }: {
    trigger: number;
    taughtFc: AnyFC | null;
    simplifiedFc: AnyFC | null;
  }) {
    const map = useMap();
    useEffect(() => {
      if (trigger === 0) return;
      const all = [taughtFc, simplifiedFc].filter(Boolean) as AnyFC[];
      const pts: Array<[number, number]> = [];
      for (const fc of all) {
        for (const f of fc.features) {
          const g = f.geometry;
          if (!g) continue;
          if (g.type === "Point") {
            const c = g.coordinates as number[];
            pts.push([c[1], c[0]]);
          } else if (g.type === "LineString") {
            for (const c of g.coordinates as number[][]) pts.push([c[1], c[0]]);
          }
        }
      }
      if (pts.length === 0) return;
      map.fitBounds(L.latLngBounds(pts), { padding: [28, 28], maxZoom: 18 });
    }, [trigger, map, taughtFc, simplifiedFc]);
    return null;
  }

  function makeNumberedDrawIcon(order: number, selected: boolean): L.DivIcon {
    const d = 30;
    const border = selected ? "#ea580c" : "#6d28d9";
    const fill = selected ? "#fef3c7" : "#ede9fe";
    const color = selected ? "#9a3412" : "#5b21b6";
    return L.divIcon({
      className: "draw-wp-marker",
      iconSize: [d, d],
      iconAnchor: [d / 2, d / 2],
      html: `<div class="draw-wp-marker-inner" style="
        width:${d}px;height:${d}px;border-radius:9999px;
        background:${fill};border:3px solid ${border};
        color:${color};font:700 13px/24px ui-sans-serif,system-ui,sans-serif;
        display:flex;align-items:center;justify-content:center;
        box-shadow:0 2px 6px rgba(0,0,0,0.22);
      ">${order}</div>`,
    });
  }

  const drawLine = useMemo<Array<[number, number]>>(
    () => drawNodes.map((n) => [n.lat, n.lon]),
    [drawNodes],
  );

  /** Draw visuals live outside LayersControl so an unchecked overlay cannot hide what you clicked. */
  const drawHint = drawMode ? (placeLoiter ? "Draw mode: loiter" : "Draw mode: waypoint") : null;

  const center = useMemo<[number, number]>(() => {
    const fc = taught ?? simplified;
    const coords =
      fc?.features
        ?.map((f) => {
          if (f.geometry?.type === "Point") {
            const c = f.geometry.coordinates as number[];
            return [c[1], c[0]] as [number, number];
          }
          return null;
        })
        .filter(Boolean) ?? [];
    return (coords[0] as [number, number] | undefined) ?? [37.4221, -122.0841];
  }, [taught, simplified]);

  function FollowUav({
    enabled,
    lat,
    lon,
    zoom,
  }: {
    enabled: boolean;
    lat: number;
    lon: number;
    zoom: number;
  }) {
    const map = useMap();
    const lastCenterRef = useRef<[number, number] | null>(null);
    const lastZoomRef = useRef<number | null>(null);

    useEffect(() => {
      if (!enabled) {
        lastCenterRef.current = null;
        lastZoomRef.current = null;
        return;
      }
      const prev = lastCenterRef.current;
      const moved =
        prev === null ||
        Math.abs(prev[0] - lat) > FOLLOW_EPS_DEG ||
        Math.abs(prev[1] - lon) > FOLLOW_EPS_DEG;
      const zoomChanged = lastZoomRef.current !== zoom;

      if (moved || zoomChanged) {
        // flyTo + poll jitter caused a visible “shake” every ~800ms; instant setView is stable.
        map.setView([lat, lon], zoom, { animate: false });
        lastCenterRef.current = [lat, lon];
        lastZoomRef.current = zoom;
      }
    }, [enabled, lat, lon, zoom, map]);
    return null;
  }

  return (
    <div style={{ height: "100%", width: "100%", position: "relative" }}>
      <MapContainer center={center} zoom={uavMapZoom} style={{ height: "100%", width: "100%" }}>
        {liveState ? (
          <FollowUav
            enabled={showLiveFollow || autoPan}
            lat={liveState.lat}
            lon={liveState.lon}
            zoom={uavMapZoom}
          />
        ) : null}
        <DrawClickCapture enabled={drawMode} onClick={onDrawMapClick} />
        <FitRoute trigger={fitRouteTrigger} taughtFc={taught} simplifiedFc={simplified} />
        <LayersControl position="topright">
          <LayersControl.BaseLayer name="Satellite + labels (Esri)">
            <>
              <TileLayer
                attribution='Tiles &copy; Esri'
                url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
              />
              <TileLayer
                attribution='Labels &copy; Esri'
                url="https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}"
                opacity={0.9}
              />
            </>
          </LayersControl.BaseLayer>

          <LayersControl.BaseLayer checked name="Google (unofficial) — Hybrid">
            <TileLayer
              attribution="Google (unofficial tile access)"
              url="https://{s}.google.com/vt/lyrs=y&x={x}&y={y}&z={z}"
              subdomains={["mt0", "mt1", "mt2", "mt3"]}
              maxZoom={21}
            />
          </LayersControl.BaseLayer>

          <LayersControl.BaseLayer name="Google (unofficial) — Satellite">
            <TileLayer
              attribution="Google (unofficial tile access)"
              url="https://{s}.google.com/vt/lyrs=s&x={x}&y={y}&z={z}"
              subdomains={["mt0", "mt1", "mt2", "mt3"]}
              maxZoom={21}
            />
          </LayersControl.BaseLayer>

          <LayersControl.BaseLayer name="OpenStreetMap">
            <TileLayer
              attribution='&copy; OpenStreetMap contributors'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
          </LayersControl.BaseLayer>

          <LayersControl.BaseLayer name="Local cache (offline) — http://127.0.0.1:8000">
            <TileLayer
              attribution="Local cache (uav-tiles)"
              url="http://127.0.0.1:8000/tiles/{z}/{x}/{y}.png"
              maxZoom={21}
            />
          </LayersControl.BaseLayer>
        </LayersControl>

        {showTaughtLayer && taught ? (
          <GeoJSON
            key={`taught-${fitRouteTrigger}-${taught.features?.length ?? 0}`}
            data={taught as unknown as GeoJsonObject}
            style={(f) => {
              const kind = (f as Feature).properties?.kind;
              if (kind === "route") return { color: "#2563eb", weight: 4, opacity: 0.9 };
              return {};
            }}
            pointToLayer={(feature, latlng) => {
              const p = feature.properties as Record<string, unknown>;
              const seq = typeof p.seq === "number" ? p.seq : undefined;
              const cmd = typeof p.command === "number" ? p.command : undefined;
              return L.circleMarker(latlng, {
                radius: 5,
                color: "#1d4ed8",
                weight: 2,
                fillOpacity: 0.2,
              }).bindTooltip(`taught seq=${seq} cmd=${cmd}`, {
                direction: "top",
                offset: L.point(0, -6),
                opacity: 0.95,
              });
            }}
          />
        ) : null}

        {showSimplifiedLayer && simplified ? (
          <GeoJSON
            key={`simplified-${fitRouteTrigger}-${simplified.features?.length ?? 0}`}
            data={simplified as unknown as GeoJsonObject}
            style={(f) => {
              const kind = (f as Feature).properties?.kind;
              if (kind === "route") return { color: "#16a34a", weight: 4, opacity: 0.9 };
              return {};
            }}
            pointToLayer={(feature, latlng) => {
              const p = feature.properties as Record<string, unknown>;
              const seq = typeof p.seq === "number" ? p.seq : undefined;
              const cmd = typeof p.command === "number" ? p.command : undefined;
              return L.circleMarker(latlng, {
                radius: 4,
                color: "#15803d",
                weight: 2,
                fillOpacity: 0.2,
              }).bindTooltip(`simplified seq=${seq} cmd=${cmd}`, {
                direction: "top",
                offset: L.point(0, -6),
                opacity: 0.95,
              });
            }}
          />
        ) : null}

        {liveState ? (
          <>
            <CircleMarker
              center={[liveState.lat, liveState.lon]}
              radius={7}
              pathOptions={{ color: liveState.armed ? "#ef4444" : "#f59e0b", weight: 3 }}
            >
              <Tooltip direction="top" opacity={0.95}>
                UAV {liveState.mode} alt={liveState.alt_m.toFixed(1)}m hdg=
                {liveState.heading_deg.toFixed(0)}
              </Tooltip>
            </CircleMarker>
            <Polyline
              positions={[
                [liveState.lat, liveState.lon],
                [
                  liveState.lat + 0.00018 * Math.cos((liveState.heading_deg * Math.PI) / 180),
                  liveState.lon + 0.00018 * Math.sin((liveState.heading_deg * Math.PI) / 180),
                ],
              ]}
              pathOptions={{ color: "#f97316", weight: 3 }}
            />
          </>
        ) : null}

        {showDrawLayer ? (
        <Pane name="draw_always" style={{ zIndex: 600 }}>
          {drawLine.length >= 2 ? (
            <Polyline positions={drawLine} pathOptions={{ color: "#7c3aed", weight: 4, opacity: 0.95 }} />
          ) : null}
          {drawNodes.map((node, idx) => (
            <Marker
              key={`${idx}-${node.kind}`}
              position={[node.lat, node.lon]}
              draggable
              icon={makeNumberedDrawIcon(idx + 1, drawSelectedIndex === idx)}
              eventHandlers={{
                click: () => onDrawSelect?.(idx),
                dragend: (e) => {
                  const latlng = (e.target as L.Marker).getLatLng();
                  onDrawMove?.(idx, latlng.lat, latlng.lng);
                },
              }}
            >
              <Tooltip direction="top" opacity={0.95}>
                {node.kind} #{idx + 1}
                {node.kind === "loiter" ? ` r=${node.radiusM}m` : ""}
              </Tooltip>
            </Marker>
          ))}
        </Pane>
        ) : null}

        {err ? (
          <Pane name="error" style={{ zIndex: 1000 }}>
            <div
              style={{
                position: "absolute",
                bottom: 16,
                left: 16,
                right: 16,
                padding: 12,
                background: "rgba(255,255,255,0.95)",
                border: "1px solid #fecaca",
                borderRadius: 12,
                color: "#991b1b",
                fontSize: 12,
              }}
            >
              {err}
            </div>
          </Pane>
        ) : null}
      </MapContainer>

      {liveState && showCameraOverlay ? (
        <div
          style={{
            position: "absolute",
            right: 14,
            bottom: 14,
            width: 280,
            height: 200,
            borderRadius: 10,
            overflow: "hidden",
            border: "1px solid #cbd5e1",
            background: "#fff",
            zIndex: 1200,
          }}
        >
          <div
            style={{
              position: "absolute",
              top: 6,
              left: 8,
              zIndex: 1400,
              fontSize: 11,
              background: "rgba(255,255,255,0.85)",
              borderRadius: 6,
              padding: "2px 6px",
            }}
          >
            {cameraSource === "gazebo"
              ? "Gazebo camera view"
              : cameraSimMode === "nadir"
                ? `Nadir sim (tile) z=${cameraZoom}`
                : `Forward cue sim (tile) z=${cameraZoom}`}
          </div>
          {cameraSource === "gazebo" ? (
            <iframe
              src={gazeboCameraUrl}
              title="Gazebo camera stream"
              style={{ width: "100%", height: "100%", border: "none" }}
              loading="lazy"
            />
          ) : (
            <MapContainer
              center={[liveState.lat, liveState.lon]}
              zoom={cameraZoom}
              style={{ height: "100%", width: "100%" }}
              zoomControl={false}
              dragging={false}
              scrollWheelZoom={false}
              doubleClickZoom={false}
              boxZoom={false}
              keyboard={false}
              attributionControl={false}
            >
              <TileLayer url="http://127.0.0.1:8000/tiles/{z}/{x}/{y}.png" />
              <CircleMarker
                center={[liveState.lat, liveState.lon]}
                radius={5}
                pathOptions={{ color: "#ef4444", weight: 2 }}
              />
              {cameraSimMode === "nadir" ? (
                <>
                  <Polyline
                    positions={[
                      [liveState.lat - 0.00012, liveState.lon],
                      [liveState.lat + 0.00012, liveState.lon],
                    ]}
                    pathOptions={{ color: "#64748b", weight: 1, opacity: 0.9 }}
                  />
                  <Polyline
                    positions={[
                      [liveState.lat, liveState.lon - 0.00012],
                      [liveState.lat, liveState.lon + 0.00012],
                    ]}
                    pathOptions={{ color: "#64748b", weight: 1, opacity: 0.9 }}
                  />
                </>
              ) : (
                <Polyline
                  positions={[
                    [liveState.lat, liveState.lon],
                    [
                      liveState.lat + 0.00018 * Math.cos((liveState.heading_deg * Math.PI) / 180),
                      liveState.lon + 0.00018 * Math.sin((liveState.heading_deg * Math.PI) / 180),
                    ],
                  ]}
                  pathOptions={{ color: "#f97316", weight: 3 }}
                />
              )}
            </MapContainer>
          )}
        </div>
      ) : null}
      {drawHint ? (
        <div
          style={{
            position: "absolute",
            left: 14,
            top: 14,
            zIndex: 1300,
            background: "rgba(255,255,255,0.9)",
            border: "1px solid #ddd6fe",
            color: "#5b21b6",
            borderRadius: 8,
            padding: "4px 8px",
            fontSize: 12,
          }}
        >
          {drawHint}
        </div>
      ) : null}
    </div>
  );
}

