"""Mirror — przebieg na sucho i domyślny korzeń.

Plan G1.2.3 zamyka się zdaniem „zrobione, gdy `task mirror -- --dry-run`
przechodzi". Dopóki tej flagi nie było, kryterium odbioru zostawało zdaniem
w planie, którego nie dało się uruchomić.

Testy chodzą bez mirrora i bez sieci: budują własny korzeń w katalogu
tymczasowym, z jednym wierszem spisu wskazującym na nieistniejący plik.
Gdyby przebieg na sucho jednak sięgnął po sieć, adres `127.0.0.1:1` odmówi
połączenia natychmiast, a plik i tak nie powstanie — i to sprawdza asercja.
"""

from __future__ import annotations

import csv
import os
import subprocess
import sys
from pathlib import Path

import pytest

from mirror import cke_mirror
from sciezki import KORZEN_REPO

INGEST = Path(__file__).resolve().parents[1]

WIERSZ = {
    "segment": "e8", "rocznik": "2025", "rocznik_w_sciezce": "2025",
    "podkatalog": "matematyka", "plik": "OMAP-100-2505-zasady.pdf",
    "kod": "OMAP", "warianty": "100", "sesja": "2025-05",
    "typ": "zasady_oceniania", "zrodlo_typu": "sufiks", "wzorzec": "sufiks",
    "url": "http://127.0.0.1:1/nie-ma-mnie.pdf",
    "sciezka_lokalna": "data/raw/e8/2025/matematyka/OMAP-100-2505-zasady.pdf",
}


@pytest.fixture()
def korzen(tmp_path: Path) -> Path:
    """Korzeń mirrora ze spisem na jeden plik, którego na dysku nie ma."""
    spis = tmp_path / "data" / "index" / "urls.tsv"
    spis.parent.mkdir(parents=True)
    with spis.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(WIERSZ), delimiter="\t")
        w.writeheader()
        w.writerow(WIERSZ)
    return tmp_path


def _uruchom(korzen: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "mirror.cke_mirror", "--katalog", str(korzen),
         "--cicho", *args],
        cwd=INGEST, capture_output=True, text=True, encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"}, check=False, timeout=120,
    )


def test_dry_run_nie_pobiera_ani_jednego_pliku(korzen: Path):
    """Kryterium odbioru G1.2.3: przebieg na sucho ma wypisać raport i nic więcej."""
    wynik = _uruchom(korzen, "--dry-run", "--filtr", "matematyka")

    assert "unrecognized arguments" not in wynik.stderr, "flaga --dry-run zniknęła"
    assert wynik.returncode == 1, "brakujący plik ma dać kod 1 (raport niepełny)"
    assert "OMAP-100-2505-zasady.pdf" in (wynik.stdout + wynik.stderr)
    pobrane = list((korzen / "data" / "raw").rglob("*.pdf"))
    assert pobrane == [], f"przebieg na sucho jednak pobierał: {pobrane}"


def test_dry_run_to_alias_tylko_raportu(korzen: Path):
    """Jedna flaga, dwie nazwy — plan mówi `--dry-run`, skrypt miał `--tylko-raport`."""
    a = _uruchom(korzen, "--dry-run")
    b = _uruchom(korzen, "--tylko-raport")
    assert a.returncode == b.returncode


def test_domyslny_korzen_to_ten_sam_katalog_co_u_parsera(monkeypatch, tmp_path: Path):
    """Mirror musi zwozić tam, gdzie parser szuka.

    Domyślny `--katalog` wskazywał katalog skryptu. Dopóki skrypt leżał
    w korzeniu repozytorium `cke-mirror`, było to poprawne; po awansie do
    `ingest/mirror/` mirror budował korpus w `ingest/mirror/data/`, a
    `task ingest` szukał go w korzeniu repo i mówił „brak urls.tsv".
    """
    monkeypatch.setenv("MIRROR_ROOT", ".")
    from sciezki import korzen_mirrora
    assert korzen_mirrora() == KORZEN_REPO

    monkeypatch.setenv("MIRROR_ROOT", str(tmp_path))
    assert korzen_mirrora() == tmp_path
    assert cke_mirror.Layout(korzen_mirrora()).urls_tsv == (
        tmp_path / "data" / "index" / "urls.tsv")
