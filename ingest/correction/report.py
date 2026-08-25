#!/usr/bin/env python3
"""Raport korekty do pliku — te same liczby co na stronie głównej ekranu.

Osobne wejście, bo pomiar S8 ma dać się porównać między dniami, a porównanie
„z pamięci" nie jest porównaniem — ta sama zasada, co przy raporcie ingestu.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from correction import db, stats
from sciezki import KORZEN_REPO

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", default=None,
                    help="gdzie zapisać (domyślnie data/reports/correction-RRRR-MM-DD.txt)")
    args = ap.parse_args()

    with db.connect() as con, con.cursor() as cur:
        text = stats.as_text(stats.collect(cur))

    default = KORZEN_REPO / "data" / "reports" / f"correction-{time.strftime('%Y-%m-%d')}.txt"
    path = Path(args.report or default)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(text)
    print(f"Raport zapisany: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
