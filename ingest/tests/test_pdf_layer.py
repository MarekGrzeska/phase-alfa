"""Regresja warstwy pozycyjnej — pułapki z `research/README.md`."""

from __future__ import annotations

import json
import os

import pytest

from pdf import reconstruct
from pdf.layout import Bar, Char, StronaZeZrzutu
from sciezki import korzen_mirrora

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
ZRZUT = os.path.join(FIXTURES, "strony-omap-100-2505.json")


@pytest.fixture(scope="module")
def strony() -> dict:
    """Zrzucone strony klucza OMAP-100-2505, po numerze w dokumencie."""
    with open(ZRZUT, encoding="utf-8") as fh:
        dane = json.load(fh)
    return {s["numer"]: StronaZeZrzutu(s) for s in dane["strony"]}


def test_normalize_sprowadza_kursywe_matematyczna():
    """`𝑥` to U+1D465, nie `x`."""
    assert reconstruct.normalize("\U0001D465") == "x"
    assert reconstruct.normalize("\U0001D44E") == "a"
    assert reconstruct.normalize("x") == "x"


def test_normalize_nie_rusza_polskich_znakow():
    """NFKC nie ma prawa rozłożyć „ą" na „a" z ogonkiem — treść jest po polsku."""
    for znak in "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ":
        assert reconstruct.normalize(znak) == znak


@pytest.mark.parametrize(("wejscie", "oczekiwane"), [
    ("k^-^1^0", "k^(-10)"),      # wykładnik -10 to JEDNA wartość, nie trzy potęgi
    ("P_A_E_C_F", "P_(AECF)"),   # indeks dolny mierzy się glif po glifie
    ("5^2", "5^2"),              # jednoznakowy wykładnik zostaje bez nawiasów
    ("a_1", "a_1"),
])
def test_scalanie_serii_wykladnikow(wejscie, oczekiwane):
    """Bez scalenia konwerter na MathJSON dostałby `k^- ⋅ 1 ⋅ 0`."""
    assert reconstruct._scal_indeksy(wejscie) == oczekiwane


def test_potega_nie_gubi_wykladnika(strony):
    """`P = 5² = 25 (cm²)` bez obsługi indeksu górnego czyta się `P = 52 = 25 (cm)`."""
    tekst = reconstruct.page_text(strony[22], pomin_przypisy=True)
    assert "(cm^2)" in tekst, "wykładnik przy jednostce zniknął"
    assert "(cm2)" not in tekst.replace(" ", ""), "wykładnik wtopił się w liczbę"


def test_ulamek_pietrowy_ze_zrzutu(strony):
    """`7/15` — płaska ekstrakcja rozbija to na osobne linie, bo licznik"""
    tekst = reconstruct.page_text(strony[22], pomin_przypisy=True).replace(" ", "")
    assert "7/15" in tekst
    assert "P_(AECF)=7/15" in tekst, "licznik oderwał się od swojego wyrażenia"


def test_licznik_i_mianownik_nie_zostaja_samotne(strony):
    """Kontrola odwrotna: gdyby rekonstrukcja przestała działać, w tekście"""
    linie = [w.strip() for w in
             reconstruct.page_text(strony[22], pomin_przypisy=True).splitlines()]
    assert "15" not in linie, "mianownik stoi samotnie w linii"
    assert "7" not in linie, "licznik stoi samotnie w linii"


def test_przypis_nie_wchodzi_do_tresci(strony):
    """Przypis nie powtarza się jak żywa pagina, więc nie ma go czym dopasować —"""
    z_przypisem = reconstruct.page_text(strony[1], pomin_przypisy=False)
    bez_przypisu = reconstruct.page_text(strony[1], pomin_przypisy=True)
    assert "Rozporządzenie" in z_przypisem, "zrzut nie zawiera przypisu — zły fixture"
    assert "Rozporządzenie" not in bez_przypisu, "przypis wszedł w treść strony"
    assert "Zadanie 1." in bez_przypisu, "odcięcie przypisu zjadło treść strony"


def test_filtr_tabel_odsiewa_krawedzie_komorek(strony):
    """Odstęp nad i pod linią NIE odróżnia kreski ułamkowej od krawędzi komórki."""
    strona = strony[14]
    assert len(strona._read_bars()) == 38, "zmienił się detektor linii"
    assert len(strona.bars) == 2, "filtr tabel przestał odsiewać krawędzie"
    tekst = reconstruct.page_text(strona, pomin_przypisy=True)
    assert "/Liczba" not in tekst
    assert "Uwagi/" not in tekst


def test_zasieg_ulamkow_na_zrzucie(strony):
    """Zamrożony zasięg: ile linii kandyduje i ile zostaje ułamkami."""
    kandydujace = sum(len(s._read_bars()) for s in strony.values())
    przyjete = sum(len(s.bars) for s in strony.values())
    assert (kandydujace, przyjete) == (70, 34)


def test_obie_warstwy_widza_ten_sam_ulamek():
    """`page_text` i `render` pytają `_pietra` o tę samą kreskę."""
    przypis = Char("1", 60.0, 64.0, 92.0, 96.0, 7.0)      # 7 pt, pierwszy w wierszu
    licznik = Char("7", 102.0, 108.0, 84.0, 92.0, 11.0)
    mianownik = [Char("1", 101.0, 106.0, 104.0, 112.0, 11.0),
                 Char("5", 106.0, 111.0, 104.0, 112.0, 11.0)]
    znaki = [przypis, licznik, *mianownik]
    kreska = Bar(100.0, 112.0, 100.0)

    assert reconstruct._pietra(znaki, kreska, size=11.0) is not None
    assert reconstruct._pietra(znaki, kreska) is not None, (
        "warstwa bez jawnego rozmiaru odrzuciła kreskę, którą druga przyjęła")
    assert "7/15" in reconstruct.render(znaki, [kreska]).replace(" ", "")


def test_liczba_mieszana_nie_skleja_sie_z_ulamkiem():
    """`1⅔ km` sklejone w `12/3 km` to błąd CICHY — poprawny na oko ułamek."""
    chars = [Char("1", 100, 106, 96, 108, 11.0),
             Char("2", 110, 116, 88, 98, 11.0),
             Char("3", 110, 116, 104, 114, 11.0),
             Char(" ", 118, 121, 96, 108, 11.0),
             Char("k", 122, 128, 96, 108, 11.0),
             Char("m", 128, 136, 96, 108, 11.0)]
    assert reconstruct.render(chars, [Bar(109, 117, 101)]) == "1 2/3 km"


@pytest.mark.xfail(strict=True,
                   reason="pierwiastki — ŚWIADOMIE: korekta ręczna (decyzja G2.3.2)")
def test_pierwiastek_ma_zasieg():
    """Zasięg pierwiastka zostaje korekcie ręcznej — błąd jest WIDOCZNY.

    Odwrotnie niż liczby mieszane: brak domknięcia zasięgu rzuca się w oczy
    przy zapisie w ekranie korekty, wystąpień jest mało, a geometria „daszka"
    nad liczbą jest niejednoznaczna. Test zostaje na czerwono jako zapis tej
    decyzji — dzień, w którym zacznie przechodzić, ma być widoczny.
    """
    chars = [Char("√", 100, 108, 92, 110, 11.0),
             Char("1", 110, 116, 96, 108, 11.0),
             Char("6", 116, 122, 96, 108, 11.0)]
    assert reconstruct.render(chars, [Bar(109, 123, 93)]) == "√(16)"


KLUCZ_2505 = "data/raw/e8/2025/matematyka/OMAP-100-2505-zasady.pdf"


@pytest.fixture(scope="module")
def tekst_klucza():
    """Cały klucz przepuszczony przez warstwę pozycyjną — tak, jak robi parser."""
    pytest.importorskip("pdfplumber")
    sciezka = os.path.join(korzen_mirrora(), KLUCZ_2505)
    if not os.path.exists(sciezka):
        pytest.skip(f"brak mirrora: {sciezka} (ustaw MIRROR_ROOT albo `task mirror`)")
    from pdf.layout import open_pdf
    with open_pdf(sciezka) as doc:
        yield "\n".join(reconstruct.page_text(s, pomin_przypisy=True) for s in doc)


@pytest.mark.mirror
def test_ulamek_pietrowy_odtworzony(tekst_klucza):
    """Cel pomiaru z 24.08.2026: całe wyrażenie zadania 16, nie sam ułamek."""
    assert "7/15-(1/5+1/6)" in tekst_klucza.replace(" ", "")


@pytest.mark.mirror
def test_zrzut_zgadza_sie_z_plikiem(tekst_klucza, strony):
    """Zrzut ma dawać TEN SAM tekst co PDF — inaczej testy offline pilnują fikcji."""
    for numer, strona in strony.items():
        tekst = reconstruct.page_text(strona, pomin_przypisy=True)
        assert tekst.strip(), f"pusty zrzut strony {numer}"
        assert tekst.strip() in tekst_klucza, f"zrzut strony {numer} rozjechał się z plikiem"
