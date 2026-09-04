#!/usr/bin/env python3
"""Raport kompletności korpusu — domknięcie kamienia A2 (G2.7).

Definicja „zrobione" dla A2 sprawdzana ZAPYTANIAMI, nie wrażeniem, i liczona
po widoku `corpus_task`, nie po `task`: rekord `pending` albo `rejected` nie
jest korpusem, choć siedzi w tej samej tabeli.

Kolumna „sparsowane" stoi obok „w korpusie" celowo. Bez niej raport z pustego
korpusu wygląda tak samo jak raport z korpusu, którego nikt nie sparsował —
a to jest dokładnie ta różnica, którą A2 domyka.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from correction import stats
from schema.migrate import polaczenie
from sciezki import KORZEN_REPO

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

RULE = "─" * 74

# Każda pozycja definicji „zrobione" jako para zapytań: ile w korpusie, ile
# w całości sparsowanego materiału. `%(scope)s` podstawia widok albo tabelę.
CHECKS = (
    ("zadania", """
        SELECT count(*) FROM {scope} t"""),
    ("zadania z bliźniakiem X/Y", """
        SELECT count(*) FROM {scope} t
        WHERE EXISTS (SELECT 1 FROM twins w WHERE w.task_id = t.id)"""),
    ("zadania z wymaganiem podstawy", """
        SELECT count(*) FROM {scope} t
        WHERE EXISTS (SELECT 1 FROM task_requirement tr WHERE tr.task_id = t.id)"""),
    ("zadania otwarte z kryteriami", """
        SELECT count(*) FROM {scope} t
        WHERE t.kind <> 'closed'
          AND EXISTS (SELECT 1 FROM criterion c WHERE c.task_id = t.id)"""),
    ("kryteria z ≥1 warunkiem", """
        SELECT count(*) FROM criterion c
        JOIN {scope} t ON t.id = c.task_id
        WHERE EXISTS (SELECT 1 FROM criterion_condition cc
                       WHERE cc.criterion_id = c.id)"""),
    ("warunki z zapisem równoważnym", """
        SELECT count(*) FROM criterion_condition cc
        JOIN criterion c ON c.id = cc.criterion_id
        JOIN {scope} t ON t.id = c.task_id
        WHERE EXISTS (SELECT 1 FROM condition_expression ce
                       WHERE ce.condition_id = cc.id)"""),
    ("zapisy z MathJSON (auto/approved)", """
        SELECT count(*) FROM condition_expression ce
        JOIN criterion_condition cc ON cc.id = ce.condition_id
        JOIN criterion c ON c.id = cc.criterion_id
        JOIN {scope} t ON t.id = c.task_id
        WHERE ce.mathjson_status IN ('auto', 'approved')"""),
    ("zapisy świadomie `failed`", """
        SELECT count(*) FROM condition_expression ce
        JOIN criterion_condition cc ON cc.id = ce.condition_id
        JOIN criterion c ON c.id = cc.criterion_id
        JOIN {scope} t ON t.id = c.task_id
        WHERE ce.mathjson_status = 'failed'"""),
    ("zadania zamknięte z odpowiedzią", """
        SELECT count(*) FROM {scope} t
        WHERE t.kind = 'closed'
          AND EXISTS (SELECT 1 FROM task_version tv
                        JOIN model_answer m ON m.task_version_id = tv.id
                       WHERE tv.task_id = t.id)"""),
    ("zadania z zasobem graficznym", """
        SELECT count(*) FROM {scope} t
        WHERE EXISTS (SELECT 1 FROM task_version tv JOIN asset a
                        ON a.task_version_id = tv.id WHERE tv.task_id = t.id)"""),
    ("zasoby z ramką węższą niż strona", """
        SELECT count(*) FROM asset a
        JOIN task_version tv ON tv.id = a.task_version_id
        JOIN {scope} t ON t.id = tv.task_id
        WHERE NOT (a.bbox[1] = 0 AND a.bbox[2] = 0)"""),
    ("zasoby z opisem zatwierdzonym", """
        SELECT count(*) FROM asset a
        JOIN task_version tv ON tv.id = a.task_version_id
        JOIN {scope} t ON t.id = tv.task_id
        WHERE a.description_status IN ('approved', 'corrected')"""),
    ("reguły arkusza z zakresem zadań", """
        SELECT count(*) FROM rule r
        WHERE r.tasks_from IS NOT NULL
          AND EXISTS (SELECT 1 FROM {scope} t
                       WHERE t.marking_scheme_id = r.marking_scheme_id)"""),
)

# Dziury, których żaden licznik „ile jest" nie pokaże — pytania o BRAK.
GAPS = (
    ("zadania bez wymagania podstawy", """
        SELECT count(*) FROM {scope} t
        WHERE NOT EXISTS (SELECT 1 FROM task_requirement tr WHERE tr.task_id = t.id)"""),
    ("zadania otwarte bez kryteriów", """
        SELECT count(*) FROM {scope} t
        WHERE t.kind <> 'closed'
          AND NOT EXISTS (SELECT 1 FROM criterion c WHERE c.task_id = t.id)"""),
    ("zasoby z ramką „cała strona”", """
        SELECT count(*) FROM asset a
        JOIN task_version tv ON tv.id = a.task_version_id
        JOIN {scope} t ON t.id = tv.task_id
        WHERE a.bbox[1] = 0 AND a.bbox[2] = 0"""),
    ("zasoby bez zatwierdzonego opisu", """
        SELECT count(*) FROM asset a
        JOIN task_version tv ON tv.id = a.task_version_id
        JOIN {scope} t ON t.id = tv.task_id
        WHERE a.description_status NOT IN ('approved', 'corrected')"""),
    ("zapisy bez MathJSON i bez decyzji", """
        SELECT count(*) FROM condition_expression ce
        JOIN criterion_condition cc ON cc.id = ce.condition_id
        JOIN criterion c ON c.id = cc.criterion_id
        JOIN {scope} t ON t.id = c.task_id
        WHERE ce.mathjson_status = 'none'"""),
    ("wymagania bez ani jednego zadania", """
        SELECT count(*) FROM requirement r
        WHERE r.kind = 'specific'
          AND NOT EXISTS (SELECT 1 FROM task_requirement tr
                            JOIN {scope} t ON t.id = tr.task_id
                           WHERE tr.requirement_id = r.id)"""),
)


def _both(con, sql: str) -> tuple[int, int]:
    """Ta sama liczba po korpusie i po całości sparsowanego materiału."""
    return (con.execute(sql.format(scope="corpus_task")).fetchone()[0],
            con.execute(sql.format(scope="task")).fetchone()[0])


def per_year(cur) -> list[dict]:
    cur.execute(
        """SELECT d.year,
                  count(*)                                        AS parsed,
                  count(*) FILTER (WHERE t.review_status = 'approved')  AS approved,
                  count(*) FILTER (WHERE t.review_status = 'corrected') AS corrected,
                  count(*) FILTER (WHERE t.review_status = 'rejected')  AS rejected,
                  count(*) FILTER (WHERE t.review_status = 'pending')   AS pending,
                  count(*) FILTER (WHERE t.review_status IN ('approved', 'corrected')
                                     AND t.reviewed_by = 'model')     AS by_model,
                  count(*) FILTER (WHERE t.review_status = 'pending' AND EXISTS (
                      SELECT 1 FROM correction_event e
                       WHERE e.task_id = t.id AND e.action = 'unsure')) AS unsure
           FROM task t
           JOIN document d ON d.id = t.marking_scheme_id
           GROUP BY d.year ORDER BY d.year"""
    )
    return cur.fetchall()


def by_actor(cur) -> dict:
    """Kto rozstrzygnął korpus — liczby do wniosku po planie A2-auto (S8′)."""
    cur.execute(
        """SELECT reviewed_by, review_model, count(*) AS n
           FROM corpus_task c JOIN task t ON t.id = c.id
           GROUP BY reviewed_by, review_model ORDER BY n DESC"""
    )
    rows = cur.fetchall()
    cur.execute("SELECT count(*) AS n FROM task t WHERE t.review_status = 'pending' AND EXISTS "
                "(SELECT 1 FROM correction_event e WHERE e.task_id = t.id AND e.action = 'unsure')")
    unsure = cur.fetchone()["n"]
    return {"rows": rows, "unsure": unsure,
            "total": sum(r["n"] for r in rows),
            "model": sum(r["n"] for r in rows if r["reviewed_by"] == "model")}


def build(con) -> str:
    lines = [
        f"KORPUS A2 — RAPORT KOMPLETNOŚCI · {time.strftime('%Y-%m-%d %H:%M')}",
        RULE,
        "Kolumna „korpus” liczy po widoku `corpus_task` (zatwierdzone",
        "i poprawione). Kolumna „sparsowane” — po całej tabeli `task`.",
        "Różnica między nimi to praca, która została do zrobienia w ekranie korekty.",
        "",
        "DEFINICJA „ZROBIONE” DLA A2",
        RULE,
        f"  {'sprawdzian':<38} {'korpus':>9} {'sparsowane':>12}",
    ]
    for label, sql in CHECKS:
        in_corpus, parsed = _both(con, sql)
        lines.append(f"  {label:<38} {in_corpus:>9} {parsed:>12}")

    lines += ["", "DZIURY — PYTANIA O BRAK", RULE,
              f"  {'sprawdzian':<38} {'korpus':>9} {'sparsowane':>12}"]
    for label, sql in GAPS:
        in_corpus, parsed = _both(con, sql)
        lines.append(f"  {label:<38} {in_corpus:>9} {parsed:>12}")

    lines += ["", "POSTĘP KOREKTY PER ROCZNIK", RULE,
              f"  {'rocznik':<8} {'sparsow.':>9} {'bez zmian':>10} {'poprawione':>11}"
              f" {'odrzuc.':>8} {'czeka':>7} {'model':>7} {'unsure':>7}"]
    with con.cursor(row_factory=dict_row) as cur:
        years = per_year(cur)
        numbers = stats.collect(cur)
        actors = by_actor(cur)
    for row in years:
        lines.append(f"  {row['year']:<8} {row['parsed']:>9} {row['approved']:>10}"
                     f" {row['corrected']:>11} {row['rejected']:>8} {row['pending']:>7}"
                     f" {row['by_model']:>7} {row['unsure']:>7}")

    # Plan A2-auto: korpus rozstrzygany modelem, człowiek na próbce. Kolumna
    # „model" wyżej i ta sekcja to S8′ — bez nich raport nie odróżnia korekty
    # ręcznej od automatu, a to jest liczba do wniosku.
    lines += ["", "KTO ROZSTRZYGNĄŁ KORPUS (plan A2-auto)", RULE]
    for r in actors["rows"]:
        who = r["reviewed_by"] + (f" ({r['review_model']})" if r["review_model"] else "")
        lines.append(f"  {who:<40} {r['n']:>7}")
    if actors["total"]:
        lines.append(f"  udział modelu w korpusie : "
                     f"{100 * actors['model'] / actors['total']:.1f}%")
    lines.append(f"  unsure — czeka na człowieka : {actors['unsure']}")

    lines += ["", "LICZBY DO WNIOSKU — S6, S7, S8", RULE, ""]
    lines += stats.s6_lines(numbers["s6"], RULE)
    lines += [""]
    lines += stats.s7_lines(numbers["s7"], RULE)
    lines += ["", "S8 — KOSZT PÓŁAUTOMATU", RULE,
              f"  rozstrzygnięć w dzienniku : {numbers['durations']['events']}",
              f"  trafienia parsera         : "
              f"{100 * numbers['status']['hit_share']:.1f}% rekordów korpusu",
              f"  mediana na zadanie        : {numbers['durations']['median']:.0f} s",
              f"  suma czasu korekty        : {numbers['durations']['total'] / 3600:.1f} h",
              f"  zostało                   : {numbers['forecast']['tasks']} zadań"
              f" ≈ {numbers['forecast']['hours']:.1f} h"]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report", default=None,
                    help="gdzie zapisać (domyślnie data/reports/corpus-A2-RRRR-MM-DD.txt)")
    ap.add_argument("--copy-to-docs", action="store_true",
                    help="dodatkowo do docs/corpus-A2.txt — `data/` jest poza gitem, "
                         "więc raport zbiorczy musi mieć kopię w repozytorium")
    args = ap.parse_args()

    with psycopg.connect(polaczenie()) as con:
        text = build(con)

    path = Path(args.report or (KORZEN_REPO / "data" / "reports"
                                / f"corpus-A2-{time.strftime('%Y-%m-%d')}.txt"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(text)
    print(f"Raport zapisany: {path}")
    if args.copy_to_docs:
        docs = KORZEN_REPO / "docs" / "corpus-A2.txt"
        docs.write_text(text, encoding="utf-8")
        print(f"Kopia w repozytorium: {docs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
