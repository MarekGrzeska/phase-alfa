# -*- coding: utf-8 -*-
"""Odtwarzanie matematyki z układu strony: ułamki, potęgi, normalizacja znaków."""
from __future__ import annotations

import re
import unicodedata
from typing import List, Sequence

from pdf.layout import Bar, Char

X_PAD = 1.2          # znak może wystawać poza kreskę o pół szerokości
Y_WINDOW = 1.45      # ile wysokości fontu w górę/dół szukamy pięter ułamka
SCRIPT_RATIO = 0.82  # glif indeksu jest wyraźnie mniejszy od tekstu bazowego
SCRIPT_SHIFT = 0.18  # i przesunięty o ułamek wysokości fontu
LINE_TOL = 3.0       # tolerancja grupowania znaków w wiersz

_DASHES = {"−": "-", "–": "-", "—": "-", "‒": "-"}


def normalize(ch: str) -> str:
    """Kursywa matematyczna → zwykła litera, warianty myślnika → minus."""
    if len(ch) == 1 and 0x1D400 <= ord(ch) <= 0x1D7FF:
        return unicodedata.normalize("NFKC", ch) or ch
    return _DASHES.get(ch, ch)


def _in_bar(c: Char, bar: Bar) -> bool:
    return bar.x0 - X_PAD <= c.cx <= bar.x1 + X_PAD


def _fits(chars: Sequence[Char], bar: Bar) -> bool:
    """Czy piętro naprawdę należy do tej kreski."""
    real = [c for c in chars if c.c.strip()]
    if not real:
        return False
    if not all(c.x0 >= bar.x0 - X_PAD - 1 and c.x1 <= bar.x1 + X_PAD + 1 for c in real):
        return False
    # Piętro ułamka jest liczbą albo krótkim wyrażeniem — nigdy słowem. Podkreślenie
    # pod nagłówkiem przechodzi wszystkie testy geometryczne i daje ułamek `Uwagi/1`.
    tekst = "".join(c.c for c in real)
    return not (len(tekst) >= 3 and tekst.isalpha())


def _mark_scripts(chars: Sequence[Char]) -> List[tuple]:
    """(x, tekst) dla każdego znaku, z ^ przed potęgą i _ przed indeksem dolnym."""
    vis = [c for c in chars if c.c.strip()]
    if len(vis) < 2:
        return [(c.cx, normalize(c.c)) for c in chars]
    sizes = [round(c.size, 1) for c in vis]
    base_size = max(set(sizes), key=sizes.count)
    base_y = sorted(c.cy for c in vis if round(c.size, 1) == base_size)
    if not base_y:
        return [(c.cx, normalize(c.c)) for c in chars]
    mid = base_y[len(base_y) // 2]
    out = []
    for c in chars:
        t = normalize(c.c)
        if c.c.strip() and c.size < base_size * SCRIPT_RATIO:
            d = (c.cy - mid) / base_size
            if d < -SCRIPT_SHIFT:
                t = "^" + t
            elif d > SCRIPT_SHIFT:
                t = "_" + t
        out.append((c.cx, t))
    return out


def _rozmiar_bazowy(chars: Sequence[Char]) -> float:
    """Rozmiar pisma wiersza — MEDIANA, nie rozmiar pierwszego znaku."""
    if not chars:
        return 11.0
    rozmiary = sorted(c.size for c in chars)
    return rozmiary[len(rozmiary) // 2]


def _pietra(chars: Sequence[Char], bar: Bar, size: float | None = None):
    """Piętra kreski — (licznik, mianownik) albo None, gdy to nie ułamek."""
    win = Y_WINDOW * (size if size else _rozmiar_bazowy(chars))
    num = [c for c in chars if _in_bar(c, bar) and bar.y - win < c.cy < bar.y]
    den = [c for c in chars if _in_bar(c, bar) and bar.y < c.cy < bar.y + win]
    if not _fits(num, bar) or not _fits(den, bar):
        return None
    return num, den


_RUN_SCRIPT = re.compile(r"([\^_])(.)((?:\1.)+)")


def _scal_indeksy(s: str) -> str:
    """`k^-^1^0` → `k^(-10)`, `P_A_E_C_F` → `P_(AECF)`."""
    def _one(m):
        znak, pierwszy, reszta = m.group(1), m.group(2), m.group(3)
        return "%s(%s%s)" % (znak, pierwszy, reszta[1::2])
    return _RUN_SCRIPT.sub(_one, s)


def _join_fragments(fragmenty: Sequence[tuple]) -> str:
    """Fragmenty `(x, tekst, czy_ulamek)` od lewej → tekst jednego segmentu.

    Ułamek tuż za cyfrą dostaje odstęp, bo `1⅔` to LICZBA MIESZANA — jeden
    i dwie trzecie. Sklejone `12/3` wygląda jak poprawny ułamek o innej
    wartości i przechodzi korektę niezauważone, więc naprawia się to w kodzie,
    a nie ręcznie (kryterium z G2.3.2: cichy błąd → parser).
    """
    out: List[str] = []
    for _, tekst, ulamek in sorted(fragmenty, key=lambda f: f[0]):
        if ulamek and out and out[-1][-1:].isdigit():
            out.append(" ")
        out.append(tekst)
    return _scal_indeksy("".join(out))


def render(chars: Sequence[Char], bars: Sequence[Bar]) -> str:
    """Znaki + kreski → tekst z ułamkami w postaci `licznik/mianownik`."""
    chars = list(chars)
    taken: set[int] = set()
    parts: List[tuple] = []

    def build(pool: Sequence[Char], scope: Sequence[Bar]) -> str:
        local: List[tuple] = []
        consumed: set[int] = set()
        for bar in sorted(scope, key=lambda b: b.x0):
            pietra = _pietra(pool, bar)
            if pietra is None:
                continue
            num, den = pietra
            inner = [b for b in scope
                     if b is not bar and bar.x0 - X_PAD <= b.x0 and b.x1 <= bar.x1 + X_PAD]
            local.append((bar.x0, "%s/%s" % (build(num, inner).strip() or "?",
                                             build(den, inner).strip() or "?"), True))
            for c in num + den:
                consumed.add(id(c))
        rest = [c for c in pool if id(c) not in consumed]
        local.extend((x, t, False) for x, t in _mark_scripts(rest))
        return _join_fragments(local)

    for bar in sorted(bars, key=lambda b: b.x0):
        pietra = _pietra(chars, bar)
        if pietra is None:
            continue
        num, den = pietra
        if any(id(c) in taken for c in num + den):
            continue
        inner = [b for b in bars
                 if b is not bar and bar.x0 - X_PAD <= b.x0 and b.x1 <= bar.x1 + X_PAD]
        parts.append((bar.x0, "%s/%s" % (build(num, inner).strip() or "?",
                                         build(den, inner).strip() or "?"), True))
        for c in num + den:
            taken.add(id(c))
    parts.extend((x, t, False) for x, t
                 in _mark_scripts([c for c in chars if id(c) not in taken]))
    return _join_fragments(parts)


def band_text(page, y_top: float, y_bottom: float) -> str:
    """Tekst poziomego pasa strony — do testów na konkretnym wyrażeniu."""
    chars = [c for c in page.chars if y_top <= c.cy <= y_bottom]
    bars = [b for b in page.bars if y_top <= b.y <= y_bottom]
    return render(chars, bars)


PRZYPIS_MARGINES = 1.5   # o ile punktów przypis jest mniejszy od tekstu bazowego


def przypisy(chars: Sequence[Char]) -> set:
    """Znaki bloku przypisów u dołu strony."""
    vis = [c for c in chars if c.c.strip()]
    if not vis:
        return set()
    sizes = [round(c.size, 1) for c in vis]
    baza = max(set(sizes), key=sizes.count)
    wiersze: dict = {}
    for c in vis:
        wiersze.setdefault(round(c.cy / LINE_TOL), []).append(c)

    # Blok kończący stronę = wiersze mniejsze od bazowego, ale sam rozmiar mniejszy
    # o pół punktu to za mało: tak wygląda żywa pagina. Tniemy dopiero, gdy w bloku
    # stoi wiersz o rozmiarze przypisu (≤ baza−1,5).
    blok, ma_przypis = [], False
    for key in sorted(wiersze, reverse=True):
        maks = max(c.size for c in wiersze[key])
        if maks > baza - 0.5:
            break
        blok.append(key)
        if maks <= baza - PRZYPIS_MARGINES:
            ma_przypis = True
    if not ma_przypis:
        return set()
    return {id(c) for key in blok for c in wiersze[key]}


def page_text(page, pomin_przypisy: bool = False) -> str:
    """Cała strona jako tekst, wiersz po wierszu, z odtworzoną matematyką."""
    chars, bars = page.chars, page.bars
    if pomin_przypisy:
        do_ciecia = przypisy(chars)
        chars = [c for c in chars if id(c) not in do_ciecia]
    if not chars:
        return ""

    vis = [c for c in chars if c.c.strip()]
    sizes = [round(c.size, 1) for c in vis]
    base_size = max(set(sizes), key=sizes.count) if sizes else 11.0
    base_rows = sorted({round(c.cy / LINE_TOL) * LINE_TOL
                        for c in vis if round(c.size, 1) >= base_size - 0.1})

    def wiersz_bazowy(y: float, tolerancja: float) -> float:
        """Najbliższy wiersz tekstu bazowego — albo `y`, gdy żaden nie jest blisko."""
        if not base_rows:
            return y
        near = min(base_rows, key=lambda row: abs(row - y))
        return near if abs(near - y) <= tolerancja else y

    anchor: dict[int, float] = {}
    for bar in bars:
        # Bez `size=`: rozmiar liczy `_rozmiar_bazowy`, ta sama liczba co w `render` —
        # inaczej obie warstwy rozstrzygają tę samą kreskę inaczej.
        pietra = _pietra(chars, bar)
        if pietra is None:
            continue
        # Ułamek STOJĄCY W ZDANIU ma zostać w wierszu tego zdania. Kotwiczony na
        # własnej kresce trafiał do osobnego wiersza (`round(y / LINE_TOL)` różni
        # się wtedy o jeden), a spłaszczenie wierszy w kryterium przenosiło go
        # na początek tekstu: „ustalenie, że 12 konkurencji stanowi ⅓ wszystkich"
        # czytało się „1/3 ustalenie, że 12 konkurencji stanowi wszystkich".
        # Tolerancja jest tu wąska (LINE_TOL), bo wiersze stoją co ~12 pt:
        # ułamek wyświetlany osobno nie ma do czego przylgnąć i zostaje sam.
        y = wiersz_bazowy(bar.y, LINE_TOL)
        for c in pietra[0] + pietra[1]:
            anchor[id(c)] = y

    # Potęgi i indeksy leżą nad/pod linią bazową i bez kotwiczenia trafiają do
    # sąsiedniego wiersza: `P_AECF = 15² − …` rozpada się na trzy linie.
    for c in chars:
        if id(c) in anchor or not c.c.strip():
            continue
        if c.size >= base_size * SCRIPT_RATIO:
            continue
        near = wiersz_bazowy(c.cy, base_size)
        if near != c.cy:
            anchor[id(c)] = near

    rows: dict[int, List[Char]] = {}
    for c in chars:
        rows.setdefault(round(anchor.get(id(c), c.cy) / LINE_TOL), []).append(c)
    out = []
    for key in sorted(rows):
        y = key * LINE_TOL
        rb = [b for b in bars if abs(b.y - y) <= LINE_TOL]
        for seg in _split_columns(rows[key]):
            out.append(render(seg, [b for b in rb if seg[0].x0 - GUTTER <= b.x0
                                    and b.x1 <= seg[-1].x1 + GUTTER]))
    return "\n".join(out)


GUTTER = 25.0        # rynna między kolumnami; odstęp w wyrażeniu bywa ~20 pt


def _split_columns(row: List[Char]) -> List[List[Char]]:
    """Tnie wiersz na segmenty w miejscach rynny między kolumnami."""
    row = sorted(row, key=lambda c: c.x0)
    segs, cur = [], [row[0]]
    for prev, c in zip(row, row[1:]):
        if c.x0 - prev.x1 > GUTTER:
            segs.append(cur)
            cur = [c]
        else:
            cur.append(c)
    segs.append(cur)
    return [s for s in segs if any(ch.c.strip() for ch in s)] or [row]
