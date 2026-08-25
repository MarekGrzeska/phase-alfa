"""Jednostki parsera i ładowarki — bez PDF-a i bez bazy.

Każdy test w tym pliku pilnuje konkretnego błędu, który raz już wszedł do kodu
(przegląd `docs/review/2026-08-25-feat-g1.2-ingest.html`). Wszystkie były
niewidoczne dla istniejących bramek: dane wchodziły do korpusu, liczby się
zgadzały, a treść była nie ta.
"""

from __future__ import annotations

from parsers.omap_e8 import loader
from parsers.omap_e8 import parser as K
from parsers.omap_e8.run import _blizniakow

# ── odpowiedzi bliźniaków: podział po numerze podpunktu, nie na pół ─────────

def test_podpunkty_jednej_wersji_nie_ida_do_dwoch_wersji():
    """`1.1` i `1.2` jednego zadania należą do TEJ SAMEJ wersji arkusza.

    Podział listy na pół dawał `{'X': [1.1], 'Y': [1.2]}` — wersja X traciła
    odpowiedź, a Y dostawała cudzą. Żaden więz tego nie łapie: numery się nie
    powtarzają, więc `UNIQUE (task_version_id, part)` jest zadowolony.
    """
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
    """Wiersz zjedzony przez ekstrakcję nie ma prawa przesunąć reszty o jeden.

    Przy podziale na pół trzy wiersze szły 1:2 i wszystkie odpowiedzi po
    przesunięciu lądowały w złej wersji.
    """
    out: dict = {}
    K._rozdziel_kolumny("1.1. TAK\n1.1. NIE\n1.2. PRAWDA", ("X", "Y"), out)
    assert out["X"] == [("1.1", "TAK"), ("1.2", "PRAWDA")]
    assert out["Y"] == [("1.1", "NIE")]


# ── klasyfikacja reguł: jedna definicja, nie dwie kopie ─────────────────────

def test_ladowarka_i_parser_klasyfikuja_regule_tak_samo():
    """Reguła arkusza idzie przez parser, „Uwagi" pod zadaniem przez ładowarkę.

    Dopóki były to dwie kopie „tych samych przesłanek", ten sam zapis dostawał
    dwa różne typy zależnie od tego, w którym miejscu klucza stał.
    """
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
    """„tylko poprawny SPOSÓB" to nie to samo co „tylko poprawny WYNIK".

    Krótszy podciąg z kopii w ładowarce łapał oba i mieszał typy w tabeli `rule`.
    """
    assert K.rodzaj_reguly("Uznaje się tylko poprawny końcowy wynik.") == "sam_wynik"
    assert K.rodzaj_reguly("Uznaje się tylko poprawny sposób.") == "inna"


# ── raport: bliźniaki przy kluczu obsługującym wiele wariantów ──────────────

def test_blizniaki_licza_sie_dla_klucza_wielowariantowego():
    """Kolumna `warianty` bywa listą, a słownik jest kluczowany pojedynczym wariantem.

    Odpytywanie go całą listą dawało zero — i to dokładnie przy kluczach
    wielowariantowych, czyli tych, dla których powstał model N:M.
    """
    blizniaki = {"100": 138, "200": 7, "400": 3}
    assert _blizniakow(blizniaki, "100,200,400,500,660,K00") == 148
    assert _blizniakow(blizniaki, "100") == 138
    assert _blizniakow(blizniaki, "") == 0
    assert _blizniakow(blizniaki, None) == 0


# ── pusta tabela wymagań: listy, nie None ──────────────────────────────────

def test_parsuj_wymagania_zwraca_listy_takze_dla_pustej_tabeli():
    """Adnotacja obiecuje listy, a ładowarka iteruje po wyniku bez sprawdzania.

    `None` w pierwszym elemencie cofał cały klucz na `TypeError` — dziś ukryty
    za filtrem tabel, ale filtr nie jest częścią kontraktu tej funkcji.
    """
    from pdf.layout import Table

    dial = K.SLOWNIK["e8-2019"]
    assert K.parsuj_wymagania(None, dial) == ([], [])
    assert K.parsuj_wymagania(Table((0, 0, 10, 10), []), dial) == ([], [])
