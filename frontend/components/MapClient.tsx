"use client";

import { useEffect, useMemo, useState } from "react";
import {
  CircleMarker,
  GeoJSON,
  LayersControl,
  MapContainer,
  Pane,
  Polyline,
  TileLayer,
  Tooltip,
  useMap,
} from "react-leaflet";
import type { Feature, FeatureCollection, GeoJsonObject, Geometry } from "geojson";
import L from "leaflet";

type AnyFC = FeatureCollection<Geometry, Record<string, unknown>>;

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
  cameraSource = "sim_tile",
  gazeboCameraUrl = "http://127.0.0.1:8080/stream?topic=/camera/image_raw",
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
}) {
  const [taught, setTaught] = useState<AnyFC | null>(taughtProp ?? null);
  const [simplified, setSimplified] = useState<AnyFC | null>(simplifiedProp ?? null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    // If caller provides data, do not fetch demo.
    if (taughtProp || simplifiedProp) {
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
  }, [taughtProp, simplifiedProp, demoStem]);

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
    useEffect(() => {
      if (!enabled) return;
      map.flyTo([lat, lon], zoom, { duration: 0.35 });
    }, [enabled, lat, lon, zoom, map]);
    return null;
  }

  return (
    <div style={{ height: "100%", width: "100%", position: "relative" }}>
      <MapContainer center={center} zoom={uavMapZoom} style={{ height: "100%", width: "100%" }}>
        {liveState ? (
          <FollowUav
            enabled={autoPan}
            lat={liveState.lat}
            lon={liveState.lon}
            zoom={uavMapZoom}
          />
        ) : null}
        <LayersControl position="topright">
          <LayersControl.BaseLayer checked name="Satellite + labels (Esri)">
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

          <LayersControl.BaseLayer name="Google (unofficial) — Hybrid">
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

        <Pane name="taught" style={{ zIndex: 400 }}>
          {taught ? (
            <GeoJSON
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
        </Pane>

        <Pane name="simplified" style={{ zIndex: 450 }}>
          {simplified ? (
            <GeoJSON
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
        </Pane>

        {liveState ? (
          <Pane name="uav" style={{ zIndex: 700 }}>
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
              : `Sim camera view (tile) z=${cameraZoom}`}
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
            </MapContainer>
          )}
        </div>
      ) : null}
    </div>
  );
}

