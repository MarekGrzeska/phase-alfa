"""Wycinki graficzne w ekranie korekty — ręczna ramka i cięcie PNG (G2.4.2).

Automat wykrywający region (G2.4.1) jeszcze nie istnieje, a pilot 2025 ma
zadania z rysunkiem. Ramka wpisana ręcznie i wycinek robiony tą samą funkcją
`pdf.crop.crop` są tu zaworem: jeśli automat nie domknie tematu, ta droga
zamyka go i tak.
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
                    "box": dict(zip(BOX_FIELDS, box, strict=True)),
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


def save(cur, task_id: int, form: Mapping[str, str], edited: dict[str, int],
         problems: list[str]) -> None:
    """Ramki z formularza → baza i pliki PNG. Wołać w transakcji, jak `db.save`."""
    for asset in for_task(cur, task_id):
        box, page = _submitted(asset, form, problems)
        if box is None:
            continue
        changed = box != [float(v) for v in asset["bbox"]] or page != asset["page"]
        if not changed and asset["cropped"]:
            continue
        if asset["paper_path"] is None:
            problems.append(
                f"Zasób {asset['path']}: nie znam zeszytu zadań tej wersji, "
                "więc nie ma z czego wyciąć. Przeładuj klucz z `--z-arkuszami`.")
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


def counts(cur) -> dict[str, int]:
    """Ile zasobów ma dociągniętą ramkę i ile ma plik — miara „0 bez wycinka".

    Ramka „cała strona" to ta, którą wstawia parser: zaczyna się w zerze.
    """
    cur.execute("SELECT path, bbox FROM asset")
    rows = cur.fetchall()
    framed = sum(1 for r in rows
                 if not (float(r["bbox"][0]) == 0 and float(r["bbox"][1]) == 0))
    return {"total": len(rows),
            "framed": framed,
            "cropped": sum(1 for r in rows if _has_file(r["path"]))}
