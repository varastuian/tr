import type { MissionItem } from "./qgcWpl";

const LOITER_COMMANDS = new Set([17, 18, 19, 31]);
const ESSENTIAL_COMMANDS = new Set([22, 21, 20]); // takeoff, land, RTL

export type SimplifyConfig = {
  removeLoiter: boolean;
  minSeparationM: number;
  minTurnDeg: number;
  rdpEpsilonM: number;
};

type LL = { lat: number; lon: number };

const EARTH_RADIUS_M = 6371008.8;

function haversineM(a: LL, b: LL): number {
  const lat1 = (a.lat * Math.PI) / 180;
  const lat2 = (b.lat * Math.PI) / 180;
  const dlat = lat2 - lat1;
  const dlon = ((b.lon - a.lon) * Math.PI) / 180;
  const s =
    Math.sin(dlat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dlon / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(s)));
}

function bearingDeg(a: LL, b: LL): number {
  const lat1 = (a.lat * Math.PI) / 180;
  const lat2 = (b.lat * Math.PI) / 180;
  const dlon = ((b.lon - a.lon) * Math.PI) / 180;
  const y = Math.sin(dlon) * Math.cos(lat2);
  const x =
    Math.cos(lat1) * Math.sin(lat2) -
    Math.sin(lat1) * Math.cos(lat2) * Math.cos(dlon);
  const brng = (Math.atan2(y, x) * 180) / Math.PI;
  return (brng + 360) % 360;
}

function angleDiffDeg(a: number, b: number): number {
  const d = ((b - a + 180) % 360) - 180;
  return Math.abs(d);
}

function crossTrackDistanceM(p: LL, a: LL, b: LL): number {
  const lat0 = (((a.lat + b.lat) / 2) * Math.PI) / 180;
  const ax = ((a.lon * Math.PI) / 180) * Math.cos(lat0);
  const ay = (a.lat * Math.PI) / 180;
  const bx = ((b.lon * Math.PI) / 180) * Math.cos(lat0);
  const by = (b.lat * Math.PI) / 180;
  const px = ((p.lon * Math.PI) / 180) * Math.cos(lat0);
  const py = (p.lat * Math.PI) / 180;

  const vx = bx - ax;
  const vy = by - ay;
  const wx = px - ax;
  const wy = py - ay;

  const vv = vx * vx + vy * vy;
  if (vv === 0) return Math.hypot(px - ax, py - ay) * EARTH_RADIUS_M;

  const t = Math.max(0, Math.min(1, (wx * vx + wy * vy) / vv));
  const cx = ax + t * vx;
  const cy = ay + t * vy;
  return Math.hypot(px - cx, py - cy) * EARTH_RADIUS_M;
}

function rdpKeepIndices(points: LL[], epsilonM: number): number[] {
  if (points.length <= 2) return points.map((_, i) => i);
  const keep = new Array(points.length).fill(false) as boolean[];
  keep[0] = true;
  keep[keep.length - 1] = true;

  const stack: Array<[number, number]> = [[0, points.length - 1]];
  while (stack.length) {
    const [i, j] = stack.pop()!;
    const a = points[i]!;
    const b = points[j]!;
    let maxD = -1;
    let maxK = -1;
    for (let k = i + 1; k < j; k++) {
      const d = crossTrackDistanceM(points[k]!, a, b);
      if (d > maxD) {
        maxD = d;
        maxK = k;
      }
    }
    if (maxK !== -1 && maxD > epsilonM) {
      keep[maxK] = true;
      stack.push([i, maxK], [maxK, j]);
    }
  }
  return keep.map((v, i) => (v ? i : -1)).filter((i) => i !== -1);
}

function isEssential(it: MissionItem): boolean {
  return ESSENTIAL_COMMANDS.has(it.command);
}

export function simplifyMission(items: MissionItem[], cfg: SimplifyConfig): MissionItem[] {
  const filtered = items.filter((it) => {
    if (!cfg.removeLoiter) return true;
    if (LOITER_COMMANDS.has(it.command) && !isEssential(it)) return false;
    return true;
  });

  const spatial = filtered.filter((it) => !isEssential(it));
  if (spatial.length === 0) return resequence(filtered);

  const pre: MissionItem[] = [spatial[0]!];
  for (const cand of spatial.slice(1)) {
    const last = pre[pre.length - 1]!;
    const a = { lat: last.lat, lon: last.lon };
    const b = { lat: cand.lat, lon: cand.lon };
    if (haversineM(a, b) < cfg.minSeparationM) continue;
    if (pre.length >= 2) {
      const prev = pre[pre.length - 2]!;
      const p = { lat: prev.lat, lon: prev.lon };
      const br1 = bearingDeg(p, a);
      const br2 = bearingDeg(a, b);
      if (angleDiffDeg(br1, br2) < cfg.minTurnDeg) continue;
    }
    pre.push(cand);
  }

  const pts = pre.map((it) => ({ lat: it.lat, lon: it.lon }));
  const keepIdx = rdpKeepIndices(pts, cfg.rdpEpsilonM);
  const kept = new Set(keepIdx.map((i) => pre[i]!.seq));

  const out = filtered.filter((it) => isEssential(it) || kept.has(it.seq));
  return resequence(out);
}

function resequence(items: MissionItem[]): MissionItem[] {
  return items.map((it, i) => ({ ...it, seq: i }));
}

