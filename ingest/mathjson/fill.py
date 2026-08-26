#!/usr/bin/env python3
"""Wypełnianie `condition_expression.mathjson` (G2.6).

Zapis z klucza → LaTeX (`normalize.to_latex`) → Compute Engine w Node
(`convert.mjs`) → MathJSON w bazie. Rozdział ról jest celowy: normalizacja
stoi w Pythonie, bo tam da się ją przetestować bez Node'a, a parsowanie
w Node, bo `@cortex-js/compute-engine` jest referencyjną implementacją
MathJSON i tym samym silnikiem, którego użyje EvaluateClosed w A3.

Odmowa normalizacji NIE woła Node'a: zdanie po polsku nie ma być parsowane
jako iloczyn liter, tylko dostać `failed` z powodem.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from mathjson import normalize
from schema.migrate import polaczenie
from sciezki import KORZEN_REPO

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
CONVERTER = HERE / "convert.mjs"

# Zakres pracy jak w ekranie korekty i w runnerze parsera: rocznik i wariant.
# Pilot G2.6 idzie na roczniku 2025, a nie na 514 zapisach naraz.
SQL_EXPRESSIONS = """
    SELECT ce.id, ce.expression, ce.mathjson_status
    FROM condition_expression ce
    JOIN criterion_condition cc ON cc.id = ce.condition_id
    JOIN criterion c ON c.id = cc.criterion_id
    JOIN task t ON t.id = c.task_id
    JOIN document d ON d.id = t.marking_scheme_id
    WHERE (%(year)s::smallint IS NULL OR d.year = %(year)s)
      AND (%(variant)s::text IS NULL
           OR %(variant)s = ANY(string_to_array(d.variants, ',')))
      AND (%(force)s OR ce.mathjson_status IN ('none', 'failed'))
    ORDER BY ce.id"""


class ConverterUnavailable(RuntimeError):
    """Node albo zależności konwertera nie ma — z instrukcją, co zrobić."""


def check_converter() -> None:
    if shutil.which("node") is None:
        raise ConverterUnavailable(
            "BRAK: node. Konwerter MathJSON stoi na @cortex-js/compute-engine "
            "(Node jest i tak wymaganiem repozytorium — patrz `task setup`).")
    if not (HERE / "node_modules").exists():
        raise ConverterUnavailable(
            "BRAK zależności konwertera. Uruchom: "
            "pnpm -C ingest/mathjson install --ignore-workspace")


def run_converter(records: list[dict]) -> dict[int, dict]:
    """NDJSON w jednym przebiegu, nie proces na zapis — start Node'a to ~200 ms."""
    if not records:
        return {}
    check_converter()
    stdin = "\n".join(json.dumps(r, ensure_ascii=False) for r in records)
    # S603/S607: uruchamiamy WŁASNY skrypt spod stałej ścieżki, bez powłoki
    # i bez danych z zewnątrz w wierszu poleceń — wyrażenia jadą przez stdin.
    # `node` po nazwie, nie po ścieżce, bo repozytorium wymaga go w PATH
    # (`task setup`) i tak samo woła go pnpm oraz generator klienta OpenAPI.
    result = subprocess.run(  # noqa: S603
        ["node", str(CONVERTER)], input=stdin, capture_output=True,  # noqa: S607
        text=True, encoding="utf-8", cwd=str(HERE), check=False,
    )
    if result.returncode != 0:
        raise ConverterUnavailable(
            f"convert.mjs zakończył się kodem {result.returncode}:\n{result.stderr}")
    out: dict[int, dict] = {}
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        parsed = json.loads(line)
        if parsed.get("id") is not None:
            out[int(parsed["id"])] = parsed
    return out


def fill(con, year: int | None = None, variant: str | None = None,
         force: bool = False) -> dict:
    with con.cursor(row_factory=dict_row) as cur:
        cur.execute(SQL_EXPRESSIONS, {"year": year, "variant": variant, "force": force})
        rows = cur.fetchall()

    to_convert: list[dict] = []
    refused: list[tuple[int, str]] = []
    for row in rows:
        latex, why = normalize.to_latex(row["expression"])
        if latex is None:
            refused.append((row["id"], why))
        else:
            to_convert.append({"id": row["id"], "latex": latex})

    converted = run_converter(to_convert)

    summary = {"considered": len(rows), "auto": 0, "failed": 0,
               "reasons": {}, "examples": []}
    with con.cursor() as cur:
        for expression_id, why in refused:
            _mark_failed(cur, expression_id, why, summary)
        for record in to_convert:
            answer = converted.get(record["id"])
            if answer is None:
                _mark_failed(cur, record["id"],
                             "konwerter nie oddał wyniku dla tego zapisu", summary)
            elif "error" in answer:
                _mark_failed(cur, record["id"],
                             f"Compute Engine: {answer['error']}"[:400], summary)
            else:
                cur.execute(
                    """UPDATE condition_expression
                       SET mathjson = %s, mathjson_status = 'auto', mathjson_error = NULL
                       WHERE id = %s""",
                    (Jsonb(answer["mathjson"]), record["id"]),
                )
                summary["auto"] += 1
    return summary


def _mark_failed(cur, expression_id: int, why: str, summary: dict) -> None:
    cur.execute(
        """UPDATE condition_expression
           SET mathjson_status = 'failed', mathjson_error = %s
           WHERE id = %s""",
        (why, expression_id),
    )
    summary["failed"] += 1
    # Powód skrócony do pierwszego nawiasu — inaczej każdy zapis ma własną
    # kategorię i podsumowanie nie mówi, CO trzeba naprawić najpierw.
    label = why.split("(")[0].split("„")[0].strip(" :,")
    summary["reasons"][label] = summary["reasons"].get(label, 0) + 1
    if len(summary["examples"]) < 8:
        summary["examples"].append((expression_id, why))


def counts(con) -> dict[str, int]:
    with con.cursor() as cur:
        cur.execute("SELECT mathjson_status, count(*) FROM condition_expression"
                    " GROUP BY mathjson_status")
        found = dict(cur.fetchall())
    return {status: found.get(status, 0)
            for status in ("none", "auto", "approved", "failed")}


def report(summary: dict, totals: dict[str, int]) -> str:
    rule = "─" * 74
    covered = totals["auto"] + totals["approved"]
    total = sum(totals.values())
    lines = [
        "MATHJSON — KONWERSJA ZAPISÓW RÓWNOWAŻNYCH",
        rule,
        f"  zapisów w korpusie     : {total}",
        f"  wzięte w tym przebiegu : {summary['considered']}",
        f"  przekonwertowane teraz : {summary['auto']}",
        f"  odmowy teraz           : {summary['failed']}",
        "",
        f"  auto                   : {totals['auto']}",
        f"  zatwierdzone przez człowieka : {totals['approved']}",
        f"  failed (robota ręczna) : {totals['failed']}",
        f"  jeszcze nie próbowano  : {totals['none']}",
        f"  pokrycie MathJSON-em   : {100 * covered / total if total else 0:.1f}%",
    ]
    if summary["reasons"]:
        lines += ["", "POWODY ODMOWY", rule]
        for label, n in sorted(summary["reasons"].items(), key=lambda p: -p[1]):
            lines.append(f"  {n:5d}  {label}")
    if summary["examples"]:
        lines += ["", "PRZYKŁADY", rule]
        for expression_id, why in summary["examples"]:
            lines.append(f"  #{expression_id}: {why}")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, default=None, help="tylko ten rocznik")
    ap.add_argument("--variant", default=None, help="tylko ten wariant, np. 100")
    ap.add_argument("--force", action="store_true",
                    help="przelicz także te, które mają już MathJSON "
                         "(zatwierdzonych przez człowieka to NIE cofa)")
    ap.add_argument("--report", default=None,
                    help="gdzie zapisać (domyślnie data/reports/mathjson-RRRR-MM-DD.txt)")
    args = ap.parse_args()

    with psycopg.connect(polaczenie(), autocommit=True) as con:
        if args.force:
            # `approved` znaczy „człowiek to sprawdził" — przeliczenie skasowałoby
            # jego pracę, a jest ona w tym kamieniu najdroższym zasobem.
            with con.cursor() as cur:
                cur.execute("UPDATE condition_expression SET mathjson_status = 'none'"
                            " WHERE mathjson_status IN ('auto', 'failed')")
        try:
            summary = fill(con, args.year, args.variant, force=False)
        except ConverterUnavailable as e:
            print(e)
            return 2
        text = report(summary, counts(con))

    path = Path(args.report or (KORZEN_REPO / "data" / "reports"
                                / f"mathjson-{time.strftime('%Y-%m-%d')}.txt"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(text)
    print(f"Raport zapisany: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
