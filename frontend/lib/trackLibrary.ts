import type { AnyFC } from "./geojson";

const STORAGE_KEY = "uav-route-track-library-v1";

export type SavedTrack = {
  id: string;
  name: string;
  savedAt: string;
  taught: AnyFC;
  simplified: AnyFC;
};

function safeParse(raw: string | null): SavedTrack[] {
  if (!raw) return [];
  try {
    const v = JSON.parse(raw) as unknown;
    if (!Array.isArray(v)) return [];
    return v.filter(
      (x) =>
        x &&
        typeof x === "object" &&
        typeof (x as SavedTrack).id === "string" &&
        typeof (x as SavedTrack).name === "string" &&
        (x as SavedTrack).taught?.type === "FeatureCollection" &&
        (x as SavedTrack).simplified?.type === "FeatureCollection",
    ) as SavedTrack[];
  } catch {
    return [];
  }
}

export function listSavedTracks(): SavedTrack[] {
  if (typeof window === "undefined") return [];
  return safeParse(window.localStorage.getItem(STORAGE_KEY)).sort((a, b) =>
    b.savedAt.localeCompare(a.savedAt),
  );
}

export function saveTrack(name: string, taught: AnyFC, simplified: AnyFC): SavedTrack {
  const trimmed = name.trim() || `Track ${new Date().toISOString().slice(0, 19)}`;
  const entry: SavedTrack = {
    id: crypto.randomUUID(),
    name: trimmed,
    savedAt: new Date().toISOString(),
    taught,
    simplified,
  };
  const next = [entry, ...listSavedTracks()];
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  return entry;
}

export function deleteTrack(id: string): void {
  const next = listSavedTracks().filter((t) => t.id !== id);
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
}

export function getTrack(id: string): SavedTrack | undefined {
  return listSavedTracks().find((t) => t.id === id);
}
