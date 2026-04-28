import type { MissionItem } from "./qgcWpl";

/**
 * Parse QGroundControl `.plan` JSON file (best-effort for mission items).
 *
 * We extract spatial mission items that have coordinate params.
 */
export function parseQgcPlan(text: string): MissionItem[] {
  const obj = JSON.parse(text) as {
    mission?: {
      items?: Array<{
        command?: number;
        frame?: number;
        params?: unknown[];
      }>;
    };
  };

  const items = obj?.mission?.items ?? [];
  const out: MissionItem[] = [];

  for (const it of items) {
    const command = Number(it.command);
    const frame = Number(it.frame ?? 3);
    const params = Array.isArray(it.params) ? it.params : [];

    // QGC uses params[4]=lat, [5]=lon, [6]=alt for many NAV commands.
    const lat = Number(params[4]);
    const lon = Number(params[5]);
    const alt = Number(params[6]);

    if (![command, frame, lat, lon, alt].every((x) => Number.isFinite(x))) continue;

    out.push({
      seq: out.length,
      command,
      frame,
      lat,
      lon,
      alt,
      param1: Number(params[0]),
      param2: Number(params[1]),
      param3: Number(params[2]),
      param4: Number(params[3]),
    });
  }

  return out.map((it, i) => ({ ...it, seq: i }));
}

