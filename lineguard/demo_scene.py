# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenWorks IT (Pty) Ltd
"""Synthetic line, flight and thermal photos for demos and tests (DJI Matrice 4T geometry).

Everything in this file is the *simulated world*: the line, its faults, the
distractors and the camera. The detection code never reads the
ground truth defined here; it only sees the rendered images and the photo
metadata a real drone would record.
"""
import math
from dataclasses import dataclass, field

import numpy as np
from scipy.ndimage import gaussian_filter, map_coordinates

# --- Camera: DJI Matrice 4T thermal (640 x 512, 45 deg diagonal FOV) --------
W, H = 640, 512
CX, CY = (W - 1) / 2, (H - 1) / 2
F_PX = math.hypot(W, H) / 2 / math.tan(math.radians(45 / 2))  # ~989 px
NETD = 0.05          # deg C, spec <=50 mK
PSF_SIGMA = 0.6      # optical blur, pixels (assumed)
MIN_INTERVAL = 0.7   # s, fastest photo interval

DT_LEVELS = [2, 4, 6, 10, 15, 25, 40]


@dataclass
class Scenario:
    name: str
    label: str
    phase_y: tuple          # lateral position of each phase, m
    cond_diam: float        # m
    attach_h: float         # conductor height at pole, m
    sag: float              # mid-span sag, m
    standoff: float         # drone height above conductor at pole, m
    clamp_len: float
    clamp_w: float
    arm_half: float
    ground_mean: float
    ground_amp: float       # metre-scale variation amplitude
    veg_dt: float           # vegetation patches relative to ground
    cond_t: float           # conductor apparent temperature
    clamp_t: float          # hardware apparent temperature (normal)
    arm_t: float            # crossarm
    bird_t: float
    rock_dt: tuple          # rocks hotter than surrounding ground
    span: float = 100.0
    n_spans: int = 5


SCENARIOS = [
    Scenario("33kv_hot", "33 kV, hot afternoon, sun-heated ground", (-1.1, 0.0, 1.1), 0.018, 11.0, 1.5, 20.0,
             0.30, 0.06, 1.5, 44.0, 6.0, -9.0, 24.0, 27.0, 40.0, 34.0, (12, 25)),
    Scenario("33kv_mild", "33 kV, cool conditions (morning or overcast)", (-1.1, 0.0, 1.1), 0.018, 11.0, 1.5, 20.0,
             0.30, 0.06, 1.5, 20.0, 2.5, -3.0, 17.5, 18.5, 21.0, 30.0, (6, 12)),
    Scenario("132kv_hot", "132 kV, hot afternoon, 30 m standoff", (-4.0, 0.0, 4.0), 0.025, 20.0, 3.0, 30.0,
             0.40, 0.08, 5.0, 44.0, 6.0, -9.0, 24.0, 27.0, 40.0, 34.0, (12, 25)),
    Scenario("132kv_mild", "132 kV, cool conditions, 30 m standoff", (-4.0, 0.0, 4.0), 0.025, 20.0, 3.0, 30.0,
             0.40, 0.08, 5.0, 20.0, 2.5, -3.0, 17.5, 18.5, 21.0, 30.0, (6, 12)),
]


@dataclass
class World:
    sc: Scenario
    rng: np.random.Generator
    poles: list = field(default_factory=list)
    hardware: list = field(default_factory=list)   # dicts: x, phase, kind, len, w, dt
    faults: list = field(default_factory=list)     # dicts: x, y, phase, dt, kind
    rocks: list = field(default_factory=list)      # (x, y, r, dt)
    vehicles: list = field(default_factory=list)   # (x0, x1, y0, y1, dt)
    birds: list = field(default_factory=list)      # (x, phase)
    phase_bias: np.ndarray = None

    @property
    def length(self):
        return self.sc.span * self.sc.n_spans

    def cond_height(self, x):
        s = np.mod(x, self.sc.span) / self.sc.span
        return self.sc.attach_h - 4 * self.sc.sag * s * (1 - s)


def build_world(sc: Scenario, seed: int) -> World:
    rng = np.random.default_rng(seed)
    w = World(sc, rng)
    L = w.length
    w.poles = [i * sc.span for i in range(sc.n_spans + 1)]
    w.phase_bias = rng.normal(0, 0.4, 3)  # slight load imbalance between phases

    sites = []
    for xp in w.poles:
        for p in range(3):
            w.hardware.append(dict(x=xp, phase=p, kind="clamp", len=sc.clamp_len, w=sc.clamp_w, dt=0.0))
        sites.append(("pole", xp))
    for k in range(sc.n_spans):
        for p in range(3):
            for _ in range(rng.integers(1, 3)):
                xj = k * sc.span + rng.uniform(12, sc.span - 12)
                w.hardware.append(dict(x=xj, phase=p, kind="joint", len=0.5, w=sc.cond_diam * 2.6,
                                       dt=rng.uniform(0.5, 1.5)))  # healthy joints run a little warm
                sites.append(("joint", len(w.hardware) - 1))

    # 21 faults per flight: 3 at each temperature-rise level, at most one phase per pole
    rng.shuffle(sites)
    levels = [d for d in DT_LEVELS for _ in range(3)]
    rng.shuffle(levels)
    used_poles, chosen = set(), []
    for kind, ref in sites:
        if len(chosen) == len(levels):
            break
        if kind == "pole":
            if ref in used_poles:
                continue
            used_poles.add(ref)
            p = int(rng.integers(0, 3))
            hw = next(h for h in w.hardware if h["kind"] == "clamp" and h["x"] == ref and h["phase"] == p)
        else:
            hw = w.hardware[ref]
            # keep faults well apart so each one is judged on its own
            if any(abs(hw["x"] - c["x"]) < 3 for c in chosen):
                continue
        chosen.append(hw)
    for hw, d in zip(chosen, levels):
        hw["dt"] = hw["dt"] + d
        w.faults.append(dict(x=hw["x"], y=sc.phase_y[hw["phase"]], phase=hw["phase"], dt=d, kind=hw["kind"]))

    # distractors
    for _ in range(16):
        under = rng.random() < 0.5
        y = sc.phase_y[rng.integers(0, 3)] + rng.normal(0, 0.15) if under else rng.uniform(-8, 8)
        w.rocks.append((rng.uniform(5, L - 5), y, rng.uniform(0.3, 0.8), rng.uniform(*sc.rock_dt)))
    xv = rng.uniform(40, L - 40)
    w.vehicles.append((xv, xv + 4.5, -1.0, 1.0, 20.0 if sc.ground_mean > 30 else 12.0))  # parked under the line
    for _ in range(2):
        xb = rng.uniform(20, L - 20)
        if all(abs(xb - f["x"]) > 5 for f in w.faults):
            w.birds.append((xb, int(rng.integers(0, 3))))

    # ground temperature field: three scales of variation plus cooler vegetation
    w.gx0, w.gy0 = -40.0, -40.0
    def grid(step, amp):
        nx = int((L + 80) / step) + 2
        ny = int(80 / step) + 2
        return (step, gaussian_filter(rng.normal(0, 1, (nx, ny)), 1.0) * amp * 2.2)
    w.grids = [grid(4.0, sc.ground_amp), grid(1.0, sc.ground_amp * 0.35), grid(0.25, sc.ground_amp * 0.15)]
    w.veg = grid(2.0, 1.0)
    return w


def ground_temp(w: World, x, y):
    t = np.full(x.shape, w.sc.ground_mean, np.float32)
    for step, g in w.grids:
        t += map_coordinates(g, [(x - w.gx0) / step, (y - w.gy0) / step], order=1, mode="nearest")
    step, g = w.veg
    v = map_coordinates(g, [(x - w.gx0) / step, (y - w.gy0) / step], order=1, mode="nearest")
    t += np.where(v > 1.2, w.sc.veg_dt, 0.0).astype(np.float32)
    return t


def cond_temp(w: World, p, x):
    t = w.sc.cond_t + w.phase_bias[p] + 0.3 * np.sin(x / 37.0 + p)
    for f in w.faults:
        if f["phase"] == p:
            t = t + 0.35 * f["dt"] * np.exp(-np.abs(x - f["x"]) / 0.6)  # heat conducted along the conductor
    return t


# --- Flight ----------------------------------------------------------------
def plan_flight(w: World, overlap=0.8):
    sc = w.sc
    along_footprint = H * sc.standoff / F_PX
    spacing = along_footprint * (1 - overlap)
    xs = np.arange(-along_footprint / 2 + 1, w.length + along_footprint / 2 - 1, spacing)
    poses = []
    for i, x in enumerate(xs):
        rng = w.rng
        true = dict(
            x=x, y=rng.normal(0, 0.25),                              # lateral drift off the route
            z=sc.attach_h + sc.standoff,                              # RTK height hold
            heading=math.radians(rng.normal(0, 1.0)),                 # yaw wobble
            tilt=(math.radians(rng.normal(0, 0.15)), math.radians(rng.normal(0, 0.15))),  # gimbal error
            offset=rng.normal(0, 0.8),                                # absolute temperature drift per photo
        )
        meta = dict(                                                 # what the photo's metadata records
            x=true["x"] + rng.normal(0, 0.015), y=true["y"] + rng.normal(0, 0.015),
            z=true["z"] + rng.normal(0, 0.02),
            heading=true["heading"] + math.radians(rng.normal(0, 0.3)),
            standoff=sc.standoff,                                     # the route's set distance
        )
        poses.append((i, true, meta))
    return poses, spacing


def render(w: World, true, S=2):
    sc = w.sc
    u = (np.arange(W * S) + 0.5) / S - 0.5
    v = (np.arange(H * S) + 0.5) / S - 0.5
    U, V = np.meshgrid(u.astype(np.float32), v.astype(np.float32))
    ox = (U - CX) / F_PX + math.tan(true["tilt"][0])
    oy = (V - CY) / F_PX + math.tan(true["tilt"][1])
    hx, hy = math.cos(true["heading"]), math.sin(true["heading"])
    rx, ry = math.sin(true["heading"]), -math.cos(true["heading"])
    ax = -oy * hx + ox * rx
    ay = -oy * hy + ox * ry

    # ground plane
    dg = true["z"]
    xg, yg = true["x"] + dg * ax, true["y"] + dg * ay
    T = ground_temp(w, xg, yg)
    for (x0, y0, r, dt) in w.rocks:
        if abs(x0 - true["x"]) < 20:
            m = (xg - x0) ** 2 + (yg - y0) ** 2 < r * r
            T[m] += dt
    for (x0, x1, y0, y1, dt) in w.vehicles:
        if x1 > true["x"] - 20 and x0 < true["x"] + 20:
            T[(xg > x0) & (xg < x1) & (yg > y0) & (yg < y1)] += dt

    # conductor level (depth follows the sag)
    d0 = true["z"] - w.cond_height(np.array(true["x"]))
    xc = true["x"] + d0 * ax
    d = true["z"] - w.cond_height(xc)
    xc, yc = true["x"] + d * ax, true["y"] + d * ay
    half = 0.5 * sc.standoff * W / F_PX + 2
    for xp in w.poles:
        if abs(xp - true["x"]) < half:
            T[(np.abs(xc - xp) < 0.05) & (np.abs(yc) < sc.arm_half)] = sc.arm_t
    inline = (xc >= 0) & (xc <= w.length)
    for p, yp in enumerate(sc.phase_y):
        m = inline & (np.abs(yc - yp) < sc.cond_diam / 2)
        T[m] = cond_temp(w, p, xc[m])
    for hw in w.hardware:
        if abs(hw["x"] - true["x"]) < half:
            yp = sc.phase_y[hw["phase"]]
            m = (np.abs(xc - hw["x"]) < hw["len"] / 2) & (np.abs(yc - yp) < hw["w"] / 2)
            T[m] = sc.clamp_t + w.phase_bias[hw["phase"]] + hw["dt"]
    for (xb, p) in w.birds:
        if abs(xb - true["x"]) < half:
            yp = sc.phase_y[p]
            m = ((xc - xb) / 0.12) ** 2 + ((yc - yp) / 0.06) ** 2 < 1
            T[m] = sc.bird_t

    img = T.reshape(H, S, W, S).mean(axis=(1, 3))
    img = gaussian_filter(img, PSF_SIGMA)
    img += w.rng.normal(0, NETD, img.shape) + true["offset"]
    return img.astype(np.float32)


def add_glint(img, rng, u, v, amp=25.0):
    """Sun glint: a bright reflection that shows up in one photo only."""
    yy, xx = np.mgrid[0:H, 0:W]
    img += amp * np.exp(-((xx - u) ** 2 + (yy - v) ** 2) / (2 * 0.9 ** 2))
    return img


def world_to_pixel(meta_or_true, x, y, depth):
    """Project a world point at the given depth below the camera (nadir)."""
    hd = meta_or_true["heading"]
    dx, dy = x - meta_or_true["x"], y - meta_or_true["y"]
    along = dx * math.cos(hd) + dy * math.sin(hd)
    across = dx * math.sin(hd) - dy * math.cos(hd)
    return CX + across / depth * F_PX, CY - along / depth * F_PX
