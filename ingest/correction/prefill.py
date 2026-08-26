#!/usr/bin/env python3
"""Wstępne wypełnianie ekranu korekty przez LLM — pomiar S6 (G2.5.1).

Model dostaje tekst zasad oceniania JEDNEGO zadania i oddaje strukturę
progi → warunki → zapisy w tym samym kształcie, który produkuje parser.
Wynik NIE wchodzi do korpusu: ląduje w `prefill_suggestion` i pokazuje się
w ekranie korekty jako RÓŻNICA przy polu, którego dotyczy — nie jako drugi
formularz do przeczytania w całości.

Ten sam wiersz jest znacznikiem ramienia pomiaru S6. Zadania z podpowiedzią
i bez niej to dwie próby tego samego eksperymentu; odsetek zatwierdzeń bez
poprawki i czas na zadanie liczy `correction.stats`.

Podział na funkcje czyste (`build_prompt`, `parse_payload`, `differences`)
i cienką warstwę wejścia-wyjścia jest wymuszony regułą „wywołań LLM nie ma
w CI": testy chodzą na utrwalonych odpowiedziach z `tests/fixtures/`.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from correction import llm
from schema.migrate import polaczenie


def _console_utf8() -> None:
    """Konsola Windows na UTF-8 — sprawa POLECENIA, nie modułu.

    Na poziomie modułu przestawiała strumienie serwera korekty, który importuje
    ten plik dla podpowiedzi (`db.prefill_hints`). Tak samo robi `parser._main`.
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


# ── kontrakt odpowiedzi ────────────────────────────────────────────────────
# Schemat jest IDENTYCZNY z modelem parsera (próg → warunek → zapis), bo tylko
# wtedy różnica parser vs model jest porównaniem, a nie tłumaczeniem.

class Condition(BaseModel):
    description: str = Field(description="treść warunku, tak jak stoi w kluczu")
    expressions: list[str] = Field(
        default_factory=list,
        description="zapisy równoważne tego warunku, każdy osobno")


class Criterion(BaseModel):
    points: int = Field(description="ile punktów daje ten próg")
    label: str | None = Field(
        default=None, description="etykieta progu, np. „pełne rozwiązanie”")
    conditions: list[Condition] = Field(
        default_factory=list,
        description="warunki progu — spełnienie DOWOLNEGO wystarcza")


class Prefill(BaseModel):
    criteria: list[Criterion] = Field(default_factory=list)


SYSTEM = """Czytasz zasady oceniania zadania z egzaminu ósmoklasisty (CKE).
Twoim zadaniem jest odtworzyć STRUKTURĘ oceniania, nie streścić jej.

Zasady:
- Próg punktowy to jedna pozycja w `criteria`; `points` to liczba punktów.
- Warunki progu są ALTERNATYWĄ: spełnienie dowolnego daje ten próg.
- Zapis równoważny to inny sposób zapisania TEGO SAMEGO warunku (wzór, rachunek).
- Przepisujesz treść z dokumentu. Nie poprawiasz jej, nie skracasz, nie tłumaczysz.
- Czego w dokumencie nie ma, tego nie wymyślasz — pusta lista jest poprawną odpowiedzią.
"""


def build_prompt(task: dict) -> str:
    """Tekst zadania dla modelu — treść, pula punktów i surowe zasady oceniania."""
    lines = [f"Zadanie {task['number']}, pula punktów 0–{task['max_points']}."]
    if task.get("content"):
        lines += ["", "TREŚĆ ZADANIA:", task["content"]]
    lines += ["", "ZASADY OCENIANIA (tekst z klucza):", task["marking_text"]]
    return "\n".join(lines)


def parse_payload(payload: dict | str) -> Prefill:
    """Odpowiedź modelu → zwalidowana struktura. Rzuca, gdy kształt się nie zgadza."""
    return Prefill.model_validate(json.loads(payload) if isinstance(payload, str)
                                  else payload)


def strict_schema(model: type[BaseModel]) -> dict:
    """Schemat pydantica → schemat, który przechodzi przez `json_schema`.

    Tryb `json_schema` żąda `additionalProperties: false` i KOMPLETNEGO
    `required` w KAŻDYM obiekcie, także w `$defs` — pydantic nie stawia ani
    jednego, ani drugiego dla pól z wartością domyślną. Bez wsadu schemat
    buduje SDK, więc 400 dostawało tylko to ramię S6, które rzadziej widać.
    """
    schema = model.model_json_schema()
    _tighten(schema)
    return schema


def _tighten(node: object) -> None:
    if isinstance(node, list):
        for item in node:
            _tighten(item)
        return
    if not isinstance(node, dict):
        return
    if node.get("type") == "object" and "properties" in node:
        node["additionalProperties"] = False
        # Pole z wartością domyślną jest dla API WYMAGANE: pustą listę model
        # ma napisać. U pydantica wstawia ją konstruktor, którego tam nie ma.
        node["required"] = list(node["properties"])
    node.pop("default", None)
    for value in list(node.values()):
        _tighten(value)


# ── różnice parser vs model ────────────────────────────────────────────────

def _normalise(text: str | None) -> str:
    return " ".join((text or "").split()).casefold()


def differences(parser_criteria: Sequence[dict], suggestion: Prefill) -> list[dict]:
    """Co model widzi inaczej niż parser — po progu punktowym.

    Porównanie idzie po `points`, bo to on jest tożsamością progu w schemacie
    (UNIQUE (task_id, points)). Wynik jest listą podpowiedzi PRZY POLACH,
    a nie drugim formularzem: `kind` mówi ekranowi, gdzie ją postawić.
    """
    by_points = {int(c["points"]): c for c in parser_criteria}
    out: list[dict] = []
    for proposed in suggestion.criteria:
        found = by_points.get(proposed.points)
        if found is None:
            out.append({"kind": "criterion_missing", "points": proposed.points,
                        "hint": proposed.label or "",
                        "detail": [c.description for c in proposed.conditions]})
            continue
        existing = [_normalise(c["description"]) for c in found.get("conditions", [])]
        for condition in proposed.conditions:
            if _normalise(condition.description) not in existing:
                out.append({"kind": "condition_missing", "points": proposed.points,
                            "criterion_id": found.get("id"),
                            "hint": condition.description,
                            "detail": condition.expressions})
    proposed_points = {c.points for c in suggestion.criteria}
    for points, found in sorted(by_points.items()):
        if points not in proposed_points:
            out.append({"kind": "criterion_extra", "points": points,
                        "criterion_id": found.get("id"),
                        "hint": "model nie widzi tego progu w kluczu", "detail": []})
    return out


# ── wejście-wyjście ────────────────────────────────────────────────────────

SQL_TASKS = """
    SELECT t.id, t.number, t.max_points,
           (SELECT tv.content FROM task_version tv
             WHERE tv.task_id = t.id AND tv.content IS NOT NULL LIMIT 1) AS content
    FROM task t
    JOIN document d ON d.id = t.marking_scheme_id
    WHERE t.review_status = 'pending'
      AND t.kind <> 'closed'
      AND (%(year)s::smallint IS NULL OR d.year = %(year)s)
      AND (%(variant)s::text IS NULL
           OR %(variant)s = ANY(string_to_array(d.variants, ',')))
      AND NOT EXISTS (SELECT 1 FROM prefill_suggestion p
                       WHERE p.task_id = t.id AND p.model = %(model)s)
    ORDER BY d.session, d.path, t.position
    LIMIT %(limit)s"""


def marking_text(cur, task_id: int) -> str:
    """Zasady oceniania zadania złożone z rekordów parsera — wejście dla modelu.

    Surowego tekstu klucza nie ma w bazie (parser go nie zapisuje), więc model
    dostaje to, co parser zrozumiał. To zawęża pomiar S6 do pytania „czy model
    układa strukturę lepiej", a nie „czy czyta PDF lepiej" — i tak jest uczciwiej,
    bo czytanie PDF-a jest rolą parsera, nie modelu.
    """
    cur.execute(
        """SELECT c.points, c.label, c.description, cc.description AS condition,
                  ce.expression
           FROM criterion c
           LEFT JOIN criterion_condition cc ON cc.criterion_id = c.id
           LEFT JOIN condition_expression ce ON ce.condition_id = cc.id
           WHERE c.task_id = %s
           ORDER BY c.points DESC, cc.position, ce.position""",
        (task_id,),
    )
    lines: list[str] = []
    seen_condition = None
    for row in cur.fetchall():
        head = f"{row['points']} pkt {row['label'] or row['description'] or ''}".strip()
        if head not in lines:
            lines.append(head)
        if row["condition"] and row["condition"] != seen_condition:
            seen_condition = row["condition"]
            lines.append(f"  • {row['condition']}")
        if row["expression"]:
            lines.append(f"      ≡ {row['expression']}")
    return "\n".join(lines)


def collect_tasks(cur, year, variant, model, limit) -> list[dict]:
    cur.execute(SQL_TASKS, {"year": year, "variant": variant, "model": model,
                            "limit": limit})
    tasks = cur.fetchall()
    for task in tasks:
        task["marking_text"] = marking_text(cur, task["id"])
    return [t for t in tasks if t["marking_text"].strip()]


def run(con, year=None, variant=None, model=llm.DEFAULT_MODEL, limit=20,
        batch=False) -> llm.Spend:
    llm.check_model(model)
    anthropic_client = llm.client()
    spend = llm.Spend(model=model, batch=batch)

    with con.cursor(row_factory=dict_row) as cur:
        tasks = collect_tasks(cur, year, variant, model, limit)
    if not tasks:
        return spend

    answers: dict[int, dict] = {}
    try:
        ask = _ask_batch if batch else _ask_one_by_one
        ask(anthropic_client, tasks, model, spend, answers)
    finally:
        # Odpowiedź jest opłacona, gdy wróci — awaria na dwunastym zadaniu
        # nie ma prawa skasować jedenastu poprzednich.
        _store(con, answers, model, batch)
    return spend


def _store(con, answers: dict[int, dict], model: str, batch: bool) -> None:
    with con.cursor() as cur:
        for task_id, payload in answers.items():
            cur.execute(
                """INSERT INTO prefill_suggestion
                   (task_id, model, payload, input_tokens, output_tokens, batch)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (task_id, model) DO UPDATE
                     SET payload = EXCLUDED.payload,
                         input_tokens = EXCLUDED.input_tokens,
                         output_tokens = EXCLUDED.output_tokens,
                         batch = EXCLUDED.batch,
                         created_at = now()""",
                (task_id, model, Jsonb(payload["data"]), payload["input"],
                 payload["output"], batch),
            )


def _ask_one_by_one(anthropic_client, tasks, model, spend, out) -> dict[int, dict]:
    for task in tasks:
        try:
            response = anthropic_client.messages.parse(
                model=model,
                max_tokens=16000,
                system=SYSTEM,
                messages=[{"role": "user", "content": build_prompt(task)}],
                output_format=Prefill,
            )
        except Exception as e:
            spend.failures.append((str(task["id"]), f"{type(e).__name__}: {e}"))
            continue
        # Rachunek przed sprawdzeniem: odmowa i ucięcie na `max_tokens` też
        # kosztują.
        spend.add(response.usage.input_tokens, response.usage.output_tokens)
        parsed = response.parsed_output
        if parsed is None:
            # Odmowa wraca z kodem 200 i pustą strukturą; bez tego warunku
            # `.model_dump()` leciał AttributeError POZA pętlę.
            spend.failures.append(
                (str(task["id"]),
                 f"model nie oddał struktury (stop_reason: {response.stop_reason})"))
            continue
        out[task["id"]] = {"data": parsed.model_dump(),
                           "input": response.usage.input_tokens,
                           "output": response.usage.output_tokens}
        print(f"  zadanie {task['number']:>4}: progów {len(parsed.criteria)}")
    return out


def _ask_batch(anthropic_client, tasks, model, spend, out) -> dict[int, dict]:
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    schema = strict_schema(Prefill)
    requests = [
        Request(
            custom_id=f"task-{task['id']}",
            params=MessageCreateParamsNonStreaming(
                model=model,
                max_tokens=16000,
                system=SYSTEM,
                messages=[{"role": "user", "content": build_prompt(task)}],
                output_config={"format": {"type": "json_schema", "schema": schema}},
            ),
        )
        for task in tasks
    ]
    results = llm.run_batch(anthropic_client, requests, model)

    for task in tasks:
        result = results.get(f"task-{task['id']}")
        if result is None or result.type != "succeeded":
            reason = "brak wyniku" if result is None else result.type
            spend.failures.append((str(task["id"]), f"wsad: {reason}"))
            continue
        message = result.message
        text = next((b.text for b in message.content if b.type == "text"), "")
        try:
            parsed = parse_payload(text)
        except Exception as e:
            spend.failures.append((str(task["id"]), f"odpowiedź nie w schemacie: {e}"))
            continue
        spend.add(message.usage.input_tokens, message.usage.output_tokens)
        out[task["id"]] = {"data": parsed.model_dump(),
                           "input": message.usage.input_tokens,
                           "output": message.usage.output_tokens}
    return out


def report(spend: llm.Spend, suggestions: int) -> str:
    rule = "─" * 74
    lines = ["PREFILL LLM — PODPOWIEDZI DO EKRANU KOREKTY (S6)", rule,
             *spend.as_lines(),
             f"  podpowiedzi w bazie    : {suggestions}"]
    if spend.failures:
        lines += ["", f"  NIEUDANE: {len(spend.failures)}"]
        lines += [f"    ↳ zadanie {task_id}: {why}"
                  for task_id, why in spend.failures[:8]]
    lines += ["", "Odsetek zatwierdzeń bez poprawki i czas na zadanie — z ramion",
              "z podpowiedzią i bez — liczy `task correction:report` (sekcja S6)."]
    return "\n".join(lines) + "\n"


def main() -> int:
    _console_utf8()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, default=None)
    ap.add_argument("--variant", default=None, help="np. 100")
    ap.add_argument("--model", default=llm.DEFAULT_MODEL,
                    choices=sorted(llm.PRICING),
                    help="model jest parametrem przebiegu — porównanie jakości "
                         "przy 5× różnicy ceny jest częścią pomiaru S6")
    ap.add_argument("--limit", type=int, default=20,
                    help="ile zadań (próbka S6 to ≥20 zadań otwartych)")
    ap.add_argument("--batch", action="store_true",
                    help="przez Batch API — o połowę taniej, wynik po godzinach")
    ap.add_argument("--report", default=None)
    args = ap.parse_args()

    with psycopg.connect(polaczenie(), autocommit=True) as con:
        try:
            spend = run(con, args.year, args.variant, args.model, args.limit,
                        batch=args.batch)
        except llm.LlmUnavailable as e:
            print(e)
            return 2
        with con.cursor() as cur:
            cur.execute("SELECT count(*) FROM prefill_suggestion")
            (suggestions,) = cur.fetchone()
    text = report(spend, suggestions)
    path = llm.report_path("prefill", args.report)
    path.write_text(text, encoding="utf-8")
    print(text)
    print(f"Raport zapisany: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
