#!/usr/bin/env python3
"""Drugi czytelnik, który rozstrzyga — korekta korpusu modelem (plan A2-auto, X2).

Model dostaje rekord zadania w kształcie formularza ekranu korekty i obraz
strony klucza, oddaje werdykt: `match` (rekord zgodny z kluczem), `fix`
(pełny rekord po poprawce) albo `unsure`. Zapis idzie tą samą drogą co
u człowieka — `db.save` i `db.decide` — więc status `approved`/`corrected`
wynika z porównania z bazą, a więzy schematu odrzucają śmieci modelu tak
samo jak śmieci parsera. Rekord odrzucony przez więz ląduje w `unsure`.

Kto rozstrzygnął, niesie schemat: `task.reviewed_by = 'model'`,
`correction_event.actor = 'model'`. Powrót do korekty ręcznej to jeden UPDATE.

Wymagania podstawy programowej są dla modelu kontekstem, nie przedmiotem
edycji: parser ma tu 100% pokrycia, a formularz przyjmuje jedno dopięcie
na zapis. Różnicę model zgłasza w `reasons`. Odpowiedzi wzorcowych model
nie dokłada (formularz tego nie umie) — poprawia istniejące albo kasuje.

Wywołań LLM nie ma w CI: część czysta (rekord ↔ formularz, schemat) jest
testowana na utrwalonych danych, warstwa wejścia-wyjścia jest cienka.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import psycopg
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

from correction import db, llm, pages
from correction.prefill import strict_schema
from schema.migrate import polaczenie


def _console_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


# ── kontrakt odpowiedzi ────────────────────────────────────────────────────
# Ten sam kształt co formularz ekranu: `id` wiersza zostaje, nowy wiersz ma
# `id: null`, wiersz pominięty przez model zostanie skasowany. Różnicę liczy
# `db.save`, nie model — dlatego model oddaje CAŁY rekord, a nie diff.

class ExpressionRow(BaseModel):
    id: int | None = Field(description="id z rekordu; null dla nowego wiersza")
    expression: str = Field(description="zapis równoważny, dokładnie jak w kluczu")


class ConditionRow(BaseModel):
    id: int | None = Field(description="id z rekordu; null dla nowego wiersza")
    description: str = Field(description="treść warunku — spełnienie DOWOLNEGO daje próg")
    expressions: list[ExpressionRow]


class CriterionRow(BaseModel):
    id: int | None = Field(description="id z rekordu; null dla nowego wiersza")
    points: int = Field(description="ile punktów daje ten próg")
    label: str | None = Field(description="etykieta progu, np. „pełne rozwiązanie”")
    description: str | None = Field(
        description="treść progu, gdy klucz nie wypunktowuje warunków")
    conditions: list[ConditionRow]


class AnswerRow(BaseModel):
    id: int
    answer: str = Field(description="odpowiedź wzorcowa, dokładnie jak w kluczu, np. PP, BD")


class VersionRow(BaseModel):
    id: int
    content: str | None = Field(description="treść zadania z arkusza; nie redaguj")
    answers: list[AnswerRow]


class TaskRecord(BaseModel):
    number: str
    max_points: int
    kind: Literal["closed", "open_short", "open_extended", "essay"]
    versions: list[VersionRow]
    criteria: list[CriterionRow]


class Verdict(BaseModel):
    verdict: Literal["match", "fix", "unsure"]
    reasons: list[str] = Field(description="po polsku, krótko: co i gdzie")
    record: TaskRecord | None = Field(description="pełny rekord po poprawce; tylko przy fix")


SYSTEM = """Porównujesz REKORD zadania (odczytany automatem z zasad oceniania CKE,
egzamin ósmoklasisty) z obrazem strony klucza. Rozstrzygasz, czy rekord wiernie
oddaje klucz.

Werdykt:
- `match` — rekord zgadza się z kluczem. Różnice w białych znakach, cudzysłowach
  i drobnej interpunkcji to NIE różnica.
- `fix` — rekord po poprawce: CAŁY, w tym samym kształcie. Wiersz, który zostaje,
  ma to samo `id`; nowy wiersz ma `id: null`; wiersz, którego w kluczu nie ma,
  pomijasz (zostanie skasowany).
- `unsure` — strona nie pokazuje tego zadania, klucz jest nieczytelny albo
  poprawka wymagałaby zgadywania. Napisz w `reasons`, czego brakuje.

Zasady:
- Zadanie zamknięte: odpowiedź to litery lub symbole dokładnie jak w kluczu
  (np. `PP`, `BD`, `FP`, `AC`).
- Klucze od 2020 r. mają PRZY KAŻDYM zadaniu zamkniętym „Zasady oceniania:
  1 pkt – odpowiedź poprawna. 0 pkt – odpowiedź niepoprawna albo brak
  odpowiedzi". To SĄ kryteria tego zadania: zostają w rekordzie, nie kasujesz
  ich i nie nazywasz „ogólnymi zasadami". Ogólne zasady klucza to osobna
  sekcja na początku dokumentu, nie tekst przy zadaniu. Rocznik 2019 tych
  zasad przy zadaniu nie ma i wtedy pusta lista kryteriów jest poprawna —
  w wiadomości dostajesz, jak jest w TYM kluczu.
- Nagłówki „Rozwiązanie – wersja X/Y" i treść rozwiązań przykładowych NIE są
  warunkami: jeśli wpadły do warunku, obetnij je.
- Próg punktowy = `points`. Warunki progu są ALTERNATYWĄ: dowolny daje próg.
  Zapis równoważny to inny zapis TEGO SAMEGO warunku (wzór, rachunek).
- Przepisujesz z klucza. Nie poprawiasz CKE, nie skracasz, nie wymyślasz.
- Treści zadania (`content`) nie redagujesz. Zmieniasz ją tylko, gdy jest pusta
  albo urwana i widzisz ją na obrazie.
- Wymagania podstawy programowej są kontekstem: różnicę wpisz w `reasons`,
  rekordu nie zmieniasz.
- Uwagi ogólne klucza (błąd rachunkowy, brak jednostek) to reguły arkusza,
  nie kryteria zadania — nie dopisujesz ich do progów.
- `reasons` zawsze po polsku, jedno zdanie na różnicę: co, gdzie.
"""

MAX_OUTPUT_TOKENS = 16000

UNSURE_ON_DB = "zapis odrzucony przez walidację lub więz bazy"


# ── rekord ↔ formularz (część czysta) ──────────────────────────────────────

def record_of(task: dict) -> TaskRecord:
    """Zadanie z `db.load_task` → rekord dla modelu, z zachowanymi `id`."""
    return TaskRecord(
        number=str(task["number"]),
        max_points=int(task["max_points"]),
        kind=task["kind"],
        versions=[
            VersionRow(id=v["id"], content=v.get("content"),
                       answers=[AnswerRow(id=a["id"], answer=a["answer"])
                                for a in v.get("answers", [])])
            for v in task.get("versions", [])
        ],
        criteria=[
            CriterionRow(
                id=c["id"], points=int(c["points"]), label=c.get("label"),
                description=c.get("description"),
                conditions=[
                    ConditionRow(
                        id=cc["id"], description=cc.get("description") or "",
                        expressions=[ExpressionRow(id=e["id"],
                                                   expression=e.get("expression") or "")
                                     for e in cc.get("expressions", [])])
                    for cc in c.get("conditions", [])
                ])
            for c in task.get("criteria", [])
        ],
    )


def requirements_text(task: dict) -> str:
    lines = [f"- {r['regime']} · {r['kind']} {r.get('stage') or ''} {r['path']}: "
             f"{(r.get('content') or '')[:120]}"
             for r in task.get("requirements", [])]
    return "\n".join(lines) or "- (brak)"


def build_prompt(task: dict) -> str:
    record = record_of(task).model_dump()
    return "\n".join([
        f"Zadanie {task['number']} z klucza {task['code']} ({task['session']}), "
        f"pula punktów 0–{task['max_points']}, rodzaj `{task['kind']}`.",
        "",
        "REKORD (JSON, z id wierszy):",
        json.dumps(record, ensure_ascii=False, indent=1),
        "",
        "WYMAGANIA PODSTAWY PROGRAMOWEJ W REKORDZIE (kontekst, nie edytuj):",
        requirements_text(task),
        "",
        "W tym kluczu zadania zamknięte "
        + ("MAJĄ przy sobie zasady oceniania 1 pkt / 0 pkt — to kryteria zadania."
           if task.get("closed_have_criteria")
           else "NIE mają zasad przy zadaniu — pusta lista kryteriów jest normą."),
        f"Na obrazach są strony klucza {', '.join(map(str, key_pages(task)))}.",
        "Oceń rekord względem klucza i oddaj werdykt.",
    ])


def _image_block(path: Path) -> dict:
    data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    return {"type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{data}"}}


# Zadanie otwarte z rozwiązaniami przykładowymi ciągnie się i pięć stron;
# kryteria stoją zwykle na końcu. Limit trzyma koszt obrazów w ryzach.
MAX_KEY_PAGES = 5


def key_pages(task: dict) -> list[int]:
    """Strony klucza od zadania do początku następnego (`page_to`), z limitem.

    Bez `page_to` (zadanie spoza `collect_tasks`) zostaje strona i następna —
    zadanie potrafi łamać się na krawędzi.
    """
    page = task.get("page")
    if not page:
        return []
    total = task.get("document_pages")
    last = task.get("page_to") or page + 1
    if total:
        last = min(last, total)
    last = min(last, page + MAX_KEY_PAGES - 1)
    return list(range(page, max(page, last) + 1))


def messages_for(task: dict) -> list:
    blocks = [_image_block(pages.render(task["document_path"], n))
              for n in key_pages(task)]
    blocks.append({"type": "text", "text": build_prompt(task)})
    return llm.messages(SYSTEM, blocks)


def parse_payload(payload: dict | str) -> Verdict:
    return Verdict.model_validate(json.loads(payload) if isinstance(payload, str)
                                  else payload)


def create_missing(cur, task_id: int, record: TaskRecord) -> bool:
    """Nowe wiersze (`id: null`) dostają id z bazy, ZANIM powstanie formularz.

    `add_criterion` bierze pierwszą wolną punktację — właściwą ustawia potem
    `db.save` z formularza, po skasowaniu wierszy, których model nie oddał.
    Zwraca, czy cokolwiek powstało: to jest poprawka, nawet gdy pola
    nowego wiersza trafią w to, co `add_*` wstawiło domyślnie.
    """
    created = False
    for criterion in record.criteria:
        if criterion.id is None:
            criterion.id = db.add_criterion(cur, task_id)
            created = True
        for condition in criterion.conditions:
            if condition.id is None:
                condition.id = db.add_condition(cur, task_id, criterion.id)
                created = True
            for expression in condition.expressions:
                if expression.id is None:
                    expression.id = db.add_expression(cur, task_id, condition.id)
                    created = True
    return created


def form_for(task: dict, record: TaskRecord) -> dict[str, str]:
    """Rekord modelu → formularz taki, jaki wysyła przeglądarka.

    Wiersz z bazy nieobecny w rekordzie dostaje `delete.<tabela>.<id>`;
    reszta idzie polami, a różnicę i tak liczy `db.save`.
    """
    for criterion in record.criteria:
        if criterion.id is None:
            raise ValueError("rekord ma wiersze bez id — najpierw `create_missing`")
    form: dict[str, str] = {
        "task.number": record.number,
        "task.max_points": str(record.max_points),
        "task.kind": record.kind,
        "add_requirement": "",
    }

    kept_versions = {v.id: v for v in record.versions}
    for version in task.get("versions", []):
        got = kept_versions.get(version["id"])
        if got is None:
            # Wersji formularz nie kasuje; brak w rekordzie = bez zmian.
            continue
        form[f"version.{version['id']}.content"] = got.content or ""
        kept_answers = {a.id: a for a in got.answers}
        for answer in version.get("answers", []):
            if answer["id"] in kept_answers:
                form[f"answer.{answer['id']}.answer"] = kept_answers[answer["id"]].answer
            else:
                form[f"delete.answer.{answer['id']}"] = "1"

    kept_criteria = {c.id: c for c in record.criteria}
    for criterion in task.get("criteria", []):
        if criterion["id"] not in kept_criteria:
            form[f"delete.criterion.{criterion['id']}"] = "1"
            continue
        got = kept_criteria[criterion["id"]]
        kept_conditions = {cc.id: cc for cc in got.conditions}
        for condition in criterion.get("conditions", []):
            if condition["id"] not in kept_conditions:
                form[f"delete.condition.{condition['id']}"] = "1"
                continue
            kept_expressions = {e.id for e in kept_conditions[condition["id"]].expressions}
            for expression in condition.get("expressions", []):
                if expression["id"] not in kept_expressions:
                    form[f"delete.expression.{expression['id']}"] = "1"

    for criterion in record.criteria:
        form[f"criterion.{criterion.id}.points"] = str(criterion.points)
        form[f"criterion.{criterion.id}.label"] = criterion.label or ""
        form[f"criterion.{criterion.id}.description"] = criterion.description or ""
        for condition in criterion.conditions:
            form[f"condition.{condition.id}.description"] = condition.description
            for expression in condition.expressions:
                form[f"expression.{expression.id}.expression"] = expression.expression
    return form


# ── zapis ──────────────────────────────────────────────────────────────────

def apply_verdict(con, task_id: int, verdict: Verdict, model: str,
                  started_at: datetime) -> str:
    """Werdykt → baza. Zwraca stan, w jakim zadanie zostało.

    `match` i `fix` idą przez `db.decide` jak „Zatwierdź" człowieka; `fix`
    najpierw przez `db.save`. Odmowa walidacji albo więzu cofa transakcję
    i zapisuje `unsure` z powodem — więzów nie luzujemy.
    """
    if verdict.verdict == "unsure" or (verdict.verdict == "fix"
                                       and verdict.record is None):
        reasons = verdict.reasons or ["model nie podał powodu"]
        if verdict.verdict == "fix":
            reasons = ["werdykt `fix` bez rekordu", *reasons]
        with con.transaction(), con.cursor(row_factory=dict_row) as cur:
            db.record_unsure(cur, task_id, model, reasons, started_at)
        return "unsure"

    try:
        with con.transaction(), con.cursor(row_factory=dict_row) as cur:
            task = db.load_task(cur, task_id)
            if task is None:
                raise db.ValidationError([f"nie ma zadania {task_id}"])
            if verdict.verdict == "match":
                # Uwagi przy `match` (rozjazd wymagania, literówka CKE) idą do
                # dziennika: to jedyne miejsce, gdzie człowiek je potem znajdzie.
                changes = {"edited": {}, "deleted": {}, "described": {},
                           **({"notes": verdict.reasons} if verdict.reasons else {})}
                created = False
            else:
                created = create_missing(cur, task_id, verdict.record)
                changes = db.save(cur, task_id, form_for(task, verdict.record))
            return db.decide(cur, task_id, "approve", started_at, changes,
                             edited_before=created, actor="model", model=model)
    except (db.ValidationError, psycopg.IntegrityError, psycopg.DataError) as exc:
        why = (exc.messages if isinstance(exc, db.ValidationError)
               else [getattr(exc.diag, "message_primary", None) or str(exc)])
        with con.transaction(), con.cursor(row_factory=dict_row) as cur:
            db.record_unsure(cur, task_id, model,
                             [UNSURE_ON_DB, *why, *verdict.reasons], started_at)
        return "unsure"


# ── wejście-wyjście ────────────────────────────────────────────────────────

SQL_TASKS = """
    SELECT t.id
    FROM task t
    JOIN document d ON d.id = t.marking_scheme_id
    WHERE t.review_status = 'pending'
      AND (%(year)s::smallint IS NULL OR d.year = %(year)s)
      AND (%(variant)s::text IS NULL
           OR %(variant)s = ANY(string_to_array(d.variants, ',')))
      AND (%(retry)s OR NOT EXISTS (
            SELECT 1 FROM correction_event e
             WHERE e.task_id = t.id AND e.action = 'unsure' AND e.model = %(model)s))
    ORDER BY d.session, d.path, t.position
    LIMIT %(limit)s"""


SQL_NEXT_PAGE = """
    SELECT min(t2.page) AS page_to
    FROM task t2
    WHERE t2.marking_scheme_id = %(document)s
      AND t2.position > %(position)s AND t2.page IS NOT NULL"""


def collect_tasks(cur, year, variant, model, limit, retry) -> list[dict]:
    cur.execute(SQL_TASKS, {"year": year, "variant": variant, "model": model,
                            "limit": limit, "retry": retry})
    ids = [r["id"] for r in cur.fetchall()]
    tasks = []
    for task in (db.load_task(cur, i) for i in ids):
        if task is None:
            continue
        # Strona następnego zadania domyka zakres obrazów: kryteria zadania
        # stoją przed nią, a bywa, że dzielą z nią stronę.
        cur.execute(SQL_NEXT_PAGE, {"document": task["document_id"],
                                    "position": task["position"]})
        row = cur.fetchone()
        task["page_to"] = (row["page_to"] if row and row["page_to"]
                           else task.get("document_pages"))
        tasks.append(task)
    return tasks


class Outcome:
    """Wynik przebiegu — do raportu i do pliku JSON obok niego."""

    def __init__(self) -> None:
        self.rows: list[dict] = []

    def add(self, task: dict, verdict: Verdict | None, state: str,
            why: str | None = None) -> None:
        self.rows.append({
            "task_id": task["id"], "number": task["number"], "code": task["code"],
            "session": str(task["session"]), "year": task["year"],
            "kind": task["kind"],
            "verdict": verdict.verdict if verdict else None,
            "reasons": verdict.reasons if verdict else ([why] if why else []),
            "state": state,
        })

    def counts(self) -> Counter:
        return Counter(r["state"] for r in self.rows)


def _refusal(result: dict) -> str:
    error = result.get("parsing_error")
    if error is not None:
        return f"odpowiedź nie w schemacie: {error}"
    raw = result.get("raw")
    metadata = getattr(raw, "response_metadata", None) or {}
    return (f"model nie oddał struktury "
            f"(finish_reason: {metadata.get('finish_reason', 'nieznany')})")


def _ask_one_by_one(structured, tasks, spend, on_verdict=None) -> dict[int, Verdict]:
    """Po jednym zadaniu, z zapisem od razu przez `on_verdict`.

    Odpowiedź jest opłacona, gdy wróci: awaria na setnym zadaniu nie ma prawa
    skasować dziewięćdziesięciu dziewięciu rozstrzygnięć czekających w pamięci.
    """
    out: dict[int, Verdict] = {}
    for task in tasks:
        try:
            result = structured.invoke(messages_for(task))
        except pages.PageUnavailable as e:
            spend.failures.append((str(task["id"]), str(e)))
            continue
        except Exception as e:
            spend.failures.append((str(task["id"]), f"{type(e).__name__}: {e}"))
            continue
        input_tokens, output_tokens = llm.usage_of(result.get("raw"))
        spend.add(input_tokens, output_tokens)
        parsed = result.get("parsed")
        if parsed is None:
            spend.failures.append((str(task["id"]), _refusal(result)))
            continue
        out[task["id"]] = parsed
        state = on_verdict(task, parsed) if on_verdict else parsed.verdict
        print(f"  zadanie {task['number']:>4} ({task['year']}): {state}"
              + (f" — {parsed.reasons[0]}" if parsed.reasons else ""))
    return out


def _ask_batch(tasks, model, spend, client=None) -> dict[int, Verdict]:
    response_format = {"type": "json_schema",
                       "json_schema": {"name": "verdict", "strict": True,
                                       "schema": strict_schema(Verdict)}}
    requests = []
    for task in tasks:
        try:
            requests.append(llm.batch_request(
                f"task-{task['id']}",
                llm.batch_body(model, messages_for(task),
                               max_tokens=MAX_OUTPUT_TOKENS,
                               response_format=response_format)))
        except pages.PageUnavailable as e:
            spend.failures.append((str(task["id"]), str(e)))
    results = llm.run_batch(requests, model, client=client)

    out: dict[int, Verdict] = {}
    for task in tasks:
        body, why = llm.batch_payload(results.get(f"task-{task['id']}"))
        if body is None:
            spend.failures.append((str(task["id"]), why))
            continue
        input_tokens, output_tokens = llm.usage_of(body.get("usage"))
        spend.add(input_tokens, output_tokens)
        message = ((body.get("choices") or [{}])[0]).get("message") or {}
        if message.get("refusal"):
            spend.failures.append((str(task["id"]), f"odmowa modelu: {message['refusal']}"))
            continue
        try:
            out[task["id"]] = parse_payload(message.get("content") or "")
        except Exception as e:
            spend.failures.append((str(task["id"]), f"odpowiedź nie w schemacie: {e}"))
    return out


def run(con, year=None, variant=None, model=llm.DEFAULT_MODEL, limit=20,
        apply=False, batch=False, retry=False) -> tuple[llm.Spend, Outcome]:
    llm.check_model(model)
    if batch:
        llm.check_batch(model)
    spend = llm.Spend(model=model, batch=batch)
    outcome = Outcome()

    with con.cursor(row_factory=dict_row) as cur:
        tasks = collect_tasks(cur, year, variant, model, limit, retry)
    if not tasks:
        return spend, outcome

    started_at = datetime.now(timezone.utc)

    def settle(task: dict, verdict: Verdict) -> str:
        state = (apply_verdict(con, task["id"], verdict, model, started_at)
                 if apply else f"dry:{verdict.verdict}")
        outcome.add(task, verdict, state)
        return state

    if batch:
        # Wsad wraca w całości, więc tu zapis po zadaniu nic nie zmienia.
        verdicts = _ask_batch(tasks, model, spend)
        for task in tasks:
            if task["id"] in verdicts:
                settle(task, verdicts[task["id"]])
    else:
        structured = llm.chat_model(
            model, max_tokens=MAX_OUTPUT_TOKENS
        ).with_structured_output(Verdict, include_raw=True)
        verdicts = _ask_one_by_one(structured, tasks, spend, on_verdict=settle)

    failed = dict(spend.failures)
    for task in tasks:
        if task["id"] not in verdicts:
            outcome.add(task, None, "failed", failed.get(str(task["id"])))
    # Raport w kolejności arkusza, nie w kolejności „najpierw udane, potem nie".
    order = {t["id"]: i for i, t in enumerate(tasks)}
    outcome.rows.sort(key=lambda r: order.get(r["task_id"], 0))
    return spend, outcome


def report(spend: llm.Spend, outcome: Outcome, apply: bool) -> str:
    rule = "─" * 74
    counts = outcome.counts()
    lines = ["VERIFY — DRUGI CZYTELNIK ROZSTRZYGA (plan A2-auto)", rule,
             *spend.as_lines(),
             f"  tryb                   : {'ZAPIS do bazy' if apply else 'na sucho, bez zapisu'}",
             f"  zadań w przebiegu      : {len(outcome.rows)}"]
    for state in sorted(counts):
        lines.append(f"  {state:<22} : {counts[state]}")
    by_year: dict[int, Counter] = {}
    for row in outcome.rows:
        by_year.setdefault(row["year"], Counter())[row["state"]] += 1
    if by_year:
        lines += ["", "PER ROCZNIK", rule]
        for year in sorted(by_year):
            parts = ", ".join(f"{k}: {v}" for k, v in sorted(by_year[year].items()))
            lines.append(f"  {year}: {parts}")
    reasons = [r for row in outcome.rows if row["verdict"] != "match"
               for r in row["reasons"]]
    if reasons:
        lines += ["", "POWODY (fix i unsure, pierwsze 15)", rule]
        lines += [f"  #{row['task_id']} z.{row['number']} ({row['year']}) "
                  f"[{row['verdict'] or row['state']}]: {reason}"
                  for row in outcome.rows if row["verdict"] != "match"
                  for reason in row["reasons"][:2]][:15]
    if spend.failures:
        lines += ["", f"  NIEUDANE: {len(spend.failures)}"]
        lines += [f"    ↳ zadanie {task_id}: {why}"
                  for task_id, why in spend.failures[:8]]
    lines += ["", "Rozbicie korpusu na człowieka i model: `task corpus:report`.",
              "Zadania `unsure` czekają w ekranie korekty z powodami nad formularzem."]
    return "\n".join(lines) + "\n"


def main() -> int:
    _console_utf8()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, default=None)
    ap.add_argument("--variant", default=None, help="np. 100")
    ap.add_argument("--model", default=llm.DEFAULT_MODEL, choices=sorted(llm.PRICING),
                    help="`dostawca:nazwa` — inny niż w `task prefill`, żeby ta sama "
                         "para oczu nie sprawdzała własnej roboty")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--apply", action="store_true",
                    help="rozstrzygaj w bazie; bez tej flagi tylko raport")
    ap.add_argument("--batch", action="store_true",
                    help="przez Batch API — o połowę taniej, wynik po godzinach; "
                         f"dostawcy z adapterem: {', '.join(llm.BATCH_PROVIDERS)}")
    ap.add_argument("--retry-unsure", action="store_true",
                    help="weź też zadania, które ten model już raz zostawił jako unsure")
    ap.add_argument("--report", default=None)
    args = ap.parse_args()

    with psycopg.connect(polaczenie(), autocommit=True) as con:
        try:
            spend, outcome = run(con, args.year, args.variant, args.model, args.limit,
                                 apply=args.apply, batch=args.batch,
                                 retry=args.retry_unsure)
        except llm.LlmUnavailable as e:
            print(e)
            return 2
    text = report(spend, outcome, args.apply)
    path = llm.report_path("verify", args.report)
    path.write_text(text, encoding="utf-8")
    path.with_suffix(".json").write_text(
        json.dumps(outcome.rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(text)
    print(f"Raport zapisany: {path} (+ .json z werdyktami)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
