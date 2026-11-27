# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenWorks IT (Pty) Ltd
"""Regenerate the files that come from LineGuard's data format definition:
docs/data-format.md and the Power Query files in integrations/powerbi/queries/.
Run after changing lineguard/opendata.py:  python integrations/generate.py"""
from pathlib import Path

from lineguard import opendata

ROOT = Path(__file__).resolve().parent.parent


def files() -> dict[Path, str]:
    out = {ROOT / "docs" / "data-format.md": opendata.markdown(),
           ROOT / "integrations" / "powerbi" / "queries" / "LineGuardTable.pq": opendata.power_query_function()}
    for name in opendata.TABLES:
        out[ROOT / "integrations" / "powerbi" / "queries" / f"{name}.pq"] = opendata.power_query(name)
    return out


if __name__ == "__main__":
    for path, text in files().items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        print(path.relative_to(ROOT))
