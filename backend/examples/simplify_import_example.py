from __future__ import annotations

import json
from pathlib import Path

from uav_route import SimplifyConfig, simplify_mission, load_mission_items_file


def mission_items_to_json(items):
    mission = []
    for it in items:
        row = dict(it.raw)
        row["seq"] = it.seq
        row["command"] = int(it.command)
        row["frame"] = it.frame
        row["lat"] = it.lat
        row["lon"] = it.lon
        row["alt"] = it.alt
        mission.append(row)
    return {"mission": mission}


def main() -> None:
    base = Path(__file__).resolve().parent

    # Try either:
    # - base / "sample_qgc_plan.plan"
    # - base / "sample_qgc_waypoints.waypoints"
    # inp = base / "sample_qgc_plan.plan"
    inp = Path("/home/varas/Downloads/sag.plan")
    items = load_mission_items_file(inp)
    cfg = SimplifyConfig(rdp_epsilon_m=8.0, min_turn_deg=6.0)

    simplified = simplify_mission(items, cfg)
    out = mission_items_to_json(simplified)

    output_file = inp.with_name("sag_simplified.json")



    with open(output_file, "w") as f:
        json.dump(out, f, indent=2)

    print(f"Saved to: {output_file}")

    print(f"Loaded {len(items)} items; simplified to {len(simplified)} items.")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()

