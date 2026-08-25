# -*- coding: utf-8 -*-
"""Warstwa pozycyjna PDF-a — jedno API, dwa silniki.

`extract_text()` zwraca strumień znaków w kolejności zapisu, a arkusze CKE
kodują znaczenie układem dwuwymiarowym: licznik nad kreską, potęga nad linią
bazową, wersja X w lewej kolumnie tabeli. Ten moduł zwraca to, z czego układ
da się odtworzyć — znaki z ramkami, poziome linie i tabele — i ukrywa różnicę
między silnikami za jednym interfejsem.

Domyślny silnik to **pdfplumber (MIT)**. PyMuPDF jest dwulicencyjny
(AGPL-3.0 albo komercyjna Artifex): AGPL uruchamia obowiązek udostępnienia
źródeł przy korzystaniu przez sieć, więc do produktu SaaS nie wchodzi.
Zostaje jako opcja badawcza — jest ~2× szybszy, a wynik ma identyczny.

    from layout import open_pdf
    with open_pdf("klucz.pdf") as doc:          # pdfplumber
        for page in doc:
            page.chars, page.bars, page.tables

    with open_pdf("klucz.pdf", engine="pymupdf") as doc:
        ...
"""
from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import Iterator, List, Tuple

# Kreska ułamkowa jest cienka i krótka; grubsza albo dłuższa linia to ramka.
BAR_MAX_THICK = 1.6
BAR_MIN_LEN = 3.0
BAR_MAX_LEN = 90.0


@dataclass
class Char:
    """Jeden glif z ramką w układzie strony (y rośnie w dół, jak w PDF-ie)."""
    c: str
    x0: float
    x1: float
    y0: float
    y1: float
    size: float

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass
class Bar:
    """Pozioma linia o rozmiarze kreski ułamkowej."""
    x0: float
    x1: float
    y: float

    @property
    def length(self) -> float:
        return self.x1 - self.x0


@dataclass
class Table:
    """Wykryta tabela: prostokąt i wiersze z rozwiniętymi komórkami scalonymi."""
    bbox: Tuple[float, float, float, float]
    rows: List[List[str]] = field(default_factory=list)

    def contains(self, bar: Bar, pad: float = 2.0) -> bool:
        x0, y0, x1, y1 = self.bbox
        return x0 - pad <= bar.x0 and bar.x1 <= x1 + pad and y0 - pad <= bar.y <= y1 + pad


class Page:
    """Strona z leniwie liczonymi warstwami — tabele są drogie, więc na żądanie."""

    def __init__(self, number: int, width: float, height: float):
        self.number = number
        self.width = width
        self.height = height
        self._chars: List[Char] | None = None
        self._bars: List[Bar] | None = None
        self._tables: List[Table] | None = None

    # podklasy dostarczają _read_*
    def _read_chars(self) -> List[Char]: raise NotImplementedError
    def _read_bars(self) -> List[Bar]: raise NotImplementedError
    def _read_tables(self) -> List[Table]: raise NotImplementedError

    @property
    def chars(self) -> List[Char]:
        if self._chars is None:
            self._chars = self._read_chars()
        return self._chars

    @property
    def tables(self) -> List[Table]:
        if self._tables is None:
            self._tables = self._read_tables()
        return self._tables

    @property
    def bars(self) -> List[Bar]:
        """Kreski ułamkowe — bez linii należących do tabel.

        Odstęp nad i pod linią NIE odróżnia kreski ułamkowej od krawędzi
        komórki: rozkłady obu mierzone na 30 kluczach nakładają się
        (mediana odstępu 0,8 vs -0,5 pt). Długość linii rozdziela tylko
        częściowo. Rozstrzyga struktura — linia wewnątrz wykrytej tabeli
        należy do tabeli. Detektor tabel jest więc też filtrem ułamków.
        """
        if self._bars is None:
            cand = self._read_bars()
            # find_tables/extract_tables kosztuje ~2× tyle co reszta parsowania,
            # więc odpalamy je tylko wtedy, gdy jest co odsiewać.
            self._bars = cand if not cand else [
                b for b in cand if not any(t.contains(b) for t in self.tables)]
        return self._bars


def _is_bar(x0: float, x1: float, thick: float) -> bool:
    return thick <= BAR_MAX_THICK and BAR_MIN_LEN <= (x1 - x0) <= BAR_MAX_LEN


# ── pdfplumber (MIT) — silnik domyślny ────────────────────────────────────
class _PlumberPage(Page):
    def __init__(self, number, raw):
        super().__init__(number, raw.width, raw.height)
        self._raw = raw

    def _read_chars(self):
        return [Char(c["text"], c["x0"], c["x1"], c["top"], c["bottom"], c["size"])
                for c in self._raw.chars]

    def _read_bars(self):
        out = []
        for o in list(self._raw.lines) + list(self._raw.rects):
            # pdfplumber liczy y0/y1 od dołu strony, top/bottom od góry
            thick = abs(o["y1"] - o["y0"])
            if _is_bar(o["x0"], o["x1"], thick):
                out.append(Bar(o["x0"], o["x1"], (o["top"] + o["bottom"]) / 2))
        return out

    def _read_tables(self):
        out = []
        for t in self._raw.find_tables():
            out.append(Table(tuple(t.bbox),
                             [[(c or "") for c in row] for row in t.extract()]))
        return out


class _PlumberDoc:
    def __init__(self, path):
        import pdfplumber
        self._pdf = pdfplumber.open(path)

    def __iter__(self) -> Iterator[Page]:
        for i, p in enumerate(self._pdf.pages):
            yield _PlumberPage(i, p)

    def __len__(self):
        return len(self._pdf.pages)

    def __getitem__(self, i):
        return _PlumberPage(i, self._pdf.pages[i])

    def close(self):
        self._pdf.close()


# ── PyMuPDF (AGPL / komercyjna) — opcjonalny, szybszy ─────────────────────
class _MuPage(Page):
    def __init__(self, number, raw):
        super().__init__(number, raw.rect.width, raw.rect.height)
        self._raw = raw

    def _read_chars(self):
        out = []
        for blk in self._raw.get_text("rawdict")["blocks"]:
            if blk["type"] != 0:
                continue
            for ln in blk["lines"]:
                for sp in ln["spans"]:
                    for ch in sp["chars"]:
                        x0, y0, x1, y1 = ch["bbox"]
                        out.append(Char(ch["c"], x0, x1, y0, y1, sp["size"]))
        return out

    def _read_bars(self):
        out = []
        for d in self._raw.get_drawings():
            for it in d["items"]:
                if it[0] == "l":
                    (ax, ay), (bx, by) = (it[1].x, it[1].y), (it[2].x, it[2].y)
                    x0, x1 = min(ax, bx), max(ax, bx)
                    y, thick = (ay + by) / 2, abs(by - ay)
                elif it[0] == "re":
                    r = it[1]
                    x0, x1, y, thick = r.x0, r.x1, (r.y0 + r.y1) / 2, r.height
                else:
                    continue
                if _is_bar(x0, x1, thick):
                    out.append(Bar(x0, x1, y))
        return out

    def _read_tables(self):
        try:
            found = self._raw.find_tables().tables
        except Exception:
            return []
        return [Table(tuple(t.bbox), [[(c or "") for c in row] for row in t.extract()])
                for t in found]


class _MuDoc:
    def __init__(self, path):
        import pymupdf
        self._doc = pymupdf.open(path)

    def __iter__(self):
        for i in range(self._doc.page_count):
            yield _MuPage(i, self._doc[i])

    def __len__(self):
        return self._doc.page_count

    def __getitem__(self, i):
        return _MuPage(i, self._doc[i])

    def close(self):
        self._doc.close()


ENGINES = {"pdfplumber": _PlumberDoc, "pymupdf": _MuDoc}


@contextlib.contextmanager
def open_pdf(path: str, engine: str = "pdfplumber"):
    """Otwiera PDF wybranym silnikiem. Domyślnie pdfplumber (MIT)."""
    if engine not in ENGINES:
        raise ValueError("nieznany silnik %r; dostępne: %s"
                         % (engine, ", ".join(sorted(ENGINES))))
    doc = ENGINES[engine](path)
    try:
        yield doc
    finally:
        doc.close()
