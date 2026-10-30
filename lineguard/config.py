# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenWorks IT (Pty) Ltd
"""Settings, read from a TOML file with sensible defaults.

Default locations (Linux):
    config  ~/.config/lineguard/config.toml
    data    ~/.local/share/lineguard   (database, crops, processed flights)
    inbox   ~/LineGuard/inbox          (drop a flight folder here)
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


def _xdg(var: str, fallback: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / fallback)


DEFAULT_CONFIG = _xdg("XDG_CONFIG_HOME", ".config") / "lineguard" / "config.toml"


@dataclass
class Camera:
    """Thermal camera geometry. Defaults are the DJI Matrice 4T thermal camera."""
    name: str = "DJI Matrice 4T thermal"
    diagonal_fov_deg: float = 45.0
    colour_diagonal_fov_deg: float = 82.0   # wide camera, used to cut the colour close-up


@dataclass
class Detection:
    phases: int = 3                 # conductors expected side by side in each photo
    threshold_c: float = 3.0        # minimum rise over the other phases to flag
    noise_multiple: float = 5.0     # and at least this many times the photo's own noise
    standoff_m: float = 20.0        # route's set distance from camera to conductors
    max_line_angle_deg: float = 12  # conductors run within this angle of the flight direction
    min_nadir_pitch_deg: float = -80  # photos must look (nearly) straight down
    confirm_min_photos: int = 2
    confirm_min_share: float = 0.5  # of the photos that covered the spot
    cluster_radius_m: float = 0.6
    history_radius_m: float = 1.5   # same fault on an earlier flight if within this distance
    severity_probable_c: float = 4.0   # NETA similar-component bands
    severity_major_c: float = 15.0


@dataclass
class Settings:
    host: str = "127.0.0.1"
    port: int = 8750
    data_dir: Path = field(default_factory=lambda: _xdg("XDG_DATA_HOME", ".local/share") / "lineguard")
    inbox_dir: Path = field(default_factory=lambda: Path.home() / "LineGuard" / "inbox")
    dji_irp: str = ""               # path to dji_irp from the DJI Thermal SDK
    tiles_url: str = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    open_browser: bool = False
    hosted: bool = False            # on a server: login required, browser uploads instead of local folders
    username: str = "argus"
    password: str = ""              # set to require a login (always set this when hosted)
    max_upload_mb: int = 4096
    share: bool = False             # let paired phones reach this laptop over Wi-Fi (listens on all interfaces)
    name: str = ""                  # shown on paired phones; defaults to the computer's name
    osm_power: bool = True          # label hotspots with the nearest OpenStreetMap tower when online
    overpass_url: str = "https://overpass-api.de/api/interpreter"
    public_url: str = ""            # hosted: the address phones use, e.g. https://lineguard.example.com
    allowed_hosts: str = ""         # extra host names this server answers to, comma separated
    dev_origins: str = ""           # browser origins allowed to call the API (app development only)
    behind_proxy: bool = False      # hosted behind Caddy etc.: take the client address from X-Forwarded-For
    source_url: str = "https://github.com/OpenWorksIT/lineguard"  # where this version's source is (AGPL section 13)
    camera: Camera = field(default_factory=Camera)
    detection: Detection = field(default_factory=Detection)

    @property
    def bind_host(self) -> str:
        return "0.0.0.0" if self.share and self.host in ("127.0.0.1", "localhost") else self.host

    @property
    def display_name(self) -> str:
        import socket
        return self.name or ("LineGuard server" if self.hosted else socket.gethostname())

    @property
    def db_path(self) -> Path:
        return self.data_dir / "lineguard.db"

    @property
    def crops_dir(self) -> Path:
        return self.data_dir / "crops"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"

    @property
    def tiles_dir(self) -> Path:
        """Optional offline map tiles laid out as {z}/{x}/{y}.png."""
        return self.data_dir / "tiles"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.crops_dir, self.inbox_dir, self.uploads_dir, self.tmp_dir):
            d.mkdir(parents=True, exist_ok=True)

    def public(self) -> dict:
        d = asdict(self)
        d["data_dir"], d["inbox_dir"] = str(self.data_dir), str(self.inbox_dir)
        d["offline_tiles"] = self.tiles_dir.is_dir()
        d.pop("password", None)
        return d


def _apply(obj, values: dict):
    names = {f.name: f for f in fields(obj)}
    for k, v in values.items():
        if k not in names:
            raise ValueError(f"unknown setting: {k}")
        cur = getattr(obj, k)
        if isinstance(cur, (Camera, Detection)):
            _apply(cur, v)
        elif isinstance(cur, Path):
            setattr(obj, k, Path(v).expanduser())
        else:
            setattr(obj, k, type(cur)(v))


def load(path: Path | None = None) -> Settings:
    s = Settings()
    p = Path(path) if path else DEFAULT_CONFIG
    if p.exists():
        with open(p, "rb") as fh:
            _apply(s, tomllib.load(fh))
    env = {
        "LINEGUARD_HOST": ("host", str), "LINEGUARD_PORT": ("port", int),
        "LINEGUARD_DATA_DIR": ("data_dir", lambda v: Path(v).expanduser()),
        "LINEGUARD_INBOX_DIR": ("inbox_dir", lambda v: Path(v).expanduser()),
        "LINEGUARD_DJI_IRP": ("dji_irp", str), "LINEGUARD_TILES_URL": ("tiles_url", str),
        "LINEGUARD_HOSTED": ("hosted", lambda v: v.strip().lower() in ("1", "true", "yes")),
        "LINEGUARD_USER": ("username", str), "LINEGUARD_PASSWORD": ("password", str),
        "LINEGUARD_MAX_UPLOAD_MB": ("max_upload_mb", int),
        "LINEGUARD_SHARE": ("share", lambda v: v.strip().lower() in ("1", "true", "yes")),
        "LINEGUARD_NAME": ("name", str),
        "LINEGUARD_OSM_POWER": ("osm_power", lambda v: v.strip().lower() in ("1", "true", "yes")),
        "LINEGUARD_OVERPASS_URL": ("overpass_url", str),
        "LINEGUARD_PUBLIC_URL": ("public_url", str),
        "LINEGUARD_ALLOWED_HOSTS": ("allowed_hosts", str),
        "LINEGUARD_DEV_ORIGINS": ("dev_origins", str),
        "LINEGUARD_SOURCE_URL": ("source_url", str),
        "LINEGUARD_BEHIND_PROXY": ("behind_proxy", lambda v: v.strip().lower() in ("1", "true", "yes")),
    }
    for var, (name, conv) in env.items():
        if os.environ.get(var):
            setattr(s, name, conv(os.environ[var]))
    s.detection.standoff_m = float(os.environ.get("LINEGUARD_STANDOFF_M", s.detection.standoff_m))
    if s.hosted and not s.password:
        raise SystemExit("LineGuard is in hosted mode but no password is set (LINEGUARD_PASSWORD).")
    if s.password and (len(s.password) < 12 or s.password.startswith("change-me")):
        raise SystemExit("The LineGuard password must be at least 12 characters and not the example one.")
    if s.hosted and not s.public_url:
        raise SystemExit("Hosted mode needs LINEGUARD_PUBLIC_URL (the https:// address phones and browsers use).")
    if s.public_url and not s.public_url.startswith("https://"):
        raise SystemExit("LINEGUARD_PUBLIC_URL must start with https:// so phones connect securely.")
    if s.behind_proxy and not s.password:
        raise SystemExit("LINEGUARD_BEHIND_PROXY needs a password: only use it behind a proxy that requires one.")
    return s


EXAMPLE = """# LineGuard settings. Every line is optional.
# host = "127.0.0.1"
# port = 8750
# inbox_dir = "~/LineGuard/inbox"
# data_dir = "~/.local/share/lineguard"
# dji_irp = "/opt/dji_thermal_sdk/utility/bin/linux/release_x64/dji_irp"
# tiles_url = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
# share = true            # let paired phones connect over Wi-Fi (for driving to faults)
# name = "Bakkie laptop"  # how this laptop shows up on phones
# allowed_hosts = "bakkie-laptop.local"  # other names you open the dashboard by (IP addresses always work)

[detection]
# standoff_m = 20.0
# threshold_c = 3.0
# phases = 3
"""
