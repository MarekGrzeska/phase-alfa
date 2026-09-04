#!/usr/bin/env python3
"""Golden set: model A pisze odpowiedzi ucznia (plan A2-auto, X5).

Dla każdego zadania otwartego w korpusie powstają trzy odpowiedzi — pełna,
częściowa i błędna — napisane tak, jak pisze ósmoklasista na karcie. Autor
dostaje treść zadania i opis rysunku; klucza NIE dostaje, żeby odpowiedzi nie
cytowały rozwiązania przykładowego. Wyjątek: zeszyty od 2025 r. odsyłają do
karty rozwiązań, której mirror nie ma — wtedy autor dostaje rozwiązanie
przykładowe i rekonstruuje treść (`content_source: "key"`, do sprawdzenia).

Ocenę robi osobne polecenie (`golden.grade`) innym modelem. Provenance
w pliku: `author` = `model:<adres>`; wpisy `human` pochodzą z ręki.
"""

from __future__ import annotations

import argparse
import sys
from typing import Literal

import psycopg
from pydantic import BaseModel, Field

from correction import llm
from golden import common
from schema.migrate import polaczenie


def _console_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


class Answer(BaseModel):
    kind: Literal["full", "partial", "wrong"]
    text: str = Field(description="odpowiedź ucznia, jak na karcie: obliczenia i wynik")
    intent: str = Field(
        description="po polsku: co uczeń zrobił dobrze, a co źle — dla oceniającego")


class Generated(BaseModel):
    task_text: str | None = Field(
        description="zrekonstruowana treść zadania, tylko gdy w wiadomości jej brak")
    answers: list[Answer]


SYSTEM = """Piszesz odpowiedzi ucznia klasy ósmej do zadania otwartego z matematyki
(egzamin ósmoklasisty). Trzy odpowiedzi, każda w innym stylu:

- `full` — rozwiązanie poprawne i kompletne: obliczenia, uzasadnienie, wynik z jednostką.
- `partial` — dobra metoda, ale błąd rachunkowy, brak ostatniego kroku albo brak
  jednostki; wynik zły lub niepełny.
- `wrong` — zła metoda albo sam wynik bez uzasadnienia, albo wynik z powietrza.

Pisz jak uczeń na papierze: krótko, w linijkach, skróty, czasem bez jednostek,
bez tłumaczenia nauczycielskiego. Nie pisz „odpowiedź: …" w każdym wierszu.
Nie podpisuj odpowiedzi rodzajem. W `intent` napisz (po polsku) w jednym zdaniu,
co uczeń zrobił i gdzie się pomylił — to jest dla oceniającego, nie dla ucznia.

Jeśli w wiadomości NIE MA treści zadania, a jest rozwiązanie przykładowe:
najpierw zrekonstruuj treść w `task_text` (dane liczbowe wprost z rozwiązania,
pytanie zgodne z tym, co rozwiązanie liczy), potem pisz odpowiedzi do niej.
W przeciwnym razie `task_text` zostaw puste (null).
"""

MAX_OUTPUT_TOKENS = 4000
DEFAULT_AUTHOR = "openai:gpt-5.6-luna"


def build_prompt(task: dict) -> tuple[str, str]:
    """Tekst dla autora i źródło treści: `paper` albo `key`."""
    lines = [f"Zadanie {task['number']} (0–{task['max_points']} pkt), "
             f"arkusz {task['exam_form']}, {task['session']}."]
    if common.has_real_content(task.get("content")):
        source = "paper"
        lines += ["", "TREŚĆ ZADANIA:", task["content"]]
    else:
        source = "key"
        lines += ["", "Treści zadania nie ma (odsyłacz do karty rozwiązań). "
                      "ROZWIĄZANIE PRZYKŁADOWE z klucza, z którego trzeba ją odtworzyć:"]
        for s in task["solutions"]:
            lines.append(f"- [{s['method'] or 'sposób'}] {s['content']}")
    if task["descriptions"]:
        lines += ["", "OPIS RYSUNKU:", *task["descriptions"]]
    lines += ["", "Napisz trzy odpowiedzi: full, partial, wrong."]
    return "\n".join(lines), source


def record_for(task: dict, generated: Generated, source: str, author: str) -> dict:
    return {
        "exam_form": task["exam_form"], "session": str(task["session"]),
        "year": task["year"], "task": task["number"], "max_points": task["max_points"],
        "content_source": source,
        "task_text": (generated.task_text if source == "key" else task["content"]),
        "answers": [{"kind": a.kind, "text": a.text, "intent": a.intent,
                     "author": f"model:{author}", "grading": None}
                    for a in generated.answers],
    }


def run(con, year=None, variant=None, model=DEFAULT_AUTHOR, limit=60,
        force=False) -> tuple[llm.Spend, list[str]]:
    llm.check_model(model)
    spend = llm.Spend(model=model)
    written: list[str] = []
    tasks = common.open_tasks(con, year, variant, limit)
    structured = llm.chat_model(
        model, max_tokens=MAX_OUTPUT_TOKENS
    ).with_structured_output(Generated, include_raw=True)

    for task in tasks:
        path = common.golden_path(task["year"], task["number"])
        if path.exists() and not force:
            continue
        prompt, source = build_prompt(task)
        try:
            result = structured.invoke(llm.messages(SYSTEM, prompt))
        except Exception as e:
            spend.failures.append((f"{task['year']}/{task['number']}",
                                   f"{type(e).__name__}: {e}"))
            continue
        spend.add(*llm.usage_of(result.get("raw")))
        generated = result.get("parsed")
        if generated is None or len(generated.answers) < 3:
            spend.failures.append((f"{task['year']}/{task['number']}",
                                   "model nie oddał trzech odpowiedzi"))
            continue
        common.write_json(path, record_for(task, generated, source, model))
        written.append(str(path.relative_to(common.ROOT)))
        print(f"  {task['year']} z.{task['number']:>3} [{source}]: "
              f"{len(generated.answers)} odpowiedzi")
    return spend, written


def report(spend: llm.Spend, written: list[str]) -> str:
    rule = "─" * 74
    lines = ["GOLDEN SET — ODPOWIEDZI UCZNIA (model A)", rule, *spend.as_lines(),
             f"  plików zapisanych      : {len(written)}"]
    if spend.failures:
        lines += ["", f"  NIEUDANE: {len(spend.failures)}"]
        lines += [f"    ↳ {where}: {why}" for where, why in spend.failures[:8]]
    lines += ["", "Ocenę pisze `task golden:grade` — innym modelem niż autor."]
    return "\n".join(lines) + "\n"


def main() -> int:
    _console_utf8()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, default=None)
    ap.add_argument("--variant", default="100")
    ap.add_argument("--model", default=DEFAULT_AUTHOR, choices=sorted(llm.PRICING),
                    help="autor odpowiedzi — inny model niż oceniający")
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--force", action="store_true", help="nadpisz istniejące pliki")
    ap.add_argument("--report", default=None)
    args = ap.parse_args()

    with psycopg.connect(polaczenie(), autocommit=True) as con:
        try:
            spend, written = run(con, args.year, args.variant, args.model, args.limit,
                                 force=args.force)
        except llm.LlmUnavailable as e:
            print(e)
            return 2
    text = report(spend, written)
    path = llm.report_path("golden-generate", args.report)
    path.write_text(text, encoding="utf-8")
    print(text)
    print(f"Raport zapisany: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
