"""Jednostki parsera i ładowarki — bez PDF-a i bez bazy."""

from __future__ import annotations

from parsers.omap_e8 import loader, run
from parsers.omap_e8 import parser as K
from parsers.omap_e8.run import _blizniakow


def test_podpunkty_jednej_wersji_nie_ida_do_dwoch_wersji():
    """`1.1` i `1.2` jednego zadania należą do TEJ SAMEJ wersji arkusza."""
    out: dict = {}
    K._rozdziel_kolumny("1.1. TAK\n1.2. NIE", ("X", "Y"), out)
    assert out == {"X": [("1.1", "TAK"), ("1.2", "NIE")]}


def test_blizniaki_rozdzielaja_sie_po_numerze_podpunktu():
    """Dwie wersje, po dwa podpunkty każda — pierwsze wystąpienie numeru do X."""
    out: dict = {}
    K._rozdziel_kolumny("1.1. A\n1.2. B\n1.1. C\n1.2. D", ("X", "Y"), out)
    assert out == {"X": [("1.1", "A"), ("1.2", "B")],
                   "Y": [("1.1", "C"), ("1.2", "D")]}


def test_nieparzysta_liczba_wierszy_nie_przesuwa_odpowiedzi():
    """Wiersz zjedzony przez ekstrakcję nie ma prawa przesunąć reszty o jeden."""
    out: dict = {}
    K._rozdziel_kolumny("1.1. TAK\n1.1. NIE\n1.2. PRAWDA", ("X", "Y"), out)
    assert out["X"] == [("1.1", "TAK"), ("1.2", "PRAWDA")]
    assert out["Y"] == [("1.1", "NIE")]


def test_ladowarka_i_parser_klasyfikuja_regule_tak_samo():
    """Reguła arkusza idzie przez parser, „Uwagi" pod zadaniem przez ładowarkę."""
    zdania = [
        "Uznaje się tylko poprawny końcowy wynik.",
        "Uznaje się tylko poprawny sposób rozwiązania.",
        "Zasady oceniania dla uczniów z dyskalkulią.",
        "Błędy rachunkowe nie wpływają na ocenę metody.",
        "Uczeń mógł korzystać z kalkulatora.",
        "W przypadku sprzecznych rozwiązań nie przyznaje się punktów.",
        "Cokolwiek, co nie pasuje do żadnej reguły.",
    ]
    for z in zdania:
        assert loader._rodzaj_reguly(z) == K.rodzaj_reguly(z), z


def test_sam_wynik_wymaga_slowa_wynik():
    """„tylko poprawny SPOSÓB" to nie to samo co „tylko poprawny WYNIK"."""
    assert K.rodzaj_reguly("Uznaje się tylko poprawny końcowy wynik.") == "sam_wynik"
    assert K.rodzaj_reguly("Uznaje się tylko poprawny sposób.") == "inna"


def test_blizniaki_licza_sie_dla_klucza_wielowariantowego():
    """Kolumna `warianty` bywa listą, a słownik jest kluczowany pojedynczym wariantem."""
    blizniaki = {"100": 138, "200": 7, "400": 3}
    assert _blizniakow(blizniaki, "100,200,400,500,660,K00") == 148
    assert _blizniakow(blizniaki, "100") == 138
    assert _blizniakow(blizniaki, "") == 0
    assert _blizniakow(blizniaki, None) == 0


def test_parsuj_wymagania_zwraca_listy_takze_dla_pustej_tabeli():
    """Adnotacja obiecuje listy, a ładowarka iteruje po wyniku bez sprawdzania."""
    from pdf.layout import Table

    dial = K.SLOWNIK["e8-2019"]
    assert K.parsuj_wymagania(None, dial) == ([], [])
    assert K.parsuj_wymagania(Table((0, 0, 10, 10), []), dial) == ([], [])


def _wiersz(**pola):
    """Wiersz spisu w tylu kolumnach, ile czyta filtr."""
    return {"typ": "zasady_oceniania", "kod": "OMAP", "segment": "e8",
            "rocznik": "2025", "warianty": "100", **pola}


def test_filtr_rocznika_odcina_pozostale_roczniki():
    """Pilot G2.2 jedzie na jednym roczniku — reszta korpusu ma zostać nietknięta."""
    assert run.matches(_wiersz(), "zasady_oceniania", (), (), {"2025"}, ())
    assert not run.matches(_wiersz(rocznik="2024"), "zasady_oceniania",
                          (), (), {"2025"}, ())


def test_filtr_wariantu_znajduje_zeszyt_zadan_mimo_litery_wersji():
    """Zeszyt ma w `warianty` także wersję („100,X") — filtr patrzy na pierwszy człon.

    Bez tego `--with-papers` z filtrem wariantu wczytywał klucz bez ani jednego
    arkusza: spis zeszytów wychodził pusty, a treści zadań nie miał kto dowieźć.
    """
    zeszyt = _wiersz(typ="arkusz", warianty="100,X")
    assert run.matches(zeszyt, "arkusz", (), (), (), {"100"})
    assert not run.matches(_wiersz(typ="arkusz", warianty="700,X"), "arkusz",
                          (), (), (), {"100"})


def test_pusty_filtr_znaczy_wszystko_ale_typ_obowiazuje():
    assert run.matches(_wiersz(rocznik="2019", warianty="800"),
                      "zasady_oceniania", (), (), (), ())
    assert not run.matches(_wiersz(typ="karta_odpowiedzi"),
                          "zasady_oceniania", (), (), (), ())


def test_wariant_bazowy_znosi_brak_kolumny():
    assert run.base_variant("100,X") == "100"
    assert run.base_variant("") == ""
    assert run.base_variant(None) == ""
