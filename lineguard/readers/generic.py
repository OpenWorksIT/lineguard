# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenWorks IT (Pty) Ltd
"""Generic format: one temperature array per photo (photo.npy, degrees C) plus
photo.json holding its position and pointing. Used by the demo flights and for
cameras other than DJI's: anything that can export per-pixel temperatures."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from . import Photo

FIELDS = ("lat", "lon", "yaw_deg", "pitch_deg", "abs_alt_m", "rel_alt_m", "range_m", "taken")
MAX_PIXELS = 50_000_000  # far above any thermal camera; stops a tiny file declaring a huge array


def _load(path: Path) -> np.ndarray:
    """Load a temperature array, checking its declared size first (no pickles, no huge allocations)."""
    with open(path, "rb") as fh:
        major, _ = np.lib.format.read_magic(fh)
        read_header = np.lib.format.read_array_header_1_0 if major == 1 else np.lib.format.read_array_header_2_0
        shape, _, dtype = read_header(fh)
    if len(shape) != 2 or shape[0] * shape[1] > MAX_PIXELS or dtype.kind not in "fiu":
        raise ValueError(f"{path.name}: not a 2-D temperature array of a sensible size")
    return np.load(path, allow_pickle=False).astype(np.float32)


def read(folder: Path) -> list[Photo]:
    photos = []
    for meta_path in sorted(folder.glob("*.json")):
        arr_path = meta_path.with_suffix(".npy")
        if not arr_path.exists():
            continue
        meta = json.loads(meta_path.read_text())
        colour = meta_path.with_name(meta_path.stem + "_colour.png")
        photos.append(Photo(
            name=meta_path.stem, path=arr_path,
            colour_path=colour if colour.exists() else None,
            _loader=lambda p=arr_path: _load(p),
            **{k: meta[k] for k in FIELDS if k in meta},
        ))
    return photos


def write(folder: Path, name: str, temps: np.ndarray, **meta) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    np.save(folder / f"{name}.npy", temps.astype(np.float32))
    (folder / f"{name}.json").write_text(json.dumps({k: v for k, v in meta.items() if v is not None}, indent=1))
