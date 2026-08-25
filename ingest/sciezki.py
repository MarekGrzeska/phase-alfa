"""Ścieżki wspólne dla runnera, mirrora i testów — w JEDNYM miejscu."""
from __future__ import annotations

import os
from pathlib import Path

# ingest/sciezki.py → ingest/ → korzeń repozytorium
KORZEN_REPO = Path(__file__).resolve().parents[1]


def korzen_mirrora() -> Path:
    """Katalog z `data/index/urls.tsv` i `data/raw/`."""
    korzen = os.environ.get("MIRROR_ROOT", ".")
    p = Path(korzen)
    return p if p.is_absolute() else (KORZEN_REPO / p).resolve()


def spis_urls() -> Path:
    """Spis zwiezionych plików — wejście parsera, wyjście mirrora."""
    return korzen_mirrora() / "data" / "index" / "urls.tsv"
