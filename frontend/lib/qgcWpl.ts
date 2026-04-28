export type MissionItem = {
  seq: number;
  command: number;
  frame: number;
  lat: number;
  lon: number;
  alt: number;
  // keep params for future use
  param1?: number;
  param2?: number;
  param3?: number;
  param4?: number;
};

/**
 * Parse QGroundControl / Mission Planner waypoint file: "QGC WPL 110"
 *
 * Format (space/tab-separated):
 *   seq current frame command p1 p2 p3 p4 x(lat) y(lon) z(alt) autocontinue
 */
export function parseQgcWpl110(text: string): MissionItem[] {
  const lines = text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l.length > 0);

  if (lines.length === 0) return [];
  if (!/^QGC\s+WPL\s+110/i.test(lines[0])) {
    throw new Error("Unsupported mission format. Expected header: QGC WPL 110");
  }

  const items: MissionItem[] = [];
  for (const line of lines.slice(1)) {
    if (line.startsWith("#")) continue;
    const parts = line.split(/\s+/);
    if (parts.length < 12) continue;

    const seq = Number(parts[0]);
    const frame = Number(parts[2]);
    const command = Number(parts[3]);
    const param1 = Number(parts[4]);
    const param2 = Number(parts[5]);
    const param3 = Number(parts[6]);
    const param4 = Number(parts[7]);
    const lat = Number(parts[8]);
    const lon = Number(parts[9]);
    const alt = Number(parts[10]);

    if (![seq, frame, command, lat, lon, alt].every((x) => Number.isFinite(x))) continue;

    items.push({
      seq,
      frame,
      command,
      lat,
      lon,
      alt,
      param1,
      param2,
      param3,
      param4,
    });
  }

  // ensure sequence order
  items.sort((a, b) => a.seq - b.seq);
  return items.map((it, i) => ({ ...it, seq: i }));
}

