"""Wycinki: sito sprzątania bloba i raport przebiegu (G2.4.1).

`--prune` kasuje pliki, a korzeń blobów dzielimy z `DiskBlobStore` po stronie
C# — sito trzeba sprawdzić tutaj, bo w produkcji sprawdzić się go już nie da.
"""

from __future__ import annotations

import pytest

from parsers.omap_e8 import crops
from pdf import crop as crop_pdf


@pytest.mark.parametrize("path", [
    "OMAP/2505/100/0/z16-0.png",
    "OMAP/2505/100/1/z18.2-3.png",
])
def test_sieve_recognises_paths_built_by_the_loader(path):
    assert crops.CROP_PATH.match(path)


@pytest.mark.parametrize("path", [
    "raporty/ingest-2026-08-26.txt",      # cudzy plik pod tym samym korzeniem
    "OMAP/2505/100/0/z16-0.pdf",          # nie PNG
    "z16-0.png",                          # bez sesji i wariantu w ścieżce
    "OMAP/2505/100/0/miniatura.png",      # PNG, ale nie z nazwy zadania
    "eksport/OMAP/2505/100/0/z16-0.png",  # poziom głębiej niż tnie loader
])
def test_sieve_leaves_everything_that_is_not_a_crop(path):
    assert not crops.CROP_PATH.match(path)


class FakeCursor:
    def __init__(self, paths):
        self._paths = paths

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, _sql):
        return None

    def fetchall(self):
        return [(p,) for p in self._paths]


class FakeConnection:
    def __init__(self, paths):
        self._paths = paths

    def cursor(self):
        return FakeCursor(self._paths)


def test_orphans_are_only_our_crops_without_a_row(tmp_path, monkeypatch):
    """Bez warunku na kształt ścieżki `--prune` kasował wszystko, na co nie
    wskazywał żaden `asset` — także to, co zapisał tam backend."""
    monkeypatch.setenv("BLOB_ROOT", str(tmp_path))
    for relative in ("OMAP/2505/100/0/z16-0.png",   # w bazie — zostaje
                     "OMAP/2505/100/0/z17-0.png",   # nasz sierota — do kasacji
                     "eksport/raport.pdf",          # cudzy — zostaje
                     "eksport/wykres.png"):         # cudzy PNG — zostaje
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x")

    found = crops.orphans(FakeConnection(["OMAP/2505/100/0/z16-0.png"]))

    assert found == ["OMAP/2505/100/0/z17-0.png"]


def test_prune_without_yes_deletes_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("BLOB_ROOT", str(tmp_path))
    orphan = tmp_path / "OMAP/2505/100/0/z17-0.png"
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(b"x")

    assert crops._prune(FakeConnection([]), delete=False) == 0

    assert orphan.exists(), "domyślne `--prune` ma tylko pokazywać"
    assert "--yes" in capsys.readouterr().out


def test_prune_with_yes_deletes_exactly_what_it_listed(tmp_path, monkeypatch):
    monkeypatch.setenv("BLOB_ROOT", str(tmp_path))
    orphan = tmp_path / "OMAP/2505/100/0/z17-0.png"
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(b"x")
    foreign = tmp_path / "eksport/wykres.png"
    foreign.parent.mkdir(parents=True)
    foreign.write_bytes(b"x")

    assert crops._prune(FakeConnection([]), delete=True) == 0

    assert not orphan.exists()
    assert foreign.exists(), "cudzy plik pod tym samym korzeniem ma zostać"


def make_summary(**over):
    base = {"total": 0, "framed": 0, "manual": 0, "cut": 0, "kept": 0,
            "no_paper": 0, "failed": []}
    return {**base, **over}


def test_report_names_manual_frames_even_when_the_detector_found_none():
    """Warunek na `framed` chował tę linię dokładnie wtedy, gdy była potrzebna."""
    text = crops.report(make_summary(total=12, framed=0, manual=12))

    assert "do ręcznego dociągnięcia   : 100% zasobów" in text


def test_report_of_an_empty_run_does_not_divide_by_zero():
    assert "do ręcznego" not in crops.report(make_summary())


def test_path_outside_the_mirror_fails_one_asset_not_the_run():
    """`PageUnavailable` we własnym typie leciał przez `cut_missing` i zabierał
    raport z całego przebiegu ingestu."""
    with pytest.raises(crop_pdf.CropError, match="poza mirror"):
        crops._paper("../../../etc/passwd")
