"""Wspólne dla generatora i oceniającego golden setu (plan A2-auto, X5).

Golden set to pliki JSON w `ingest/golden/<rok>/task-<numer>.json` — część
kontraktu między warstwami, więc kształt pliku jest tutaj, w jednym miejscu.
Provenance jest obowiązkowa: `author` i `grader` w postaci `model:<adres>`
albo `human`. Bez tego benchmark A3 nie wie, czy mierzy zgodność z człowiekiem,
czy modelu z samym sobą.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from psycopg.rows import dict_row

from correction import db
from correction.prefill import marking_text

ROOT = Path(__file__).resolve().parent

# Zeszyty od 2025 r. odsyłają do osobnej karty rozwiązań, której mirror nie ma:
# treść zadania otwartego trzeba wtedy zrekonstruować z rozwiązania przykładowego.
PLACEHOLDER = re.compile(r"ZNAJDUJE SIĘ NA KARCIE", re.I)

SQL_OPEN_TASKS = """
    SELECT t.id, t.number, t.max_points, t.kind, d.year, d.session, d.code,
           (SELECT f.code || '-' || f.variant || coalesce('-' || f.version, '')
              FROM task_version tv JOIN exam_form f ON f.id = tv.exam_form_id
             WHERE tv.task_id = t.id ORDER BY f.version NULLS FIRST LIMIT 1) AS exam_form,
           (SELECT tv.content FROM task_version tv JOIN exam_form f ON f.id = tv.exam_form_id
             WHERE tv.task_id = t.id AND tv.content IS NOT NULL
             ORDER BY f.version NULLS FIRST LIMIT 1) AS content
    FROM corpus_task c
    JOIN task t ON t.id = c.id
    JOIN document d ON d.id = t.marking_scheme_id
    WHERE t.kind <> 'closed'
      AND (%(year)s::smallint IS NULL OR d.year = %(year)s)
      AND (%(variant)s::text IS NULL
           OR %(variant)s = ANY(string_to_array(d.variants, ',')))
    ORDER BY d.year, t.position
    LIMIT %(limit)s"""


def golden_path(year: int, number: str) -> Path:
    return ROOT / str(year) / f"task-{number}.json"


def has_real_content(content: str | None) -> bool:
    return bool(content) and not PLACEHOLDER.search(content)


def load_task_context(cur, task_id: int) -> dict:
    """Wszystko, czego potrzebuje autor albo oceniający: treść, klucz, reguły, opisy."""
    cur.execute(
        """SELECT points, method, content FROM example_solution
           WHERE task_id = %s ORDER BY position, id""", (task_id,))
    solutions = cur.fetchall()
    cur.execute(
        """SELECT a.description FROM asset a
           JOIN task_version tv ON tv.id = a.task_version_id
           WHERE tv.task_id = %s AND a.description IS NOT NULL
           ORDER BY a.id""", (task_id,))
    descriptions = [r["description"] for r in cur.fetchall()]
    cur.execute(
        """SELECT r.kind, r.content, r.tasks_from, r.tasks_to, t.number
           FROM rule r JOIN task t ON t.marking_scheme_id = r.marking_scheme_id
           WHERE t.id = %s ORDER BY r.position""", (task_id,))
    rules = [r for r in cur.fetchall() if db.rule_applies(r, r["number"])]
    return {"solutions": solutions, "descriptions": descriptions,
            "rules": [r["content"] for r in rules],
            "marking_text": marking_text(cur, task_id)}


def open_tasks(con, year, variant, limit) -> list[dict]:
    with con.cursor(row_factory=dict_row) as cur:
        cur.execute(SQL_OPEN_TASKS, {"year": year, "variant": variant, "limit": limit})
        tasks = cur.fetchall()
        for task in tasks:
            task.update(load_task_context(cur, task["id"]))
    return tasks


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")
