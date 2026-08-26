#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Parser kluczy CKE — słownik nagłówków zamiast jednego regexu."""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from pdf import reconstruct, regions
from pdf.layout import open_pdf

RE_ZADANIE = re.compile(
    r"Zadanie\s+(\d+(?:\.\d+)*)\.\s*\(\s*(?:0\s*[–—−-]\s*(\d+)|(\d+)\s*pkt)\s*\)")

# Drugi człon zjada opcjonalny poziom: bez tego MMAP-P0-100 i MMAP-R0-100 to jedna forma.
RE_FORMA = re.compile(r"\b([A-Z]{4})-((?:[A-Z]\d-)?[A-Z0-9]{3})(?:-(\d{4}))?\b")

RE_WERSJE = re.compile(r"wersj\w*\s+arkusza:?\s+([A-Z])\s+i\s+([A-Z])", re.I)

RE_TERMIN = re.compile(r"Termin\s*egzaminu:\s*(\d{1,2})\s+(\w+)\s+(\d{4})")
MIESIACE = {"stycznia": 1, "lutego": 2, "marca": 3, "kwietnia": 4, "maja": 5,
            "czerwca": 6, "lipca": 7, "sierpnia": 8, "września": 9,
            "października": 10, "listopada": 11, "grudnia": 12}

# Reżim z podpisu tabeli, nie z roku publikacji. Wzorce szczegółowe przed ogólnymi.
REZIMY = (
    (re.compile(r"Wymagania egzaminacyjne\s+(\d{4})(?:\s+i\s+(\d{4}))?"), None),
    (re.compile(r"Podstawa programowa\s*\^?\(?\d*\)?\s*2012"), "pp2012"),
    (re.compile(r"Podstawa programowa\s*\^?\(?\d*\)?\s*2017"), "pp2017"),
    (re.compile(r"Wymagania określone w podstawie programowej"), "pp-akt"),
    (re.compile(r"Podstawa programowa"), "pp-akt"),
)

# Tożsamością reżimu jest akt z przypisu — ten sam akt bywa podpisany różnie.
RE_ODSYLACZ = re.compile(r"\s*\^?\(?(\d{1,2})\)?")
# Treść kończy się przed odsyłaczem następnego przypisu: inaczej nr 1 zjada nr 2.
_MARKER = r"\^?\d{1,2}\s*(?:Rozporządzenie|Załącznik)"
RE_PRZYPIS_TRESC = re.compile(
    r"(?:^|\s)\^?(\d{1,2})\s*((?:Rozporządzenie|Załącznik).{20,600}?)"
    r"(?=\s" + _MARKER + r"|\n|\Z)", re.S)
RE_DZIENNIK = re.compile(r"Dz\.\s*U\.[^)]{0,60}poz\.\s*\d+[^)]{0,20}")

# Rok mówi przypis, nie nagłówek: poz. 996 to szkoła podstawowa, 1019 — liceum.
DZIENNIKI = (
    (re.compile(r"poz\.\s*996"), "pp2024"),
    (re.compile(r"poz\.\s*1019"), "pp2024"),
    (re.compile(r"poz\.\s*356"), "pp2017"),
    (re.compile(r"poz\.\s*977"), "pp2012"),
)


# Trzy postacie progu: nagłówek (E8 otwarte), w linii z opisem (E8 zamknięte,
# matura 2023+) i punktacja na końcu linii (matura do 2022). Rozdzielacze bez
# `\s*`, bo obejmuje nową linię i zjadało pierwszy warunek do pola `etykieta`.
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
    sciezka_szczegolowa: str


_PAGINA_WSPOLNA = (r"Strona\s+\d+\s+z\s+\d+"
                   r"|Zasady oceniania rozwiązań zadań")
PAGINA_E8 = re.compile(
    r"^\s*(?:" + _PAGINA_WSPOLNA +
    r"|Egzamin ósmoklasisty z .{3,40}?[-–—] termin .{3,30}?\d{4} r\.)\s*$", re.M)
PAGINA_MATURA = re.compile(
    r"^\s*(?:" + _PAGINA_WSPOLNA +
    r"|Egzamin maturalny z .{3,60}?[-–—] termin .{3,30}?\d{4} r\.)\s*$", re.M)

SLOWNIK: Dict[str, Dialekt] = {

    # Rocznik 2019: tabela wymagań ma cztery kolumny, bo klucz mapuje zadanie na dwie podstawy.
    "e8-2019": Dialekt(
        kod="e8-2019",
        etykieta="E8 · rocznik 2019 (dwie podstawy, separator „lub”)",
        egzamin="e8",
        progi=((RE_PROG_NAGLOWEK, False), (RE_PROG_LINIA, True)),
        alternatywa=re.compile(r"\n\s*(?:LUB|lub)\s*,?\s*\n"),
        zapis=re.compile(r"\n\s*(?:albo)\s*,?\s*\n|\s{3,}(?:albo)\s{3,}"),
        odpowiedzi=("solo",),
        rozwiazania=re.compile(r"Przykładowe rozwiązani\w*(?:[^\n]*)"),
        sposob=re.compile(r"^\s*(I{1,3}V?|VI{0,3})\s+sposób", re.M),
        # `Uwag[ai]`, nie `Uwagi?`: to drugie obcina się do „Uwag" i nie łapie „Uwaga",
        # a wtedy treść sekcji wchodzi w całości do kryterium za 0 pkt.
        uwagi_zadania=re.compile(r"\n\s*Uwag[ai][.:]?\s*\n"),
        reguly_naglowek=re.compile(r"^\s*Uwagi ogólne:?\s*$", re.M),
        reguly_punkt=re.compile(r"•\s*(.{20,600}?)(?=\n\s*•|\n\s*\n)", re.S),
        koniec_zadan=re.compile(r"\n\s*(?:Ogólne zasady oceniania|Ocena prac)"),
        pagina=PAGINA_E8,
        sciezka_szczegolowa="dzial-punkt",
    ),

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

    # Matura: aneks dla osób z dyskalkulią powtarza nagłówki „Zadanie 14." bez puli punktów —
    # bez markera końca dokleja się do ostatniego zadania i łamie UNIQUE (task, points).
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

    # Do 2022 r. punktacja progu stoi na KOŃCU linii, więc bez osobnego dialektu zadania
    # otwarte wchodzą do korpusu bez kryteriów, po cichu.
    "matura-2015": Dialekt(
        kod="matura-2015",
        etykieta="Matura · dokument do 2022 r. (progi „Zdający otrzymuje … N pkt”)",
        egzamin="matura",
        # Trzeci wzorzec to punktacja etapowa zadań za 5–7 punktów. Etapy powtarzają tę
        # samą punktację, a UNIQUE (task, points) bierze tylko pierwszy — nie ma pojęcia „etap".
        progi=((RE_PROG_ZDAJACY, False), (RE_PROG_NAGLOWEK, True),
               (RE_PROG_LINIA, True)),
        alternatywa=re.compile(r"\n\s*ALBO\s*,?\s*\n"),
        zapis=re.compile(r"\n\s*(?:albo|lub)\s*,?\s*\n|\s{3,}(?:albo|lub)\s{3,}"),
        odpowiedzi=("wersje", "ab", "solo"),
        rozwiazania=re.compile(r"Przykładow\w+ (?:pełn\w+ )?rozwiązani\w*(?:[^\n]*)"),
        sposob=re.compile(r"^\s*Sposób\s+(\d+|I{1,3}V?|VI{0,3})\.?", re.M),
        uwagi_zadania=re.compile(r"\n\s*Uwag[ai][.:]?\s*\n"),
        # Bez nagłówka „Uwagi ogólne" — wprowadza je tytuł sekcji zadań otwartych.
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
    """Który układ dokumentu — mierzone na tekście, nie zgadywane z nazwy."""
    if "Egzamin maturalny" in tekst[:4000] or re.search(r"^[EM]M[A-Z]{2}-", nazwa):
        # Wielokropek przed punktacją jest w 6 kluczach do 2022 r. i w żadnym późniejszym.
        if RE_PROG_ZDAJACY.search(tekst):
            return SLOWNIK["matura-2015"]
        return SLOWNIK["matura"]
    # Pagina, a nie separator warunków: rocznik 2019 miesza „LUB" z „lub" (0/8 w 2019, 67/67 dalej).
    if re.search(r"Egzamin ósmoklasisty z .{3,40}?[-–—] termin .{3,30}?\d{4} r\.", tekst):
        return SLOWNIK["e8-2020"]
    return SLOWNIK["e8-2019"]


# Odsyłacz przy literze wersji („wersja Y²") ujawniła dopiero rekonstrukcja potęg.
_PRZYPIS = r"(?:\^\(?[\d,]*\)?)?"
# Litera nie jest wpisana na sztywno: E8 ma X i Y, matura A i B, nagłówek ten sam.
RE_ODP_WERSJE = re.compile(
    r"Rozwiązanie\s*[–—−-]\s*wersja\s*([A-Z])" + _PRZYPIS + r"\s*\n"
    r"\s*Rozwiązanie\s*[–—−-]\s*wersja\s*([A-Z])" + _PRZYPIS + r"\s*\n(.+?)(?:\n\s*\n|\Z)",
    re.S)
RE_ODP_AB = re.compile(
    r"Rozwiązanie\s*\n\s*Wersja\s+([A-Z])" + _PRZYPIS + r"\s*\n"
    r"\s*Wersja\s+([A-Z])" + _PRZYPIS + r"\s*\n(.+?)(?:\n\s*\n|\Z)", re.S)
RE_ODP_SOLO = re.compile(r"^[ \t]*Rozwiązanie[ \t]*$\n(.+?)(?:\n\s*\n|\Z)", re.M | re.S)

# Bez tego oba wiersze sklejają się w „1.1. TAK 1.2. NIE".
RE_PODPUNKT = re.compile(r"^\s*(\d+(?:\.\d+)+)\.?\s+(.+?)\s*$")

WIERSZE_NAGLOWKA = 5

# Dział numeruje się rzymską w podstawie 2017 i ARABSKĄ w 2012; 2019 i 2020 niosą obie.
RE_DZIAL = re.compile(r"([IVX]+|\d+)\.\s+([^:]{3,90}?)\.\s*(?:Uczeń|Zdający):")
RE_PUNKT = re.compile(r"(\d+)\)\s+(.{5,}?)(?=\s+\d+\)|$)")
# Cztery notacje o tym samym miejscu: I.1) i XIII.R1) — formuła 2023; 1.3), G1.6) — 2015.
_SCIEZKA_JAWNA = r"(?:[IVX]+|[GR]?\d+)(?:\.(?:[A-Z]?\d+|R\d+))?"
RE_PUNKT_JAWNY = re.compile(
    r"\b(%s)\)\s+(.{5,}?)(?=\s+%s\)|$)" % (_SCIEZKA_JAWNA, _SCIEZKA_JAWNA))
# Cztery zapisy etapu w JEDNYM pliku (OMAP-100-1904); zgubiony rozdziela punkt podstawy na dwa byty.
RE_ETAP = re.compile(
    r"((?:KLASY|Klasy)\s+[IVX]+(?:\s*[–—-]\s*[IVX]+)?(?:\s+[iI]\s+[IVX]+)?"
    r"|\b(?:IV\s*[–—-]\s*VI|VII\s*[–—-]\s*VIII)\b)")


@dataclass
class Zadanie:
    numer: str
    punkty: int
    kolejnosc: int
    typ: str
    strona: Optional[int] = None
    # Lista, bo klucze 2019 i 2020 mapują zadanie na dwie podstawy naraz.
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


def closed_without_criteria(k: Klucz) -> Optional[bool]:
    """Czy w TYM kluczu zadania zamknięte nie mają sekcji kryteriów — norma czy dziura.

    `True` = norma dokumentu (żadne zadanie zamknięte kryteriów nie ma; tak wygląda
    rocznik 2019, gdzie klucz podaje dla nich samą odpowiedź wzorcową).
    `False` = kryteria tam są, więc zadanie zamknięte bez nich jest dziurą.
    `None` = klucz nie ma zadań zamkniętych, więc pytanie jest bez treści.

    Mierzone z dokumentu, nie wpisane po roczniku: w 2019 r. warianty 800 i Q00
    kryteria dla zadań zamkniętych MAJĄ, choć sześć pozostałych nie ma.
    """
    zamkniete = [z for z in k.zadania if z.typ == "zamkniete"]
    if not zamkniete:
        return None
    return not any(z.kryteria for z in zamkniete)


def czytaj_klucz(path: str, silnik: str = "pdfplumber") -> Klucz:
    """Klucz oceniania → rekordy w kształcie `schema.sql`."""
    strony: List[str] = []
    stopki: List[str] = []                         # przypisy, odcięte od treści
    tabele: List[Tuple[int, float, object]] = []   # (strona, górna krawędź, tabela)
    naglowki: List[Tuple[int, float]] = []         # (strona, y) nagłówków zadań
    with open_pdf(path, engine=silnik) as doc:
        for page in doc:
            strony.append(reconstruct.page_text(page, pomin_przypisy=True))
            naglowki += [(len(strony) - 1, y) for _, y in _heading_positions(page)]
            # To w przypisach stoi numer Dz.U., po którym poznajemy obowiązującą podstawę.
            odciete = reconstruct.przypisy(page.chars)
            if odciete:
                stopki.append(_tekst_stopki(
                    [c for c in page.chars if id(c) in odciete]))
            # Z SIATKI tabeli, nie regexem: w płaskim tekście kolumny sklejają się linia po linii.
            for t in page.tables:
                # Nagłówek kolumn nie zawsze jest w wierszu zerowym — w 2019 r. stoi tam podpis
                # podstawy. Szukanie w samym zerowym gubiło wymagania 21 zadań.
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

    granice = []
    acc = 0
    for s in strony:
        granice.append(acc)
        acc += len(s) + 1

    def strona_offsetu(off: int) -> int:
        """Numer strony DLA CZŁOWIEKA, liczony od 1 — tak samo jak w stopce PDF-a.

        Warstwa pozycyjna indeksuje strony od zera; rekord w bazie ogląda się
        w ekranie korekty obok skanu, więc trzyma numer, a nie indeks.
        """
        lo, hi = 0, len(granice) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if granice[mid] <= off:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1

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
    otwarte_bez = sum(1 for z in k.zadania if z.typ != "zamkniete" and not z.kryteria)
    if otwarte_bez:
        k.ostrzezenia.append("zadań otwartych bez kryteriów: %d z %d"
                             % (otwarte_bez, sum(1 for z in k.zadania
                                                 if z.typ != "zamkniete")))
    if closed_without_criteria(k) is False:
        # Niezgodność WEWNĄTRZ klucza: część zadań zamkniętych ma sekcję kryteriów,
        # a część nie. Brak jej u wszystkich naraz jest normą rocznika 2019
        # i nie zasługuje na ostrzeżenie — brak u połowy znaczy, że parser
        # przegapił sekcję i trzeba na to popatrzeć.
        brak = [z.numer for z in k.zadania if z.typ == "zamkniete" and not z.kryteria]
        if brak:
            k.ostrzezenia.append("zadań zamkniętych bez kryteriów mimo klucza, "
                                 "który je ma: %s" % ", ".join(brak[:8]))
    bez_odpowiedzi = sum(1 for z in k.zadania
                         if z.typ == "zamkniete" and not z.odpowiedzi)
    if bez_odpowiedzi:
        k.ostrzezenia.append("zadań zamkniętych bez odpowiedzi: %d" % bez_odpowiedzi)

    k.reguly = _reguly(tekst, dial)
    return k


# Tabela należy do NAJBLIŻSZEGO nagłówka nad nią. Parowanie kolejnością przesuwa
# resztę, gdy zadanie nie ma tabeli — cicho, bo zadanie dostaje cudze wymaganie.
TOL_TABELI = 6.0     # ramka tabeli bywa tuż nad nagłówkiem, gdy go obejmuje


def _tekst_stopki(znaki) -> str:
    """Przypisy jako tekst — z odstępami odtworzonymi z odległości między glifami."""
    znaki = sorted(znaki, key=lambda c: (round(c.cy), c.x0))
    out, poprzedni = [], None
    for c in znaki:
        if poprzedni is not None and (c.x0 - poprzedni.x1 > 0.25 * c.size
                                      or c.cy - poprzedni.cy > 2):
            out.append(" ")
        out.append(c.c)
        poprzedni = c
    return "".join(out)


def _heading_positions(page) -> List[Tuple[str, float]]:
    """(numer zadania, górna krawędź nagłówka) — w kolejności od góry strony."""
    wiersze: Dict[int, list] = {}
    for c in page.chars:
        wiersze.setdefault(round(c.y0 / reconstruct.LINE_TOL), []).append(c)
    out = []
    for cs in wiersze.values():
        cs.sort(key=lambda c: c.x0)
        tekst = "".join(c.c for c in cs).strip()
        m = RE_ZADANIE.match(tekst) if tekst.startswith("Zadanie") else None
        if m:
            out.append((m.group(1), min(c.y0 for c in cs)))
    return sorted(out, key=lambda p: p[1])


def _task_bands(page) -> Dict[str, Tuple[float, float]]:
    """Pionowy zakres zadania na stronie: od jego nagłówka do następnego.

    Zakres jest wejściem wykrywania regionu graficznego — bez niego kandydatami
    byłyby kształty CAŁEJ strony i rysunek sąsiada wchodziłby do wycinka.
    """
    naglowki = _heading_positions(page)
    out: Dict[str, Tuple[float, float]] = {}
    for i, (numer, gora) in enumerate(naglowki):
        dol = naglowki[i + 1][1] if i + 1 < len(naglowki) else page.height
        out.setdefault(numer, (gora, dol))
    return out


def _sparuj_tabele(naglowki, tabele, ile_zadan: int):
    if len(naglowki) < ile_zadan:
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
    """Reżimy wymagań zadeklarowane w kluczu — bywają dwa naraz."""
    # Przypis rocznika 2019 nie wpada w blok cięty ze strony — szukamy w obu miejscach.
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
    """Formy arkusza z nagłówka — sedno relacji N:M."""
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

    # Nagłówek „Zasady oceniania" znika, gdy zadanie łamie się przez stronę — wtedy czytamy całe ciało.
    i_zas = body.find("Zasady oceniania")
    poczatek = i_zas if i_zas >= 0 else 0
    kryteria_txt = body[poczatek:i_rozw] if (i_rozw is not None and i_rozw > poczatek) \
        else body[poczatek:]
    # Uwagi to reguła TEGO zadania, nie część progu 0 pkt.
    uwagi = []
    m_uw = dial.uwagi_zadania.search(kryteria_txt)
    if m_uw:
        ogon = kryteria_txt[m_uw.end():]
        kryteria_txt = kryteria_txt[:m_uw.start()]
        uwagi = [" ".join(u.split()) for u in re.split(r"\n\s*(?=\d+\.\s)", ogon)
                 if len(u.strip()) > 15]

    kryteria = _kryteria(kryteria_txt, dial)

    # Typ po budowie klucza, nie po punktach: rozstrzyga obecność rozwiązania.
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
    """Odpowiedzi wzorcowe per wersja arkusza."""
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
    """Wiersze pod nagłówkiem dwóch wersji → odpowiedź lewej i prawej kolumny."""
    linie = [l.strip() for l in blok.split("\n") if l.strip()]
    if not linie:
        return
    z_podpunktami = [RE_PODPUNKT.match(l) for l in linie]
    if all(z_podpunktami) and len(linie) >= 2:
        # Wystąpienie ponad liczbę wersji: nie zgadujemy, oddajemy pierwszej i to widać w bazie.
        widziane: dict[str, int] = {}
        for m in z_podpunktami:
            numer, tresc = m.group(1), m.group(2)
            i = widziane.get(numer, 0)
            widziane[numer] = i + 1
            out.setdefault(wersje[i] if i < len(wersje) else wersje[0], []).append(
                (numer, tresc))
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
    """Progi → warunki → zapisy równoważne, czyli trzy poziomy dysjunkcji."""
    if not txt.strip():
        return []
    # Oba układy progu stoją w tym samym pliku. Ogon nagłówka to ETYKIETA progu,
    # ogon linii — pierwszy WARUNEK.
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
            # „albo"/„lub" bywa spójnikiem w prozie; separator odróżnia typografia — stoi
            # samotnie w linii albo jest odsunięty kilkoma spacjami.
            do_ciecia = re.sub(r"\((?:lub|albo)[^)]*\)", "", w)
            czesci = [_oczysc(c) for c in dial.zapis.split(do_ciecia)]
            czesci = [c for c in czesci if c]
            # Granicą jest „np.", które w kluczach CKE wprowadza zapis, a nie zdanie.
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
    return " ".join(s.split()).lstrip("•-– ").strip(" ,;").replace("Zasady oceniania", "").strip()


def rodzaj_reguly(tresc: str) -> str:
    """Rodzaj reguły przekrojowej — po treści zapisu, w języku dokumentu."""
    return ("rachunkowa" if "błęd" in tresc and "rachunkow" in tresc else
            "sam_wynik" if "tylko poprawny końcowy wynik" in tresc
                           or "tylko poprawny wynik" in tresc else
            "sprzeczne_rozwiazania" if "sprzecznych" in tresc else
            "dostosowanie" if "dostosowanych zasad" in tresc
                              or "dyskalkulią" in tresc else
            "kalkulator" if "kalkulator" in tresc else "inna")


def _reguly(tekst: str, dial: Dialekt) -> List[dict]:
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
        rodzaj = rodzaj_reguly(tresc)
        zak = re.search(r"zadani\w+\s+(\d+)[.,]?\s*[–—-]\s*(\d+)", tresc)
        if not zak:
            zak = re.search(r"zadani\w+\s+(\d+)\.(?:,| i)\s.*?(\d+)\.", tresc)
        out.append({"rodzaj": rodzaj, "tresc": tresc,
                    "zadania_od": zak.group(1) if zak else None,
                    "zadania_do": zak.group(2) if zak else None,
                    "kolejnosc": len(out) + 1})
    return out


# ── WYMAGANIA PODSTAWY PROGRAMOWEJ ───────────────────────────────────────────

def parsuj_wymagania(tab, dial: Dialekt,
                     rezimy: Sequence[str] = ()) -> Tuple[List[dict], List[dict]]:
    """Wymagania z tabeli: (ogólne, [szczegółowe])."""
    if tab is None or not tab.rows:
        # Puste listy, nie None: ładowarka iteruje po wyniku bez sprawdzania.
        return [], []
    pary = _kolumny(tab)
    ogolne: List[dict] = []
    szczegolowe = []
    for i_para, (i_og, i_sz) in enumerate(pary):
        # Podpis stoi nad parą kolumn tylko przy pierwszym zadaniu, dalej musi wystarczyć kolejność.
        rezim = _rezim_kolumny(tab, i_og, i_sz)
        if rezim is not None:
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
            if any(re.match(r"(?:Podstawa programowa|Zadanie\s+\d)", c) for c in cells):
                continue
            if i_og < len(cells):
                lewa += " " + cells[i_og]
            if i_sz < len(cells):
                prawa += " \n" + cells[i_sz]
        # Numer wymagania ogólnego SZUKAMY, nie kotwiczymy: w 2019 r. pierwszy wiersz to
        # podpis podstawy i kotwica gubiła wymagania wszystkich 21 zadań.
        m = re.search(r"\b([IVX]+)\.\s*(.+)", " ".join(lewa.split()))
        if m:
            ogolne.append({"sciezka": m.group(1), "tresc": m.group(2).strip()[:400],
                           "rezim": rezim})
        for sz in _szczegolowe(prawa, dial):
            sz["rezim"] = rezim
            szczegolowe.append(sz)
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
                # „Podstawa programowa" bez roku nie mówi która — brak rozpoznania włącza dopasowanie po kolejności.
                return None if kod == "pp-akt" else kod
    return None


def _kolumny(tab) -> List[Tuple[int, int]]:
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
    out = []
    etap = None
    for kawalek in RE_ETAP.split(prawa):
        k = " ".join(kawalek.split())
        if re.match(r"(?:KLASY|Klasy)\b", k) or re.fullmatch(
                r"(?:IV|VII)\s*[–—-]\s*(?:VI|VIII)", k):
            # Bez ujednolicenia myślnika UNIQUE zapisuje ten sam etap dwa razy.
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


# ── ZESZYT ZADAŃ — treść zadania i prostokąty rysunków ────────────────────────

# Zadanie odwołuje się do grafiki. Wzorzec rozstrzyga TAKŻE o rodzaju zasobu,
# bo `asset.kind` czyta przeglądarka korpusu — „diagram" dla każdego rysunku
# był uproszczeniem z czasu, gdy nikt tej kolumny nie oglądał.
GRAPHIC_KINDS = (
    (re.compile(r"\bwykres\w*\b", re.I), "wykres"),
    (re.compile(r"\bdiagram\w*\b", re.I), "diagram"),
    (re.compile(r"\b(?:rysunek|rysunk\w+|siatc\w+|osi liczbowej)\b", re.I), "rysunek"),
)

# Zadanie z trzema osobnymi rysunkami na jednej stronie zdarza się; z dziesięcioma
# nie — to znaczy, że klaster się rozsypał i lepiej oddać ramkę człowiekowi.
MAX_ASSETS_PER_PAGE = 3


def graphic_kind(tresc: str) -> Optional[str]:
    for wzor, rodzaj in GRAPHIC_KINDS:
        if wzor.search(tresc):
            return rodzaj
    return None


def czytaj_arkusz(path: str, silnik: str = "pdfplumber") -> Tuple[dict, int]:
    """Treść zadań + zasoby graficzne per numer zadania, plus liczba stron zeszytu.

    Liczba stron jedzie razem z treścią, bo inaczej trzeba by otworzyć ten sam
    plik drugi raz — a zeszyt to kilkadziesiąt stron pełnych grafiki.
    """
    out: Dict[str, dict] = {}
    if not os.path.exists(path):
        return out, 0
    with open_pdf(path, engine=silnik) as doc:
        stron = len(doc)
        for page in doc:
            txt = reconstruct.page_text(page, pomin_przypisy=True)
            bands = _task_bands(page)
            for m in RE_ZADANIE.finditer(txt):
                nr = m.group(1)
                nast = RE_ZADANIE.search(txt, m.end())
                tresc = txt[m.end():nast.start() if nast else len(txt)]
                # Numer od 1, jak w kluczu i jak w stopce arkusza — indeks
                # z warstwy pozycyjnej pokazywałby stronę wcześniejszą.
                out.setdefault(nr, {"tresc": " ".join(tresc.split())[:1500],
                                    "strona": page.number + 1,
                                    "zasoby": []})
                # Numer zadania trafia się na dwóch stronach — zasoby liczą się
                # raz na stronę, nie raz na trafienie nagłówka.
                strony_zasobow = {z["strona"] for z in out[nr]["zasoby"]}
                rodzaj = graphic_kind(tresc)
                if rodzaj is None or page.number + 1 in strony_zasobow:
                    continue
                band = bands.get(nr)
                frames = regions.detect(page, *band) if band else []
                for bbox in frames[:MAX_ASSETS_PER_PAGE]:
                    out[nr]["zasoby"].append({"rodzaj": rodzaj,
                                              "strona": page.number + 1,
                                              "bbox": [float(v) for v in bbox]})
                if not frames:
                    # Automat nie domknął — zasób zostaje z ramką całej strony
                    # i przejmuje go ręczne dociągnięcie z G2.4.2. To zawór
                    # nr 3 z Planu Implementacji, nie awaria przebiegu.
                    out[nr]["zasoby"].append({
                        "rodzaj": rodzaj,
                        "strona": page.number + 1,
                        "bbox": [0.0, 0.0, float(page.width), float(page.height)],
                    })
    return out, stron


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
