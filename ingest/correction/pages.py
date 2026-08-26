"""Render strony PDF do PNG — dokument obok formularza, bo korekta bez źródła
jest zgadywaniem."""

from __future__ import annotations

import hashlib
from pathlib import Path

from sciezki import KORZEN_REPO, korzen_mirrora

CACHE = KORZEN_REPO / "data" / "cache" / "pages"

# 2× to ~144 DPI: drobny druk kryteriów jest czytelny, a strona waży
# kilkaset kilobajtów zamiast kilku megabajtów.
SCALE = 2.0

# Siatka współrzędnych pod ręczną ramkę (G2.4.2): kreska co 50 pt, podpis co 100.
# Bez niej wpisanie bboxa jest zgadywaniem, a ekran nie ma ani linijki
# JavaScriptu, więc przeciąganie myszą nie wchodzi w grę.
GRID_STEP = 50
GRID_LABEL_EVERY = 100


class PageUnavailable(Exception):
    """Nie ma czego pokazać — z powodem po polsku, do wyświetlenia w ekranie."""


def source_pdf(relative_path: str) -> Path:
    """Ścieżka z bazy jest WZGLĘDNA wobec mirrora i ma w nim zostać.

    Ten sam sprawdzian co w `DiskBlobStore`: nazwy w bazie biorą się z nazw
    plików CKE, więc `..` w takiej ścieżce nie jest scenariuszem z bajki.
    """
    root = korzen_mirrora().resolve()
    candidate = (root / relative_path).resolve()
    if not candidate.is_relative_to(root):
        raise PageUnavailable(f"ścieżka wychodzi poza mirror: {relative_path}")
    return candidate


def render(relative_path: str, page: int, grid: bool = False) -> Path:
    """Strona (numerowana od 1) jako PNG w pamięci podręcznej."""
    pdf_path = source_pdf(relative_path)
    if not pdf_path.exists():
        raise PageUnavailable(
            f"brak pliku w mirrorze: {relative_path} — ustaw MIRROR_ROOT albo `task mirror`")

    # Klucz cache'u to ścieżka i numer strony, bez znacznika czasu: mirror jest
    # z założenia niezmienny („mirror raz, potem tylko kopia"), a plik pobrany
    # ponownie ma tę samą treść i sumę SHA-256.
    stamp = hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:16]
    # Skala w nazwie, bo `SCALE` jest stała do podkręcenia — a bez niej ekran
    # po jej zmianie dalej trafiał w stary plik i pokazywał starą rozdzielczość.
    out = CACHE / f"{stamp}-{page}-{SCALE:g}{'-grid' if grid else ''}.png"
    if out.exists():
        return out

    try:
        import pypdfium2 as pdfium
    except ImportError as e:  # pragma: no cover - zależność jest w pyproject
        raise PageUnavailable("brak pypdfium2 — uruchom `uv sync` w ingest/") from e

    try:
        # Pusty właściciel hasła: jeden klucz w korpusie (MMAP-R0-100-2605-zasady)
        # jest zaszyfrowany AES-em z pustym hasłem. To przypadek, nie błąd.
        document = pdfium.PdfDocument(str(pdf_path), password="")
        try:
            if not 1 <= page <= len(document):
                raise PageUnavailable(
                    f"strona {page} poza dokumentem (stron: {len(document)})")
            bitmap = document[page - 1].render(scale=SCALE)
            image = bitmap.to_pil()
            if grid:
                _draw_grid(image)
            out.parent.mkdir(parents=True, exist_ok=True)
            image.save(out)
        finally:
            document.close()
    except PageUnavailable:
        raise
    except Exception as e:
        raise PageUnavailable(f"nie da się wyrenderować strony: {e}") from e
    return out


def _draw_grid(image) -> None:
    """Siatka w PUNKTACH PDF, nie w pikselach — bo w punktach liczy się bbox."""
    from PIL import ImageDraw

    draw = ImageDraw.Draw(image)
    for axis in range(2):
        limit = image.size[axis] / SCALE
        point = 0
        while point <= limit:
            at = point * SCALE
            line = ((at, 0, at, image.size[1]) if axis == 0
                    else (0, at, image.size[0], at))
            labelled = point % GRID_LABEL_EVERY == 0
            draw.line(line, fill=(210, 60, 60) if labelled else (150, 190, 220), width=1)
            if labelled and point:
                spot = (at + 2, 2) if axis == 0 else (2, at + 2)
                draw.text(spot, str(point), fill=(210, 60, 60))
            point += GRID_STEP
