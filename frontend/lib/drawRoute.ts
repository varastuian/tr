export type DrawNode =
  | { kind: "waypoint"; lat: number; lon: number }
  | { kind: "loiter"; lat: number; lon: number; radiusM: number };
