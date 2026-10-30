# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenWorks IT (Pty) Ltd
"""Pairing phones with this LineGuard: short-lived codes, long-lived device tokens.

On the laptop, "Connect a phone" shows a QR code holding this server's
addresses and a 6-digit code. The LineGuard app exchanges the code for a
device token, which it then sends with every request. Codes expire after ten
minutes or eight wrong guesses; tokens are stored only as hashes and can be
revoked from the dashboard.
"""
from __future__ import annotations

import hashlib
import ipaddress
import secrets
import socket
import subprocess
import threading
import time
from urllib.parse import quote

CODE_TTL = 600
# Wrong guesses are limited per address (5 per 10 minutes, in web.py). This cap per code only stops a
# guesser spread over many addresses: 30 guesses at a 6-digit code is a 0.003% chance.
MAX_FAILURES = 30


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Pairing:
    def __init__(self):
        self._lock = threading.Lock()
        self.code = None
        self.expires = 0.0
        self.failures = 0

    def new_code(self) -> tuple[str, float]:
        with self._lock:
            self.code = f"{secrets.randbelow(10**6):06d}"
            self.expires = time.time() + CODE_TTL
            self.failures = 0
            return self.code, self.expires

    def check(self, code: str) -> bool:
        with self._lock:
            if not self.code or time.time() > self.expires:
                return False
            if secrets.compare_digest(str(code).strip(), self.code):
                self.code = None          # one phone per code
                return True
            self.failures += 1
            if self.failures >= MAX_FAILURES:
                self.code = None
            return False


def lan_addresses() -> list[str]:
    """IPv4 addresses a phone on the same Wi-Fi could reach, most likely first."""
    found = []
    try:
        out = subprocess.run(["ip", "-o", "-4", "addr", "show", "up"], capture_output=True, text=True, timeout=3).stdout
        for line in out.splitlines():
            parts = line.split()
            iface, addr = parts[1], parts[3].split("/")[0]
            if iface == "lo" or iface.startswith(("docker", "br-", "veth", "virbr")):
                continue
            found.append(addr)
    except (OSError, subprocess.SubprocessError):
        pass
    try:   # the address used for the default route
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        found.insert(0, s.getsockname()[0])
        s.close()
    except OSError:
        pass
    out, seen = [], set()
    for a in found:
        try:
            ip = ipaddress.ip_address(a)
        except ValueError:
            continue
        if ip.is_loopback or a in seen:
            continue
        seen.add(a)
        out.append(a)
    # NetworkManager hotspots use 10.42.0.1; list it first when present
    out.sort(key=lambda a: (not a.startswith("10.42."), not ipaddress.ip_address(a).is_private))
    return out


def pair_link(urls: list[str], code: str, name: str) -> str:
    q = "&".join(f"u={quote(u, safe='')}" for u in urls)
    return f"lineguard://pair?c={code}&n={quote(name, safe='')}&{q}"
