from __future__ import annotations

import json
from pathlib import Path

from uav_route.geojson import mission_to_geojson
from uav_route.mission import load_mission_json
from uav_route.simplify import SimplifyConfig, simplify_mission


def main() -> None:
    backend_dir = Path(__file__).resolve().parents[3]
    root_dir = backend_dir.parent

    out_dir = root_dir / "frontend" / "public" / "demo"
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg = SimplifyConfig(
        remove_loiter=True,
        min_separation_m=2.0,
        min_turn_deg=6.0,
        rdp_epsilon_m=10.0,
    )

    def run_case(stem: str) -> None:
        sample_path = backend_dir / "sample_data" / f"{stem}.json"
        data = json.loads(sample_path.read_text(encoding="utf-8"))
        taught = load_mission_json(data)
        simplified = simplify_mission(taught, cfg)

        (out_dir / f"{stem}.taught.geojson").write_text(
            json.dumps(mission_to_geojson(taught, f"{stem}.taught"), indent=2),
            encoding="utf-8",
        )
        (out_dir / f"{stem}.simplified.geojson").write_text(
            json.dumps(mission_to_geojson(simplified, f"{stem}.simplified"), indent=2),
            encoding="utf-8",
        )
        (out_dir / f"{stem}.meta.json").write_text(
            json.dumps(
                {
                    "config": cfg.__dict__,
                    "counts": {
                        "taught_items": len(taught),
                        "simplified_items": len(simplified),
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"Wrote: {out_dir / f'{stem}.taught.geojson'}")
        print(f"Wrote: {out_dir / f'{stem}.simplified.geojson'}")
        print(f"Wrote: {out_dir / f'{stem}.meta.json'}")

    run_case("taught_mission")
    run_case("complex_mission")


if __name__ == "__main__":
    main()

