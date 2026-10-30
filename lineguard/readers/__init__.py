# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenWorks IT (Pty) Ltd
"""Photo readers. Every reader yields Photo objects with the same fields, so the
analysis never needs to know which drone or camera took them."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import numpy as np


@dataclass
class Photo:
    name: str
    path: Path
    lat: float
    lon: float
    yaw_deg: float                  # camera heading, compass degrees (0 = north)
    pitch_deg: float = -90.0        # -90 = straight down
    abs_alt_m: Optional[float] = None
    rel_alt_m: Optional[float] = None
    range_m: Optional[float] = None  # laser rangefinder distance, when the camera recorded one
    taken: str = ""
    colour_path: Optional[Path] = None
    width: int = 0
    height: int = 0
    _loader: Callable[[], np.ndarray] = field(default=None, repr=False)

    def temperatures(self) -> np.ndarray:
        """Temperature of every pixel, degrees C, float32 array (height x width)."""
        img = self._loader()
        self.height, self.width = img.shape
        return img


class ReaderError(RuntimeError):
    pass


def read_folder(folder: Path, settings) -> list[Photo]:
    """Pick the right reader for a flight folder."""
    from . import dji, generic

    folder = Path(folder)
    if not folder.is_dir():
        raise ReaderError(f"not a folder: {folder}")
    photos = generic.read(folder)
    if photos:
        return photos
    photos = dji.read(folder, settings)
    if photos:
        return photos
    raise ReaderError("no thermal photos found (expected DJI *_T.JPG files, or .npy + .json pairs)")
