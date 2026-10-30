# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenWorks IT (Pty) Ltd
"""Write a simulated flight in LineGuard's generic format, so the dashboard can
be tried without a drone. The planted faults are saved to _truth.json."""
from __future__ import annotations

import dataclasses
import json
import math
from pathlib import Path

import numpy as np

from . import demo_scene as scene
from .geo import LocalFrame
from .readers.generic import write

BASE = (-32.2850, 22.5310)    # somewhere in the Karoo; any point works
LINE_BEARING = 62.0           # compass bearing the line runs on


def scenarios():
    return {s.name: s.label for s in scene.SCENARIOS}


def make_flight(out: Path, scenario="33kv_mild", seed=1, spans=5, glints=12) -> dict:
    sc = next(s for s in scene.SCENARIOS if s.name == scenario)
    sc = dataclasses.replace(sc, n_spans=spans)
    w = scene.build_world(sc, seed)
    poses, _ = scene.plan_flight(w)
    rng = np.random.default_rng(seed + 1000)
    frame = LocalFrame(*BASE)
    line_angle = math.radians(90 - LINE_BEARING)   # line direction as a math angle

    def to_latlon(xl, yl):
        e = xl * math.cos(line_angle) - yl * math.sin(line_angle)
        n = xl * math.sin(line_angle) + yl * math.cos(line_angle)
        return frame.to_latlon(e, n)

    glint_frames = set(rng.choice(len(poses), size=min(glints, len(poses)), replace=False).tolist())
    out = Path(out)
    for i, true, meta in poses:
        img = scene.render(w, true)
        if i in glint_frames:
            p = int(rng.integers(0, 3))
            x = true["x"] + rng.uniform(-4, 4) * sc.standoff / 20
            if 0 < x < w.length:
                depth = float(true["z"] - w.cond_height(np.array(x)))
                u, v = scene.world_to_pixel(true, x, sc.phase_y[p], depth)
                if 10 < u < scene.W - 10 and 10 < v < scene.H - 10:
                    scene.add_glint(img, rng, u, v)
        lat, lon = to_latlon(meta["x"], meta["y"])
        yaw = (90 - math.degrees(line_angle + meta["heading"])) % 360
        write(out, f"DEMO_{i:04d}", img, lat=lat, lon=lon, yaw_deg=yaw, pitch_deg=-90.0,
              rel_alt_m=float(meta["z"]), taken=f"simulated {sc.label}")
    truth = dict(
        scenario=sc.name, label=sc.label, standoff_m=sc.standoff,
        faults=[dict(zip(("lat", "lon"), to_latlon(f["x"], f["y"])), dt=f["dt"], kind=f["kind"]) for f in w.faults],
    )
    (out / "_truth.json").write_text(json.dumps(truth, indent=1))
    return truth
