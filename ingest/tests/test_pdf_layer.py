"""Regresja warstwy pozycyjnej — cztery pułapki z `research/README.md`.

Te testy pilnują wyniku, który został **zmierzony** 24.08.2026 na 75 kluczach
matematyki E8 (punkt odniesienia: `tests/fixtures/bakeoff-2026-08-24.txt`).
Nie sprawdzają, że kod „działa" — sprawdzają, że daje TEN SAM wynik co przed
przeprowadzką z `research/` do `ingest/`.

Podział jest celowy:

* testy jednostkowe (`normalize`, scalanie serii) nie potrzebują ani jednego
  PDF-a i chodzą zawsze, także w CI;
* testy na prawdziwym kluczu są oznaczone `mirror` i pomijają się, gdy mirrora
  nie ma. Arkusze CKE NIE wchodzą do repozytorium, dopóki nie ma odpowiedzi
  na zapytanie o komercyjne użycie (pozycja G0.1).
"""

from __future__ import annotations

import os

import pytest

from pdf import reconstruct

pdfplumber = pytest.importorskip("pdfplumber")


# ── pułapka 3: kursywa matematyczna (bez PDF-a) ─────────────────────────────

def test_normalize_sprowadza_kursywe_matematyczna():
    """`𝑥` to U+1D465, nie `x`.

    W arkuszach matematyki wariantu bazowego jest 1045 takich znaków, 59
    różnych. Bez normalizacji porównanie stringów i wyszukiwanie po nazwie
    zmiennej mija się z celem.
    """
    assert reconstruct.normalize("\U0001D465") == "x"
    assert reconstruct.normalize("\U0001D44E") == "a"
    assert reconstruct.normalize("x") == "x"


def test_normalize_nie_rusza_polskich_znakow():
    """NFKC nie ma prawa rozłożyć „ą" na „a" z ogonkiem — treść jest po polsku."""
    for znak in "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ":
        assert reconstruct.normalize(znak) == znak


# ── pułapka 2: potęga, czyli błąd groźniejszy od ułamka ─────────────────────

@pytest.mark.parametrize(("wejscie", "oczekiwane"), [
    ("k^-^1^0", "k^(-10)"),      # wykładnik -10 to JEDNA wartość, nie trzy potęgi
    ("P_A_E_C_F", "P_(AECF)"),   # indeks dolny mierzy się glif po glifie
    ("5^2", "5^2"),              # jednoznakowy wykładnik zostaje bez nawiasów
    ("a_1", "a_1"),
])
def test_scalanie_serii_wykladnikow(wejscie, oczekiwane):
    """Bez scalenia konwerter na MathJSON dostałby `k^- ⋅ 1 ⋅ 0`.

    Scalone serie dostają nawias, bo `k^-10` czyta się dwuznacznie —
    a nawias jest dokładnie tym, czego potrzebuje konwerter (G2.6).
    Wykładnik jednoznakowy nawiasu nie dostaje, żeby nie zaśmiecać zapisu.
    """
    assert reconstruct._scal_indeksy(wejscie) == oczekiwane


# ── pułapki 1 i 4: ułamek piętrowy i przypis, na prawdziwym kluczu ──────────

KLUCZ_2505 = "data/raw/e8/2025/matematyka/OMAP-100-2505-zasady.pdf"


def _mirror_root() -> str:
    korzen = os.environ.get("MIRROR_ROOT", ".")
    if not os.path.isabs(korzen):
        repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        korzen = os.path.normpath(os.path.join(repo, korzen))
    return korzen


@pytest.fixture(scope="module")
def tekst_klucza():
    """Cały klucz przepuszczony przez warstwę pozycyjną — tak, jak robi parser.

    `open_pdf` zwraca dokument iterowalny, nie obiekt z `.pages`; ten sam
    interfejs ukrywa oba silniki (pdfplumber i PyMuPDF), żeby przełączenie
    było jednym argumentem.
    """
    sciezka = os.path.join(_mirror_root(), KLUCZ_2505)
    if not os.path.exists(sciezka):
        pytest.skip(f"brak mirrora: {sciezka} (ustaw MIRROR_ROOT albo `task mirror`)")
    from pdf.layout import open_pdf
    with open_pdf(sciezka) as doc:
        yield "\n".join(reconstruct.page_text(s, pomin_przypisy=True) for s in doc)


@pytest.mark.mirror
def test_ulamek_pietrowy_odtworzony(tekst_klucza):
    """`7/15 − (1/5 + 1/6)` — płaska ekstrakcja rozbija to na osobne linie,
    bo licznik i mianownik leżą na różnych wysokościach.

    Wynik oczekiwany wpisany na sztywno, bo to jest CEL pomiaru z 24.08.2026,
    a nie wartość, którą wolno przeliczyć.
    """
    assert "7/15-(1/5+1/6)" in tekst_klucza.replace(" ", "")


@pytest.mark.mirror
def test_licznik_nie_zostaje_na_wlasnej_linii(tekst_klucza):
    """Kontrola odwrotna do poprzedniej: gdyby rekonstrukcja przestała
    działać, w tekście stanąłby goły `7` nad gołym `15`."""
    linie = [w.strip() for w in tekst_klucza.splitlines()]
    assert "15" not in linie or "7/15" in tekst_klucza.replace(" ", ""), (
        "mianownik stoi samotnie w linii — kreska ułamkowa nie została odczytana"
    )
