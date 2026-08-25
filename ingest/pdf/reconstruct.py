# -*- coding: utf-8 -*-
"""Odtwarzanie matematyki z układu strony: ułamki, potęgi, normalizacja znaków.

Cztery rzeczy, które płaska ekstrakcja niszczy w kluczach CKE, i sposób na każdą:

1. **Ułamek piętrowy.** `7/15 − (1/5 + 1/6)` wychodzi z extract_text() jako sześć
   osobnych linii, bo licznik i mianownik leżą na różnych wysokościach. Kreska
   ułamkowa jest jednak w tych PDF-ach obiektem wektorowym o znanych
   współrzędnych, więc przypisanie pięter jest deterministyczne, nie
   heurystyczne: znaki nad kreską w jej przedziale x to licznik, pod — mianownik.

2. **Potęga.** `P = 5² = 25 (cm²)` bez obsługi indeksu górnego czyta się jako
   `P = 52 = 25 (cm)`. To błąd cichy — wynik dalej wygląda na poprawną liczbę,
   więc nie wywala parsera, tylko zatruwa korpus. Potęga jest osobnym glifem
   o mniejszym rozmiarze (7,0 przy bazie 11,0) i podniesionej linii bazowej.

3. **Kursywa matematyczna.** `𝑥` to U+1D465, nie `x`. Bez normalizacji NFKC
   porównanie stringów i wyszukiwanie po nazwie zmiennej mija się z celem;
   w samych arkuszach matematyki wariantu bazowego jest ich 1045.

4. **Przypis ze stopki strony.** Nie powtarza się jak żywa pagina, więc nie ma
   go czym dopasować, a po sklejeniu stron wchodzi w środek kryterium:
   „…zapisanie 4·9 ⏎ 3 Dla arkusza OMAP-C00-2405 – pudełko puzzli." to jeden
   warunek w korpusie. Rozstrzyga rozmiar fontu — 9,0 pkt przy bazie 11,0
   i pozycja na samym dole strony. Włącza to `page_text(pomin_przypisy=True)`.

Test rozstrzygający (pomiar: `tests/fixtures/bakeoff-2026-08-24.txt`, regresja:
`tests/test_pdf_layer.py`): zadanie 16 z OMAP-100-2505-zasady.pdf
składa się w `7/15-(1/5+1/6)=14/30-11/30=3/30=1/10`.
"""
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
    """Czy piętro naprawdę należy do tej kreski.

    Sprawdzamy tylko ZNACZĄCE znaki. Spacja w tych PDF-ach ma bbox szerszy od
    samego odstępu i zachodzi na kreskę — liczona razem z resztą kasowała
    poprawne ułamki (3/30, 1/10).

    Warunku „piętro wypełnia kreskę" tu nie ma celowo: licznik `1` jest dużo
    węższy od kreski dobranej do mianownika `10`, więc każdy próg na szerokość
    obcina prawdziwe ułamki. Krawędzie tabel odsiewa `Page.bars`, nie ten test.
    """
    real = [c for c in chars if c.c.strip()]
    if not real:
        return False
    if not all(c.x0 >= bar.x0 - X_PAD - 1 and c.x1 <= bar.x1 + X_PAD + 1 for c in real):
        return False
    # Piętro ułamka jest liczbą albo krótkim wyrażeniem — nigdy słowem.
    # Podkreślenie pod nagłówkiem („Uwagi" nad „1.") przechodzi wszystkie
    # testy geometryczne i daje ułamek `Uwagi/1`, którego nikt nie zauważy
    # przed wejściem do korpusu. Filtr tabel go nie łapie, bo tabeli tam nie ma.
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
    """Rozmiar pisma wiersza — MEDIANA, nie rozmiar pierwszego znaku.

    Pierwszym znakiem wiersza bywa odnośnik do przypisu albo indeks górny
    (7 pt przy tekście 11 pt). Okno szukania pięter kurczyło się wtedy
    z 15,95 pt do 10,15 pt i ta sama kreska przestawała być ułamkiem —
    ale tylko w tej warstwie, która rozmiaru nie podała jawnie. Mediana nie
    daje się zbić pojedynczym glifem, więc wszystkie warstwy dostają tę samą
    liczbę bez pamiętania o argumencie.
    """
    if not chars:
        return 11.0
    rozmiary = sorted(c.size for c in chars)
    return rozmiary[len(rozmiary) // 2]


def _pietra(chars: Sequence[Char], bar: Bar, size: float | None = None):
    """Piętra kreski — (licznik, mianownik) albo None, gdy to nie ułamek.

    Jedno miejsce na test „czy ta kreska jest kreską ułamkową", bo pytają
    o to trzy warstwy: składanie wyrażenia, grupowanie wierszy i pomiar
    zasięgu (`tests/fixtures/bakeoff-2026-08-24.txt`). Rozjechanie się ich
    odpowiedzi kosztowało wcześniej sklejone wiersze (patrz `page_text`).
    """
    win = Y_WINDOW * (size if size else _rozmiar_bazowy(chars))
    num = [c for c in chars if _in_bar(c, bar) and bar.y - win < c.cy < bar.y]
    den = [c for c in chars if _in_bar(c, bar) and bar.y < c.cy < bar.y + win]
    if not _fits(num, bar) or not _fits(den, bar):
        return None
    return num, den


_RUN_SCRIPT = re.compile(r"([\^_])(.)((?:\1.)+)")


def _scal_indeksy(s: str) -> str:
    """`k^-^1^0` → `k^(-10)`, `P_A_E_C_F` → `P_(AECF)`.

    `_mark_scripts` znakuje każdy glif osobno, bo mierzy każdy osobno.
    Wykładnik `-10` to jednak jedna wartość, a nie trzy jednoznakowe potęgi;
    bez scalenia konwerter na MathJSON dostałby `k^- * 1 * 0`. Znacznik przy
    jednym znaku zostaje bez nawiasów, żeby `15^2` czytało się jak dotąd.
    """
    def _one(m):
        znak, pierwszy, reszta = m.group(1), m.group(2), m.group(3)
        return "%s(%s%s)" % (znak, pierwszy, reszta[1::2])
    return _RUN_SCRIPT.sub(_one, s)


def render(chars: Sequence[Char], bars: Sequence[Bar]) -> str:
    """Znaki + kreski → tekst z ułamkami w postaci `licznik/mianownik`.

    Rekurencja obsługuje ułamki piętrowe: kreska leżąca w całości nad inną
    należy do jej licznika i składa się pierwsza.
    """
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
                                             build(den, inner).strip() or "?")))
            for c in num + den:
                consumed.add(id(c))
        rest = [c for c in pool if id(c) not in consumed]
        local.extend(_mark_scripts(rest))
        return _scal_indeksy("".join(t for _, t in sorted(local, key=lambda p: p[0])))

    # kreski przetwarzamy w kontekście całego zbioru znaków
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
                                         build(den, inner).strip() or "?")))
        for c in num + den:
            taken.add(id(c))
    parts.extend(_mark_scripts([c for c in chars if id(c) not in taken]))
    return _scal_indeksy("".join(t for _, t in sorted(parts, key=lambda p: p[0])))


def band_text(page, y_top: float, y_bottom: float) -> str:
    """Tekst poziomego pasa strony — do testów na konkretnym wyrażeniu."""
    chars = [c for c in page.chars if y_top <= c.cy <= y_bottom]
    bars = [b for b in page.bars if y_top <= b.y <= y_bottom]
    return render(chars, bars)


PRZYPIS_MARGINES = 1.5   # o ile punktów przypis jest mniejszy od tekstu bazowego


def przypisy(chars: Sequence[Char]) -> set:
    """Znaki bloku przypisów u dołu strony.

    Przypis nie jest żywą paginą — nie powtarza się i nie da się go dopasować
    wzorcem. Wchodzi za to w środek kryterium po sklejeniu stron: „…zapisanie
    4·9 ⏎ 3 Dla arkusza OMAP-C00-2405 – pudełko puzzli." to jeden warunek
    w korpusie. Zmierzone: 70 z 4379 warunków na 75 kluczach.

    Rozstrzyga rozmiar fontu, nie treść. Cięcie po samym wzorcu „samotna cyfra
    w linii, po niej zdanie z wielkiej litery" ma na tym korpusie 186 trafień,
    z czego kilkadziesiąt to piętro ułamka nad zdaniem rozwiązania („2 ⏎
    Obliczamy pole trójkąta…") — czyli lek gorszy od choroby. Przypis ma
    w tych plikach 9,0 pkt przy bazie 11,0 i stoi na samym dole strony, więc
    idziemy wierszami od dołu, dopóki cały wiersz jest mniejszy od bazy.
    Margines 1,5 pkt zostawia poza cięciem tekst tabel (10,0 pkt).
    """
    vis = [c for c in chars if c.c.strip()]
    if not vis:
        return set()
    sizes = [round(c.size, 1) for c in vis]
    baza = max(set(sizes), key=sizes.count)
    wiersze: dict = {}
    for c in vis:
        wiersze.setdefault(round(c.cy / LINE_TOL), []).append(c)

    # Blok kończący stronę = wiersze mniejsze od tekstu bazowego. Sam rozmiar
    # mniejszy o pół punktu to za mało, żeby coś wyciąć — tak wygląda żywa
    # pagina (10,0) i tekst tabeli wymagań w roczniku 2019. Cięcie następuje
    # dopiero wtedy, gdy w bloku stoi wiersz o rozmiarze przypisu (≤ baza−1,5),
    # bo pagina bez przypisu i tak wypada później na wzorcu.
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
    """Cała strona jako tekst, wiersz po wierszu, z odtworzoną matematyką.

    Ułamek rozciąga się na dwie wysokości tekstu, więc jego piętra kotwiczymy
    na y kreski — inaczej licznik i mianownik trafiłyby do sąsiednich wierszy
    i rozpadły się z powrotem na `7` i `15`.

    Kotwiczą TYLKO kreski, które `render()` przyjmie jako ułamkowe. Kotwiczenie
    przy każdej kresce sklejało nagłówek z akapitem pod nim: podkreślenie pod
    „Uwagi" ściągało do jednego wiersza „Uwagi" i „1. Jeżeli…", co w kluczu
    z 2024 dawało `1U. waJgei ⏎ żeli uczeń…` w środku kryterium. Sam ułamek
    `Uwagi/1` odsiewał już `_fits`, ale kotwica działała przed tym testem.
    """
    chars, bars = page.chars, page.bars
    if pomin_przypisy:
        do_ciecia = przypisy(chars)
        chars = [c for c in chars if id(c) not in do_ciecia]
    if not chars:
        return ""
    anchor: dict[int, float] = {}
    for bar in bars:
        # Bez `size=`: rozmiar liczy `_rozmiar_bazowy` — ta sama liczba, którą
        # dostaje `render`. Wpisane tu wcześniej 11.0 znaczyło, że obie warstwy
        # potrafiły rozstrzygnąć tę samą kreskę inaczej.
        pietra = _pietra(chars, bar)
        if pietra is None:
            continue
        for c in pietra[0] + pietra[1]:
            anchor[id(c)] = bar.y

    # Potęgi i indeksy dolne leżą nad/pod linią bazową, więc bez kotwiczenia
    # trafiają do sąsiedniego wiersza: `P_AECF = 15² − …` rozpada się na trzy
    # linie — `2`, `P=15-…` i `AECF`. Przypinamy je do najbliższego wiersza
    # tekstu bazowego, tak samo jak piętra ułamka do kreski.
    vis = [c for c in chars if c.c.strip()]
    if vis:
        sizes = [round(c.size, 1) for c in vis]
        base_size = max(set(sizes), key=sizes.count)
        base_rows = sorted({round(c.cy / LINE_TOL) * LINE_TOL
                            for c in vis if round(c.size, 1) >= base_size - 0.1})
        if base_rows:
            for c in chars:
                if id(c) in anchor or not c.c.strip():
                    continue
                if c.size >= base_size * SCRIPT_RATIO:
                    continue
                near = min(base_rows, key=lambda y: abs(y - c.cy))
                if abs(near - c.cy) <= base_size:
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
    """Tnie wiersz na segmenty w miejscach rynny między kolumnami.

    Grupowanie samym `y` skleja tekst stojący obok siebie: nagłówek „Uwagi"
    z sąsiadującym „1. Jeżeli…" wychodzi jako `1U. wJaegżi eli`, a dwukolumnowa
    tabela wymagań — jako `IV. Rozumowanie i argumentacja. KLASY IV-VI`.
    Rynna jest znacznie szersza od największego odstępu wewnątrz wyrażenia,
    więc rozdziela je bez ryzyka rozcięcia wzoru.
    """
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
