import type { AnyFC } from "./geojson";

/** GeoJSON LineString coords are [lon, lat]. Returns vertices as [lat, lon]. */
export function simplifiedRouteLatLon(fc: AnyFC | null): [number, number][] | null {
  if (!fc) return null;
  const line = fc.features.find((f) => f.geometry?.type === "LineString");
  if (!line || line.geometry?.type !== "LineString") return null;
  const coords = line.geometry.coordinates as [number, number][];
  if (coords.length < 2) return null;
  return coords.map(([lon, lat]) => [lat, lon] as [number, number]);
}

/** Bearing deg 0=north from (lat1,lon1) to (lat2,lon2). */
export function bearingDeg(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const φ1 = (lat1 * Math.PI) / 180;
  const φ2 = (lat2 * Math.PI) / 180;
  const Δλ = ((lon2 - lon1) * Math.PI) / 180;
  const y = Math.sin(Δλ) * Math.cos(φ2);
  const x = Math.cos(φ1) * Math.sin(φ2) - Math.sin(φ1) * Math.cos(φ2) * Math.cos(Δλ);
  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
}

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

export type VbnPlayback = {
  /** Reversed route: mission end → home (first wp). */
  points: [number, number][];
  segIndex: number;
  /** 0..1 along segment segIndex → segIndex+1 */
  alpha: number;
};

export function initVbnPlayback(fc: AnyFC | null): VbnPlayback | null {
  const fwd = simplifiedRouteLatLon(fc);
  if (!fwd || fwd.length < 2) return null;
  const points = [...fwd].reverse();
  return { points, segIndex: 0, alpha: 0 };
}

/** Step toward home; `step` is fraction of current segment per tick (~0.08 @ 5Hz ≈ smooth). */
export function stepVbnPlayback(
  p: VbnPlayback,
  step: number,
): { playback: VbnPlayback; lat: number; lon: number; heading_deg: number } {
  const { points } = p;
  let { segIndex, alpha } = p;

  if (segIndex >= points.length - 1) {
    const [lat, lon] = points[points.length - 1];
    return {
      playback: { points, segIndex, alpha: 1 },
      lat,
      lon,
      heading_deg: 0,
    };
  }

  alpha += step;
  while (alpha >= 1 && segIndex < points.length - 1) {
    alpha -= 1;
    segIndex += 1;
  }

  if (segIndex >= points.length - 1) {
    const [lat, lon] = points[points.length - 1];
    return {
      playback: { points, segIndex: points.length - 1, alpha: 1 },
      lat,
      lon,
      heading_deg: 0,
    };
  }

  const [la0, lo0] = points[segIndex];
  const [la1, lo1] = points[segIndex + 1];
  const lat = lerp(la0, la1, alpha);
  const lon = lerp(lo0, lo1, alpha);
  const heading_deg = bearingDeg(lat, lon, la1, lo1);

  return {
    playback: { points, segIndex, alpha },
    lat,
    lon,
    heading_deg,
  };
}
