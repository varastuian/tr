const DEFAULT_BRIDGE_URL = "http://127.0.0.1:8765";

export function getBridgeUrl(): string {
  const raw = process.env.NEXT_PUBLIC_BRIDGE_URL?.trim();
  if (!raw) return DEFAULT_BRIDGE_URL;
  return raw.replace(/\/+$/, "");
}
