"""Wycinek fragmentu strony PDF do pliku PNG.

Jedna droga dla obu źródeł ramki: automatu wykrywającego region (G2.4.1)
i ręcznego dociągnięcia w ekranie korekty (G2.4.2). Różnią się tym, skąd
bierze się `bbox` — nie tym, jak powstaje plik.
"""

from __future__ import annotations

import os
from pathlib import Path

from sciezki import KORZEN_REPO

# 200 DPI: rysunek z arkusza ma być czytelny po powiększeniu w przeglądarce
# korpusu, a nie tylko jako miniatura obok formularza.
DPI = 200
SCALE = DPI / 72

Bbox = tuple[float, float, float, float]


class CropError(Exception):
    """Nie da się wyciąć — z powodem po polsku, do pokazania w ekranie."""


def blob_root() -> Path:
    """Korzeń blobów: ta sama wartość, którą czyta `DiskBlobStore` w C#."""
    root = os.environ.get("BLOB_ROOT", "data/blob")
    p = Path(root)
    return p if p.is_absolute() else (KORZEN_REPO / p).resolve()


def target_path(relative: str) -> Path:
    """Ścieżka z `asset.path` jest WZGLĘDNA i ma zostać pod korzeniem blobów."""
    root = blob_root()
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root):
        raise CropError(f"ścieżka wychodzi poza katalog blobów: {relative}")
    return candidate


def crop(pdf_path: Path, page: int, bbox: Bbox, relative_target: str) -> Path:
    """Fragment strony `page` (numerowanej od 1) → PNG pod `relative_target`.

    `bbox` to `(x0, top, x1, bottom)` w punktach PDF, liczone od LEWEGO GÓRNEGO
    rogu strony — tak samo jak `top`/`bottom` w warstwie pozycyjnej
    (`pdf/layout.py`), z której wezmą się ramki automatu. pdfium liczy inaczej,
    stąd przeliczenie na marginesy poniżej.
    """
    try:
        import pypdfium2 as pdfium
    except ImportError as e:  # pragma: no cover - zależność jest w pyproject
        raise CropError("brak pypdfium2 — uruchom `uv sync` w ingest/") from e

    if not pdf_path.exists():
        raise CropError(f"brak pliku: {pdf_path.name}")

    x0, top, x1, bottom = (float(v) for v in bbox)
    if x1 <= x0 or bottom <= top:
        raise CropError("ramka jest pusta: prawy brzeg musi być za lewym, "
                        "a dolny pod górnym")

    document = pdfium.PdfDocument(str(pdf_path), password="")
    try:
        if not 1 <= page <= len(document):
            raise CropError(f"strona {page} poza dokumentem (stron: {len(document)})")
        sheet = document[page - 1]
        width, height = sheet.get_width(), sheet.get_height()
        if x1 > width + 1 or bottom > height + 1 or x0 < -1 or top < -1:
            raise CropError(
                f"ramka wychodzi poza stronę {page} ({width:.0f}×{height:.0f} pt)")
        # `crop` w pdfium to MARGINESY od krawędzi, w kolejności lewy, dolny,
        # prawy, górny — a nie współrzędne rogów.
        bitmap = sheet.render(scale=SCALE,
                              crop=(x0, height - bottom, width - x1, top))
        out = target_path(relative_target)
        out.parent.mkdir(parents=True, exist_ok=True)
        bitmap.to_pil().save(out)
    except CropError:
        raise
    except Exception as e:
        raise CropError(f"nie da się wyciąć fragmentu: {e}") from e
    finally:
        document.close()
    return out
