#!/usr/bin/env python3
"""Ramka rysunku z siatki — model zamiast ręcznego „Wytnij" (plan A2-auto, X3).

Zasób z ramką „cała strona" (parser wstawia zero w lewym górnym rogu) dostaje
obraz strony zeszytu z siatką — ten sam, który widzi człowiek w ekranie korekty —
i model oddaje cztery liczby w pikselach tego obrazu; na punkty PDF przelicza je
kod, bo zna skalę renderu. Cięcie robi `pdf.crop.crop`, jak przy ręcznej ramce,
więc automat i człowiek różnią się wyłącznie tym, skąd bierze się `bbox`.

Provenance ramki nie ma w schemacie (parser, człowiek i model piszą tę samą
kolumnę) — to świadoma luka MVP: ramka jest widoczna gołym okiem w przeglądarce
W2, a zła ramka nie psuje oceny, tylko obraz. Raport z przebiegu jest śladem.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

from correction import llm, pages
from pdf import crop as crop_pdf
from schema.migrate import polaczenie


def _console_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


# Model oddaje PIKSELE obrazu, który widzi — nie punkty PDF. Pierwsza wersja
# prosiła o punkty z podpisów siatki i dostawała piksele (obraz jest w skali 2),
# czyli ramki wychodzące poza stronę. Przeliczenie robi kod, bo zna skalę.
class Frame(BaseModel):
    found: bool = Field(description="czy na stronie jest rysunek tego zadania")
    x0: float = Field(description="lewy brzeg w PIKSELACH obrazu, od lewej krawędzi")
    top: float = Field(description="górny brzeg w PIKSELACH obrazu, od górnej krawędzi")
    x1: float = Field(description="prawy brzeg w pikselach obrazu")
    bottom: float = Field(description="dolny brzeg w pikselach obrazu")
    reason: str = Field(description="po polsku: co obejmuje ramka albo dlaczego jej nie ma")


SYSTEM = """Na obrazie jest strona zeszytu zadań egzaminu ósmoklasisty z naniesioną
siatką pomocniczą. Znajdź rysunek, wykres, diagram albo tabelę-ilustrację należącą
do wskazanego zadania i oddaj ramkę `x0, top, x1, bottom` W PIKSELACH OBRAZU,
liczonych od LEWEGO GÓRNEGO rogu obrazu (oś pionowa rośnie w dół), z zapasem
ok. 10 pikseli z każdej strony — tak, żeby objąć cały rysunek z podpisami osi
i etykietami, ale bez treści zadania i bez sąsiednich zadań.

W wiadomości dostajesz rozmiar obrazu w pikselach; żadna współrzędna nie może
go przekroczyć.

`found: false`, gdy na tej stronie nie ma rysunku tego zadania (np. zadanie ma
tylko tekst albo rysunek jest na innej stronie). Wtedy liczby ustaw na 0.
"""

MAX_OUTPUT_TOKENS = 2000
MIN_SIZE = 20.0       # w punktach PDF
SLACK = 6.0           # o tyle ramka może wystawać poza stronę — przycinamy, nie odrzucamy

SQL_ASSETS = """
    SELECT a.id, a.path, a.kind, a.page, a.bbox,
           t.number, tv.content, d.path AS paper_path, d.pages AS paper_pages,
           m.year, f.variant
    FROM asset a
    JOIN task_version tv ON tv.id = a.task_version_id
    JOIN task t ON t.id = tv.task_id
    JOIN document m ON m.id = t.marking_scheme_id
    JOIN exam_form f ON f.id = tv.exam_form_id
    LEFT JOIN exam_form_document fd ON fd.exam_form_id = f.id AND fd.role = 'paper'
    LEFT JOIN document d ON d.id = fd.document_id
    WHERE a.bbox[1] = 0 AND a.bbox[2] = 0
      AND (%(year)s::smallint IS NULL OR m.year = %(year)s)
      AND (%(variant)s::text IS NULL OR f.variant = %(variant)s)
    ORDER BY m.year, f.variant, t.position, a.id
    LIMIT %(limit)s"""


def collect_assets(cur, year, variant, limit) -> list[dict]:
    cur.execute(SQL_ASSETS, {"year": year, "variant": variant, "limit": limit})
    return cur.fetchall()


def build_prompt(asset: dict, size: tuple[int, int]) -> str:
    lines = [f"Zadanie {asset['number']}, rodzaj zasobu: {asset['kind']}, "
             f"strona {asset['page']} zeszytu.",
             f"Obraz ma {size[0]} × {size[1]} pikseli (szerokość × wysokość)."]
    if asset.get("content"):
        lines += ["", "TREŚĆ ZADANIA (dla rozpoznania, którego rysunku szukać):",
                  asset["content"][:800]]
    lines += ["", "Oddaj ramkę rysunku tego zadania w pikselach obrazu."]
    return "\n".join(lines)


def image_size(path) -> tuple[int, int]:
    from PIL import Image
    with Image.open(path) as image:
        return image.size


def messages_for(asset: dict) -> tuple[list, tuple[int, int]]:
    """Wiadomości dla modelu i rozmiar obrazu — ten sam obraz, który widzi człowiek."""
    path = pages.render(asset["paper_path"], asset["page"], grid=True)
    size = image_size(path)
    data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    return llm.messages(SYSTEM, [
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{data}"}},
        {"type": "text", "text": build_prompt(asset, size)}]), size


def parse_payload(payload: dict | str) -> Frame:
    return Frame.model_validate(json.loads(payload) if isinstance(payload, str)
                                else payload)


def to_points(frame: Frame, size: tuple[int, int],
              scale: float = pages.SCALE) -> tuple[list[float] | None, str | None]:
    """Piksele obrazu → punkty PDF; albo powód, dlaczego ramki nie wolno zapisać.

    Wystawanie do `SLACK` pt przycinamy do strony (model dodaje zapas), większe
    odrzucamy — to znak, że współrzędne są w innej skali, a nie że rysunek
    dotyka krawędzi.
    """
    if not frame.found:
        return None, frame.reason or "model nie widzi rysunku na tej stronie"
    width, height = size[0] / scale, size[1] / scale
    box = [frame.x0 / scale, frame.top / scale, frame.x1 / scale, frame.bottom / scale]
    if min(box) < -SLACK or box[2] > width + SLACK or box[3] > height + SLACK:
        return None, (f"ramka poza stroną {width:.0f}×{height:.0f} pt: "
                      f"{[round(v) for v in box]}")
    box = [max(0.0, box[0]), max(0.0, box[1]), min(width, box[2]), min(height, box[3])]
    if box[2] - box[0] < MIN_SIZE or box[3] - box[1] < MIN_SIZE:
        return None, f"ramka za mała: {[round(v) for v in box]}"
    if box[0] == 0 and box[1] == 0:
        return None, "ramka zaczyna się w rogu strony — to jest „cała strona”, nie rysunek"
    return box, None


def apply_frame(cur, asset: dict, frame: Frame, size: tuple[int, int]) -> str:
    """Wycięcie i zapis ramki. Zwraca stan: `framed` albo powód odmowy."""
    box, why = to_points(frame, size)
    if why:
        return why
    try:
        crop_pdf.crop(pages.source_pdf(asset["paper_path"]), asset["page"],
                      (box[0], box[1], box[2], box[3]), asset["path"])
    except (crop_pdf.CropError, pages.PageUnavailable) as e:
        return f"cięcie odrzucone: {e}"
    cur.execute("UPDATE asset SET bbox = %s WHERE id = %s", (box, asset["id"]))
    return "framed"


def run(con, year=None, variant=None, model=llm.DEFAULT_MODEL, limit=20,
        apply=False) -> tuple[llm.Spend, list[dict]]:
    llm.check_model(model)
    spend = llm.Spend(model=model)
    with con.cursor(row_factory=dict_row) as cur:
        assets = collect_assets(cur, year, variant, limit)
    rows: list[dict] = []
    if not assets:
        return spend, rows

    structured = llm.chat_model(
        model, max_tokens=MAX_OUTPUT_TOKENS
    ).with_structured_output(Frame, include_raw=True)

    for asset in assets:
        row = {"asset_id": asset["id"], "path": asset["path"], "year": asset["year"],
               "number": asset["number"], "state": None, "box": None, "reason": None}
        rows.append(row)
        if asset["paper_path"] is None:
            row["state"] = "failed"
            row["reason"] = "brak zeszytu zadań w bazie — `task ingest -- --with-papers`"
            spend.failures.append((asset["path"], row["reason"]))
            continue
        try:
            messages, size = messages_for(asset)
            result = structured.invoke(messages)
        except Exception as e:
            row["state"], row["reason"] = "failed", f"{type(e).__name__}: {e}"
            spend.failures.append((asset["path"], row["reason"]))
            continue
        spend.add(*llm.usage_of(result.get("raw")))
        frame = result.get("parsed")
        if frame is None:
            row["state"], row["reason"] = "failed", "model nie oddał struktury"
            spend.failures.append((asset["path"], row["reason"]))
            continue
        box, why = to_points(frame, size)
        row["box"] = [round(v, 1) for v in box] if box else None
        row["reason"] = frame.reason
        if apply:
            with con.transaction(), con.cursor(row_factory=dict_row) as cur:
                row["state"] = apply_frame(cur, asset, frame, size)
        else:
            row["state"] = "dry:ok" if why is None else f"dry:refused — {why}"
        print(f"  {asset['path']}: {row['state']}"
              + (f" {row['box']}" if row["box"] else ""))
    return spend, rows


def report(spend: llm.Spend, rows: list[dict], apply: bool) -> str:
    rule = "─" * 74
    framed = sum(1 for r in rows if r["state"] in ("framed", "dry:ok"))
    lines = ["RAMKI Z SIATKI — MODEL ZAMIAST RĘCZNEGO „WYTNIJ” (plan A2-auto, X3)", rule,
             *spend.as_lines(),
             f"  tryb                   : {'ZAPIS do bazy i bloba' if apply else 'na sucho'}",
             f"  zasobów w przebiegu    : {len(rows)}",
             f"  wyciętych              : {framed}",
             f"  odmów / błędów         : {len(rows) - framed}"]
    for r in rows:
        if r["state"] != "framed":
            lines.append(f"    ↳ {r['path']}: {r['state']}"
                         + (f" — {r['reason']}" if r["reason"] and "—" not in r["state"] else ""))
    lines += ["", "Ramki widać w przeglądarce W2 i w ekranie korekty (karta „Wycinki”)."]
    return "\n".join(lines) + "\n"


def main() -> int:
    _console_utf8()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, default=None)
    ap.add_argument("--variant", default=None, help="np. 100")
    ap.add_argument("--model", default=llm.DEFAULT_MODEL, choices=sorted(llm.PRICING))
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--apply", action="store_true",
                    help="tnij i zapisuj ramki; bez tej flagi tylko raport")
    ap.add_argument("--report", default=None)
    args = ap.parse_args()

    with psycopg.connect(polaczenie(), autocommit=True) as con:
        try:
            spend, rows = run(con, args.year, args.variant, args.model, args.limit,
                              apply=args.apply)
        except llm.LlmUnavailable as e:
            print(e)
            return 2
    text = report(spend, rows, args.apply)
    path = llm.report_path("frame", args.report)
    path.write_text(text, encoding="utf-8")
    path.with_suffix(".json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(text)
    print(f"Raport zapisany: {path} (+ .json) · {datetime.now(timezone.utc):%H:%M} UTC")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
