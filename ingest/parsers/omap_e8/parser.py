#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Parser kluczy CKE — słownik nagłówków zamiast jednego regexu.

`probe_load.py` dowiódł, że schemat udźwignie dane, ale robił to jednym
zestawem wzorców dopasowanym do klucza matematyki E8 z 2025 r. Na pełnym
zakresie ten zestaw się rozsypuje, bo CKE przebudowała dokument cztery razy.
Zmierzone na 75 kluczach matematyki E8 i 19 maturalnych:

    Zadanie 1. (0–1)            93 pliki    nagłówek z pulą punktów
    Zadanie 1. (2 pkt)           1 plik     OMAP-Q00-1904 — pula w innej formie
    2 punkty – pełne rozwiązanie 75 kluczy  próg nagłówkiem (E8)
    Zdający otrzymuje …… 2 pkt    4 klucze  próg z punktacją na końcu linii
    „lub" samotne w linii         8 plików  rocznik 2019
    „LUB" samotne w linii        67 plików  roczniki 2020+
    „ALBO"                       19 kluczy  cała matematyka maturalna
    Rozwiązanie – wersja X | Y   25 plików  bliźniaki E8
    Rozwiązanie / Wersja A | B   15 kluczy  bliźniaki matury od 2023 r.

Stąd `SLOWNIK`: nazwy sekcji i separatory wiszą przy dialekcie, a nie
w ciele parsera. Rozpoznanie dialektu jest pomiarem na tekście dokumentu,
nie zgadywaniem po nazwie pliku — ta sama sesja potrafi mieć dwa układy
(OMAP-800 kontra OMAP-100 z tego samego maja).

    from klucz import czytaj_klucz
    k = czytaj_klucz("data/raw/e8/2025/matematyka/OMAP-100-2505-zasady.pdf")
    k.dialekt, len(k.zadania), k.ostrzezenia

Wynik jest w kształcie `schema.sql`: `formy`, `zadania` z `kryteria` →
`warunki` → `zapisy`, `odpowiedzi` per wersja, `reguly` przekrojowe.
Ładuje go `ingest.py` (75 kluczy) albo `probe_load.py` (jeden, ze sprawdzianem).
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from pdf import reconstruct
from pdf.layout import open_pdf

# =============================================================================
# SŁOWNIK NAGŁÓWKÓW — jedno miejsce na to, czym roczniki i egzaminy się różnią
# =============================================================================

# Nagłówek zadania w dwóch formach naraz: „(0–2)" we wszystkich kluczach poza
# OMAP-Q00-1904, który podaje pulę jako „(2 pkt)". Numer bywa dwuczłonowy —
# matura numeruje podpunkty („Zadanie 33.1."), E8 nie.
RE_ZADANIE = re.compile(
    r"Zadanie\s+(\d+(?:\.\d+)*)\.\s*\(\s*(?:0\s*[–—−-]\s*(\d+)|(\d+)\s*pkt)\s*\)")

# Kod formy: E8 „OMAP-100-2505", matura „MMAP-P0-100" (poziom przed wariantem,
# sesja tylko w E8). Drugi człon zjada opcjonalny poziom, żeby wariant matury
# nie gubił „P0" — bez tego MMAP-P0-100 i MMAP-R0-100 są tą samą formą.
RE_FORMA = re.compile(r"\b([A-Z]{4})-((?:[A-Z]\d-)?[A-Z0-9]{3})(?:-(\d{4}))?\b")

# Bliźniaki deklarowane przy formie: „(wersje arkusza X i Y)" w E8,
# „(wersje arkusza: A i B)" w maturze.
RE_WERSJE = re.compile(r"wersj\w*\s+arkusza:?\s+([A-Z])\s+i\s+([A-Z])", re.I)

RE_TERMIN = re.compile(r"Termin\s*egzaminu:\s*(\d{1,2})\s+(\w+)\s+(\d{4})")
MIESIACE = {"stycznia": 1, "lutego": 2, "marca": 3, "kwietnia": 4, "maja": 5,
            "czerwca": 6, "lipca": 7, "sierpnia": 8, "września": 9,
            "października": 10, "listopada": 11, "grudnia": 12}

# Reżim wymagań stoi w podpisie tabeli wymagań i NIE WOLNO go zgadywać z roku
# publikacji: klucze 2021–2024 sprawdzają okrojony zakres pandemiczny, a te
# z 2025 i 2026 — podstawę z 2024 r. pod dwiema różnymi nazwami sekcji.
# Kolejność ma znaczenie: wzorce szczegółowe przed ogólnymi.
REZIMY = (
    (re.compile(r"Wymagania egzaminacyjne\s+(\d{4})(?:\s+i\s+(\d{4}))?"), None),
    (re.compile(r"Podstawa programowa\s*\^?\(?\d*\)?\s*2012"), "pp2012"),
    (re.compile(r"Podstawa programowa\s*\^?\(?\d*\)?\s*2017"), "pp2017"),
    (re.compile(r"Wymagania określone w podstawie programowej"), "pp-akt"),
    (re.compile(r"Podstawa programowa"), "pp-akt"),
)

# Odsyłacz do przypisu stoi ZA podpisem tabeli („Podstawa programowa 2012¹",
# „Wymagania egzaminacyjne 2021¹"), a w przypisie stoi akt prawny. To on jest
# prawdziwą tożsamością reżimu — podpis bywa dla tego samego aktu różny:
# osiem kluczy z 2023 r. pisze „Wymagania egzaminacyjne 2023 i 2024",
# a dziewiąty „Wymagania egzaminacyjne 2023".
RE_ODSYLACZ = re.compile(r"\s*\^?\(?(\d{1,2})\)?")
# Przypisy stoją jeden za drugim w tym samym bloku, więc treść musi się kończyć
# przed odsyłaczem następnego — inaczej przypis nr 1 zjada nr 2 i wymaganiu
# z podstawy 2017 przypisuje się Dziennik Ustaw z 2012 r.
_MARKER = r"\^?\d{1,2}\s*(?:Rozporządzenie|Załącznik)"
RE_PRZYPIS_TRESC = re.compile(
    r"(?:^|\s)\^?(\d{1,2})\s*((?:Rozporządzenie|Załącznik).{20,600}?)"
    r"(?=\s" + _MARKER + r"|\n|\Z)", re.S)
RE_DZIENNIK = re.compile(r"Dz\.\s*U\.[^)]{0,60}poz\.\s*\d+[^)]{0,20}")

# „pp-akt" znaczy „obowiązująca podstawa" — który to rok, mówi przypis pod
# tabelą, a nie nagłówek. Dz.U. 2024 poz. 996 to podstawa dla szkoły
# podstawowej, poz. 1019 — dla liceum; obie wchodzą w życie w 2024 r.
DZIENNIKI = (
    (re.compile(r"poz\.\s*996"), "pp2024"),
    (re.compile(r"poz\.\s*1019"), "pp2024"),
    (re.compile(r"poz\.\s*356"), "pp2017"),
    (re.compile(r"poz\.\s*977"), "pp2012"),
)


# Próg punktowy ma w korpusie trzy postacie i każda należy do innego układu:
#
#   2 punkty – pełne rozwiązanie            nagłówek; E8, zadania otwarte
#   1 pkt – odpowiedź poprawna.             w linii z opisem; E8 zamknięte, matura 2023+
#   Zdający otrzymuje ......... 2 p.        punktacja NA KOŃCU; matura do 2022
#
# Klasy znaków rozdzielających są zawężone do spacji i tabulatora celowo:
# `\s*` obejmuje znak nowej linii, więc „2 punkty" z pustym ogonem zjadało
# następny wiersz i pierwszy warunek progu lądował w polu `etykieta`.
RE_PROG_NAGLOWEK = re.compile(r"^[ \t]*(\d+)[ \t]+punkt(?:y|ów)?\b[ \t]*(.*)$", re.M)
RE_PROG_LINIA = re.compile(r"^[ \t]*(\d+)[ \t]*pkt\b[ \t]*[–—−-]?[ \t]*(.*)$", re.M)
RE_PROG_ZDAJACY = re.compile(
    r"^[ \t]*Zdający otrzymuje[ \t.…]*[ \t]*(\d+)[ \t]*(?:p\.|pkt)[ \t]*()$", re.M)

@dataclass(frozen=True)
class Dialekt:
    """Nazwy sekcji i separatory jednego układu dokumentu."""
    kod: str
    etykieta: str
    egzamin: str                      # 'e8' | 'matura'
    progi: Tuple[Tuple, ...]          # (wzorzec progu, czy ogon jest warunkiem)
    alternatywa: re.Pattern           # granica warunku wewnątrz progu
    zapis: re.Pattern                 # granica zapisu równoważnego
    odpowiedzi: Tuple[str, ...]       # które czytniki odpowiedzi uruchomić
    rozwiazania: re.Pattern           # nagłówek sekcji przykładowych rozwiązań
    sposob: re.Pattern                # „I sposób" / „Sposób I"
    uwagi_zadania: re.Pattern         # sekcja uwag pod jednym zadaniem
    reguly_naglowek: re.Pattern       # sekcja reguł przekrojowych
    reguly_punkt: re.Pattern          # jak wypunktowana jest jedna reguła
    koniec_zadan: re.Pattern          # gdzie kończy się część zadaniowa
    pagina: re.Pattern                # żywa pagina do odcięcia
    # 'dzial-punkt' — dział rzymski albo arabski, po nim punkt („V. … Uczeń: 3)")
    # 'jawna'       — ścieżka wpisana wprost przy wymaganiu („I.4)", „R11.1)")
    sciezka_szczegolowa: str


# Żywa pagina powtarza się na każdej stronie i po sklejeniu stron ląduje
# w środku zdania z kryterium („…poprawnych zależności Strona 12 z 26 Zasady
# oceniania rozwiązań zadań między liczbą plakatów…"). Bez odcięcia wchodzi
# do korpusu jako część treści kryterium.
_PAGINA_WSPOLNA = (r"Strona\s+\d+\s+z\s+\d+"
                   r"|Zasady oceniania rozwiązań zadań")
PAGINA_E8 = re.compile(
    r"^\s*(?:" + _PAGINA_WSPOLNA +
    r"|Egzamin ósmoklasisty z .{3,40}?[-–—] termin .{3,30}?\d{4} r\.)\s*$", re.M)
PAGINA_MATURA = re.compile(
    r"^\s*(?:" + _PAGINA_WSPOLNA +
    r"|Egzamin maturalny z .{3,60}?[-–—] termin .{3,30}?\d{4} r\.)\s*$", re.M)

SLOWNIK: Dict[str, Dialekt] = {

    # ── E8, rocznik 2019 ────────────────────────────────────────────────────
    # Pierwszy rocznik egzaminu. Progi mają formę nagłówka, warunki rozdziela
    # MAŁE „lub", zadania zamknięte nie mają w ogóle sekcji kryteriów (sam
    # nagłówek „Rozwiązanie" i litera), a tabela wymagań ma cztery kolumny,
    # bo klucz mapuje zadanie na dwie podstawy programowe naraz.
    "e8-2019": Dialekt(
        kod="e8-2019",
        etykieta="E8 · rocznik 2019 (dwie podstawy, separator „lub”)",
        egzamin="e8",
        progi=((RE_PROG_NAGLOWEK, False), (RE_PROG_LINIA, True)),
        # W 2019 r. separator warunków bywa pisany obiema wielkościami liter
        # (14 wystąpień „lub" na 2 „LUB" w OMAP-Q00-1904), więc bierzemy oba.
        # Od 2020 r. zostaje samo „LUB" i tam małe „lub" samotne w linii jest
        # już tylko efektem zawinięcia wiersza.
        alternatywa=re.compile(r"\n\s*(?:LUB|lub)\s*,?\s*\n"),
        zapis=re.compile(r"\n\s*(?:albo)\s*,?\s*\n|\s{3,}(?:albo)\s{3,}"),
        # `Uwag[ai]` a nie `Uwagi?`: to drugie NIE dopasowuje słowa „Uwaga",
        # bo `i?` obcina się do „Uwag" i zostaje wisząca litera. Sekcja pod
        # zadaniem bywa w obu liczbach i przy liczbie pojedynczej jej treść
        # wchodziła w całości do kryterium za 0 punktów.
        odpowiedzi=("solo",),
        rozwiazania=re.compile(r"Przykładowe rozwiązani\w*(?:[^\n]*)"),
        sposob=re.compile(r"^\s*(I{1,3}V?|VI{0,3})\s+sposób", re.M),
        uwagi_zadania=re.compile(r"\n\s*Uwag[ai][.:]?\s*\n"),
        reguly_naglowek=re.compile(r"^\s*Uwagi ogólne:?\s*$", re.M),
        reguly_punkt=re.compile(r"•\s*(.{20,600}?)(?=\n\s*•|\n\s*\n)", re.S),
        koniec_zadan=re.compile(r"\n\s*(?:Ogólne zasady oceniania|Ocena prac)"),
        pagina=PAGINA_E8,
        sciezka_szczegolowa="dzial-punkt",
    ),

    # ── E8, roczniki 2020–2026 ──────────────────────────────────────────────
    # Układ, który przeżył zmianę podstawy programowej i pandemię. Różnice
    # wewnątrz tego przedziału (bliźniaki X/Y, sekcja „Uwagi ogólne", reżim
    # wymagań, etap edukacyjny przy wymaganiu szczegółowym) NIE są osobnymi
    # dialektami — parser mierzy je w każdym pliku z osobna, bo w tej samej
    # sesji jedne warianty je mają, a inne nie.
    "e8-2020": Dialekt(
        kod="e8-2020",
        etykieta="E8 · roczniki 2020–2026 (separator „LUB”)",
        egzamin="e8",
        progi=((RE_PROG_NAGLOWEK, False), (RE_PROG_LINIA, True)),
        alternatywa=re.compile(r"\n\s*LUB\s*,?\s*\n"),
        zapis=re.compile(r"\n\s*(?:albo|lub)\s*,?\s*\n|\s{3,}(?:albo|lub)\s{3,}"),
        odpowiedzi=("wersje", "solo"),
        rozwiazania=re.compile(r"Przykładowe rozwiązani\w*(?:[^\n]*)"),
        sposob=re.compile(r"^\s*(I{1,3}V?|VI{0,3})\s+sposób", re.M),
        uwagi_zadania=re.compile(r"\n\s*Uwag[ai][.:]?\s*\n"),
        reguly_naglowek=re.compile(r"^\s*Uwagi ogólne:?\s*$", re.M),
        reguly_punkt=re.compile(r"•\s*(.{20,600}?)(?=\n\s*•|\n\s*\n)", re.S),
        koniec_zadan=re.compile(r"\n\s*(?:Ogólne zasady oceniania|Ocena prac)"),
        pagina=PAGINA_E8,
        sciezka_szczegolowa="dzial-punkt",
    ),

    # ── Matura, dokument od 2023 r. (formuły 2015 i 2023) ───────────────────
    # Obie formuły maturalne od sesji 2023 dostały ten sam układ dokumentu —
    # różni je numeracja wymagań, nie budowa klucza. Trzy rzeczy łamią tu
    # parser E8:
    #   • bliźniaki nazywają się „Wersja A" i „Wersja B", nie X i Y,
    #   • warunki rozdziela „ALBO", a nie „LUB",
    #   • po ostatnim zadaniu stoi ANEKS z zasadami dla osób z dyskalkulią,
    #     w którym nagłówki „Zadanie 14." NIE mają puli punktów. Bez markera
    #     końca aneks dokleja się do ostatniego zadania i wnosi do niego
    #     drugi próg „2 pkt" — czyli dokładnie ten błąd, który w E8 złapał
    #     UNIQUE (zadanie_id, punkty) na sekcji reguł przekrojowych.
    "matura": Dialekt(
        kod="matura",
        etykieta="Matura · dokument od 2023 r. (progi „N pkt”, separator „ALBO”)",
        egzamin="matura",
        progi=((RE_PROG_LINIA, True),),
        alternatywa=re.compile(r"\n\s*ALBO\s*,?\s*\n"),
        zapis=re.compile(r"\n\s*(?:albo|lub)\s*,?\s*\n|\s{3,}(?:albo|lub)\s{3,}"),
        odpowiedzi=("ab", "wersje", "solo"),
        rozwiazania=re.compile(r"Przykładow\w+ (?:pełn\w+ )?rozwiązani\w*(?:[^\n]*)"),
        sposob=re.compile(r"^\s*Sposób\s+(\d+|I{1,3}V?|VI{0,3})\.?", re.M),
        uwagi_zadania=re.compile(r"\n\s*Uwag[ai][.:]?\s*\n"),
        reguly_naglowek=re.compile(r"^\s*Uwagi ogólne:?\s*$", re.M),
        reguly_punkt=re.compile(r"^\s*\d+\.\s*(.{20,600}?)(?=\n\s*\d+\.\s|\n\s*\n)",
                                re.S | re.M),
        koniec_zadan=re.compile(
            r"\n\s*(?:Ocena prac osób ze stwierdzoną dyskalkulią"
            r"|I{1,2}\.\s*Dodatkowe szczegółowe zasady oceniania"
            r"|Ogólne zasady oceniania)"),
        pagina=PAGINA_MATURA,
        sciezka_szczegolowa="jawna",
    ),

    # ── Matura, dokument do 2022 r. ─────────────────────────────────────────
    # Formuła 2015 przed ujednoliceniem dokumentów. Zmierzone na sześciu
    # kluczach EMAP z lat 2021–2023: układ zmienia się w SESJI 2023, nie wraz
    # z formułą — EMAP-P0-100-2305 ma już nowy, a EMAP-P0-100-2205 stary.
    # Różnica, która wywraca parsowanie kryteriów: punktacja progu stoi na
    # KOŃCU linii, za wielokropkiem wiodącym.
    #
    #     Zdający otrzymuje  ...................................  2 pkt
    #     gdy:
    #     • wypisze wszystkie zdarzenia elementarne […]
    #     ALBO
    #     • poda liczbę wszystkich zdarzeń elementarnych […]
    #
    # Wzorzec „N pkt na początku linii" nie trafia tu ANI RAZU, więc bez
    # osobnego dialektu klucz wchodzi do korpusu z zadaniami otwartymi bez
    # jednego kryterium — i nic tego nie zgłasza.
    "matura-2015": Dialekt(
        kod="matura-2015",
        etykieta="Matura · dokument do 2022 r. (progi „Zdający otrzymuje … N pkt”)",
        egzamin="matura",
        # Trzeci wzorzec progu to punktacja etapowa zadań za 5–7 punktów
        # („2 punkty zdający otrzymuje, gdy zapisze nierówność…"). Bez niego
        # zadanie 11 z EMAP-R0-100-2105 (0–5) wchodzi do korpusu bez ani
        # jednego kryterium. UWAGA: etapy powtarzają tę samą punktację
        # (1 punkt w etapie II i w etapie III), a `UNIQUE (zadanie_id, punkty)`
        # przepuszcza tylko pierwszy — model nie ma jeszcze pojęcia „etap".
        progi=((RE_PROG_ZDAJACY, False), (RE_PROG_NAGLOWEK, True),
               (RE_PROG_LINIA, True)),
        alternatywa=re.compile(r"\n\s*ALBO\s*,?\s*\n"),
        zapis=re.compile(r"\n\s*(?:albo|lub)\s*,?\s*\n|\s{3,}(?:albo|lub)\s{3,}"),
        odpowiedzi=("wersje", "ab", "solo"),
        rozwiazania=re.compile(r"Przykładow\w+ (?:pełn\w+ )?rozwiązani\w*(?:[^\n]*)"),
        sposob=re.compile(r"^\s*Sposób\s+(\d+|I{1,3}V?|VI{0,3})\.?", re.M),
        uwagi_zadania=re.compile(r"\n\s*Uwag[ai][.:]?\s*\n"),
        # Reguły przekrojowe stoją tu bez nagłówka „Uwagi ogólne" — wprowadza
        # je tytuł sekcji zadań otwartych, a zaraz po nim idzie lista numerowana.
        reguly_naglowek=re.compile(r"^\s*ZADANIA OTWARTE[^\n]*$", re.M),
        reguly_punkt=re.compile(r"^\s*\d+\.\s*(.{20,600}?)(?=\n\s*\d+\.\s|\n\s*\n)",
                                re.S | re.M),
        koniec_zadan=re.compile(
            r"\n\s*(?:Ogólne zasady oceniania zadań otwartych"
            r"|Kryteria uwzględniające specyficzne trudności"
            r"|Ocena prac osób ze stwierdzoną dyskalkulią)"),
        pagina=PAGINA_MATURA,
        sciezka_szczegolowa="jawna",
    ),
}


def wykryj_dialekt(tekst: str, nazwa: str = "") -> Dialekt:
    """Który układ dokumentu — mierzone na tekście, nie zgadywane z nazwy.

    Nazwa pliku mówi tylko, czym plik miał być. OMAP-800 i OMAP-100 z tej
    samej sesji mają inny zestaw sekcji, a rocznik 2019 różni się od 2020
    bardziej niż 2020 od 2026 — więc rozstrzyga zawartość.
    """
    if "Egzamin maturalny" in tekst[:4000] or re.search(r"^[EM]M[A-Z]{2}-", nazwa):
        # Układ maturalny rozstrzyga postać progu, bo tylko ona łamie parser.
        # Wielokropek wiodący przed punktacją występuje w 6 kluczach do 2022 r.
        # i w żadnym późniejszym.
        if RE_PROG_ZDAJACY.search(tekst):
            return SLOWNIK["matura-2015"]
        return SLOWNIK["matura"]
    # Rozstrzyga żywa pagina, a nie separator warunków. Separator wygląda na
    # oczywistą cechę rocznika i nią nie jest: OMAP-Q00-1904 ma 2 warunki
    # rozdzielone wielkim „LUB" przy 14 małych „lub" w tym samym roczniku.
    # Nagłówek strony rozdziela roczniki bez wyjątku — 0 z 8 plików z 2019 r.
    # i 67 z 67 późniejszych.
    if re.search(r"Egzamin ósmoklasisty z .{3,40}?[-–—] termin .{3,30}?\d{4} r\.", tekst):
        return SLOWNIK["e8-2020"]
    return SLOWNIK["e8-2019"]


# =============================================================================
# WZORCE WSPÓLNE
# =============================================================================

# Po literze wersji bywa odsyłacz do przypisu („wersja Y²" — „Odpowiedzi
# w wersji Y dotyczą wyłącznie arkusza OMAP-100-2505"). W płaskim tekście był
# niewidoczny, bo cyfra przypisu zlewała się z tłem; ujawniła go dopiero
# rekonstrukcja potęg — i zerwała zakotwiczony regex.
_PRZYPIS = r"(?:\^\(?[\d,]*\)?)?"
# Litera wersji NIE jest wpisana na sztywno: E8 ma bliźniaki X i Y, a matura
# formuły 2015 do 2022 r. używa dokładnie tego samego nagłówka z literami
# A i B. Jeden czytnik zamiast dwóch prawie identycznych.
RE_ODP_WERSJE = re.compile(
    r"Rozwiązanie\s*[–—−-]\s*wersja\s*([A-Z])" + _PRZYPIS + r"\s*\n"
    r"\s*Rozwiązanie\s*[–—−-]\s*wersja\s*([A-Z])" + _PRZYPIS + r"\s*\n(.+?)(?:\n\s*\n|\Z)",
    re.S)
RE_ODP_AB = re.compile(
    r"Rozwiązanie\s*\n\s*Wersja\s+([A-Z])" + _PRZYPIS + r"\s*\n"
    r"\s*Wersja\s+([A-Z])" + _PRZYPIS + r"\s*\n(.+?)(?:\n\s*\n|\Z)", re.S)
RE_ODP_SOLO = re.compile(r"^[ \t]*Rozwiązanie[ \t]*$\n(.+?)(?:\n\s*\n|\Z)", re.M | re.S)

# Odpowiedź wieloczęściowa: „1.1. TAK" / „1.2. NIE". Zmierzone w OMAP-Q00-1904
# i w kluczach z podpunktami — bez tego oba wiersze sklejają się w jedną
# odpowiedź „1.1. TAK 1.2. NIE", której nie da się porównać z pracą ucznia.
RE_PODPUNKT = re.compile(r"^\s*(\d+(?:\.\d+)+)\.?\s+(.+?)\s*$")

# Ile pierwszych wierszy tabeli może zająć nagłówek z podpisem reżimu. Cztery
# to zmierzone maksimum (OMAP-Q00-2004: nagłówek zadania, pusty wiersz, podpis
# podstawy, nazwy kolumn), piąty jest zapasem.
WIERSZE_NAGLOWKA = 5

# Dział wymagań szczegółowych numeruje się cyfrą rzymską w podstawie z 2017 r.
# i ARABSKĄ w podstawie z 2012 r. („12. Obliczenia praktyczne. Uczeń:").
# Klucze 2019 i 2020 niosą obie naraz, więc wzorzec musi brać obie — inaczej
# połowa mapy braków tych roczników przepada bez śladu w logu.
RE_DZIAL = re.compile(r"([IVX]+|\d+)\.\s+([^:]{3,90}?)\.\s*(?:Uczeń|Zdający):")
RE_PUNKT = re.compile(r"(\d+)\)\s+(.{5,}?)(?=\s+\d+\)|$)")
# Ścieżka wymagania maturalnego ma cztery notacje w korpusie i wszystkie
# oznaczają to samo miejsce w dokumencie wymagań:
#   I.1)  VI.5)  XIII.R1)   — formuła 2023 i formuła 2015 od sesji 2023
#   1.3)  10.2)  R1.2)  G1.6)  — formuła 2015 do 2022 („G" = III etap)
_SCIEZKA_JAWNA = r"(?:[IVX]+|[GR]?\d+)(?:\.(?:[A-Z]?\d+|R\d+))?"
RE_PUNKT_JAWNY = re.compile(
    r"\b(%s)\)\s+(.{5,}?)(?=\s+%s\)|$)" % (_SCIEZKA_JAWNA, _SCIEZKA_JAWNA))
# Etap edukacyjny bywa zapisany na cztery sposoby w JEDNYM pliku: „KLASY IV–VI",
# „Klasy IV–VI", „KLASY VII I VIII" (spójnik wersalikiem) i sam zakres
# „VII-VIII" bez słowa. Zmierzone w kluczu OMAP-100-1904 — wszystkie cztery,
# na sąsiednich stronach. Wzorzec bierze wszystkie, bo etap zgubiony przy
# jednym zadaniu rozdziela ten sam punkt podstawy na dwa byty w mapie braków.
RE_ETAP = re.compile(
    r"((?:KLASY|Klasy)\s+[IVX]+(?:\s*[–—-]\s*[IVX]+)?(?:\s+[iI]\s+[IVX]+)?"
    r"|\b(?:IV\s*[–—-]\s*VI|VII\s*[–—-]\s*VIII)\b)")


# =============================================================================
# WYNIK PARSOWANIA — kształt z schema.sql
# =============================================================================

@dataclass
class Zadanie:
    numer: str
    punkty: int
    kolejnosc: int
    typ: str
    strona: Optional[int] = None
    # Lista, nie pojedynczy rekord: klucze 2019 i 2020 mapują zadanie na dwie
    # podstawy programowe naraz i mają po jednym wymaganiu ogólnym na każdą.
    ogolne: List[dict] = field(default_factory=list)
    szczegolowe: List[dict] = field(default_factory=list)
    odpowiedzi: Dict[Optional[str], List[Tuple[Optional[str], str]]] = field(default_factory=dict)
    kryteria: List[dict] = field(default_factory=list)
    rozwiazania: List[dict] = field(default_factory=list)
    uwagi: List[str] = field(default_factory=list)


@dataclass
class Klucz:
    plik: str
    dialekt: str
    egzamin: str
    rezimy: List[dict] = field(default_factory=list)
    termin: Optional[str] = None
    formy: List[dict] = field(default_factory=list)
    zadania: List[Zadanie] = field(default_factory=list)
    reguly: List[dict] = field(default_factory=list)
    stron: int = 0
    ostrzezenia: List[str] = field(default_factory=list)


# =============================================================================
# CZYTANIE
# =============================================================================

def czytaj_klucz(path: str, silnik: str = "pdfplumber") -> Klucz:
    """Klucz oceniania → rekordy w kształcie `schema.sql`."""
    strony: List[str] = []
    stopki: List[str] = []                         # przypisy, odcięte od treści
    tabele: List[Tuple[int, float, object]] = []   # (strona, górna krawędź, tabela)
    naglowki: List[Tuple[int, float]] = []         # (strona, y) nagłówków zadań
    with open_pdf(path, engine=silnik) as doc:
        for page in doc:
            strony.append(reconstruct.page_text(page, pomin_przypisy=True))
            naglowki += [(len(strony) - 1, y) for y in _pozycje_naglowkow(page)]
            # Przypisy wypadają z treści, ale nie z dokumentu: to w nich stoi
            # numer Dziennika Ustaw, po którym poznajemy, KTÓRA podstawa
            # programowa obowiązuje. Nagłówek tabeli mówi tylko „Podstawa
            # programowa", bez roku.
            odciete = reconstruct.przypisy(page.chars)
            if odciete:
                stopki.append(_tekst_stopki(
                    [c for c in page.chars if id(c) in odciete]))
            # Wymagania podstawy stoją w tabeli — także w kluczu matematyki,
            # nie tylko angielskiego. W płaskim tekście kolumny sklejają się
            # linia po linii („IV. Rozumowanie i argumentacja. KLASY IV–VI"),
            # więc czytamy je z siatki, nie regexem. Tabela zagnieżdżona
            # wewnątrz komórki (matura, lewa kolumna bywa wykrywana osobno)
            # nie ma w nagłówku słowa „Wymagani" i odpada tu sama.
            for t in page.tables:
                # Nagłówek „Wymaganie ogólne | Wymaganie szczegółowe" stoi
                # w pierwszym wierszu tylko wtedy, gdy tabela nie ma podpisu.
                # W roczniku 2019 pierwszy wiersz zajmuje „Podstawa programowa
                # 2012 | Podstawa programowa 2017", a w OMAP-Q00-2004 ramka
                # obejmuje też nagłówek zadania i pusty wiersz — nagłówek
                # kolumn jest tam czwarty. Szukanie w samym wierszu zerowym
                # gubiło wymagania 21 zadań rocznika 2019 i 6 zadań Q00.
                head = " ".join(" ".join(r) for r in t.rows[:WIERSZE_NAGLOWKA])
                if "Wymagani" in head:
                    tabele.append((len(strony) - 1, t.bbox[1], t))

    tekst = "\n".join(strony)
    dial = wykryj_dialekt(tekst, os.path.basename(path))
    k = Klucz(plik=path, dialekt=dial.kod, egzamin=dial.egzamin, stron=len(strony))

    k.rezimy = _rezimy(tekst, dial, "\n".join(stopki))
    naglowek = tekst[:_pierwsze_zadanie(tekst)] or tekst[:2500]
    k.termin = _termin(naglowek)
    k.formy = _formy(naglowek)
    if not k.formy:
        k.ostrzezenia.append("nagłówek bez formy arkusza")

    # Mapa „offset w sklejonym tekście → indeks strony": zadanie tniemy
    # z tekstu, a numer strony jest potrzebny przy rekordzie `zadanie_wersja`
    # (i przy ręcznej korekcie — bez niego nie ma jak wrócić do oryginału).
    granice = []
    acc = 0
    for s in strony:
        granice.append(acc)
        acc += len(s) + 1

    def strona_offsetu(off: int) -> int:
        lo, hi = 0, len(granice) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if granice[mid] <= off:
                lo = mid
            else:
                hi = mid - 1
        return lo

    zadania_pozycje = _tnij_zadania(tekst, dial)
    if not zadania_pozycje:
        k.ostrzezenia.append("nie znaleziono ani jednego nagłówka zadania")
        return k

    przypisane, uwaga = _sparuj_tabele(naglowki, tabele, len(zadania_pozycje))
    if uwaga:
        k.ostrzezenia.append(uwaga)

    for i, (start, koniec, numer, punkty) in enumerate(zadania_pozycje):
        z = _parsuj_zadanie(numer, punkty, tekst[start:koniec], i + 1, dial,
                            przypisane.get(i), [r["kod"] for r in k.rezimy])
        z.strona = strona_offsetu(start)
        k.zadania.append(z)

    bez_tabeli = sum(1 for z in k.zadania if not z.ogolne and not z.szczegolowe)
    if bez_tabeli:
        k.ostrzezenia.append("zadań bez wymagań podstawy: %d z %d"
                             % (bez_tabeli, len(k.zadania)))
    bez_kryteriow = sum(1 for z in k.zadania if not z.kryteria)
    if bez_kryteriow:
        k.ostrzezenia.append("zadań bez kryteriów: %d z %d"
                             % (bez_kryteriow, len(k.zadania)))
    bez_odpowiedzi = sum(1 for z in k.zadania
                         if z.typ == "zamkniete" and not z.odpowiedzi)
    if bez_odpowiedzi:
        k.ostrzezenia.append("zadań zamkniętych bez odpowiedzi: %d" % bez_odpowiedzi)

    k.reguly = _reguly(tekst, dial)
    return k


# Tabela wymagań stoi ZARAZ pod nagłówkiem swojego zadania, ale „zaraz" jest
# stwierdzeniem o UKŁADZIE STRONY, nie o kolejności w strumieniu tekstu.
# Parowanie kolejnością zawodzi na dwa sposoby, oba zmierzone w korpusie:
# zadanie bez tabeli (EMAP-R0-100-2205 zad. 5) przesuwa całą resztę o jeden,
# a strona bez zadania (trzy strony rozwiązań przykładowych) — o tyle, ile
# tabel na niej stanęło. Skutek jest ten sam i cichy: zadanie z cudzym
# wymaganiem podstawy, czyli fałszywa mapa braków.
#
# Rozstrzygamy współrzędnymi: tabela należy do NAJBLIŻSZEGO nagłówka nad nią.
TOL_TABELI = 6.0     # ramka tabeli bywa tuż nad nagłówkiem, gdy go obejmuje


def _tekst_stopki(znaki) -> str:
    """Przypisy jako tekst — z odstępami odtworzonymi z odległości między glifami.

    Nie idzie tu o czytelność, tylko o to, żeby „Dz.U. 2024, poz. 996" dało się
    znaleźć wzorcem: w tych plikach odstęp bywa pozycjonowaniem, a nie znakiem
    spacji, i bez tego cały przypis skleja się w jeden wyraz.
    """
    znaki = sorted(znaki, key=lambda c: (round(c.cy), c.x0))
    out, poprzedni = [], None
    for c in znaki:
        if poprzedni is not None and (c.x0 - poprzedni.x1 > 0.25 * c.size
                                      or c.cy - poprzedni.cy > 2):
            out.append(" ")
        out.append(c.c)
        poprzedni = c
    return "".join(out)


def _pozycje_naglowkow(page) -> List[float]:
    """Górne krawędzie wierszy „Zadanie N. (0–M)" na stronie."""
    wiersze: Dict[int, list] = {}
    for c in page.chars:
        wiersze.setdefault(round(c.y0 / reconstruct.LINE_TOL), []).append(c)
    out = []
    for cs in wiersze.values():
        cs.sort(key=lambda c: c.x0)
        tekst = "".join(c.c for c in cs).strip()
        if tekst.startswith("Zadanie") and RE_ZADANIE.match(tekst):
            out.append(min(c.y0 for c in cs))
    return sorted(out)


def _sparuj_tabele(naglowki, tabele, ile_zadan: int):
    """Tabela wymagań → indeks zadania, po współrzędnych na stronie."""
    if len(naglowki) < ile_zadan:
        # Nagłówek rozjechany na dwa wiersze albo strona bez warstwy tekstowej.
        # Wracamy do parowania kolejnością, ale mówimy o tym wprost.
        przypisane = {i: t for i, (_, _, t) in enumerate(tabele) if i < ile_zadan}
        return przypisane, ("nagłówków w układzie strony %d, zadań %d — "
                            "tabele wymagań sparowane kolejnością"
                            % (len(naglowki), ile_zadan))
    naglowki = naglowki[:ile_zadan]
    zdarzenia = ([(p, y, "n", i) for i, (p, y) in enumerate(naglowki)] +
                 [(p, y + TOL_TABELI, "t", t) for p, y, t in tabele])
    zdarzenia.sort(key=lambda z: (z[0], z[1]))
    przypisane: Dict[int, object] = {}
    biezace = None
    for _, _, typ, obj in zdarzenia:
        if typ == "n":
            biezace = obj
        elif biezace is not None and biezace not in przypisane:
            przypisane[biezace] = obj
    return przypisane, ""


def _pierwsze_zadanie(tekst: str) -> int:
    m = RE_ZADANIE.search(tekst)
    return m.start() if m else 0


def _tnij_zadania(tekst: str, dial: Dialekt) -> List[Tuple[int, int, str, int]]:
    """Granice zadań: (start ciała, koniec ciała, numer, pula punktów).

    Ostatnie zadanie kończy się tam, gdzie zaczyna się aneks — a nie na końcu
    pliku. W maturze aneks („Ocena prac osób ze stwierdzoną dyskalkulią")
    powtarza nagłówki `Zadanie 14.` BEZ puli punktów i wnosi własne progi;
    doklejony do ostatniego zadania łamie UNIQUE (zadanie_id, punkty).
    """
    trafienia = list(RE_ZADANIE.finditer(tekst))
    if not trafienia:
        return []
    m_koniec = dial.koniec_zadan.search(tekst, trafienia[-1].end())
    kres = m_koniec.start() if m_koniec else len(tekst)

    out = []
    for i, m in enumerate(trafienia):
        koniec = trafienia[i + 1].start() if i + 1 < len(trafienia) else kres
        punkty = int(m.group(2) or m.group(3))
        out.append((m.end(), min(koniec, kres), m.group(1), punkty))
    return [t for t in out if t[0] < t[1]]


def _rezimy(tekst: str, dial: Dialekt, stopki: str = "") -> List[dict]:
    """Reżimy wymagań zadeklarowane w kluczu — bywają dwa naraz.

    Klucze 2019 i 2020 mapują KAŻDE zadanie na dwie podstawy programowe
    jednocześnie (2012 i 2017), bo rocznik był przejściowy. Wpisanie tylko
    jednej z nich gubi połowę mapy braków.
    """
    # Przypis rocznika 2019 ma 10,0 pkt przy bazie 11,0, więc nie wpada
    # w blok cięty ze strony — szukamy i tam, i w treści.
    przypisy = {nr: " ".join(t.split())
                for nr, t in RE_PRZYPIS_TRESC.findall(stopki + "\n" + tekst)}
    out, widziane = [], set()
    aktualna = None
    for wzor, kod in DZIENNIKI:
        if wzor.search(stopki) or wzor.search(tekst):
            aktualna = kod
            break
    for wzor, kod in REZIMY:
        for m in wzor.finditer(tekst):
            if kod is None:                        # „Wymagania egzaminacyjne 2021"
                lata = "-".join(g for g in m.groups() if g)
                nazwa = "wym%s" % lata
            elif kod == "pp-akt":
                nazwa = aktualna or "pp-akt"
            else:
                nazwa = kod
            pelny = "%s-%s" % (dial.egzamin, nazwa)
            if pelny in widziane:
                continue
            widziane.add(pelny)
            # akt prawny z przypisu, na który wskazuje odsyłacz przy podpisie
            odsylacz = RE_ODSYLACZ.match(tekst, m.end())
            przypis = przypisy.get(odsylacz.group(1)) if odsylacz else None
            dziennik = RE_DZIENNIK.search(przypis) if przypis else None
            out.append({"kod": pelny, "nazwa": " ".join(m.group(0).split()),
                        "zrodlo": dziennik.group(0) if dziennik else
                                  (przypis[:200] if przypis else None)})
    return out


def _termin(naglowek: str) -> Optional[str]:
    m = RE_TERMIN.search(" ".join(naglowek.split()))
    if not m:
        return None
    mies = MIESIACE.get(m.group(2).lower())
    if not mies:
        return None
    return "%s-%02d-%02d" % (m.group(3), mies, int(m.group(1)))


def _formy(naglowek: str) -> List[dict]:
    """Formy arkusza z nagłówka — sedno relacji N:M.

    Jeden klucz OMAP-100-2505 deklaruje sześć form, a forma 100 ma dwa
    zeszyty zadań (wersje X i Y). Deklaracja bliźniaków stoi w nawiasie przy
    tej formie, której dotyczy, więc czytamy ją linia po linii — przypisanie
    wersji do pierwszej formy z brzegu myli się wszędzie tam, gdzie bliźniaki
    ma forma inna niż pierwsza.
    """
    formy, widziane = [], set()
    for linia in naglowek.split("\n"):
        wersje = RE_WERSJE.search(linia)
        for kod, wariant, sesja in RE_FORMA.findall(linia):
            klucz = (kod, wariant)
            if klucz in widziane:
                continue
            widziane.add(klucz)
            formy.append({"kod": kod, "wariant": wariant, "sesja": sesja or None,
                          "wersje": [wersje.group(1).upper(), wersje.group(2).upper()]
                                    if wersje else [None]})
    return formy


def _parsuj_zadanie(numer: str, punkty: int, body: str, kolejnosc: int,
                    dial: Dialekt, tab=None, rezimy: Sequence[str] = ()) -> Zadanie:
    body = dial.pagina.sub("", body)

    ogolne, szczegolowe = (parsuj_wymagania(tab, dial, rezimy)
                          if tab is not None else ([], []))
    odpowiedzi = _odpowiedzi(body, dial)
    rozwiazania, i_rozw = _rozwiazania(body, dial)

    # Sekcja kryteriów kończy się tam, gdzie zaczynają się przykładowe
    # rozwiązania albo uwagi do zadania. Uwagi to reguła TEGO zadania,
    # nie część progu 0 pkt — wpuszczone do kryterium wchodzą do korpusu
    # jako warunek, którego nikt nie zapisał w kluczu.
    # Sekcja kryteriów zaczyna się nagłówkiem „Zasady oceniania" — ale nie
    # zawsze: gdy zadanie łamie się przez stronę, nagłówek potrafi zniknąć
    # i progi zaczynają się wprost od „3 punkty – pełne rozwiązanie"
    # (OMAP-700-2105 zad. 18, OMAP-800-2605 zad. 17 i cztery inne). Wtedy
    # czytamy całe ciało zadania — próg punktowy jest na tyle charakterystyczny,
    # że nie ma go czym pomylić, a brak kryteriów w zadaniu otwartym oznacza
    # dziurę w korpusie, której nikt później nie zauważy.
    i_zas = body.find("Zasady oceniania")
    poczatek = i_zas if i_zas >= 0 else 0
    kryteria_txt = body[poczatek:i_rozw] if (i_rozw is not None and i_rozw > poczatek) \
        else body[poczatek:]
    uwagi = []
    m_uw = dial.uwagi_zadania.search(kryteria_txt)
    if m_uw:
        ogon = kryteria_txt[m_uw.end():]
        kryteria_txt = kryteria_txt[:m_uw.start()]
        uwagi = [" ".join(u.split()) for u in re.split(r"\n\s*(?=\d+\.\s)", ogon)
                 if len(u.strip()) > 15]

    kryteria = _kryteria(kryteria_txt, dial)

    # Typ zadania po budowie klucza, nie po liczbie punktów: OMAP-Q00-1904
    # ma zadania zamknięte za 2 i 3 punkty (wieloczęściowe „1.1./1.2."),
    # a klucz matury — otwarte za 1 punkt. Rozstrzyga obecność przykładowego
    # rozwiązania: zadanie zamknięte go nie ma, bo nie ma czego pokazywać.
    if not rozwiazania and odpowiedzi:
        typ = "zamkniete"
    elif punkty <= 2:
        typ = "otwarte_krotkie"
    else:
        typ = "otwarte_rozszerzone"

    return Zadanie(numer=numer, punkty=punkty, kolejnosc=kolejnosc, typ=typ,
                   ogolne=ogolne, szczegolowe=szczegolowe, odpowiedzi=odpowiedzi,
                   kryteria=kryteria, rozwiazania=rozwiazania, uwagi=uwagi[:6])


def _odpowiedzi(body: str, dial: Dialekt) -> Dict[Optional[str], List[Tuple[Optional[str], str]]]:
    """Odpowiedzi wzorcowe per wersja arkusza.

    Trzy układy w jednym korpusie: bliźniaki X/Y (E8 od 2020), bliźniaki
    A/B (matura) i jedna odpowiedź bez wersji (warianty dostosowane oraz
    cały rocznik 2019). Płaska ekstrakcja skleja kolumny bliźniaków w „BD AC"
    i traci przypisanie — dlatego czytamy je z układu wierszy pod nagłówkiem.
    """
    out: Dict[Optional[str], List[Tuple[Optional[str], str]]] = {}
    for czytnik in dial.odpowiedzi:
        if czytnik == "wersje":
            m = RE_ODP_WERSJE.search(body)
            if m:
                _rozdziel_kolumny(m.group(3), (m.group(1), m.group(2)), out)
        elif czytnik == "ab":
            m = RE_ODP_AB.search(body)
            if m:
                _rozdziel_kolumny(m.group(3), (m.group(1), m.group(2)), out)
        elif czytnik == "solo":
            m = RE_ODP_SOLO.search(body)
            if m:
                pozycje = _pozycje_odpowiedzi(m.group(1))
                if pozycje:
                    out.setdefault(None, pozycje)
        if out:
            break
    return out


def _rozdziel_kolumny(blok: str, wersje: Sequence[str], out: dict) -> None:
    """Wiersze pod nagłówkiem dwóch wersji → odpowiedź lewej i prawej kolumny.

    Bliźniaki stoją obok siebie w tabeli, ale po sklejeniu wierszy wychodzą
    jeden pod drugim: pierwszy wiersz to wersja X, drugi — Y. Przy zadaniu
    wieloczęściowym wierszy jest 2·n i numer podpunktu je rozdziela.
    """
    linie = [l.strip() for l in blok.split("\n") if l.strip()]
    if not linie:
        return
    z_podpunktami = [RE_PODPUNKT.match(l) for l in linie]
    if all(z_podpunktami) and len(linie) >= 2:
        polowa = len(linie) // 2
        for w, kawalek in zip(wersje, (linie[:polowa], linie[polowa:])):
            out.setdefault(w, []).extend(
                (RE_PODPUNKT.match(l).group(1), RE_PODPUNKT.match(l).group(2))
                for l in kawalek)
        return
    for w, l in zip(wersje, linie):
        out.setdefault(w, []).append((None, l[:200]))


def _pozycje_odpowiedzi(blok: str) -> List[Tuple[Optional[str], str]]:
    linie = [l.strip() for l in blok.split("\n") if l.strip()]
    if not linie:
        return []
    podpunkty = [RE_PODPUNKT.match(l) for l in linie]
    if all(podpunkty):
        return [(m.group(1), m.group(2)[:200]) for m in podpunkty]
    return [(None, linie[0][:200])]


def _rozwiazania(body: str, dial: Dialekt) -> Tuple[List[dict], Optional[int]]:
    """Przykładowe rozwiązania autorstwa komisji — gotowy materiał few-shot.

    Zwraca też offset początku sekcji, bo tam kończą się kryteria.
    """
    m = dial.rozwiazania.search(body)
    if not m:
        return [], None
    naglowek = " ".join(m.group(0).split())
    m_pkt = re.search(r"ocenion\w+ na\s+(\d+)\s+punkt", naglowek)
    punkty = int(m_pkt.group(1)) if m_pkt else None

    ogon = body[m.end():]
    sposoby = list(dial.sposob.finditer(ogon))
    out = []
    if not sposoby:
        tresc = " ".join(ogon.split())
        if len(tresc) > 20:
            out.append({"sposob": None, "punkty": punkty, "tresc": tresc[:4000],
                        "kolejnosc": 1})
    for i, ms in enumerate(sposoby):
        koniec = sposoby[i + 1].start() if i + 1 < len(sposoby) else len(ogon)
        tresc = " ".join(ogon[ms.end():koniec].split())
        out.append({"sposob": ms.group(1), "punkty": punkty,
                    "tresc": tresc[:4000], "kolejnosc": i + 1})
    return out, m.start()


def _kryteria(txt: str, dial: Dialekt) -> List[dict]:
    """Progi → warunki → zapisy równoważne, czyli trzy poziomy dysjunkcji.

    Próg jest osiągnięty, gdy spełniony jest DOWOLNY warunek; warunek — gdy
    uczeń zapisał DOWOLNY z zapisów równoważnych. Spłaszczenie tego do pola
    tekstowego oznacza, że silnik dostanie akapit prozy zamiast listy
    sprawdzalnych alternatyw.
    """
    if not txt.strip():
        return []
    # Zadania otwarte E8 mają próg nagłówkiem („2 punkty – pełne rozwiązanie"),
    # zamknięte — w linii („1 pkt – odpowiedź poprawna."). Oba układy stoją
    # w tym samym pliku, więc bierzemy oba i sortujemy po pozycji; duplikat
    # na tej samej punktacji odsiewa `widziane`. Różnica nie jest kosmetyczna:
    # ogon nagłówka to ETYKIETA progu, ogon linii — pierwszy WARUNEK.
    progi = []
    for wzor, ogon_to_warunek in dial.progi:
        progi += [(m, ogon_to_warunek) for m in wzor.finditer(txt)]
    progi.sort(key=lambda p: p[0].start())

    out, widziane = [], set()
    for k, (mp, w_linii) in enumerate(progi):
        koniec = progi[k + 1][0].start() if k + 1 < len(progi) else len(txt)
        punkty = int(mp.group(1))
        if punkty in widziane:
            continue
        widziane.add(punkty)
        ogon = mp.group(2).strip(" –—-").strip()
        blok = (ogon + "\n" if w_linii else "") + txt[mp.end():koniec]

        etykieta = None if w_linii else (ogon or None)
        warunki = []
        for w in dial.alternatywa.split(blok):
            opis = _oczysc(w)
            if not opis:
                continue
            # „albo"/„lub" bywa spójnikiem w prozie („plakatów Basi lub
            # Marka"), a nie separatorem zapisów równoważnych. Odróżnia je
            # typografia: separator stoi samotnie w linii albo jest odsunięty
            # kilkoma spacjami od obu wyrażeń; zwykły spójnik ma po jednej.
            do_ciecia = re.sub(r"\((?:lub|albo)[^)]*\)", "", w)
            czesci = [_oczysc(c) for c in dial.zapis.split(do_ciecia)]
            czesci = [c for c in czesci if c]
            # Pierwszy zapis nosi jeszcze prozę warunku („…pola czworokąta
            # AECF, np. zapisanie P=15^2−…"). Granicą jest „np." — w kluczach
            # CKE wprowadza ono zapis, a nie zdanie. Bez tego cięcia w tabeli
            # `warunek_zapis` ląduje opis warunku udający wyrażenie.
            if czesci:
                m_np = re.search(r",?\s*np\.\s*", czesci[0])
                if m_np:
                    czesci[0] = czesci[0][m_np.end():].strip() or czesci[0]
            zapisy = list(czesci) if len(czesci) > 1 else []
            warunki.append({"opis": opis[:600], "zapisy": zapisy[:6]})
        out.append({"punkty": punkty, "etykieta": etykieta,
                    "opis": None if warunki else (ogon or None),
                    "warunki": warunki, "kolejnosc": len(out) + 1})
    return out


def _oczysc(s: str) -> str:
    """Jedna linia bez wypunktowania i bez nagłówka sekcji.

    „Zasady oceniania" wypada tu, bo pierwszy próg zaczyna się w tym samym
    kawałku tekstu co nagłówek sekcji i bez tego wchodziłby do treści warunku.
    """
    return " ".join(s.split()).lstrip("•-– ").strip(" ,;").replace("Zasady oceniania", "").strip()


def _reguly(tekst: str, dial: Dialekt) -> List[dict]:
    """Sekcja reguł przekrojowych — „Uwagi ogólne".

    To nie kryteria zadania, tylko reguły całego arkusza: błąd rachunkowy
    obniża ocenę o 1 punkt, sam wynik w zadaniach 16–21 to 0 punktów,
    11 tolerancji dla uczniów uprawnionych do dostosowanych zasad oceniania.
    Działają PO ocenie wszystkich kryteriów naraz — w kroku `Compose`.
    E8 wypunktowuje je kropką, matura numerem; stąd wzorzec przy dialekcie.
    """
    m = dial.reguly_naglowek.search(tekst)
    if not m:
        return []
    blok = tekst[m.end():m.end() + 4000]
    m_koniec = RE_ZADANIE.search(blok)
    if m_koniec:
        blok = blok[:m_koniec.start()]
    blok = dial.pagina.sub("", blok)

    out = []
    for linia in dial.reguly_punkt.findall(blok):
        tresc = " ".join((linia if isinstance(linia, str) else linia[0]).split())
        rodzaj = ("rachunkowa" if "błęd" in tresc and "rachunkow" in tresc else
                  "sam_wynik" if "tylko poprawny końcowy wynik" in tresc
                                 or "tylko poprawny wynik" in tresc else
                  "sprzeczne_rozwiazania" if "sprzecznych" in tresc else
                  "dostosowanie" if "dostosowanych zasad" in tresc
                                    or "dyskalkulią" in tresc else
                  "kalkulator" if "kalkulator" in tresc else "inna")
        zak = re.search(r"zadani\w+\s+(\d+)[.,]?\s*[–—-]\s*(\d+)", tresc)
        if not zak:
            zak = re.search(r"zadani\w+\s+(\d+)\.(?:,| i)\s.*?(\d+)\.", tresc)
        out.append({"rodzaj": rodzaj, "tresc": tresc,
                    "zadania_od": zak.group(1) if zak else None,
                    "zadania_do": zak.group(2) if zak else None,
                    "kolejnosc": len(out) + 1})
    return out


# =============================================================================
# WYMAGANIA PODSTAWY PROGRAMOWEJ
# =============================================================================

def parsuj_wymagania(tab, dial: Dialekt,
                     rezimy: Sequence[str] = ()) -> Tuple[List[dict], List[dict]]:
    """Wymagania z tabeli: (ogólne, [szczegółowe]).

    Tabela ma dwie kolumny (ogólne | szczegółowe) albo cztery — roczniki 2019
    i 2020 mapują zadanie na dwie podstawy programowe naraz i wtedy pary
    kolumn powtarzają się obok siebie. Kolumny bierzemy z NAGŁÓWKA tabeli,
    a nie z pozycji: „pierwsza i ostatnia" miesza wtedy wymaganie ogólne
    z 2012 r. ze szczegółowym z 2017 r. i produkuje ścieżkę, której nie ma
    w żadnym dokumencie.
    """
    if tab is None or not tab.rows:
        return None, []
    pary = _kolumny(tab)
    ogolne: List[dict] = []
    szczegolowe = []
    for i_para, (i_og, i_sz) in enumerate(pary):
        # Który reżim opisuje ta para kolumn. Podpis stoi nad nią tylko przy
        # pierwszym zadaniu w dokumencie — dalej tabela zaczyna się od razu od
        # „Wymaganie ogólne", więc kolejność par musi wystarczyć. Wymaganie bez
        # reżimu jest bezużyteczne: ta sama ścieżka „V.3" znaczy co innego
        # w podstawie z 2012 r., w wymaganiach pandemicznych i w podstawie
        # z 2024 r., a mapa braków sumuje po ścieżce.
        rezim = _rezim_kolumny(tab, i_og, i_sz)
        if rezim is not None:
            # podpis niesie samą nazwę reżimu, lista dokumentu — z egzaminem
            pasujace = [r for r in rezimy if r.endswith(rezim)]
            rezim = pasujace[0] if pasujace else rezim
        if rezim is None:
            rezim = rezimy[i_para] if i_para < len(rezimy) else (
                rezimy[0] if rezimy else None)
        lewa = prawa = ""
        for row in tab.rows:
            cells = [(c or "").strip() for c in row]
            if any("Wymagani" in c for c in cells) or not any(cells):
                continue
            # podpis reżimu i nagłówek zadania nie są treścią wymagania
            if any(re.match(r"(?:Podstawa programowa|Zadanie\s+\d)", c) for c in cells):
                continue
            if i_og < len(cells):
                lewa += " " + cells[i_og]
            if i_sz < len(cells):
                prawa += " \n" + cells[i_sz]
        # Numer wymagania ogólnego SZUKAMY, a nie kotwiczymy na początku
        # komórki: w roczniku 2019 pierwszy wiersz tabeli to podpis („Podstawa
        # programowa 2012"), więc kotwica nie trafia i wszystkie 21 zadań
        # zostaje bez wymagania ogólnego.
        m = re.search(r"\b([IVX]+)\.\s*(.+)", " ".join(lewa.split()))
        if m:
            ogolne.append({"sciezka": m.group(1), "tresc": m.group(2).strip()[:400],
                           "rezim": rezim})
        for sz in _szczegolowe(prawa, dial):
            sz["rezim"] = rezim
            szczegolowe.append(sz)
    # ta sama ścieżka bywa w obu podstawach — deduplikacja po (etap, ścieżka)
    widziane, unikalne = set(), []
    for s in szczegolowe:
        k = (s["rezim"], s["etap"], s["sciezka"])
        if k not in widziane:
            widziane.add(k)
            unikalne.append(s)
    widziane_og, unikalne_og = set(), []
    for o in ogolne:
        k = (o["rezim"], o["sciezka"])
        if k not in widziane_og:
            widziane_og.add(k)
            unikalne_og.append(o)
    return unikalne_og, unikalne


def _rezim_kolumny(tab, i_og: int, i_sz: int) -> Optional[str]:
    """Podpis reżimu stojący nad parą kolumn („Podstawa programowa 2012")."""
    for row in tab.rows[:WIERSZE_NAGLOWKA]:
        cells = [(c or "").strip() for c in row]
        podpis = " ".join(cells[i_og:i_sz + 1]).strip()
        if not podpis or "Wymagani" in podpis:
            continue
        for wzor, kod in REZIMY:
            m = wzor.search(podpis)
            if m:
                if kod is None:
                    return "wym%s" % "-".join(g for g in m.groups() if g)
                # „Podstawa programowa" bez roku nie mówi która — rozstrzyga
                # przypis pod tabelą, którego tu nie ma. Zwracamy brak
                # rozpoznania, żeby zadziałało dopasowanie po kolejności.
                return None if kod == "pp-akt" else kod
    return None


def _kolumny(tab) -> List[Tuple[int, int]]:
    """Pary (kolumna wymagań ogólnych, kolumna szczegółowych) z nagłówka."""
    for row in tab.rows[:WIERSZE_NAGLOWKA]:
        cells = [(c or "").strip() for c in row]
        og = [i for i, c in enumerate(cells) if re.match(r"Wymagani[ae]\s+ogóln", c)]
        sz = [i for i, c in enumerate(cells) if re.match(r"Wymagani[ae]\s+szczegół", c)]
        if og and sz and len(og) == len(sz):
            return list(zip(og, sz))
    # brak nagłówka (tabela urwana przez podział strony) — pierwsza i ostatnia
    szer = max(len(r) for r in tab.rows)
    return [(0, szer - 1)] if szer > 1 else []


def _szczegolowe(prawa: str, dial: Dialekt) -> List[dict]:
    """Wymagania szczegółowe z prawej kolumny.

    Punkt należy do działu, który go POPRZEDZA, więc dział trzeba śledzić
    w trakcie czytania, a nie brać pierwszy z brzegu. Etap edukacyjny stoi
    śródtytułem („KLASY IV–VI") i obowiązuje aż do następnego — w kluczach
    2021–2024 nie ma go wcale, bo wymagania pandemiczne były jedną listą.
    Matura numeruje wymagania jawnie („I.4)", „XIII.R1)"), więc tam działu
    nie ma czego śledzić.
    """
    out = []
    etap = None
    for kawalek in RE_ETAP.split(prawa):
        k = " ".join(kawalek.split())
        if re.match(r"(?:KLASY|Klasy)\b", k) or re.fullmatch(
                r"(?:IV|VII)\s*[–—-]\s*(?:VI|VIII)", k):
            # „KLASY IV–VI" i „KLASY IV-VI" to ten sam etap; bez ujednolicenia
            # myślnika UNIQUE w tabeli `wymaganie` zapisuje go dwa razy
            # i mapa braków dzieli zadania między dwa byty widmo.
            etap = re.sub(r"^(?:KLASY|Klasy)\s+", "", k)
            etap = re.sub(r"\s+[iI]\s+", "-", etap).replace(" ", "")
            for myslnik in "–—−":
                etap = etap.replace(myslnik, "-")
            continue
        if dial.sciezka_szczegolowa == "jawna":
            for m in RE_PUNKT_JAWNY.finditer(k):
                out.append({"sciezka": m.group(1), "etap": etap,
                            "tresc": " ".join(m.group(2).split())[:400]})
            continue
        dzial = None
        for m in re.finditer(r"(?:%s)|(?:%s)" % (RE_DZIAL.pattern, RE_PUNKT.pattern), k):
            if m.group(1):
                dzial = m.group(1)
            elif dzial and m.group(3):
                out.append({"sciezka": "%s.%s" % (dzial, m.group(3)), "etap": etap,
                            "tresc": " ".join(m.group(4).split())[:400]})
    return out


# =============================================================================
# ZESZYT ZADAŃ — treść zadania i prostokąty rysunków
# =============================================================================

def czytaj_arkusz(path: str, silnik: str = "pdfplumber") -> dict:
    """Treść zadań + zasoby graficzne, per numer zadania."""
    out: Dict[str, dict] = {}
    if not os.path.exists(path):
        return out
    with open_pdf(path, engine=silnik) as doc:
        for page in doc:
            txt = reconstruct.page_text(page, pomin_przypisy=True)
            for m in RE_ZADANIE.finditer(txt):
                nr = m.group(1)
                nast = RE_ZADANIE.search(txt, m.end())
                tresc = txt[m.end():nast.start() if nast else len(txt)]
                out.setdefault(nr, {"tresc": " ".join(tresc.split())[:1500],
                                    "strona": page.number,
                                    "zasoby": []})
                # zadanie odwołujące się do grafiki — zmierzone 38% w E8
                if re.search(r"\b(diagram\w*|rysunk\w+|rysunek|wykres\w*|siatc\w+"
                             r"|osi liczbowej)\b", tresc, re.I):
                    out[nr]["zasoby"].append({
                        "rodzaj": "diagram",
                        "strona": page.number,
                        # UPROSZCZENIE: bbox to cała strona, nie wycinek wokół
                        # rysunku — wykrywanie regionu grafiki to osobna robota.
                        "bbox": [0, 0, page.width, page.height],
                    })
    return out


def _main() -> int:
    """Podgląd jednego klucza — do ręcznego sprawdzenia dialektu."""
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plik")
    ap.add_argument("--zadanie", help="pokaż szczegóły tego zadania")
    args = ap.parse_args()
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")

    k = czytaj_klucz(args.plik)
    print("dialekt : %s" % SLOWNIK[k.dialekt].etykieta)
    print("reżimy  : %s" % ", ".join(r["kod"] for r in k.rezimy))
    print("termin  : %s" % (k.termin or "—"))
    print("formy   : %s" % ", ".join(
        "%s-%s%s" % (f["kod"], f["wariant"],
                     "/" + "".join(w for w in f["wersje"] if w) if f["wersje"][0] else "")
        for f in k.formy))
    print("zadania : %d (%d pkt)" % (len(k.zadania), sum(z.punkty for z in k.zadania)))
    print("reguły  : %d" % len(k.reguly))
    for o in k.ostrzezenia:
        print("UWAGA   : %s" % o)
    for z in k.zadania:
        if args.zadanie and z.numer != args.zadanie:
            continue
        print("\nZadanie %s (0–%d) · %s · str. %s" % (z.numer, z.punkty, z.typ, z.strona))
        for o in z.ogolne:
            print("  ogólne: %s. %s" % (o["sciezka"], o["tresc"][:70]))
        for s in z.szczegolowe:
            print("  szczeg: %-10s %-8s %s" % (s["etap"] or "—", s["sciezka"],
                                               s["tresc"][:60]))
        for w, poz in z.odpowiedzi.items():
            print("  odp %-4s %s" % (w or "—",
                                     "; ".join("%s%s" % (p + ": " if p else "", v)
                                               for p, v in poz)[:80]))
        for kr in z.kryteria:
            print("  %d pkt %s" % (kr["punkty"], kr["etykieta"] or ""))
            for w in kr["warunki"]:
                print("    • %s" % w["opis"][:84])
                for zap in w["zapisy"][:3]:
                    print("        ≡ %s" % zap[:76])
        for r in z.rozwiazania:
            print("  sposób %-4s %s" % (r["sposob"] or "—", r["tresc"][:70]))
        for u in z.uwagi:
            print("  uwaga: %s" % u[:80])
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
