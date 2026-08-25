"""Regresja warstwy pozycyjnej — pułapki z `research/README.md`.

Te testy pilnują wyniku, który został **zmierzony** 24.08.2026 na 75 kluczach
matematyki E8 (punkt odniesienia: `tests/fixtures/bakeoff-2026-08-24.txt`).
Nie sprawdzają, że kod „działa" — sprawdzają, że daje TEN SAM wynik co przed
przeprowadzką z `research/` do `ingest/`.

Podział jest celowy:

* testy na **zrzucie strony** (`tests/fixtures/strony-omap-100-2505.json`) nie
  potrzebują ani jednego PDF-a i chodzą zawsze, także w CI. Zrzut to znaki,
  kreski i tabele trzech stron — z nich `reconstruct` odtwarza dokładnie ten
  sam tekst co z pliku źródłowego;
* testy jednostkowe (`normalize`, scalanie serii, znane luki) też chodzą zawsze;
* testy na prawdziwym kluczu są oznaczone `mirror` i pomijają się, gdy mirrora
  nie ma. Arkusze CKE NIE wchodzą do repozytorium, dopóki nie ma odpowiedzi
  na zapytanie o komercyjne użycie (pozycja G0.1).

`pytest.importorskip("pdfplumber")` stało wcześniej w ciele modułu i pomijało
CAŁY plik, także testy, które o pdfplumberze nic nie wiedzą. Blokada siedzi
teraz w fixture'rze tych dwóch testów, które faktycznie otwierają PDF-a.
"""

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


def test_potega_nie_gubi_wykladnika(strony):
    """`P = 5² = 25 (cm²)` bez obsługi indeksu górnego czyta się `P = 52 = 25 (cm)`.

    To błąd CICHY: `52` dalej wygląda na poprawną liczbę, więc nie wywala
    parsera, tylko zatruwa korpus. Strona 22 klucza niesie osiem takich
    jednostek kwadratowych.
    """
    tekst = reconstruct.page_text(strony[22], pomin_przypisy=True)
    assert "(cm^2)" in tekst, "wykładnik przy jednostce zniknął"
    assert "(cm2)" not in tekst.replace(" ", ""), "wykładnik wtopił się w liczbę"


# ── pułapka 1: ułamek piętrowy, na zrzucie i na prawdziwym kluczu ───────────

def test_ulamek_pietrowy_ze_zrzutu(strony):
    """`7/15` — płaska ekstrakcja rozbija to na osobne linie, bo licznik
    i mianownik leżą na różnych wysokościach.

    Wynik oczekiwany wpisany na sztywno, bo to jest CEL pomiaru z 24.08.2026,
    a nie wartość, którą wolno przeliczyć.
    """
    tekst = reconstruct.page_text(strony[22], pomin_przypisy=True).replace(" ", "")
    assert "7/15" in tekst
    assert "P_(AECF)=7/15" in tekst, "licznik oderwał się od swojego wyrażenia"


def test_licznik_i_mianownik_nie_zostaja_samotne(strony):
    """Kontrola odwrotna: gdyby rekonstrukcja przestała działać, w tekście
    stanąłby goły `7` nad gołym `15`.

    Wcześniejsza wersja tego testu miała asercję `'15' not in linie or '7/15'
    in tekst` — słabszą niż test powyżej, więc nie mogła zapalić się sama.
    Test, który zawsze był zielony, jest nieodróżnialny od testu, który nic
    nie sprawdza.
    """
    linie = [w.strip() for w in
             reconstruct.page_text(strony[22], pomin_przypisy=True).splitlines()]
    assert "15" not in linie, "mianownik stoi samotnie w linii"
    assert "7" not in linie, "licznik stoi samotnie w linii"


# ── pułapka 4: przypis ze stopki nie ma prawa wejść do kryterium ────────────

def test_przypis_nie_wchodzi_do_tresci(strony):
    """Przypis nie powtarza się jak żywa pagina, więc nie ma go czym dopasować —
    po sklejeniu stron wchodzi w środek kryterium.

    Rozstrzyga rozmiar fontu (9,0 pkt przy bazie 11,0) i pozycja na dole strony.
    """
    z_przypisem = reconstruct.page_text(strony[1], pomin_przypisy=False)
    bez_przypisu = reconstruct.page_text(strony[1], pomin_przypisy=True)
    assert "Rozporządzenie" in z_przypisem, "zrzut nie zawiera przypisu — zły fixture"
    assert "Rozporządzenie" not in bez_przypisu, "przypis wszedł w treść strony"
    assert "Zadanie 1." in bez_przypisu, "odcięcie przypisu zjadło treść strony"


# ── ślepe uliczki: linie tabel nie są kreskami ułamkowymi ──────────────────

def test_filtr_tabel_odsiewa_krawedzie_komorek(strony):
    """Odstęp nad i pod linią NIE odróżnia kreski ułamkowej od krawędzi komórki.

    Rozstrzyga struktura: linia wewnątrz wykrytej tabeli należy do tabeli.
    Strona 14 jest tu pomiarem — 38 linii kandydujących, z czego 36 to krawędzie
    czterech tabel. Bez tego filtru wychodziły ułamki `' '/'Liczba'` i `Uwagi/1`.
    """
    strona = strony[14]
    assert len(strona._read_bars()) == 38, "zmienił się detektor linii"
    assert len(strona.bars) == 2, "filtr tabel przestał odsiewać krawędzie"
    tekst = reconstruct.page_text(strona, pomin_przypisy=True)
    assert "/Liczba" not in tekst
    assert "Uwagi/" not in tekst


def test_zasieg_ulamkow_na_zrzucie(strony):
    """Zamrożony zasięg: ile linii kandyduje i ile zostaje ułamkami.

    Pomiar całego korpusu z 24.08.2026 to 3330/4472 kresek (74,5%); tutaj ta
    sama proporcja na trzech stronach. Rozjazd znaczy, że zmienił się detektor
    albo filtr — jedno i drugie trzeba zobaczyć od razu, a nie po przebiegu
    na 43 tysiącach stron.
    """
    kandydujace = sum(len(s._read_bars()) for s in strony.values())
    przyjete = sum(len(s.bars) for s in strony.values())
    assert (kandydujace, przyjete) == (70, 34)


# ── obie warstwy muszą rozstrzygać kreskę tak samo ─────────────────────────

def test_obie_warstwy_widza_ten_sam_ulamek():
    """`page_text` i `render` pytają `_pietra` o tę samą kreskę.

    `page_text` podawał rozmiar bazowy na sztywno (11,0), `render` nie podawał
    go wcale — a wtedy funkcja brała rozmiar PIERWSZEGO znaku wiersza. Wiersz
    zaczynający się od odnośnika do przypisu (7 pt) kurczył okno z 15,95 pt do
    10,15 pt i ta sama kreska przestawała być ułamkiem tylko dla jednej z warstw:
    `7/15` wychodziło jako `175`, czyli liczba wyglądająca poprawnie.
    """
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


# ── znane luki: mają być czerwone dopiero, gdy ktoś je naprawi (G2.3.2) ─────

@pytest.mark.xfail(strict=True, reason="liczby mieszane — decyzja w G2.3.2")
def test_liczba_mieszana_nie_skleja_sie_z_ulamkiem():
    """`1⅔ km` wychodzi dziś jako `12/3 km` — całość wtapia się w licznik.

    Zapis jest nie do odróżnienia od „dwanaście trzecich", więc korpus niesie
    liczbę, której nie ma w dokumencie. Test ma zapalić się na ZIELONO w dniu,
    w którym luka zostanie zamknięta — dlatego `strict=True`.
    """
    chars = [Char("1", 100, 106, 96, 108, 11.0),
             Char("2", 110, 116, 88, 98, 11.0),
             Char("3", 110, 116, 104, 114, 11.0),
             Char(" ", 118, 121, 96, 108, 11.0),
             Char("k", 122, 128, 96, 108, 11.0),
             Char("m", 128, 136, 96, 108, 11.0)]
    assert reconstruct.render(chars, [Bar(109, 117, 101)]) == "1 2/3 km"


@pytest.mark.xfail(strict=True, reason="pierwiastki — decyzja w G2.3.2")
def test_pierwiastek_ma_zasieg():
    """Znak pierwiastka jest glifem, ale „daszek" nad liczbą bywa linią.

    Dziś linia jest ignorowana, więc `√16` i `√1 · 6` dają ten sam zapis —
    zasięg pierwiastka ginie i konwerter na MathJSON (G2.6) nie ma go skąd wziąć.
    """
    chars = [Char("√", 100, 108, 92, 110, 11.0),
             Char("1", 110, 116, 96, 108, 11.0),
             Char("6", 116, 122, 96, 108, 11.0)]
    assert reconstruct.render(chars, [Bar(109, 123, 93)]) == "√(16)"


# ── ten sam pomiar na prawdziwym pliku, gdy mirror jest pod ręką ────────────

KLUCZ_2505 = "data/raw/e8/2025/matematyka/OMAP-100-2505-zasady.pdf"


@pytest.fixture(scope="module")
def tekst_klucza():
    """Cały klucz przepuszczony przez warstwę pozycyjną — tak, jak robi parser.

    `open_pdf` zwraca dokument iterowalny, nie obiekt z `.pages`; ten sam
    interfejs ukrywa oba silniki (pdfplumber i PyMuPDF), żeby przełączenie
    było jednym argumentem.
    """
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
    """Zrzut ma dawać TEN SAM tekst co PDF — inaczej testy offline pilnują fikcji.

    To jedyny test, który wiąże obie ścieżki. Gdy się zapali, fixture trzeba
    zbudować na nowo (`zrzut_strony` z `pdf.layout`), a nie poprawiać asercje.
    """
    for numer, strona in strony.items():
        tekst = reconstruct.page_text(strona, pomin_przypisy=True)
        assert tekst.strip(), f"pusty zrzut strony {numer}"
        assert tekst.strip() in tekst_klucza, f"zrzut strony {numer} rozjechał się z plikiem"
