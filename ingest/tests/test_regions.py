"""Wykrywanie regionu graficznego (G2.4.1) — na zrzucie zeszytu i na figurach.

Zrzut trzyma prawdziwą stronę arkusza, bo pułapki tego kroku są geometryczne
i nie da się ich wymyślić: kropkowana linia na odpowiedź ucznia to 4479
prostokątów, a tabela „Prawda / Fałsz" pod treścią zadania wygląda dla
detektora dokładnie jak siatka wykresu.
"""

from __future__ import annotations

import json
import os

import pytest

from pdf import regions
from pdf.layout import Shape, StronaZeZrzutu

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
ZRZUT = os.path.join(FIXTURES, "arkusz-omap-100-x-2505.json")


@pytest.fixture(scope="module")
def strony() -> dict:
    with open(ZRZUT, encoding="utf-8") as fh:
        dane = json.load(fh)
    return {s["numer"]: StronaZeZrzutu(s) for s in dane["strony"]}


def test_zrzut_niesie_ksztalty(strony):
    """Wartownik: zrzut bez kształtów przepuściłby każdy test niżej jako pusty."""
    assert all(page.shapes for page in strony.values())


def test_wykres_wchodzi_w_jedna_ramke(strony):
    """Wykres słupkowy to 40 kresek siatki — ma zostać JEDNYM zasobem."""
    ramki = regions.detect(strony[3], 100.0, 340.0)

    assert len(ramki) == 1
    x0, top, x1, bottom = ramki[0]
    assert 380 < x1 - x0 < 430, "ramka wykresu zgubiła oś albo objęła kolumnę tekstu"
    assert 190 < bottom - top < 240


def test_ramka_nie_obejmuje_calej_strony(strony):
    """Zysk z G2.4.1 jest tu i tylko tu: wycinek zamiast całego arkusza."""
    strona = strony[3]
    (x0, top, x1, bottom), = regions.detect(strona, 100.0, 340.0)

    assert (x1 - x0) * (bottom - top) < 0.35 * strona.width * strona.height


def test_tabela_prawda_falsz_nie_jest_rysunkiem(strony):
    """Siatka na pełną szerokość kolumny to tabela odpowiedzi, nie rysunek.

    Bez tego filtra zadanie 11 dostawało DWA zasoby: rysunek i tabelę
    „Wybierz P albo F", która grafiką nie jest.
    """
    ramki = regions.detect(strony[9], 300.0, 620.0)

    assert len(ramki) == 1
    assert ramki[0][2] - ramki[0][0] < 300, "w ramce wylądowała tabela odpowiedzi"


def test_pasek_naglowka_nie_jest_nawet_kandydatem(strony):
    """Pasek pod „Zadanie N." ma szerokość kolumny — jest linijką, nie grafiką.

    Asercja na KANDYDATACH, nie na ramkach: pasek i tak nie przeszedłby progu
    rozmiaru, więc test na wyniku `detect` byłby zielony także bez filtra.
    """
    strona = strony[5]
    szeroki = [s for s in strona.shapes if s.width > 400 and s.height < 20]
    assert szeroki, "zrzut nie zawiera paska nagłówka — zły fixture"

    kandydaci = regions.candidates(strona, 60.0, 120.0)

    assert all(s.width <= 400 for s in kandydaci)


def _shape(x0, top, x1, bottom, kind="rect") -> Shape:
    return Shape(kind, x0, top, x1, bottom)


def test_kropkowana_linia_odpowiedzi_odpada():
    """Prostokąt 13,7 × 0,5 pt to kreska pod odpowiedź, nie rysunek."""
    assert regions._is_dash(_shape(100, 500, 113.7, 500.5))
    assert regions._is_dash(_shape(100, 500, 100.5, 500.5))
    # Kreska siatki wykresu jest równie cienka, ale DŁUGA — musi zostać.
    assert not regions._is_dash(_shape(160, 138, 160, 283))


def test_klastrowanie_laczy_lancuch_kresek():
    """A dotyka B, B dotyka C, A z C już nie — jedno przejście dałoby dwa zasoby."""
    laczone = regions.cluster([(0, 0, 10, 10), (14, 0, 24, 10), (28, 0, 38, 10)], gap=5)

    assert laczone == [(0, 0, 38, 10)]


def test_klastrowanie_nie_laczy_odleglych():
    daleko = regions.cluster([(0, 0, 10, 10), (100, 0, 110, 10)], gap=5)

    assert len(daleko) == 2
