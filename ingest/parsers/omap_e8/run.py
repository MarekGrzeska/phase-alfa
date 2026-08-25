#!/usr/bin/env python3
"""Ingest całego zakresu — 75 kluczy matematyki E8 do jednej bazy, z raportem.

`tests/test_corpus_load.py` sprawdza model na jednym kluczu. Ten skrypt sprawdza PARSER
na wszystkim, co jest w mirrorze: ładuje każdy klucz do tej samej bazy
z włączonymi więzami i mierzy pokrycie — ile zadań, ile z wymaganiami
podstawy, ile z odpowiedzią, ile z kryteriami. Liczby są tu ważniejsze niż
zielone „OK": klucz, z którego wyszło 12 zadań zamiast 21, nie wywala
żadnego więzu, tylko po cichu wnosi do korpusu dziurę.

    task ingest                              # 75 kluczy E8, ~2 min
    task ingest -- --limit 8                 # szybki przebieg
    task ingest -- --kod MMAP,EMAP           # matematyka maturalna
    task ingest -- --szczegoly               # wiersz na każdy klucz
    task ingest -- --wyczysc                 # wyczyść korpus przed ładowaniem

Kod wyjścia 1, gdy którykolwiek klucz nie przeszedł progów pokrycia — to jest
test regresji parsera, nie tylko raport.

Baza jest PostgreSQL wskazany przez `.env` (patrz `schema/migrate.py`), a nie
plik SQLite jak w sondzie. Konsekwencja praktyczna: baza jest TRWAŁA. Drugi
przebieg dokłada się do pierwszego, chyba że podasz `--wyczysc`.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import os
import sys
import time
import warnings
from pathlib import Path

import psycopg

from parsers.omap_e8 import loader
from parsers.omap_e8 import parser as K
from schema.migrate import polaczenie
from sciezki import KORZEN_REPO, korzen_mirrora, spis_urls

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

# Korzeń mirrora i spis — reguła stoi w `sciezki.py`, wspólna dla mirrora,
# runnera i testów. Wcześniej każdy z nich liczył ją u siebie, z własną liczbą
# wywołań `dirname` dobraną do swojej głębokości w drzewie.
ROOT = str(korzen_mirrora())
URLS = str(spis_urls())

# Progi pokrycia. Nie są ambicją, tylko linią, poniżej której wynik znaczy
# „parser się rozjechał", a nie „klucz jest ubogi". Zmierzone na korpusie:
# najkrótszy klucz matematyki E8 (OMAP-800) ma 15 zadań, najdłuższy 21;
# wymagania podstawy niesie 100% kluczy, więc brak choćby jednego jest
# sygnałem, że tabela nie została sparowana z zadaniem.
PROG_WYMAGANIA = 0.95        # udział zadań z wymaganiem podstawy
PROG_ODPOWIEDZI = 0.95       # udział zadań zamkniętych z odpowiedzią wzorcową
PROG_KRYTERIA = 0.90         # udział zadań otwartych z kryteriami
MIN_ZADAN = 10


def wiersze(kody, segmenty, typ="zasady_oceniania"):
    with open(URLS, encoding="utf-8") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            if r["typ"] != typ:
                continue
            if kody and r["kod"] not in kody:
                continue
            if segmenty and r["segment"] not in segmenty:
                continue
            r["sciezka_lokalna"] = r["sciezka_lokalna"].replace("\\", "/")
            yield r


def meta_z_wiersza(r: dict) -> dict:
    return {
        "segment": r["segment"],
        "rocznik": r["rocznik"],
        "kod": r["kod"],
        "warianty": r["warianty"],
        "sesja_data": (r["sesja"] + "-01") if r.get("sesja") else None,
        "typ": r["typ"],
        "zrodlo_typu": r["zrodlo_typu"],
        "url": r["url"],
        "sciezka": r["sciezka_lokalna"],
        "przedmiot": przedmiot(r["kod"]),
    }


def przedmiot(kod: str) -> str:
    """Przedmiot z kodu arkusza — trzecia i czwarta litera to jego skrót."""
    return {"MA": "matematyka", "PO": "jezyk polski", "JA": "jezyk angielski",
            "MB": "jezyk bialoruski"}.get(kod[1:3], kod)


def arkusze_dla(r: dict, wersje, spis) -> dict:
    """Zeszyty zadań tej samej formy — po jednym na wersję.

    Szukamy ich w `urls.tsv`, nie po nazwie pliku: konwencja nazw zmieniała się
    trzy razy (`Arkusz_OMAP-100-1904.pdf` → `OMAP-100-X-2505-zeszyt-zadan.pdf`),
    a spis ma to już rozłożone na kolumny `kod / warianty / sesja / typ`.
    Brak pliku nie jest błędem — mirror bywa filtrowany, a wersja zadania
    powstaje i bez treści; klucz mówi, ILE jest wersji, a treść mieszka
    w zeszycie.
    """
    wlasny = (r["warianty"] or "").split(",")[0]
    znalezione = {}
    for a in spis:
        if a["kod"] != r["kod"] or a["sesja"] != r["sesja"]:
            continue
        czesci = (a["warianty"] or "").split(",")
        if czesci[0] != wlasny:
            continue
        litera = czesci[1] if len(czesci) > 1 and len(czesci[1]) == 1 else None
        if os.path.exists(os.path.join(ROOT, a["sciezka_lokalna"])):
            znalezione[litera] = {"sciezka": a["sciezka_lokalna"], "url": a["url"]}

    # Wersje w kluczu i litery w nazwach plików nie zawsze się pokrywają:
    # w 2025 r. zeszyt wariantu 400 nazywa się „…-400-X-2505…", choć klucz
    # deklaruje dla tej formy jedną wersję bez litery. Gdy zeszyt jest jeden,
    # należy do tej jedynej wersji — cokolwiek stoi w jego nazwie.
    out = {}
    for w in wersje:
        if w in znalezione:
            out[w] = znalezione[w]
        elif len(znalezione) == 1 and len(wersje) == 1:
            out[w] = next(iter(znalezione.values()))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kod", default="OMAP", help="kody arkuszy po przecinku (domyślnie OMAP)")
    ap.add_argument("--segment", default="", help="segmenty po przecinku (domyślnie wszystkie)")
    ap.add_argument("--wyczysc", action="store_true",
                    help="opróżnij tabele korpusu przed ładowaniem (baza jest trwała)")
    ap.add_argument("--limit", type=int, default=None, help="ile kluczy przetworzyć")
    ap.add_argument("--silnik", default="pdfplumber", choices=["pdfplumber", "pymupdf"])
    ap.add_argument("--z-arkuszami", action="store_true",
                    help="doczytaj zeszyty zadań — treść zadań i zasoby "
                         "(8× wolniej: 15 min zamiast 2, bo arkusze są pełne grafiki)")
    ap.add_argument("--szczegoly", action="store_true", help="wiersz na każdy klucz")
    ap.add_argument("--raport", default=None,
                    help="gdzie zapisać raport (domyślnie data/reports/ingest-RRRR-MM-DD.txt)")
    args = ap.parse_args()

    # Zawężone i dopiero tutaj: `filterwarnings("ignore")` w ciele modułu gasiło
    # wszystko w całym procesie — także `ResourceWarning` o niezamkniętych
    # plikach i połączeniach — każdemu, kto ten moduł zaimportuje.
    for modul in ("pdfplumber", "pdfminer", "pypdf"):
        warnings.filterwarnings("ignore", category=UserWarning, module=modul)

    kody = {k.strip() for k in args.kod.split(",") if k.strip()}
    segmenty = {s.strip() for s in args.segment.split(",") if s.strip()}

    if not os.path.exists(URLS):
        print(f"brak {URLS}")
        print("Ustaw MIRROR_ROOT w .env na katalog ze spisem, albo pobierz mirror:")
        print("  task mirror -- --filtr matematyka")
        return 2

    zadania_do_zrobienia = list(wiersze(kody, segmenty))
    if args.limit:
        zadania_do_zrobienia = zadania_do_zrobienia[:args.limit]
    if not zadania_do_zrobienia:
        print("nic nie pasuje do filtra kod=%s segment=%s" % (args.kod, args.segment))
        return 2

    spis_arkuszy = list(wiersze(kody, segmenty, typ="arkusz")) if args.z_arkuszami else []

    # autocommit=True, żeby `con.transaction()` w ładowarce zakładał PRAWDZIWĄ
    # transakcję na każdy klucz, a nie punkt przywracania wewnątrz jednej
    # wielkiej — inaczej błąd ostatniego klucza cofa cały przebieg.
    con = psycopg.connect(polaczenie(), autocommit=True)
    if args.wyczysc:
        with con.cursor() as cur:
            cur.execute("TRUNCATE %s RESTART IDENTITY CASCADE"
                        % ", ".join(loader.TABELE))
        print("korpus wyczyszczony")
    lad = loader.Ladowarka(con)

    print("kluczy do przetworzenia: %d" % len(zadania_do_zrobienia))
    print("%-34s %-10s %5s %5s %5s %5s %5s  %s"
          % ("plik", "dialekt", "zad", "pkt", "wym%", "odp%", "kryt%", "uwagi"))
    print("─" * 118)

    t0 = time.perf_counter()
    wyniki, pominiete, bledy = [], [], []
    for r in zadania_do_zrobienia:
        p = os.path.join(ROOT, r["sciezka_lokalna"])
        if not os.path.exists(p):
            pominiete.append(r["plik"])
            continue
        try:
            k = K.czytaj_klucz(p, silnik=args.silnik)
            arkusze = {}
            if args.z_arkuszami:
                wlasny = (r["warianty"] or "").split(",")[0]
                wersje = sorted({w for f in k.formy if f["wariant"] == wlasny
                                 for w in f["wersje"]}, key=lambda w: (w is None, w))
                for w, dane in arkusze_dla(r, wersje or [None], spis_arkuszy).items():
                    dane["zadania"] = K.czytaj_arkusz(os.path.join(ROOT, dane["sciezka"]),
                                                      silnik=args.silnik)
                    arkusze[w] = dane
            stat = lad.zaladuj(k, meta_z_wiersza(r), arkusze)
        except Exception as e:
            bledy.append((r["plik"], "%s: %s" % (type(e).__name__, e)))
            print("%-34s BŁĄD %s: %s" % (r["plik"][:34], type(e).__name__, e))
            continue

        w = _ocena(k, stat, r)
        wyniki.append(w)
        if args.szczegoly or w["uwagi"]:
            print("%-34s %-10s %5d %5d %5.0f %5.0f %5.0f  %s"
                  % (r["plik"][:34], k.dialekt, w["zadan"], w["punkty"],
                     100 * w["wym"], 100 * w["odp"], 100 * w["kryt"],
                     "; ".join(w["uwagi"])[:34]))
    czas = time.perf_counter() - t0

    try:
        _zapisz_raport(args.raport, con, wyniki, pominiete, bledy, czas, lad)
    finally:
        # W `finally`, bo raport potrafi się wywalić na zapytaniu — a wtedy
        # połączenie zostawało otwarte i nikt się o tym nie dowiadywał,
        # bo `ResourceWarning` było wyciszone.
        con.close()
    return 1 if bledy or any(w["blad"] for w in wyniki) else 0


def _zapisz_raport(sciezka, con, wyniki, pominiete, bledy, czas, lad) -> None:
    """Ten sam raport na ekran i do pliku — plan G1.2.2 każe go porównać z sondą.

    Porównanie „z pamięci" nie jest porównaniem: raport ma zostać na dysku,
    żeby dało się do niego wrócić po tygodniu i zobaczyć, co się zmieniło.
    """
    sciezka = sciezka or (KORZEN_REPO / "data" / "reports"
                          / ("ingest-%s.txt" % time.strftime("%Y-%m-%d")))
    sciezka = Path(sciezka)
    sciezka.parent.mkdir(parents=True, exist_ok=True)
    with (open(sciezka, "w", encoding="utf-8") as fh,
          contextlib.redirect_stdout(_Tee(sys.stdout, fh))):
        _raport(con, wyniki, pominiete, bledy, czas, lad)
    print("\nRaport zapisany: %s" % sciezka)


class _Tee:
    """Pisze naraz na ekran i do pliku — raport ma być w obu miejscach."""

    def __init__(self, *strumienie):
        self._strumienie = strumienie

    def write(self, tekst: str) -> int:
        for s in self._strumienie:
            s.write(tekst)
        return len(tekst)

    def flush(self) -> None:
        for s in self._strumienie:
            s.flush()


def _ocena(k, stat: dict, r: dict) -> dict:
    """Pokrycie jednego klucza plus lista tego, co poniżej progu."""
    zadan = len(k.zadania)
    zamkniete = [z for z in k.zadania if z.typ == "zamkniete"]
    otwarte = [z for z in k.zadania if z.typ != "zamkniete"]
    wym = sum(1 for z in k.zadania if z.ogolne or z.szczegolowe) / max(zadan, 1)
    odp = (sum(1 for z in zamkniete if z.odpowiedzi) / len(zamkniete)) if zamkniete else 1.0
    kryt = (sum(1 for z in otwarte if z.kryteria) / len(otwarte)) if otwarte else 1.0

    uwagi = []
    if zadan < MIN_ZADAN:
        uwagi.append("tylko %d zadań" % zadan)
    if wym < PROG_WYMAGANIA:
        uwagi.append("wymagania %.0f%%" % (100 * wym))
    if odp < PROG_ODPOWIEDZI:
        uwagi.append("odpowiedzi %.0f%%" % (100 * odp))
    if kryt < PROG_KRYTERIA:
        uwagi.append("kryteria %.0f%%" % (100 * kryt))
    # Numeracja zadań musi być ciągła: dziura znaczy, że nagłówek nie trafił
    # w regex, a nie że CKE pominęła zadanie. Liczy się numer główny — matura
    # dzieli zadanie na podpunkty („33.1", „33.2") i wtedy samo „33" nie
    # istnieje, co przy naiwnym porównaniu wygląda jak brak zadania.
    numery = sorted({int(z.numer.split(".")[0]) for z in k.zadania})
    if numery and numery != list(range(1, numery[-1] + 1)):
        brakuje = [n for n in range(1, numery[-1] + 1) if n not in numery]
        uwagi.append("brak zadań: %s" % ",".join(str(n) for n in brakuje[:8]))

    return {"plik": r["plik"], "rocznik": r["rocznik"], "wariant": r["warianty"],
            "dialekt": k.dialekt, "zadan": zadan, "punkty": sum(z.punkty for z in k.zadania),
            "wym": wym, "odp": odp, "kryt": kryt, "stat": stat,
            "reguly": len(k.reguly), "rezimy": [x["kod"] for x in k.rezimy],
            "uwagi": uwagi, "blad": bool(uwagi)}


def _blizniakow(blizniaki: dict, warianty: str) -> int:
    """Ile bliźniaków ma klucz obsługujący te warianty.

    Kolumna `warianty` ze spisu bywa listą (`100,200,400,500,660,K00`), a słownik
    jest kluczowany pojedynczym `exam_form.variant`. Odpytywanie go całą listą
    dawało zawsze zero — i to dokładnie przy kluczach wielowariantowych, czyli
    tych, dla których powstał model N:M.
    """
    return sum(blizniaki.get(w.strip(), 0)
               for w in (warianty or "").split(",") if w.strip())


def _raport(con, wyniki, pominiete, bledy, czas, lad) -> None:
    print("\n" + "─" * 74)
    print("CO WESZŁO DO BAZY")
    print("─" * 74)
    for tab, n in loader.licz(con).items():
        print("  %-26s %6d" % (tab, n))

    print("\n" + "─" * 74)
    print("POKRYCIE PER ROCZNIK")
    print("─" * 74)
    print("  %-8s %-10s %6s %6s %6s %6s %6s %6s"
          % ("rocznik", "dialekt", "kluczy", "zadań", "wym%", "odp%", "kryt%", "reguł"))
    for rocznik in sorted({w["rocznik"] for w in wyniki}):
        grupa = [w for w in wyniki if w["rocznik"] == rocznik]
        n = len(grupa)
        print("  %-8s %-10s %6d %6d %6.0f %6.0f %6.0f %6d"
              % (rocznik, grupa[0]["dialekt"], n, sum(g["zadan"] for g in grupa),
                 100 * sum(g["wym"] for g in grupa) / n,
                 100 * sum(g["odp"] for g in grupa) / n,
                 100 * sum(g["kryt"] for g in grupa) / n,
                 sum(g["reguly"] for g in grupa)))

    print("\n" + "─" * 74)
    print("WARIANTY DOSTOSOWANE — 700 i 800 mają INNE zadania na to samo wymaganie")
    print("─" * 74)
    # Bliźniak = zadanie istniejące w dwóch wersjach tej samej formy. Liczymy
    # je per wariant, bo to on rozstrzyga, czy CKE robiła w danym roku dwa
    # zeszyty zadań: wariant 100 ma bliźniaki od 2020 r., a 700 i 800 nie mają
    # ich nigdy — mają za to WŁASNE, łatwiejsze zadania na to samo wymaganie.
    # PostgreSQL nie pozwala grupować po samym `t.id` i wybierać `f.variant`
    # ani odwoływać się w HAVING do aliasu z SELECT — SQLite w sondzie na oba
    # pozwalał. Stąd pełna lista kolumn w GROUP BY i powtórzony count().
    blizniaki = dict(con.execute("""
        SELECT variant, count(*) FROM (
            SELECT f.variant AS variant, t.id AS task_id
            FROM task t
            JOIN task_version tv ON tv.task_id = t.id
            JOIN exam_form f ON f.id = tv.exam_form_id
            GROUP BY f.variant, t.id
            HAVING count(*) > 1) s
        GROUP BY variant""").fetchall())
    print("  %-8s %6s %8s %8s %10s %9s"
          % ("wariant", "kluczy", "zadań", "pkt śr.", "bliźniaków", "zadań/klucz"))
    for wariant in sorted({w["wariant"] for w in wyniki}):
        grupa = [w for w in wyniki if w["wariant"] == wariant]
        zadan = sum(g["zadan"] for g in grupa)
        print("  %-8s %6d %8d %8.1f %10d %9.1f"
              % (wariant, len(grupa), zadan,
                 sum(g["punkty"] for g in grupa) / len(grupa),
                 _blizniakow(blizniaki, wariant), zadan / len(grupa)))

    print("\n" + "─" * 74)
    print("MAPA BRAKÓW — najczęściej sprawdzane punkty podstawy programowej")
    print("─" * 74)
    for rezim, etap, sciezka, zadan, punktow in con.execute("""
            SELECT rr.code, coalesce(r.stage,'—'), r.path,
                   count(DISTINCT t.id), sum(t.max_points)
            FROM requirement r
            JOIN requirement_regime rr ON rr.id = r.regime_id
            JOIN task_requirement tr ON tr.requirement_id = r.id
            JOIN task t ON t.id = tr.task_id
            WHERE r.kind = 'specific'
            GROUP BY r.id, rr.code, r.stage, r.path
            ORDER BY count(DISTINCT t.id) DESC LIMIT 10"""):
        print("  %-14s %-10s %-9s zadań=%-4d punktów=%s"
              % (rezim, etap, sciezka, zadan, punktow))

    print("\n" + "─" * 74)
    print("FORMY OBSŁUGIWANE PRZEZ WIĘCEJ NIŻ JEDEN KLUCZ (relacja N:M w praktyce)")
    print("─" * 74)
    wiele = con.execute("""
        SELECT f.code, f.variant, coalesce(f.version,'—'), f.session,
               count(DISTINCT fd.document_id) AS ile
        FROM exam_form f
        JOIN exam_form_document fd ON fd.exam_form_id = f.id
        WHERE fd.role = 'marking_scheme'
        GROUP BY f.id, f.code, f.variant, f.version, f.session
        HAVING count(DISTINCT fd.document_id) > 1
        ORDER BY 5 DESC, f.session LIMIT 8""").fetchall()
    for kod, wariant, wersja, sesja, ile in wiele:
        print("  %s-%s wersja %-3s %s — kluczy: %d" % (kod, wariant, wersja, sesja, ile))
    if not wiele:
        print("  (brak — każda forma ma dokładnie jeden klucz)")

    print("\n" + "─" * 74)
    print("SPÓJNOŚĆ — pytania, na które więzy schematu nie odpowiadają")
    print("─" * 74)
    # Te trzy zapytania łapią to, czego CHECK-i złapać nie mogą, bo dotyczą
    # relacji między tabelami. Wynik niezerowy nie zawsze znaczy błąd parsera:
    # pierwszy z nich wskazuje literówkę w samym kluczu CKE.
    for opis, sql in (
        ("próg punktowy wyższy niż pula zadania",
         """SELECT count(*) FROM criterion c JOIN task t ON t.id = c.task_id
            WHERE c.points > t.max_points"""),
        ("zadania bez progu 0 pkt",
         """SELECT count(*) FROM task t WHERE NOT EXISTS
            (SELECT 1 FROM criterion c WHERE c.task_id = t.id AND c.points = 0)"""),
        ("zadania bez progu za komplet punktów",
         """SELECT count(*) FROM task t WHERE NOT EXISTS
            (SELECT 1 FROM criterion c WHERE c.task_id = t.id
             AND c.points = t.max_points)"""),
        ("kryteria bez ani jednego warunku",
         """SELECT count(*) FROM criterion c WHERE NOT EXISTS
            (SELECT 1 FROM criterion_condition cc WHERE cc.criterion_id = c.id)"""),
        ("wersje zadania bez odpowiedzi i bez treści",
         """SELECT count(*) FROM task_version tv
            JOIN task t ON t.id = tv.task_id
            WHERE t.kind = 'closed' AND tv.content IS NULL AND NOT EXISTS
            (SELECT 1 FROM model_answer m WHERE m.task_version_id = tv.id)"""),
    ):
        (n,) = con.execute(sql).fetchone()
        print("  %-44s %5d" % (opis, n))
    for sciezka, numer, pmax, pkt in con.execute(
            """SELECT d.path, t.number, t.max_points, c.points
               FROM criterion c JOIN task t ON t.id = c.task_id
               JOIN document d ON d.id = t.marking_scheme_id
               WHERE c.points > t.max_points LIMIT 5"""):
        print("    ↳ %s zad. %s: pula 0–%d, a próg za %d pkt"
              % (os.path.basename(sciezka), numer, pmax, pkt))

    print("\n" + "─" * 74)
    print("PODSUMOWANIE")
    print("─" * 74)
    n = len(wyniki)
    if n:
        print("  kluczy sparsowanych : %d w %.0f s (%.1f s/klucz)" % (n, czas, czas / n))
        print("  zadań               : %d (%d punktów)"
              % (sum(w["zadan"] for w in wyniki), sum(w["punkty"] for w in wyniki)))
        print("  pokrycie wymagań    : %.1f%%" % (100 * sum(w["wym"] for w in wyniki) / n))
        print("  pokrycie odpowiedzi : %.1f%%" % (100 * sum(w["odp"] for w in wyniki) / n))
        print("  pokrycie kryteriów  : %.1f%%" % (100 * sum(w["kryt"] for w in wyniki) / n))
    if lad.kolizje_form:
        print("  form w dwóch kluczach: %d" % len(lad.kolizje_form))
    # Ta sama ścieżka podstawy z inną treścią niż zapisana w bazie. Do korpusu
    # wchodzi pierwsza — reszta ginęłaby bez śladu, gdyby nie ta linia.
    if lad.kolizje_wymagan:
        print("  wymagań o rozjechanej treści: %d (do bazy weszła pierwsza)"
              % len(lad.kolizje_wymagan))
        # Klucz sortowania przez `str`, bo `etap` bywa None (roczniki bez podziału
        # na klasy) — gołe `sorted` porównałoby wtedy None ze stringiem i wywaliło
        # cały raport w miejscu, w którym raport miał ostrzegać.
        for (rodzaj, etap, sciezka) in sorted(lad.kolizje_wymagan,
                                              key=lambda k: (k[0], k[1] or "", k[2]))[:5]:
            print("    ↳ %s %s %s — wersji treści: %d"
                  % (rodzaj, etap or "—", sciezka,
                     1 + len(lad.kolizje_wymagan[(rodzaj, etap, sciezka)])))
    if lad.kolizje_rezimow:
        print("  reżimów o rozjechanej nazwie: %d" % len(lad.kolizje_rezimow))
    if pominiete:
        print("  brak pliku w mirrorze: %d (%s)"
              % (len(pominiete), ", ".join(pominiete[:3])))
    problemy = [w for w in wyniki if w["uwagi"]]
    if problemy:
        print("\n  PONIŻEJ PROGU — %d z %d:" % (len(problemy), n))
        for w in problemy:
            print("    %-34s %s" % (w["plik"][:34], "; ".join(w["uwagi"])))
    else:
        print("\n  wszystkie klucze powyżej progów pokrycia")
    if bledy:
        print("\n  BŁĘDY TWARDE — %d:" % len(bledy))
        for plik, e in bledy:
            print("    %-34s %s" % (plik[:34], e))


if __name__ == "__main__":
    raise SystemExit(main())
