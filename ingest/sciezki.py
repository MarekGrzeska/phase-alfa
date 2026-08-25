"""Ścieżki wspólne dla runnera, mirrora i testów — w JEDNYM miejscu.

Reguła jest jedna i była wcześniej powielona w czterech plikach, każdy z własną
liczbą wywołań `dirname` dobraną do swojej głębokości: przeniesienie któregokolwiek
z nich psuło po cichu tylko tę jedną kopię.

Reguła: `MIRROR_ROOT` ze środowiska (`.env`); ścieżkę względną liczymy od KORZENIA
REPOZYTORIUM, nie od katalogu roboczego. Taskfile woła moduły z `ingest/`, więc
`../cke-mirror` z `.env` liczone od katalogu roboczego wskazywałoby
`phase-alfa/cke-mirror` — katalog, którego nie ma.
"""
from __future__ import annotations

import os
from pathlib import Path

# ingest/sciezki.py → ingest/ → korzeń repozytorium
KORZEN_REPO = Path(__file__).resolve().parents[1]


def korzen_mirrora() -> Path:
    """Katalog, w którym leżą `data/index/urls.tsv` i `data/raw/`.

    Mirror bywa poza tym repozytorium (zasada „mirror raz, potem tylko kopia"),
    więc ścieżka idzie z konfiguracji, a nie z układu katalogów.
    """
    korzen = os.environ.get("MIRROR_ROOT", ".")
    p = Path(korzen)
    return p if p.is_absolute() else (KORZEN_REPO / p).resolve()


def spis_urls() -> Path:
    """Spis zwiezionych plików — wejście parsera, wyjście mirrora."""
    return korzen_mirrora() / "data" / "index" / "urls.tsv"
