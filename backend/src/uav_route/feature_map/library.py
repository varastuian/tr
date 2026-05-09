"""
On-disk **feature map**: ORB descriptors per keyframe (ordered along flight path).

Use case
--------
1. **Teach / log:** while the UAV flies, save down-looking camera frames (or video frames) in order.
2. **Build map:** ``FeatureMapLibrary.ingest_directory`` or repeated ``add_image``.
3. **Return toward home:** ``suggest_toward_home`` picks the best-matching earlier keyframe
   (greedy step along index toward 0). This is **not** a full VIO stack — pair with GPS/INS or
   odometry for closed-loop control.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np


@dataclass
class KeyframeRecord:
    index: int
    meta: dict[str, Any]
    keypoints_xy: list[tuple[float, float]]
    descriptors: np.ndarray


class FeatureMapLibrary:
    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self._frames: list[KeyframeRecord] = []

    @property
    def frames(self) -> list[KeyframeRecord]:
        return self._frames

    def __len__(self) -> int:
        return len(self._frames)

    def add_image(self, bgr: np.ndarray, meta: dict[str, Any] | None = None) -> int:
        """Add one BGR image as a keyframe; returns its index."""
        orb = cv2.ORB_create(nfeatures=1500, scaleFactor=1.2, nlevels=8)
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
        kp, des = orb.detectAndCompute(gray, None)
        if des is None or len(kp) < 10:
            raise ValueError("Too few ORB features in frame; use richer texture or resize.")

        xy = [(float(k.pt[0]), float(k.pt[1])) for k in kp]
        idx = len(self._frames)
        self._frames.append(
            KeyframeRecord(index=idx, meta=meta or {}, keypoints_xy=xy, descriptors=des.copy()),
        )
        return idx

    def save(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        manifest = []
        for f in self._frames:
            stem = f"{f.index:06d}"
            np.save(self.directory / f"des_{stem}.npy", f.descriptors)
            side = {"index": f.index, "meta": f.meta, "keypoints_xy": f.keypoints_xy}
            (self.directory / f"kp_{stem}.json").write_text(json.dumps(side), encoding="utf-8")
            manifest.append(stem)
        (self.directory / "manifest.json").write_text(
            json.dumps({"version": 1, "keyframes": manifest}, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, directory: Path) -> FeatureMapLibrary:
        lib = cls(directory)
        man_path = directory / "manifest.json"
        if not man_path.is_file():
            raise FileNotFoundError(man_path)
        man = json.loads(man_path.read_text(encoding="utf-8"))
        for stem in man["keyframes"]:
            des = np.load(directory / f"des_{stem}.npy")
            side = json.loads((directory / f"kp_{stem}.json").read_text(encoding="utf-8"))
            lib._frames.append(
                KeyframeRecord(
                    index=int(side["index"]),
                    meta=dict(side.get("meta") or {}),
                    keypoints_xy=[tuple(p) for p in side["keypoints_xy"]],
                    descriptors=des,
                ),
            )
        lib._frames.sort(key=lambda x: x.index)
        return lib

    def match_best(self, query_bgr: np.ndarray, ratio: float = 0.75) -> tuple[int, int]:
        """Return (best_keyframe_index, good_match_count)."""
        orb = cv2.ORB_create(nfeatures=1500, scaleFactor=1.2, nlevels=8)
        gray = cv2.cvtColor(query_bgr, cv2.COLOR_BGR2GRAY) if query_bgr.ndim == 3 else query_bgr
        _, des_q = orb.detectAndCompute(gray, None)
        if des_q is None:
            return -1, 0

        bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
        best_i, best_cnt = -1, 0
        for kf in self._frames:
            matches = bf.knnMatch(des_q, kf.descriptors, k=2)
            good = 0
            for pair in matches:
                if len(pair) < 2:
                    continue
                m, n = pair[0], pair[1]
                if m.distance < ratio * n.distance:
                    good += 1
            if good > best_cnt:
                best_cnt, best_i = good, kf.index
        return best_i, best_cnt

    def suggest_toward_home(
        self,
        query_bgr: np.ndarray,
        *,
        min_matches: int = 25,
        step: int = 3,
    ) -> dict[str, Any]:
        """
        Greedy hint: assume keyframe **0** is “home” / start of path. Move matching index
        backward by ``step`` toward 0.
        """
        best_i, cnt = self.match_best(query_bgr)
        if best_i < 0 or cnt < min_matches:
            return {
                "ok": False,
                "reason": "weak_match",
                "best_index": best_i,
                "matches": cnt,
                "target_index": None,
            }
        target = max(0, best_i - step)
        return {
            "ok": True,
            "best_index": best_i,
            "matches": cnt,
            "target_index": target,
            "note": "Use target_index to load reference image or pose; close loop with odometry.",
        }
