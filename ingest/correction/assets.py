"""Wycinki graficzne i opisy rysunków w ekranie korekty (G2.4.2, G2.5.2).

Ramkę wykrywa automat z `pdf.regions` (G2.4.1), a gdy nie domknie — dociąga
ją człowiek w formularzu. Obie drogi tną tą samą funkcją `pdf.crop.crop`
i różnią się WYŁĄCZNIE źródłem `bbox`; ręczna jest zaworem nr 3 z Planu
Implementacji, nie awarią.

Opis rysunku (alt-text) proponuje model, a rozstrzyga człowiek: `approved`
znaczy „model trafił sam", `corrected` — „człowiek poprawił". Na tej różnicy
stoi pomiar S7.
"""

from __future__ import annotations

from collections.abc import Mapping

from correction import pages
from pdf import crop as crop_pdf

# Pola ramki w formularzu, w kolejności, w jakiej stoją w `asset.bbox`.
BOX_FIELDS = ("x0", "top", "x1", "bottom")


def for_task(cur, task_id: int) -> list[dict]:
    """Zasoby zadania z ramką, źródłowym zeszytem i informacją, czy plik już jest."""
    cur.execute(
        """SELECT DISTINCT ON (a.id)
                  a.id, a.kind, a.path, a.page, a.bbox,
                  a.description, a.description_status,
                  f.variant, f.version, d.path AS paper_path, d.pages AS paper_pages
           FROM asset a
           JOIN task_version tv ON tv.id = a.task_version_id
           JOIN exam_form f ON f.id = tv.exam_form_id
           LEFT JOIN exam_form_document fd
                  ON fd.exam_form_id = f.id AND fd.role = 'paper'
           LEFT JOIN document d ON d.id = fd.document_id
           WHERE tv.task_id = %s
           ORDER BY a.id, f.variant, f.version""",
        (task_id,),
    )
    out = []
    for row in cur.fetchall():
        box = [float(v) for v in row["bbox"]]
        out.append({**row,
                    # Tekst, nie liczba: po nieudanej walidacji w to samo pole
                    # wchodzi to, co człowiek wpisał, a szablon nie ma wtedy
                    # czego formatować.
                    "box": {name: f"{value:.1f}" for name, value
                            in zip(BOX_FIELDS, box, strict=True)},
                    "cropped": _has_file(row["path"]),
                    # Parser wstawia ramkę „cała strona" z zerem w lewym górnym
                    # rogu; ręczna i automatyczna prawie nigdy tam nie zaczyna.
                    "framed": not (box[0] == 0 and box[1] == 0)})
    return out


def _has_file(relative: str) -> bool:
    try:
        return crop_pdf.target_path(relative).exists()
    except crop_pdf.CropError:
        return False


# `manual` — opis człowieka tam, gdzie modelu nie było — stoi poza S7 tak samo,
# jak `rejected` stoi poza S8: nie ma czego przepuścić ani poprawić.
DESCRIPTION_STATUSES = ("none", "auto", "approved", "corrected", "manual")

# O rodowodzie rozstrzyga stan POPRZEDNI: po edycji tekst w bazie jest już
# tekstem człowieka, więc porównanie z nim mówi tylko, czy ktoś kliknął dwa razy.
_AFTER_HUMAN_EDIT = {"none": "manual", "manual": "manual",
                     "auto": "corrected", "approved": "corrected",
                     "corrected": "corrected"}


def save_description(cur, asset: dict, form: Mapping[str, str],
                     described: dict[str, int], problems: list[str]) -> None:
    """Opis rysunku i jego rozstrzygnięcie — pomiar S7 (G2.5.2).

    Trafieniem jest wyłącznie stan `auto` przyjęty bez zmiany; sama edycja
    rozstrzyga S7 na „nie" i nie czeka na zatwierdzenie. Wynik idzie do
    `described`, nie do `edited` — zatwierdzenie opisu nie jest poprawką
    parsera i nie ma prawa ruszyć S8.
    """
    submitted = form.get(f"asset.{asset['id']}.description")
    if submitted is None:
        return
    approving = form.get(f"asset.{asset['id']}.approve_description") is not None
    text = submitted.strip() or None
    was = asset["description_status"]
    changed = text != (asset["description"] or None)

    if approving and text is None:
        problems.append(f"Zasób {asset['path']}: nie ma czego zatwierdzić — "
                        "opis jest pusty.")
        return

    if text is None:
        # Pusty rekord w mianowniku S7 byłby rozstrzygnięciem, którego nie ma.
        status = "none"
    elif changed:
        status = _AFTER_HUMAN_EDIT[was]
    elif approving:
        status = {"auto": "approved", "none": "manual"}.get(was, was)
    else:
        status = was

    if not changed and status == was:
        return
    cur.execute(
        "UPDATE asset SET description = %s, description_status = %s WHERE id = %s",
        (text, status, asset["id"]),
    )
    if cur.rowcount:
        described[status] = described.get(status, 0) + cur.rowcount


def save(cur, task_id: int, form: Mapping[str, str], edited: dict[str, int],
         described: dict[str, int], problems: list[str]) -> None:
    """Ramki i opisy z formularza → baza i pliki PNG. Wołać w transakcji, jak `db.save`.

    Ramki idą do `edited` (S8), opisy do `described` (S7) — wspólny licznik
    mieszałby dwie niezależne liczby.
    """
    for asset in for_task(cur, task_id):
        save_description(cur, asset, form, described, problems)
        box, page = _submitted(asset, form, problems)
        if box is None:
            continue
        changed = box != [float(v) for v in asset["bbox"]] or page != asset["page"]
        if not changed and asset["cropped"]:
            continue
        if asset["paper_path"] is None:
            problems.append(
                f"Zasób {asset['path']}: nie znam zeszytu zadań tej wersji, "
                "więc nie ma z czego wyciąć. Przeładuj klucz z `--with-papers`.")
            continue
        try:
            crop_pdf.crop(pages.source_pdf(asset["paper_path"]), page,
                          (box[0], box[1], box[2], box[3]), asset["path"])
        except (crop_pdf.CropError, pages.PageUnavailable) as e:
            problems.append(f"Zasób {asset['path']}: {e}")
            continue
        if changed:
            cur.execute("UPDATE asset SET bbox = %s, page = %s WHERE id = %s",
                        (box, page, asset["id"]))
            edited["asset"] = edited.get("asset", 0) + 1


def _submitted(asset: dict, form: Mapping[str, str],
               problems: list[str]) -> tuple[list[float] | None, int]:
    """Ramka i strona z formularza. `None` znaczy „tego zasobu nie przysłano"."""
    raw = {name: form.get(f"asset.{asset['id']}.{name}") for name in BOX_FIELDS}
    raw_page = form.get(f"asset.{asset['id']}.page")
    if all(v is None for v in raw.values()) and raw_page is None:
        return None, asset["page"]

    box: list[float] = []
    for name in BOX_FIELDS:
        value = (raw[name] or "").strip().replace(",", ".")
        try:
            box.append(float(value))
        except ValueError:
            problems.append(f"Zasób {asset['path']}: pole {name} nie jest liczbą "
                            f"({value or 'puste'}).")
            return None, asset["page"]

    page = asset["page"]
    if raw_page is not None and str(raw_page).strip():
        if not str(raw_page).strip().isdigit():
            problems.append(f"Zasób {asset['path']}: strona nie jest liczbą.")
            return None, asset["page"]
        page = int(str(raw_page).strip())
    return box, page


def source(cur, asset_id: int) -> dict | None:
    """Zasób z ramką i zeszytem źródłowym — do podglądu strony i wycinka."""
    cur.execute(
        """SELECT DISTINCT ON (a.id)
                  a.id, a.path, a.page, a.bbox,
                  d.path AS paper_path, d.pages AS paper_pages
           FROM asset a
           JOIN task_version tv ON tv.id = a.task_version_id
           JOIN exam_form f ON f.id = tv.exam_form_id
           LEFT JOIN exam_form_document fd
                  ON fd.exam_form_id = f.id AND fd.role = 'paper'
           LEFT JOIN document d ON d.id = fd.document_id
           WHERE a.id = %s
           ORDER BY a.id, f.variant, f.version""",
        (asset_id,),
    )
    return cur.fetchone()


def _blob_files() -> set[str]:
    """Ścieżki względne plików pod korzeniem blobów — JEDNO przejście po katalogu.

    Pytanie o każdy zasób osobno kosztuje przy pełnym korpusie 587 zapytań
    do dysku na każde otwarcie strony głównej.
    """
    try:
        root = crop_pdf.blob_root()
    except crop_pdf.CropError:
        return set()
    if not root.exists():
        return set()
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def counts(cur) -> dict[str, int]:
    """Ile zasobów ma dociągniętą ramkę i ile ma plik — miara „0 bez wycinka".

    Ramka „cała strona" to ta, którą wstawia parser: zaczyna się w zerze.
    """
    cur.execute("SELECT path, bbox FROM asset")
    rows = cur.fetchall()
    framed = sum(1 for r in rows
                 if not (float(r["bbox"][0]) == 0 and float(r["bbox"][1]) == 0))
    na_dysku = _blob_files()
    return {"total": len(rows),
            "framed": framed,
            "cropped": sum(1 for r in rows
                           if r["path"].replace("\\", "/") in na_dysku),
            **describe_counts(cur)}


def describe_counts(cur) -> dict[str, int]:
    """Stan opisów rysunków — surowiec pomiaru S7."""
    cur.execute("SELECT description_status, count(*) AS n FROM asset"
                " GROUP BY description_status")
    found = {r["description_status"]: r["n"] for r in cur.fetchall()}
    return {f"description_{status}": found.get(status, 0)
            for status in DESCRIPTION_STATUSES}
