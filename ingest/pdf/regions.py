"""Wykrywanie regionu graficznego w pasie zadania (G2.4.1).

Zasób w bazie miał do tej pory ramkę „cała strona", więc przeglądarka korpusu
pokazywałaby przy zadaniu z rysunkiem cały arkusz. Tu powstaje ramka wokół
samego rysunku; wycina ją potem ta sama funkcja co ramkę wpisaną ręcznie
(`pdf.crop.crop`) — automat i fallback z G2.4.2 różnią się WYŁĄCZNIE tym,
skąd bierze się `bbox`.

Współrzędne wszędzie w punktach PDF, `(x0, top, x1, bottom)` od lewego górnego
rogu strony — tak jak `top`/`bottom` w `pdf.layout`.
"""

from __future__ import annotations

from typing import List, Sequence, Tuple

from pdf.layout import Page, Shape

Bbox = Tuple[float, float, float, float]

# Diagram to zwykle kilkadziesiąt kresek, które mają zostać JEDNYM zasobem.
# 8 pt to mniej niż odstęp między wierszami tekstu (~12 pt), więc sąsiednie
# akapity nie sklejają się w jeden „rysunek".
CLUSTER_GAP = 8.0
CROP_MARGIN = 6.0

# Poniżej tego rysunku nie ma: zostaje ozdobnik, znak wodny albo resztka kreski.
MIN_SIDE = 24.0
MIN_AREA = 2500.0

# Kropkowana linia na odpowiedź ucznia: setki prostokątów 13,7 × 0,5 pt.
# Jedna strona odpowiedzi ma ich 4479 — bez tego filtra klastrowanie liczyłoby
# je kwadratowo, a i tak nie są rysunkiem.
DASH_MAX_THICK = 1.0
DASH_MAX_LONG = 20.0

# Pasek pod nagłówkiem zadania ma DOKŁADNIE szerokość kolumny tekstu. Tym się
# różni od rysunku: rysunek jest wcięty albo wyśrodkowany, linijka strony nie.
RULE_WIDTH_SHARE = 0.95
RULE_MAX_HEIGHT = 20.0

# Ta sama proporcja, ale dla całego klastra: siatka rozpięta na pełną szerokość
# kolumny to TABELA (wiersze „Prawda / Fałsz" pod treścią zadania), nie rysunek.
# Wykres z 2025 r. zajmuje 0,86 kolumny, tabela odpowiedzi 0,99 — próg rozdziela
# je z zapasem. Rysunek naprawdę pełnowymiarowy przepada wtedy na rzecz ręcznej
# ramki i to jest tańsza pomyłka niż tabela w korpusie jako „rysunek".
FULL_COLUMN_SHARE = 0.97

# Powyżej tego progu strona jest ozdobna (okładka, tabela odpowiedzi) i nie ma
# na niej czego wykrywać. Zwracamy pustkę, czyli ręczną ramkę z G2.4.2 —
# świadome oddanie pola człowiekowi jest tańsze niż klastrowanie tysiąca pudełek.
MAX_CANDIDATES = 400


def text_column(page: Page) -> Tuple[float, float]:
    """Lewy i prawy brzeg kolumny tekstu — odniesienie dla „pełnej szerokości"."""
    visible = [c for c in page.chars if c.c.strip()]
    if not visible:
        return 0.0, page.width
    return min(c.x0 for c in visible), max(c.x1 for c in visible)


def _is_dash(shape: Shape) -> bool:
    return ((shape.height <= DASH_MAX_THICK and shape.width <= DASH_MAX_LONG)
            or (shape.width <= DASH_MAX_THICK and shape.height <= DASH_MAX_LONG))


def _is_rule(shape: Shape, column: Tuple[float, float]) -> bool:
    """Linijka strony: pełna szerokość kolumny tekstu przy małej wysokości."""
    span = column[1] - column[0]
    return (span > 0 and shape.width >= RULE_WIDTH_SHARE * span
            and shape.height <= RULE_MAX_HEIGHT)


def _in_band(shape: Shape, top: float, bottom: float) -> bool:
    """Czy kształt należy do pasa zadania — połową wysokości, nie dotknięciem.

    Rysunek zaczynający się tuż nad nagłówkiem następnego zadania należy jeszcze
    do poprzedniego; kształt, który tylko ociera się o granicę, nie.
    """
    overlap = min(shape.bottom, bottom) - max(shape.top, top)
    if shape.height <= 0:
        return top <= shape.top <= bottom
    return overlap >= 0.5 * shape.height


def candidates(page: Page, top: float, bottom: float) -> List[Shape]:
    column = text_column(page)
    return [s for s in page.shapes
            if _in_band(s, top, bottom) and not _is_dash(s) and not _is_rule(s, column)]


def _touching(a: Bbox, b: Bbox, gap: float) -> bool:
    return not (a[2] + gap < b[0] or b[2] + gap < a[0]
                or a[3] + gap < b[1] or b[3] + gap < a[1])


def _union(a: Bbox, b: Bbox) -> Bbox:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def cluster(boxes: Sequence[Bbox], gap: float = CLUSTER_GAP) -> List[Bbox]:
    """Scala ramki leżące bliżej niż `gap` — aż do stanu, w którym nic nie sąsiaduje.

    Pętla do skutku, a nie jedno przejście: kreska A styka się z B, B z C,
    a A z C już nie — po jednym przejściu diagram zostałby dwoma zasobami.
    """
    out = [tuple(b) for b in boxes]
    merged = True
    while merged:
        merged = False
        result: List[Bbox] = []
        for box in out:
            for i, kept in enumerate(result):
                if _touching(kept, box, gap):
                    result[i] = _union(kept, box)
                    merged = True
                    break
            else:
                result.append(box)
        out = result
    return out


def _big_enough(box: Bbox) -> bool:
    width, height = box[2] - box[0], box[3] - box[1]
    return (min(width, height) >= MIN_SIDE and width * height >= MIN_AREA)


def _full_column(box: Bbox, column: Tuple[float, float]) -> bool:
    span = column[1] - column[0]
    return span > 0 and (box[2] - box[0]) >= FULL_COLUMN_SHARE * span


def _padded(box: Bbox, page: Page, margin: float) -> Bbox:
    return (max(0.0, box[0] - margin), max(0.0, box[1] - margin),
            min(page.width, box[2] + margin), min(page.height, box[3] + margin))


def detect(page: Page, top: float, bottom: float) -> List[Bbox]:
    """Ramki rysunków w pasie `top`–`bottom`, od góry strony.

    Pusta lista znaczy „automat nie domyka" — wtedy zasób zostaje z ramką
    całej strony i przejmuje go ręczne dociągnięcie z G2.4.2. To jest
    zawór nr 3 z Planu Implementacji, nie awaria.
    """
    found = candidates(page, top, bottom)
    if not found or len(found) > MAX_CANDIDATES:
        return []
    column = text_column(page)
    boxes = [b for b in cluster([(s.x0, s.top, s.x1, s.bottom) for s in found])
             if _big_enough(b) and not _full_column(b, column)]
    return sorted((_padded(b, page, CROP_MARGIN) for b in boxes),
                  key=lambda b: (b[1], b[0]))
