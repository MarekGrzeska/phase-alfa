#!/usr/bin/env python3
"""Golden set: model B ocenia odpowiedzi wg klucza (plan A2-auto, X5).

Oceniający dostaje treść zadania, kryteria z korpusu (próg → warunek → zapis),
reguły przekrojowe arkusza i rozwiązanie przykładowe, a oddaje punkty
z uzasadnieniem próg po progu i cytatem z odpowiedzi. Zapis idzie do tego
samego pliku JSON pod `answers[i].grading`, z `grader = model:<adres>`.

Autor ≠ oceniający ≠ model testowany w A3 — inaczej benchmark mierzy zgodność
modelu z samym sobą. Próbka oceniona ręką (`grader: human`) daje rozrzut.
"""

from __future__ import annotations

import argparse
import sys

import psycopg
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

from correction import llm
from golden import common
from schema.migrate import polaczenie


def _console_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


class CriterionVerdict(BaseModel):
    points: int = Field(description="próg punktowy z klucza")
    met: bool = Field(description="czy odpowiedź spełnia którykolwiek warunek tego progu")
    quote: str = Field(description="fragment odpowiedzi ucznia, który o tym rozstrzyga")
    note: str = Field(description="po polsku, jedno zdanie")


class Grade(BaseModel):
    points: int = Field(description="przyznane punkty po regułach przekrojowych")
    criteria: list[CriterionVerdict]
    justification: str = Field(description="po polsku, dwa–trzy zdania")


SYSTEM = """Oceniasz odpowiedź ucznia do zadania otwartego z egzaminu ósmoklasisty
z matematyki, ściśle według zasad oceniania CKE.

Zasady:
- Progi punktowe są rozłączne: uczeń dostaje NAJWYŻSZY próg, którego dowolny
  warunek spełnia. Warunki progu to alternatywa.
- Zapis równoważny to inny zapis tego samego warunku — liczy się treść, nie forma.
- Reguły przekrojowe arkusza (np. błąd rachunkowy odejmuje punkt, brak jednostki)
  stosuj PO ustaleniu progu, i tylko wtedy, gdy reguła wprost tego dotyczy.
- Cytuj odpowiedź ucznia, nie parafrazuj. Nie oceniaj intencji — oceniasz zapis.
- `points` nie może przekroczyć puli zadania ani być ujemne.
"""

MAX_OUTPUT_TOKENS = 3000
DEFAULT_GRADER = "openai:gpt-5.6-terra"


def build_prompt(record: dict, task: dict, answer: dict) -> str:
    lines = [f"Zadanie {record['task']} (0–{record['max_points']} pkt), "
             f"arkusz {record['exam_form']}.",
             "", "TREŚĆ ZADANIA:", record.get("task_text") or "(brak)",
             "", "ZASADY OCENIANIA (próg → warunek → zapis):", task["marking_text"]]
    if task["rules"]:
        lines += ["", "REGUŁY PRZEKROJOWE ARKUSZA:", *[f"- {r}" for r in task["rules"]]]
    if task["solutions"]:
        lines += ["", "ROZWIĄZANIE PRZYKŁADOWE (do porównania metody):"]
        lines += [f"- [{s['method'] or 'sposób'}] {s['content']}" for s in task["solutions"]]
    lines += ["", "ODPOWIEDŹ UCZNIA:", answer["text"], "",
              "Oceń próg po progu i podaj punkty."]
    return "\n".join(lines)


def _task_by_number(con, year: int, number: str) -> dict | None:
    with con.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """SELECT t.id FROM corpus_task c JOIN task t ON t.id = c.id
               JOIN document d ON d.id = t.marking_scheme_id
               WHERE d.year = %s AND t.number = %s AND t.kind <> 'closed'
               ORDER BY t.id LIMIT 1""", (year, number))
        row = cur.fetchone()
        if row is None:
            return None
        return common.load_task_context(cur, row["id"])


def run(con, year=None, model=DEFAULT_GRADER, limit=200,
        force=False) -> tuple[llm.Spend, int]:
    llm.check_model(model)
    spend = llm.Spend(model=model)
    graded = 0
    structured = llm.chat_model(
        model, max_tokens=MAX_OUTPUT_TOKENS
    ).with_structured_output(Grade, include_raw=True)

    paths = sorted(common.ROOT.glob("*/task-*.json"))
    for path in paths:
        record = common.read_json(path)
        if year and record["year"] != year:
            continue
        task = _task_by_number(con, record["year"], record["task"])
        if task is None:
            spend.failures.append((str(path.name), "zadania nie ma w korpusie"))
            continue
        changed = False
        for answer in record["answers"]:
            if answer.get("grading") and not force:
                continue
            if graded >= limit:
                break
            try:
                result = structured.invoke(
                    llm.messages(SYSTEM, build_prompt(record, task, answer)))
            except Exception as e:
                spend.failures.append((f"{path.name}/{answer['kind']}",
                                       f"{type(e).__name__}: {e}"))
                continue
            spend.add(*llm.usage_of(result.get("raw")))
            grade = result.get("parsed")
            if grade is None:
                spend.failures.append((f"{path.name}/{answer['kind']}",
                                       "model nie oddał struktury"))
                continue
            answer["grading"] = {
                "grader": f"model:{model}",
                "points": max(0, min(grade.points, record["max_points"])),
                "criteria": [c.model_dump() for c in grade.criteria],
                "justification": grade.justification,
            }
            graded += 1
            changed = True
            print(f"  {record['year']} z.{record['task']:>3} {answer['kind']:<8}: "
                  f"{answer['grading']['points']}/{record['max_points']}")
        if changed:
            common.write_json(path, record)
    return spend, graded


def report(spend: llm.Spend, graded: int) -> str:
    rule = "─" * 74
    lines = ["GOLDEN SET — OCENA ODPOWIEDZI (model B)", rule, *spend.as_lines(),
             f"  ocenionych odpowiedzi  : {graded}"]
    if spend.failures:
        lines += ["", f"  NIEUDANE: {len(spend.failures)}"]
        lines += [f"    ↳ {where}: {why}" for where, why in spend.failures[:8]]
    lines += ["", "Próbkę ocenia człowiek w pliku: `grader: human` obok oceny modelu."]
    return "\n".join(lines) + "\n"


def main() -> int:
    _console_utf8()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, default=None)
    ap.add_argument("--model", default=DEFAULT_GRADER, choices=sorted(llm.PRICING),
                    help="oceniający — inny model niż autor")
    ap.add_argument("--limit", type=int, default=200, help="ile odpowiedzi ocenić")
    ap.add_argument("--force", action="store_true", help="oceń od nowa także ocenione")
    ap.add_argument("--report", default=None)
    args = ap.parse_args()

    with psycopg.connect(polaczenie(), autocommit=True) as con:
        try:
            spend, graded = run(con, args.year, args.model, args.limit, force=args.force)
        except llm.LlmUnavailable as e:
            print(e)
            return 2
    text = report(spend, graded)
    path = llm.report_path("golden-grade", args.report)
    path.write_text(text, encoding="utf-8")
    print(text)
    print(f"Raport zapisany: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
