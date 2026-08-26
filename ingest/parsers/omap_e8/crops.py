#!/usr/bin/env python3
"""Wycinki PNG dla zasobów korpusu — cięcie i sprzątanie bloba (G2.4.1).

Cięcie stoi POZA transakcją ładowania i dlatego jest tu, a nie w `loader.py`:
dysk nie cofa się razem z transakcją, więc plik wycięty przed nieudanym
zapisem zostawałby na miejscu z ramką, której w bazie nie ma. Ta sama lekcja
co w ekranie korekty (`correction/db.py`).

Sprzątanie bloba jest w tym samym narzędziu, bo `task db:reset` kasuje wolumen
Postgresa, a pliki PNG w `data/blob` zostawia — po resecie ścieżki w świeżej
bazie i pliki na dysku rozjeżdżają się po cichu. Reguła z A1: czyszczenie robi
narzędzie, nie `rm` w Taskfile (na Windows go zresztą nie ma).
"""

from __future__ import annotations

import argparse
import re
import sys

import psycopg
from psycopg.rows import dict_row

from pdf import crop as crop_pdf
from schema.migrate import polaczenie

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# Kształt ścieżki z `loader.py`: kod/sesja/wariant/wersja/zNR-I.png. Korzeń
# blobów dzielimy z `DiskBlobStore`, więc sprzątanie musi poznać SWOJE pliki.
CROP_PATH = re.compile(r"[^/]+/[^/]+/[^/]+/[^/]+/z[^/]+-\d+\.png$")

# Parser wstawia ramkę „cała strona" z zerem w lewym górnym rogu, gdy automat
# nie domknął regionu. Takiego zasobu NIE tniemy: wycinkiem byłby cały arkusz,
# a w ekranie korekty wyglądałby na gotowy. Ramkę dociąga wtedy człowiek (G2.4.2).
SQL_ASSETS = """
    SELECT a.id, a.path, a.page, a.bbox, p.path AS paper_path
    FROM asset a
    JOIN task_version tv ON tv.id = a.task_version_id
    JOIN task t ON t.id = tv.task_id
    LEFT JOIN document p ON p.id = tv.paper_id
    WHERE (%(document)s::int IS NULL OR t.marking_scheme_id = %(document)s)
    ORDER BY a.id"""


def whole_page(bbox) -> bool:
    return float(bbox[0]) == 0.0 and float(bbox[1]) == 0.0


def assets(cur, document: int | None = None) -> list[dict]:
    cur.execute(SQL_ASSETS, {"document": document})
    return cur.fetchall()


def cut_missing(con, document: int | None = None, force: bool = False) -> dict:
    """Tnie wycinki dla zasobów z dociągniętą ramką. Idempotentne."""
    summary = {"total": 0, "framed": 0, "manual": 0, "cut": 0, "kept": 0,
               "no_paper": 0, "failed": []}
    with con.cursor(row_factory=dict_row) as cur:
        rows = assets(cur, document)
    for row in rows:
        summary["total"] += 1
        if whole_page(row["bbox"]):
            summary["manual"] += 1
            continue
        summary["framed"] += 1
        if row["paper_path"] is None:
            summary["no_paper"] += 1
            continue
        try:
            target = crop_pdf.target_path(row["path"])
        except crop_pdf.CropError as e:
            summary["failed"].append((row["path"], str(e)))
            continue
        if target.exists() and not force:
            summary["kept"] += 1
            continue
        try:
            crop_pdf.crop(_paper(row["paper_path"]), row["page"],
                          tuple(float(v) for v in row["bbox"]), row["path"])
        except crop_pdf.CropError as e:
            summary["failed"].append((row["path"], str(e)))
            continue
        summary["cut"] += 1
    return summary


def _paper(relative_path: str):
    """Zeszyt zadań z mirrora — ta sama ochrona ścieżki co w ekranie korekty.

    `PageUnavailable` wychodzi jako `CropError`, bo dla wołającego to ten sam
    wypadek; we własnym typie leciał przez `cut_missing` i zabierał raport.
    """
    from correction.pages import PageUnavailable, source_pdf
    try:
        return source_pdf(relative_path)
    except PageUnavailable as e:
        raise crop_pdf.CropError(str(e)) from e


def orphans(con) -> list[str]:
    """Wycinki w blobie, do których nie prowadzi żaden wiersz `asset`.

    Sito jest podwójne — kształt ścieżki ORAZ brak w bazie. Plik nierozpoznany
    jako nasz wycinek zostaje.
    """
    root = crop_pdf.blob_root()
    if not root.exists():
        return []
    with con.cursor() as cur:
        cur.execute("SELECT path FROM asset")
        known = {p.replace("\\", "/") for (p,) in cur.fetchall()}
    found = (f.relative_to(root).as_posix() for f in root.rglob("*") if f.is_file())
    return sorted(p for p in found if CROP_PATH.match(p) and p not in known)


def report(summary: dict) -> str:
    rule = "─" * 74
    lines = [
        "WYCINKI GRAFICZNE",
        rule,
        f"  zasobów razem              : {summary['total']}",
        f"  ramka z automatu (G2.4.1)  : {summary['framed']}",
        f"  cała strona — ramka ręczna : {summary['manual']}",
        f"  wyciętych w tym przebiegu  : {summary['cut']}",
        f"  już było na dysku          : {summary['kept']}",
    ]
    if summary["no_paper"]:
        lines.append(f"  bez zeszytu w bazie        : {summary['no_paper']}"
                     "  (przeładuj klucz z --with-papers)")
    if summary["failed"]:
        lines.append(f"  BŁĘDY CIĘCIA               : {len(summary['failed'])}")
        for path, why in summary["failed"][:5]:
            lines.append(f"    ↳ {path}: {why}")
    # Warunek na `total`, a NIE na `framed`: przebieg bez ani jednej ramki
    # z automatu to ten, w którym ta linia jest najbardziej potrzebna.
    if summary["total"]:
        share = 100 * summary["manual"] / summary["total"]
        lines.append(f"  do ręcznego dociągnięcia   : {share:.0f}% zasobów")
    return "\n".join(lines)


def _prune(con, delete: bool) -> int:
    """Osierocone wycinki: najpierw lista, kasowanie dopiero na `--yes`.

    Kasowanie nie ma wycofania, a lista bierze się z bazy — pomylony
    `DATABASE_URL` wskazuje pustą bazę i KAŻDY wycinek jest wtedy osierocony.
    """
    to_delete = orphans(con)
    root = crop_pdf.blob_root()
    if not to_delete:
        print("Osieroconych wycinków nie ma.")
        return 0

    if not delete:
        print(f"Osieroconych wycinków: {len(to_delete)} (nic nie skasowano)")
        for relative in to_delete[:10]:
            print(f"  - {relative}")
        if len(to_delete) > 10:
            print(f"  … i jeszcze {len(to_delete) - 10}")
        print("Kasowanie: task crops -- --prune --yes")
        return 0

    removed, failed = 0, []
    for relative in to_delete:
        try:
            # Plik mógł zniknąć między listą a kasowaniem — to nie powód,
            # żeby przerwać sprzątanie w połowie.
            (root / relative).unlink(missing_ok=True)
            removed += 1
        except OSError as e:
            failed.append((relative, str(e)))
    print(f"Osieroconych wycinków skasowanych: {removed} z {len(to_delete)}")
    for relative, why in failed[:5]:
        print(f"  ! {relative}: {why}")
    return 1 if failed else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true",
                    help="przetnij od nowa także te, które mają już plik")
    ap.add_argument("--prune", action="store_true",
                    help="pokaż osierocone wycinki — pliki w blobie, do których "
                         "nie prowadzi żaden zasób (po `task db:reset` blob "
                         "zostaje, a baza jest pusta). Samo w sobie nic nie kasuje")
    ap.add_argument("--yes", action="store_true",
                    help="skasuj to, co wypisał --prune")
    args = ap.parse_args()

    with psycopg.connect(polaczenie(), autocommit=True) as con:
        if args.prune:
            return _prune(con, delete=args.yes)
        print(report(cut_missing(con, force=args.force)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
