import type { FeatureCollection, Geometry } from "geojson";
import type { MissionItem } from "./qgcWpl";

export type AnyFC = FeatureCollection<Geometry, Record<string, unknown>>;

export function missionToGeoJson(items: MissionItem[], name: string): AnyFC {
  const lineCoords: Array<[number, number]> = [];
  const features: AnyFC["features"] = [];

  for (const it of items) {
    lineCoords.push([it.lon, it.lat]);
    features.push({
      type: "Feature",
      geometry: { type: "Point", coordinates: [it.lon, it.lat] },
      properties: { seq: it.seq, command: it.command, alt: it.alt },
    });
  }

  features.unshift({
    type: "Feature",
    geometry: { type: "LineString", coordinates: lineCoords },
    properties: { name, kind: "route" },
  });

  return {
    type: "FeatureCollection",
    features,
  };
}

