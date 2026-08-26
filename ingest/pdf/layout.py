# -*- coding: utf-8 -*-
"""Warstwa pozycyjna PDF-a — jedno API, dwa silniki."""
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
    x0: float
    x1: float
    y: float

    @property
    def length(self) -> float:
        return self.x1 - self.x0


@dataclass
class Shape:
    """Obiekt graficzny strony — obraz, krzywa, prostokąt albo linia.

    Współrzędne jak u znaków: `top`/`bottom` liczone od GÓRNEJ krawędzi strony.
    Silniki podają je inaczej, więc ujednolicenie stoi w czytnikach.
    """
    kind: str
    x0: float
    top: float
    x1: float
    bottom: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.bottom - self.top


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
        self._shapes: List[Shape] | None = None

    def _read_chars(self) -> List[Char]: raise NotImplementedError
    def _read_bars(self) -> List[Bar]: raise NotImplementedError
    def _read_tables(self) -> List[Table]: raise NotImplementedError
    def _read_shapes(self) -> List[Shape]: raise NotImplementedError

    @property
    def chars(self) -> List[Char]:
        if self._chars is None:
            self._chars = self._read_chars()
        return self._chars

    @property
    def shapes(self) -> List[Shape]:
        if self._shapes is None:
            self._shapes = self._read_shapes()
        return self._shapes

    @property
    def tables(self) -> List[Table]:
        if self._tables is None:
            self._tables = self._read_tables()
        return self._tables

    @property
    def bars(self) -> List[Bar]:
        if self._bars is None:
            cand = self._read_bars()
            # find_tables kosztuje ~2× tyle co reszta parsowania — odpalamy tylko wtedy,
            # gdy jest co odsiewać.
            self._bars = cand if not cand else [
                b for b in cand if not any(t.contains(b) for t in self.tables)]
        return self._bars


def _is_bar(x0: float, x1: float, thick: float) -> bool:
    return thick <= BAR_MAX_THICK and BAR_MIN_LEN <= (x1 - x0) <= BAR_MAX_LEN


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

    def _read_shapes(self):
        out = []
        for rodzaj, obiekty in (("image", self._raw.images), ("curve", self._raw.curves),
                                ("rect", self._raw.rects), ("line", self._raw.lines)):
            for o in obiekty:
                out.append(Shape(rodzaj, o["x0"], o["top"], o["x1"], o["bottom"]))
        return out


class _PlumberDoc:
    def __init__(self, path):
        import pdfplumber
        self._pdf = pdfplumber.open(path)
        self._strony: dict[int, Page] = {}

    def __iter__(self) -> Iterator[Page]:
        return (self[i] for i in range(len(self)))

    def __len__(self):
        return len(self._pdf.pages)

    def __getitem__(self, i):
        if i not in self._strony:
            self._strony[i] = _PlumberPage(i, self._pdf.pages[i])
        return self._strony[i]

    def close(self):
        self._strony.clear()
        self._pdf.close()


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

    def _read_shapes(self):
        out = [Shape("curve", d["rect"].x0, d["rect"].y0, d["rect"].x1, d["rect"].y1)
               for d in self._raw.get_drawings()]
        out += [Shape("image", i["bbox"][0], i["bbox"][1], i["bbox"][2], i["bbox"][3])
                for i in self._raw.get_image_info()]
        return out


class _MuDoc:
    def __init__(self, path):
        import pymupdf
        self._doc = pymupdf.open(path)
        self._strony: dict[int, Page] = {}

    def __iter__(self):
        return (self[i] for i in range(len(self)))

    def __len__(self):
        return self._doc.page_count

    def __getitem__(self, i):
        if i not in self._strony:
            self._strony[i] = _MuPage(i, self._doc[i])
        return self._strony[i]

    def close(self):
        self._strony.clear()
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


# ── zrzut strony do JSON-a — testy bez PDF-a ────────────────────────────────
# Arkusze CKE nie wchodzą do repozytorium (G0.1), więc regresja chodziłaby tylko
# na maszynie z mirrorem. Zrzut warstwy pozycyjnej to kilkadziesiąt kilobajtów.

def zrzut_strony(page: Page) -> dict:
    return {
        "numer": page.number,
        "szerokosc": page.width,
        "wysokosc": page.height,
        "znaki": [[c.c, c.x0, c.x1, c.y0, c.y1, c.size] for c in page.chars],
        "kreski": [[b.x0, b.x1, b.y] for b in page.bars],
        "kreski_kandydujace": [[b.x0, b.x1, b.y] for b in page._read_bars()],
        "tabele": [{"bbox": list(t.bbox), "wiersze": t.rows} for t in page.tables],
        "ksztalty": [[s.kind, s.x0, s.top, s.x1, s.bottom] for s in page.shapes],
    }


class StronaZeZrzutu(Page):
    """Strona odtworzona ze zrzutu — ma ten sam interfejs co strona z PDF-a."""

    def __init__(self, dane: dict):
        super().__init__(dane["numer"], dane["szerokosc"], dane["wysokosc"])
        self._dane = dane

    def _read_chars(self) -> List[Char]:
        return [Char(c, x0, x1, y0, y1, size)
                for c, x0, x1, y0, y1, size in self._dane["znaki"]]

    def _read_bars(self) -> List[Bar]:
        return [Bar(x0, x1, y) for x0, x1, y in self._dane["kreski_kandydujace"]]

    def _read_tables(self) -> List[Table]:
        return [Table(tuple(t["bbox"]), t["wiersze"]) for t in self._dane["tabele"]]

    def _read_shapes(self) -> List[Shape]:
        # `.get`, bo zrzuty sprzed G2.4.1 kształtów nie mają. Test regionów
        # asercją na NIEPUSTEJ liście broni się przed cichym przejściem
        # na zrzucie, w którym ich po prostu nie zapisano.
        return [Shape(kind, x0, top, x1, bottom)
                for kind, x0, top, x1, bottom in self._dane.get("ksztalty", [])]
