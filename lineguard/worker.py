# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenWorks IT (Pty) Ltd
"""Background worker: watches the inbox for new flight folders and processes queued flights."""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from .pipeline import process
from .store import Store

log = logging.getLogger("lineguard")

SETTLE_SECONDS = 20   # a folder must stop changing for this long before it is picked up (card still copying)


def _folder_signature(folder: Path):
    files = [p for p in folder.rglob("*") if p.is_file()]
    return len(files), sum(p.stat().st_size for p in files), max((p.stat().st_mtime for p in files), default=0)


class Worker(threading.Thread):
    def __init__(self, store: Store, settings, poll=3.0):
        super().__init__(daemon=True, name="lineguard-worker")
        self.store, self.settings, self.poll = store, settings, poll
        self._seen: dict[Path, tuple] = {}
        self._stop = threading.Event()
        self.wake = threading.Event()

    def stop(self):
        self._stop.set()
        self.wake.set()

    def scan_inbox(self):
        inbox = self.settings.inbox_dir
        if not inbox.is_dir():
            return
        for folder in sorted(p for p in inbox.iterdir() if p.is_dir() and not p.name.startswith(".")):
            if self.store.folder_known(folder):
                continue
            sig = _folder_signature(folder)
            if sig[0] == 0:
                continue
            prev = self._seen.get(folder)
            self._seen[folder] = sig
            if prev == sig and time.time() - sig[2] > SETTLE_SECONDS:
                fid = self.store.add_flight(folder.name, folder)
                log.info("queued flight %s from inbox: %s", fid, folder)

    def run(self):
        self.store.reset_interrupted()
        while not self._stop.is_set():
            try:
                self.scan_inbox()
                for f in self.store.queued():
                    if self._stop.is_set():
                        break
                    process(self.store, self.settings, f["id"])
            except Exception:
                log.exception("worker loop error")
            self.wake.wait(self.poll)
            self.wake.clear()
