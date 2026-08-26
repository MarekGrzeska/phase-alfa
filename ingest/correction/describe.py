#!/usr/bin/env python3
"""Opisy rysunków — alt-text dla zasobów graficznych, pomiar S7 (G2.5.2).

Wycinek PNG + treść zadania jako kontekst → opis po polsku →
`asset.description` ze statusem `auto` → walidacja w ekranie korekty → `approved`.

Test jakości jest jeden i twardy: **opis ma pozwolić rozwiązać zadanie bez
patrzenia na rysunek**. „Ładny opis" nie jest kryterium — to wejście do A/B
„obraz vs opis" w A3 (G3.4.1, pytanie S1) i do WCAG, a w obu liczy się,
czy z opisu da się odtworzyć dane.

Provenance niesie schemat, nie pamięć: `description_status` w stanach
'none' → 'auto' → 'approved' (model trafił sam) albo 'corrected' (człowiek
poprawił opis modelu); 'manual' to opis napisany od zera, gdy modelu tu
nie było, i stoi POZA pomiarem S7.
"""

from __future__ import annotations

import argparse
import base64
import sys

import psycopg
from psycopg.rows import dict_row

from correction import llm
from correction.assets import DESCRIPTION_STATUSES
from pdf import crop as crop_pdf
from schema.migrate import polaczenie

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# Praca człowieka — nie tyka jej nawet `--force`. Przebieg modelu kosztuje
# kilka centów i da się powtórzyć; zatwierdzony opis nie.
HUMAN_STATUSES = ("approved", "corrected", "manual")

SYSTEM = """Opisujesz rysunek z arkusza egzaminacyjnego dla ucznia, który go
nie widzi.

Test jakości jest jeden: po przeczytaniu Twojego opisu ma się dać rozwiązać
zadanie bez oglądania rysunku.

Zasady:
- Podaj WSZYSTKIE dane liczbowe i oznaczenia widoczne na rysunku: długości,
  kąty, etykiety wierzchołków, podpisy osi, wartości na skali, jednostki.
- Nazwij typ rysunku (wykres słupkowy, oś liczbowa, figura, siatka, układ
  współrzędnych) i to, co przedstawia.
- Nie rozwiązuj zadania i nie podpowiadaj metody.
- Nie opisuj kolorów ani stylu, jeśli nie niosą danych.
- Piszesz po polsku, zwięźle, pełnymi zdaniami. Bez wstępu „na rysunku widać".
"""

SQL_ASSETS = """
    SELECT a.id, a.path, a.kind, a.description_status,
           t.number, tv.content
    FROM asset a
    JOIN task_version tv ON tv.id = a.task_version_id
    JOIN task t ON t.id = tv.task_id
    JOIN document d ON d.id = t.marking_scheme_id
    WHERE NOT (a.description_status = ANY(%(human)s))
      AND (%(force)s OR a.description_status = 'none')
      AND (%(year)s::smallint IS NULL OR d.year = %(year)s)
      AND (%(variant)s::text IS NULL
           OR %(variant)s = ANY(string_to_array(d.variants, ',')))
    ORDER BY d.session, d.path, t.position, a.id
    LIMIT %(limit)s"""


# Opis to kilka zdań, ale modele myślące liczą do tego limitu także tokeny
# rozumowania — przy limicie na miarę samego opisu grozi pusty tekst po opłacie.
MAX_OUTPUT_TOKENS = 4000


def build_prompt(asset: dict) -> str:
    lines = [f"Rysunek do zadania {asset['number']} (rodzaj: {asset['kind']})."]
    if asset.get("content"):
        lines += ["", "TREŚĆ ZADANIA:", asset["content"]]
    lines += ["", "Opisz rysunek tak, żeby dało się rozwiązać zadanie bez niego."]
    return "\n".join(lines)


def image_block(relative_path: str) -> dict:
    """Wycinek z bloba jako blok obrazu. Brak pliku to błąd, nie pusty opis.

    Postać `image_url` z URI danych, a nie blok natywny dostawcy: przyjmują ją
    zarówno pakiety LangChaina, jak i konwerter do ciała wsadowego, więc obraz
    jest budowany RAZ dla obu ścieżek.
    """
    path = crop_pdf.target_path(relative_path)
    if not path.exists():
        raise crop_pdf.CropError(
            f"brak wycinka {relative_path} — najpierw `task crops` albo ręczna ramka")
    data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    return {"type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{data}"}}


def message_for(asset: dict) -> list:
    """Wiadomości w postaci LangChaina — te same dla przebiegu wsadowego."""
    return llm.messages(SYSTEM, [image_block(asset["path"]),
                                 {"type": "text", "text": build_prompt(asset)}])


def collect_assets(cur, year, variant, limit, force) -> list[dict]:
    cur.execute(SQL_ASSETS, {"year": year, "variant": variant, "limit": limit,
                             "force": force, "human": list(HUMAN_STATUSES)})
    return cur.fetchall()


def run(con, year=None, variant=None, model=llm.DEFAULT_MODEL, limit=20,
        batch=False, force=False) -> llm.Spend:
    llm.check_model(model)
    if batch:
        llm.check_batch(model)
    spend = llm.Spend(model=model, batch=batch)

    with con.cursor(row_factory=dict_row) as cur:
        wanted = collect_assets(cur, year, variant, limit, force)
    if not wanted:
        return spend

    described: dict[int, str] = {}
    try:
        if batch:
            _ask_batch(wanted, model, spend, described)
        else:
            # Limit przy budowie modelu, nie przy wywołaniu: nazwę parametru
            # mapuje na dostawcę LangChain (`max_completion_tokens` u OpenAI).
            _ask_one_by_one(llm.chat_model(model, max_tokens=MAX_OUTPUT_TOKENS),
                            wanted, spend, described)
    finally:
        # Odpowiedź jest opłacona, gdy wróci — awaria na dwunastym zasobie
        # nie ma prawa skasować jedenastu poprzednich.
        _store(con, described)
    return spend


def _store(con, described: dict[int, str]) -> None:
    with con.cursor() as cur:
        for asset_id, description in described.items():
            # `auto`, nigdy `approved`: status podnosi tylko ekran korekty.
            # Warunek powtarza sito zapytania — między odczytem a zapisem
            # człowiek mógł zdążyć zatwierdzić opis.
            cur.execute(
                "UPDATE asset SET description = %s, description_status = 'auto' "
                "WHERE id = %s AND NOT (description_status = ANY(%s))",
                (description, asset_id, list(HUMAN_STATUSES)),
            )


def _text_of(content) -> str:
    """Treść odpowiedzi jako tekst — LangChain oddaje ją napisem albo blokami."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content
                       if isinstance(part, dict)).strip()
    return ""


def _ask_one_by_one(chat, assets, spend, out) -> dict[int, str]:
    for asset in assets:
        try:
            messages = message_for(asset)
        except crop_pdf.CropError as e:
            spend.failures.append((asset["path"], str(e)))
            continue
        try:
            response = chat.invoke(messages)
        except Exception as e:
            spend.failures.append((asset["path"], f"{type(e).__name__}: {e}"))
            continue
        # Rachunek przed sprawdzeniem: pusta odpowiedź też jest opłacona.
        spend.add(*llm.usage_of(response))
        text = _text_of(response.content)
        if not text:
            spend.failures.append((asset["path"], "model nie oddał tekstu"))
            continue
        out[asset["id"]] = text
        print(f"  zadanie {asset['number']:>4}: {text[:70]}")
    return out


def _ask_batch(assets, model, spend, out, client=None) -> dict[int, str]:
    requests, wanted = [], []
    for asset in assets:
        try:
            messages = message_for(asset)
        except crop_pdf.CropError as e:
            spend.failures.append((asset["path"], str(e)))
            continue
        wanted.append(asset)
        requests.append(llm.batch_request(
            f"asset-{asset['id']}",
            llm.batch_body(model, messages, max_tokens=MAX_OUTPUT_TOKENS)))
    if not requests:
        return out
    results = llm.run_batch(requests, model, client=client)

    for asset in wanted:
        body, why = llm.batch_payload(results.get(f"asset-{asset['id']}"))
        if body is None:
            spend.failures.append((asset["path"], why))
            continue
        spend.add(*llm.usage_of(body.get("usage")))
        choice = (body.get("choices") or [{}])[0]
        text = _text_of((choice.get("message") or {}).get("content"))
        if text:
            out[asset["id"]] = text
        else:
            spend.failures.append((asset["path"], "model nie oddał tekstu"))
    return out


def counts(con) -> dict[str, int]:
    """Stan opisów w całej bazie — mianownik pokrycia.

    Listę stanów bierze `assets`: wypisana tu z pamięci gubiła stan dodany
    migracją, a wtedy mianownik kurczy się z każdą poprawką człowieka.
    """
    with con.cursor() as cur:
        cur.execute("SELECT description_status, count(*) FROM asset"
                    " GROUP BY description_status")
        found = dict(cur.fetchall())
    return {status: found.get(status, 0) for status in DESCRIPTION_STATUSES}


def report(spend: llm.Spend, totals: dict[str, int]) -> str:
    rule = "─" * 74
    total = sum(totals.values())
    described = total - totals["none"]
    lines = ["OPISY RYSUNKÓW — ALT-TEXT (S7)", rule, *spend.as_lines(), "",
             f"  zasobów razem          : {total}",
             f"  bez opisu              : {totals['none']}",
             f"  opis z modelu (auto)   : {totals['auto']}",
             f"  zatwierdzone (approved): {totals['approved']}",
             f"  poprawione (corrected) : {totals['corrected']}",
             f"  własne człowieka       : {totals['manual']}",
             "  S7 — zatwierdzone bez poprawki: liczy `task correction:report`"]
    if total:
        lines.append(f"  pokrycie opisami       : {100 * described / total:.1f}%")
    if spend.failures:
        lines += ["", f"  NIEUDANE: {len(spend.failures)}"]
        lines += [f"    ↳ {path}: {why}" for path, why in spend.failures[:8]]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, default=None)
    ap.add_argument("--variant", default=None, help="np. 100")
    ap.add_argument("--model", default=llm.DEFAULT_MODEL, choices=sorted(llm.PRICING),
                    help="`dostawca:nazwa` — model i dostawca są parametrem przebiegu")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--batch", action="store_true",
                    help="przez Batch API — o połowę taniej, całe roczniki naraz; "
                         f"dostawcy z adapterem: {', '.join(llm.BATCH_PROVIDERS)}")
    ap.add_argument("--force", action="store_true",
                    help="opisz od nowa także te, które mają już opis z modelu; "
                         "opisów zatwierdzonych, poprawionych i własnych "
                         "człowieka nie tyka ani treścią, ani statusem")
    ap.add_argument("--report", default=None)
    args = ap.parse_args()

    with psycopg.connect(polaczenie(), autocommit=True) as con:
        try:
            spend = run(con, args.year, args.variant, args.model, args.limit,
                        batch=args.batch, force=args.force)
        except llm.LlmUnavailable as e:
            print(e)
            return 2
        text = report(spend, counts(con))
    path = llm.report_path("descriptions", args.report)
    path.write_text(text, encoding="utf-8")
    print(text)
    print(f"Raport zapisany: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
