# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenWorks IT (Pty) Ltd
"""Command line: lineguard serve | open | process | demo | install-service | init-config"""
from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

from . import __version__, config

UNIT = """[Unit]
Description=LineGuard thermal inspection service
After=network.target

[Service]
ExecStart={exe} serve
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""

DESKTOP = """[Desktop Entry]
Type=Application
Name=LineGuard
Comment=Thermal inspection dashboard
Exec=xdg-open http://{host}:{port}/
Icon={icon}
Terminal=false
Categories=Utility;
"""


def url(s):
    return f"http://{s.host}:{s.port}/"


def cmd_serve(s, args):
    from waitress import serve

    from .store import Store
    from .web import create_app
    from .worker import Worker

    if getattr(args, "share", False):
        s.share = True
    s.ensure_dirs()
    store = Store(s.db_path)
    worker = Worker(store, s)
    worker.start()
    app = create_app(s, store, worker)
    log = logging.getLogger("lineguard")
    log.info("LineGuard %s at %s, watching %s", __version__, url(s), s.inbox_dir)
    if s.share and not s.hosted:
        from .phones import lan_addresses
        addrs = ", ".join(f"http://{a}:{s.port}" for a in lan_addresses()) or "no Wi-Fi address yet"
        log.info("Sharing with paired phones on: %s", addrs)
    if args.open or s.open_browser:
        webbrowser.open(url(s))
    proxy = {}
    if s.behind_proxy:
        # One proxy in front (Caddy): the client's own address is the last X-Forwarded-For entry,
        # so login and pairing limits apply per client rather than to the proxy as a whole.
        # Only safe when nothing but the proxy can reach this port (no published ports in deploy/vps).
        proxy = dict(trusted_proxy="*", trusted_proxy_count=1,
                     trusted_proxy_headers={"x-forwarded-for", "x-forwarded-proto"},
                     clear_untrusted_proxy_headers=True)
    # Large request bodies are spooled to disk: keep that on the data volume (the container's own
    # filesystem is read-only) where the free-space checks apply.
    import tempfile
    tempfile.tempdir = str(s.tmp_dir)
    # Browser uploads only exist on a hosted LineGuard; on a laptop the biggest request is a tower file.
    body_mb = s.max_upload_mb if s.hosted else 64
    serve(app, host=s.bind_host, port=s.port, threads=8, _quiet=True,
          max_request_body_size=body_mb * 1024 * 1024,
          channel_timeout=60,          # seconds of silence before a connection is dropped (a slow upload still counts as activity)
          connection_limit=200, cleanup_interval=10, **proxy)


def cmd_open(s, args):
    webbrowser.open(url(s))
    print(url(s))


def cmd_process(s, args):
    from .pipeline import process
    from .store import Store

    s.ensure_dirs()
    store = Store(s.db_path)
    folder = Path(args.folder).expanduser().resolve()
    fid = store.add_flight(args.name or folder.name, folder)
    process(store, s, fid)
    f = store.flight(fid)
    print(f"{f['status']}: {f['message']}")
    for h in store.hotspots(fid):
        print(f"  LG-{h['id']}  +{h['dt']:5.1f} °C  {h['severity']:<8}  {h['lat']:.7f}, {h['lon']:.7f}")
    return 0 if f["status"] == "done" else 1


def cmd_demo(s, args):
    from .demo import make_flight

    s.ensure_dirs()
    target = Path(args.out).expanduser() if args.out else s.inbox_dir / f"demo_{args.scenario}_{args.seed}"
    tmp = target.with_name("." + target.name)          # write hidden, then move in one step
    print(f"Simulating a {args.spans * 100} m flight ({args.scenario}), this takes a minute or two ...")
    truth = make_flight(tmp, args.scenario, args.seed, args.spans)
    if target.exists():
        shutil.rmtree(target)
    tmp.rename(target)
    print(f"Wrote {target} with {len(truth['faults'])} planted faults. "
          + ("The service will pick it up shortly." if not args.out else ""))


def cmd_install_service(s, args):
    exe = shutil.which("lineguard") or f"{sys.executable} -m lineguard"
    unit_dir = Path.home() / ".config/systemd/user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit = UNIT.format(exe=exe)
    if args.share:
        unit = unit.replace(" serve\n", " serve --share\n")
    (unit_dir / "lineguard.service").write_text(unit)
    icon = Path(__file__).parent / "static" / "logo-mark.svg"
    apps = Path.home() / ".local/share/applications"
    apps.mkdir(parents=True, exist_ok=True)
    (apps / "lineguard.desktop").write_text(DESKTOP.format(host=s.host, port=s.port, icon=icon))
    print(f"Wrote {unit_dir / 'lineguard.service'} and a 'LineGuard' app launcher.")
    if shutil.which("systemctl"):
        for cmd in (["systemctl", "--user", "daemon-reload"], ["systemctl", "--user", "enable", "--now", "lineguard"]):
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                print(f"  {' '.join(cmd)} failed: {r.stderr.strip()}")
                return 1
        print(f"Service running. Dashboard: {url(s)}")
        print("To keep it running after logout: loginctl enable-linger $USER")
    return 0


def cmd_hotspot(s, args):
    """Turn this laptop into a Wi-Fi hotspot (NetworkManager), so phones in the vehicle can connect."""
    if not shutil.which("nmcli"):
        print("nmcli (NetworkManager) is not available. Create a hotspot in your system's Wi-Fi settings instead.")
        return 1
    if args.off:
        r = subprocess.run(["nmcli", "connection", "down", "Hotspot"], capture_output=True, text=True)
        print(r.stdout.strip() or r.stderr.strip())
        return r.returncode
    import secrets
    password = args.password or "".join(secrets.choice("abcdefghjkmnpqrstuvwxyz23456789") for _ in range(14))
    cmd = ["nmcli", "device", "wifi", "hotspot", "ssid", args.ssid, "password", password]
    if args.ifname:
        cmd[3:3] = ["ifname", args.ifname]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"Could not start the hotspot: {(r.stderr or r.stdout).strip()}")
        return 1
    print(f"Wi-Fi hotspot on. Network: {args.ssid}   Password: {password}")
    print(f"Connect the phone to it, then pair from the dashboard (Connect a phone). The laptop is usually http://10.42.0.1:{s.port}")
    if not s.share:
        print("Phone sharing is off: set share = true in config.toml, or run lineguard serve --share.")
    return 0


def cmd_init_config(s, args):
    p = config.DEFAULT_CONFIG
    if p.exists():
        print(f"{p} already exists")
        return 1
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(config.EXAMPLE)
    print(f"Wrote {p}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="lineguard", description="LineGuard thermal powerline inspection")
    ap.add_argument("--config", type=Path, help="path to config.toml")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("serve", help="run the background service and dashboard")
    p.add_argument("--open", action="store_true", help="open the dashboard in a browser")
    p.add_argument("--share", action="store_true", help="let paired phones connect over Wi-Fi")
    sub.add_parser("open", help="open the dashboard in a browser")
    p = sub.add_parser("process", help="process one flight folder now, without the service")
    p.add_argument("folder")
    p.add_argument("--name")
    p = sub.add_parser("demo", help="write a simulated flight into the inbox")
    p.add_argument("--scenario", default="33kv_mild",
                   choices=["33kv_mild", "33kv_hot", "132kv_mild", "132kv_hot"])
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--spans", type=int, default=5, help="100 m spans to simulate")
    p.add_argument("--out", help="write here instead of the inbox")
    p = sub.add_parser("install-service", help="install and start as a systemd user service (Linux)")
    p.add_argument("--share", action="store_true", help="let paired phones connect over Wi-Fi")
    p = sub.add_parser("hotspot", help="turn this laptop into a Wi-Fi hotspot for phones (NetworkManager)")
    p.add_argument("--ssid", default="LineGuard")
    p.add_argument("--password", help="at least 8 characters; random if left out")
    p.add_argument("--ifname", help="Wi-Fi device, e.g. wlan0")
    p.add_argument("--off", action="store_true", help="turn the hotspot off")
    sub.add_parser("init-config", help="write an example config.toml")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    s = config.load(args.config)
    fn = {"serve": cmd_serve, "open": cmd_open, "process": cmd_process, "demo": cmd_demo,
          "install-service": cmd_install_service, "init-config": cmd_init_config,
          "hotspot": cmd_hotspot}[args.cmd]
    sys.exit(fn(s, args) or 0)
