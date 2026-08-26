"""Zapis równoważny z klucza CKE → LaTeX dla Compute Engine (G2.6).

Ta warstwa stoi po stronie Pythona, choć konwerter jest w Node: to TU rodzą
się pomyłki (dwukropek CKE, przecinek dziesiętny, ułamek liniowy z rekonstrukcji),
a tutaj da się je przetestować bez uruchamiania Node'a — czyli także w CI.

Funkcja zwraca parę `(latex, powod_odmowy)`. Odmowa jest wynikiem, nie awarią:
`mathjson_status = 'failed'` jest w schemacie jawnym stanem właśnie po to, żeby
zapis, którego konwerter nie ugryzł, był widoczny w ekranie korekty jako robota
do zrobienia, a nie znikał w tle.
"""

from __future__ import annotations

import re
import unicodedata

# Jednostki wolno zostawić w wyrażeniu — Compute Engine zrobi z nich iloczyn
# symboli i tak wejdą do MathJSON-a. Reszta słów znaczy, że w kolumnie stoi
# ZDANIE, a nie wyrażenie, i konwersja dałaby poprawnie wyglądającą bzdurę.
UNITS = frozenset({
    "km", "cm", "dm", "mm", "m", "min", "h", "s", "kg", "dag", "g", "t",
    "l", "ml", "ha", "zl", "zł", "szt", "pkt",
})

# Ogon po polsku: „lub zapisy równoważne", „oraz …", „gdzie a jest długością…".
# Ucinamy do PIERWSZEGO takiego spójnika — drugie wyrażenie po „oraz" jest
# osobnym zapisem i w kolumnie na jedno wyrażenie nie ma dla niego miejsca.
TAIL = re.compile(
    r"\s*(?:\b(?:lub|albo|oraz|bez|gdzie|jeżeli|jeśli|przy|dla|i)\b|,\s*(?:gdzie|np)\b).*$",
    re.S | re.I)

# Czasownikowy wstęp klucza: „zapisanie: P = …", „obliczenie 240 ∶ 60".
LEAD = re.compile(r"^\s*(?:zapisanie|zapisanie:|obliczenie|wyznaczenie|ustalenie"
                  r"|podanie|przedstawienie)\b\s*:?\s*", re.I)

SUPERSCRIPTS = {"⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4",
                "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9"}

# Operatory z dokumentów CKE. `∶` (U+2236) to dzielenie, nie dwukropek zdania.
OPERATORS = {
    "⋅": r" \cdot ", "∙": r" \cdot ", "·": r" \cdot ", "×": r" \times ",
    "∶": r" \div ", ":": r" \div ", "÷": r" \div ",
    "−": "-", "–": "-", "—": "-", "‒": "-",
    "≈": r" \approx ", "≤": r" \le ", "≥": r" \ge ", "≠": r" \ne ",
    "≡": r" \equiv ", "≪": " < ", "≫": " > ",
    "π": r" \pi ", "∆": r" \Delta ", "Δ": r" \Delta ", "∘": r"^{\circ}",
}

# Pierwiastek zostaje ręcznej korekcie (decyzja G2.3.2): rekonstrukcja nie
# odtwarza zasięgu daszka, więc `√16+9` jest nieodróżnialne od `√(16+9)`.
ROOT = "√"

WORD = re.compile(r"[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]{3,}")

# Człon ułamka liniowego z rekonstrukcji: liczba, POJEDYNCZA litera albo nawias.
# Litera musi stać samotnie: bez tego `60 min/40 min` czytało się jako
# `mi` + ułamek `n/40`, czyli jednostka rozpadała się na pół.
LETTER = r"(?<![A-Za-z])[A-Za-z](?![A-Za-z])"
FRACTION_PART = rf"(?:\d+(?:[.,]\d+)?|{LETTER}|\([^()]*\)|\[[^\[\]]*\])"
FRACTION = re.compile(rf"({FRACTION_PART})\s*/\s*({FRACTION_PART})")

GROUP = re.compile(r"([\^_])\(([^()]*)\)")
SINGLE = re.compile(r"([\^_])(?![{(])(-?\w)")
DECIMAL = re.compile(r"(?<=\d),(?=\d)")
BRACED = re.compile(r"[\^_]\{[^{}]*\}")
COMMAND = re.compile(r"\\[A-Za-z]+")


def prose_word(latex: str) -> str | None:
    """Pierwsze słowo, które nie jest jednostką ani poleceniem LaTeX-a.

    Bez tego sita „zapisanie P=15" wchodzi do korpusu jako iloczyn dziewięciu
    symboli — MathJSON poprawny składniowo i bezwartościowy, czyli błąd cichy.
    """
    bare = COMMAND.sub(" ", BRACED.sub(" ", latex))
    for match in WORD.finditer(bare):
        if match.group(0).lower() not in UNITS:
            return match.group(0)
    return None


def to_latex(expression: str) -> tuple[str | None, str | None]:
    """Zapis z klucza → (LaTeX, None) albo (None, powód odmowy po polsku)."""
    text = expression or ""
    for glyph, digit in SUPERSCRIPTS.items():
        text = text.replace(glyph, f"^{{{digit}}}")
    text = unicodedata.normalize("NFKC", text)
    text = LEAD.sub("", TAIL.sub("", text)).strip()
    if not text:
        return None, "po odcięciu opisu nie zostało wyrażenie"
    if ROOT in text:
        return None, "pierwiastek — zasięg nieodtworzony, korekta ręczna (G2.3.2)"

    for glyph, latex in OPERATORS.items():
        text = text.replace(glyph, latex)
    text = GROUP.sub(r"\1{\2}", text)
    text = SINGLE.sub(r"\1{\2}", text)
    text = DECIMAL.sub(".", text)
    # Dopóki jest co zamieniać: `1/2/3` ma dwa poziomy i jedno przejście
    # zostawiłoby drugi ukośnik nietknięty.
    while True:
        replaced = FRACTION.sub(r"\\frac{\1}{\2}", text)
        if replaced == text:
            break
        text = replaced
    text = text.replace("%", r"\%")
    # Kropka i średnik na końcu to interpunkcja zdania klucza, nie wyrażenia —
    # Compute Engine widzi w nich składnię i odrzuca poprawny zapis.
    text = " ".join(text.split()).rstrip(".;,")

    word = prose_word(text)
    if word is not None:
        return None, f"tekst, nie wyrażenie — słowo {word!r}"
    if not re.search(r"[0-9A-Za-z]", text):
        return None, "brak jakiejkolwiek wielkości do policzenia"
    return text, None
