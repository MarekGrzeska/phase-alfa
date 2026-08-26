#!/usr/bin/env python3
"""Opisy rysunków — alt-text dla zasobów graficznych, pomiar S7 (G2.5.2).

Wycinek PNG + treść zadania jako kontekst → opis po polsku →
`asset.description` ze statusem `auto` → walidacja w ekranie korekty → `approved`.

Test jakości jest jeden i twardy: **opis ma pozwolić rozwiązać zadanie bez
patrzenia na rysunek**. „Ładny opis" nie jest kryterium — to wejście do A/B
„obraz vs opis" w A3 (G3.4.1, pytanie S1) i do WCAG, a w obu liczy się,
czy z opisu da się odtworzyć dane.

Provenance niesie schemat, nie pamięć: `description_status` w stanach
'none' → 'auto' → 'approved'. Do korpusu wchodzi wyłącznie `approved`.
"""

from __future__ import annotations

import argparse
import base64
import sys

import psycopg
from psycopg.rows import dict_row

from correction import llm
from pdf import crop as crop_pdf
from schema.migrate import polaczenie

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

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
    WHERE (%(force)s OR a.description_status = 'none')
      AND (%(year)s::smallint IS NULL OR d.year = %(year)s)
      AND (%(variant)s::text IS NULL
           OR %(variant)s = ANY(string_to_array(d.variants, ',')))
    ORDER BY d.session, d.path, t.position, a.id
    LIMIT %(limit)s"""


def build_prompt(asset: dict) -> str:
    lines = [f"Rysunek do zadania {asset['number']} (rodzaj: {asset['kind']})."]
    if asset.get("content"):
        lines += ["", "TREŚĆ ZADANIA:", asset["content"]]
    lines += ["", "Opisz rysunek tak, żeby dało się rozwiązać zadanie bez niego."]
    return "\n".join(lines)


def image_block(relative_path: str) -> dict:
    """Wycinek z bloba jako blok obrazu. Brak pliku to błąd, nie pusty opis."""
    path = crop_pdf.target_path(relative_path)
    if not path.exists():
        raise crop_pdf.CropError(
            f"brak wycinka {relative_path} — najpierw `task crops` albo ręczna ramka")
    data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    return {"type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": data}}


def message_for(asset: dict) -> list[dict]:
    return [{"role": "user",
             "content": [image_block(asset["path"]),
                         {"type": "text", "text": build_prompt(asset)}]}]


def collect_assets(cur, year, variant, limit, force) -> list[dict]:
    cur.execute(SQL_ASSETS, {"year": year, "variant": variant, "limit": limit,
                             "force": force})
    return cur.fetchall()


def run(con, year=None, variant=None, model=llm.DEFAULT_MODEL, limit=20,
        batch=False, force=False) -> llm.Spend:
    llm.check_model(model)
    anthropic_client = llm.client()
    spend = llm.Spend(model=model, batch=batch)

    with con.cursor(row_factory=dict_row) as cur:
        assets = collect_assets(cur, year, variant, limit, force)
    if not assets:
        return spend

    described = (_ask_batch(anthropic_client, assets, model, spend) if batch
                 else _ask_one_by_one(anthropic_client, assets, model, spend))
    with con.cursor() as cur:
        for asset_id, description in described.items():
            # `auto`, nigdy `approved`: to model, a nie człowiek. Bramka stoi
            # w ekranie korekty i tylko ona podnosi status.
            cur.execute(
                "UPDATE asset SET description = %s, description_status = 'auto' "
                "WHERE id = %s",
                (description, asset_id),
            )
    return spend


def _ask_one_by_one(anthropic_client, assets, model, spend) -> dict[int, str]:
    out: dict[int, str] = {}
    for asset in assets:
        try:
            messages = message_for(asset)
        except crop_pdf.CropError as e:
            spend.failures.append((asset["path"], str(e)))
            continue
        try:
            response = anthropic_client.messages.create(
                model=model, max_tokens=2000, system=SYSTEM, messages=messages)
        except Exception as e:
            spend.failures.append((asset["path"], f"{type(e).__name__}: {e}"))
            continue
        spend.add(response.usage.input_tokens, response.usage.output_tokens)
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        if not text:
            spend.failures.append((asset["path"], "model nie oddał tekstu"))
            continue
        out[asset["id"]] = text
        print(f"  zadanie {asset['number']:>4}: {text[:70]}")
    return out


def _ask_batch(anthropic_client, assets, model, spend) -> dict[int, str]:
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    requests, wanted = [], []
    for asset in assets:
        try:
            messages = message_for(asset)
        except crop_pdf.CropError as e:
            spend.failures.append((asset["path"], str(e)))
            continue
        wanted.append(asset)
        requests.append(Request(
            custom_id=f"asset-{asset['id']}",
            params=MessageCreateParamsNonStreaming(
                model=model, max_tokens=2000, system=SYSTEM, messages=messages),
        ))
    if not requests:
        return {}
    results = llm.run_batch(anthropic_client, requests, model)

    out: dict[int, str] = {}
    for asset in wanted:
        result = results.get(f"asset-{asset['id']}")
        if result is None or result.type != "succeeded":
            spend.failures.append((asset["path"],
                                   f"wsad: {'brak wyniku' if result is None else result.type}"))
            continue
        message = result.message
        spend.add(message.usage.input_tokens, message.usage.output_tokens)
        text = "".join(b.text for b in message.content if b.type == "text").strip()
        if text:
            out[asset["id"]] = text
        else:
            spend.failures.append((asset["path"], "model nie oddał tekstu"))
    return out


def counts(con) -> dict[str, int]:
    with con.cursor() as cur:
        cur.execute("SELECT description_status, count(*) FROM asset"
                    " GROUP BY description_status")
        found = dict(cur.fetchall())
    return {status: found.get(status, 0) for status in ("none", "auto", "approved")}


def report(spend: llm.Spend, totals: dict[str, int]) -> str:
    rule = "─" * 74
    total = sum(totals.values())
    decided = totals["auto"] + totals["approved"]
    lines = ["OPISY RYSUNKÓW — ALT-TEXT (S7)", rule, *spend.as_lines(), "",
             f"  zasobów razem          : {total}",
             f"  bez opisu              : {totals['none']}",
             f"  opis z modelu (auto)   : {totals['auto']}",
             f"  zatwierdzone (approved): {totals['approved']}",
             "  S7 — zatwierdzone bez poprawki: liczy `task correction:report`"]
    if total:
        lines.append(f"  pokrycie opisami       : {100 * decided / total:.1f}%")
    if spend.failures:
        lines += ["", f"  NIEUDANE: {len(spend.failures)}"]
        lines += [f"    ↳ {path}: {why}" for path, why in spend.failures[:8]]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, default=None)
    ap.add_argument("--variant", default=None, help="np. 100")
    ap.add_argument("--model", default=llm.DEFAULT_MODEL, choices=sorted(llm.PRICING))
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--batch", action="store_true",
                    help="przez Batch API — o połowę taniej, całe roczniki naraz")
    ap.add_argument("--force", action="store_true",
                    help="opisz także te, które mają już opis (zatwierdzonych "
                         "przez człowieka to NIE cofa — status zostaje)")
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
