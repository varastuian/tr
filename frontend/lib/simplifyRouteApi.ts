import { missionToGeoJson, type AnyFC } from "./geojson";
import { getBridgeUrl } from "./bridgeUrl";
import type { DrawNode } from "./drawRoute";
import { parseQgcPlan } from "./qgcPlan";
import { parseQgcWpl110, type MissionItem } from "./qgcWpl";
import { simplifyMission } from "./simplifyMission";

export type SimplifyTuning = {
  removeLoiter?: boolean;
  minSeparationM?: number;
  minTurnDeg?: number;
  rdpEpsilonM?: number;
  fastReturnMode?: boolean;
  maxShortcutDeviationM?: number;
  /** When true (default), simplification must use the Python bridge (no TS fallback). */
  pythonOnly?: boolean;
};

type SimplifyResponse = {
  ok?: boolean;
  source?: string;
  warning?: string;
  points_in?: number;
  points_out?: number;
  taught_fc?: AnyFC;
  simplified_fc?: AnyFC;
  error?: string;
};

const defaultTune: Required<SimplifyTuning> = {
  removeLoiter: true,
  minSeparationM: 2,
  minTurnDeg: 6,
  rdpEpsilonM: 8,
  fastReturnMode: false,
  maxShortcutDeviationM: 300,
  pythonOnly: true,
};

function normalizeTune(tune: SimplifyTuning = {}): Required<SimplifyTuning> {
  return {
    removeLoiter: tune.removeLoiter ?? defaultTune.removeLoiter,
    minSeparationM: tune.minSeparationM ?? defaultTune.minSeparationM,
    minTurnDeg: tune.minTurnDeg ?? defaultTune.minTurnDeg,
    rdpEpsilonM: tune.rdpEpsilonM ?? defaultTune.rdpEpsilonM,
    fastReturnMode: tune.fastReturnMode ?? defaultTune.fastReturnMode,
    maxShortcutDeviationM: tune.maxShortcutDeviationM ?? defaultTune.maxShortcutDeviationM,
    pythonOnly: tune.pythonOnly ?? defaultTune.pythonOnly,
  };
}

function drawNodesToMission(nodes: DrawNode[]): MissionItem[] {
  return nodes.map((n, seq) => ({
    seq,
    command: n.kind === "loiter" ? 17 : 16,
    frame: 3,
    lat: n.lat,
    lon: n.lon,
    alt: 25,
    param1: n.kind === "loiter" ? n.radiusM : 0,
  }));
}

function parseMissionFromUpload(fileName: string, content: string): MissionItem[] {
  const lower = fileName.toLowerCase();
  if (content.trimStart().startsWith("QGC WPL")) return parseQgcWpl110(content);
  if (lower.endsWith(".waypoints") || lower.endsWith(".txt")) return parseQgcWpl110(content);
  if (lower.endsWith(".plan")) return parseQgcPlan(content);
  const obj = JSON.parse(content) as unknown;
  if (Array.isArray(obj)) {
    return obj.map((row, i) => {
      if (!Array.isArray(row) || row.length < 2) throw new Error("Invalid JSON point array");
      return {
        seq: i,
        command: 16,
        frame: 3,
        lat: Number(row[0]),
        lon: Number(row[1]),
        alt: 25,
      };
    });
  }
  if (typeof obj === "object" && obj !== null && "mission" in obj) {
    const mission = (obj as { mission?: unknown }).mission;
    if (!Array.isArray(mission)) throw new Error("Invalid mission payload");
    return mission.map((it, idx) => {
      const row = it as Record<string, unknown>;
      return {
        seq: idx,
        command: Number(row.command ?? 16),
        frame: Number(row.frame ?? 3),
        lat: Number(row.lat),
        lon: Number(row.lon),
        alt: Number(row.alt ?? 25),
      };
    });
  }
  throw new Error("Unsupported route format");
}

const BRIDGE_HINT =
  "Start: cd backend && source .venv/bin/activate && pip install -e . && PYTHONPATH=src python -m uav_route.sitl_bridge";

async function fetchPythonSimplify(
  mission: MissionItem[],
  tune: Required<SimplifyTuning>,
): Promise<SimplifyResponse> {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), 30000);
  try {
    const res = await fetch(`${getBridgeUrl()}/api/simplify/mission`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: ctrl.signal,
      body: JSON.stringify({
        mission,
        args: {
          remove_loiter: tune.removeLoiter,
          min_separation_m: tune.minSeparationM,
          min_turn_deg: tune.minTurnDeg,
          rdp_epsilon_m: tune.rdpEpsilonM,
          fast_return: tune.fastReturnMode,
          max_shortcut_deviation_m: tune.maxShortcutDeviationM,
        },
      }),
    });
    const data = (await res.json().catch(() => ({}))) as SimplifyResponse & { error?: string };
    if (!res.ok) {
      throw new Error(data.error || res.statusText || `HTTP ${res.status}`);
    }
    if (!data.taught_fc || !data.simplified_fc) {
      throw new Error(data.error || "Bridge response missing taught_fc / simplified_fc");
    }
    return data;
  } finally {
    clearTimeout(t);
  }
}

type LL = { lat: number; lon: number };
const EARTH_RADIUS_M = 6371008.8;

function haversineM(a: LL, b: LL): number {
  const lat1 = (a.lat * Math.PI) / 180;
  const lat2 = (b.lat * Math.PI) / 180;
  const dlat = lat2 - lat1;
  const dlon = ((b.lon - a.lon) * Math.PI) / 180;
  const s =
    Math.sin(dlat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dlon / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(s)));
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

function subPathDistance(points: LL[], i: number, j: number): number {
  let d = 0;
  for (let k = i; k < j; k++) d += haversineM(points[k]!, points[k + 1]!);
  return d;
}

function maxDeviationOnSubPath(points: LL[], i: number, j: number): number {
  if (j - i <= 1) return 0;
  const a = points[i]!;
  const b = points[j]!;
  let maxDev = 0;
  for (let k = i + 1; k < j; k++) {
    maxDev = Math.max(maxDev, crossTrackDistanceM(points[k]!, a, b));
  }
  return maxDev;
}

function shortestReverseShortcutPath(
  points: LL[],
  maxDeviationM: number,
): { route: LL[]; jumps: number } {
  const n = points.length;
  if (n < 2) return { route: points.slice().reverse(), jumps: 0 };

  const rev = points.slice().reverse();
  const maxDev = Math.max(1, maxDeviationM);
  const best = new Array<number>(n).fill(Number.POSITIVE_INFINITY);
  const prev = new Array<number>(n).fill(-1);
  best[0] = 0;

  for (let i = 0; i < n; i++) {
    if (!Number.isFinite(best[i])) continue;
    for (let j = i + 1; j < n; j++) {
      const dev = maxDeviationOnSubPath(rev, i, j);
      if (dev > maxDev) continue;
      const direct = haversineM(rev[i]!, rev[j]!);
      const cand = best[i]! + direct;
      if (cand < best[j]!) {
        best[j] = cand;
        prev[j] = i;
      }
    }
  }

  const idx: number[] = [];
  let cur = n - 1;
  if (!Number.isFinite(best[cur]!)) return { route: rev, jumps: 0 };
  while (cur >= 0) {
    idx.push(cur);
    if (cur === 0) break;
    cur = prev[cur]!;
  }
  idx.reverse();
  const route = idx.map((i) => rev[i]!);
  return { route, jumps: Math.max(0, n - route.length) };
}

function simplifyInBrowser(mission: MissionItem[], tune: Required<SimplifyTuning>): SimplifyResponse {
  if (tune.fastReturnMode) {
    const pts: LL[] = mission.map((m) => ({ lat: m.lat, lon: m.lon }));
    const out = shortestReverseShortcutPath(pts, tune.maxShortcutDeviationM);
    const simplifiedMission: MissionItem[] = out.route.map((p, i) => ({
      seq: i,
      command: 16,
      frame: 3,
      lat: p.lat,
      lon: p.lon,
      alt: mission[mission.length - 1]?.alt ?? 25,
    }));
    return {
      source: "browser-fast-return",
      warning:
        "Fast return mode: built shortest end->start shortcut route constrained by traced-path deviation.",
      points_in: mission.length,
      points_out: simplifiedMission.length,
      taught_fc: missionToGeoJson(mission, "taught"),
      simplified_fc: missionToGeoJson(simplifiedMission, "simplified"),
    };
  }
  const simplified = simplifyMission(mission, {
    removeLoiter: tune.removeLoiter,
    minSeparationM: tune.minSeparationM,
    minTurnDeg: tune.minTurnDeg,
    rdpEpsilonM: tune.rdpEpsilonM,
  });
  return {
    source: "browser-fallback",
    warning: "Python bridge unavailable, used browser fallback simplification.",
    points_in: mission.length,
    points_out: simplified.length,
    taught_fc: missionToGeoJson(mission, "taught"),
    simplified_fc: missionToGeoJson(simplified, "simplified"),
  };
}

export async function simplifyDrawNodes(
  nodes: DrawNode[],
  tune?: SimplifyTuning,
): Promise<SimplifyResponse> {
  if (nodes.length < 2) throw new Error("Need at least 2 nodes to simplify");
  const mission = drawNodesToMission(nodes);
  const fullTune = normalizeTune(tune);
  try {
    return await fetchPythonSimplify(mission, fullTune);
  } catch (err) {
    if (fullTune.pythonOnly) {
      throw new Error(
        `${err instanceof Error ? err.message : String(err)}. ${BRIDGE_HINT}`,
      );
    }
    return simplifyInBrowser(mission, fullTune);
  }
}

export async function simplifyRouteUpload(
  fileName: string,
  content: string,
  tune?: SimplifyTuning,
): Promise<SimplifyResponse> {
  const mission = parseMissionFromUpload(fileName, content);
  if (mission.length < 2) throw new Error("Uploaded route has too few points");
  const fullTune = normalizeTune(tune);
  try {
    return await fetchPythonSimplify(mission, fullTune);
  } catch (err) {
    if (fullTune.pythonOnly) {
      throw new Error(
        `${err instanceof Error ? err.message : String(err)}. ${BRIDGE_HINT}`,
      );
    }
    return simplifyInBrowser(mission, fullTune);
  }
}
