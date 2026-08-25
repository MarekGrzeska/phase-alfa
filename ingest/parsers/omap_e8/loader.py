#!/usr/bin/env python3
"""Ładowanie sparsowanego klucza do PostgreSQL z włączonymi więzami.

Jedno miejsce na zamianę rekordów z `parser.py` na wiersze w tabelach — bo
korzystają z niego dwa wejścia: sprawdzian modelu na jednym kluczu i przebieg
na całym zakresie. Rozdzielenie tego na dwie kopie skończyłoby się
rozjechaniem ich odpowiedzi, a wtedy sprawdzian przestaje cokolwiek sprawdzać.

Ta warstwa jest zarazem **tłumaczem słownika**. `parser.py` mówi językiem
dokumentu — bo czyta polskie klucze CKE i jego nazwy mają się zgadzać z tym,
co widać w PDF-ie. Schemat bazy mówi po angielsku (patrz CLAUDE.md). Przekład
stoi więc tutaj, w jednym miejscu i w postaci słowników, a nie rozsypany po
kodzie parsera. Dzięki temu `parser.py` przeszedł z research/ bez ani jednej
zmiany logiki.

Więzy są tu włączone celowo. `UNIQUE` i `CHECK` mają odrzucać dane, których
model nie przewiduje; przy pierwszym ładowaniu w sondzie `UNIQUE (task_id,
points)` złapał zadanie z dwoma progami „0 pkt" i wskazał realny błąd cięcia
tekstu, a nie kaprys schematu.
"""

from __future__ import annotations

import os
import re

from parsers.omap_e8 import parser as K

# ── słownik: język dokumentu (parser) → język schematu (baza) ────────────────
# Pełny słownik pojęć stoi w CLAUDE.md; tu są tylko wartości, które parser
# faktycznie emituje. Brak klucza w słowniku ma być głośny, dlatego wszędzie
# jest `[...]`, a nie `.get(...)` z cichym domyślnym.

TYP_ZADANIA = {
    "zamkniete": "closed",
    "otwarte_krotkie": "open_short",
    "otwarte_rozszerzone": "open_extended",
    "wypracowanie": "essay",
}

RODZAJ_WYMAGANIA = {
    "ogolne": "general",
    "szczegolowe": "specific",
}

RODZAJ_REGULY = {
    "rachunkowa": "arithmetic",
    "sprzeczne_rozwiazania": "conflicting_solutions",
    "sam_wynik": "result_only",
    "dostosowanie": "accommodation",
    "kalkulator": "calculator",
    "inna": "other",
}

RODZAJ_ZASOBU = {
    "rysunek": "drawing",
    "diagram": "diagram",
    "wykres": "chart",
    "tabela": "table",
    "mapa": "map",
    "nuty": "sheet_music",
}

TYP_DOKUMENTU = {
    "arkusz": "paper",
    "zasady_oceniania": "marking_scheme",
    "karta_odpowiedzi": "answer_sheet",
    "transkrypcja": "transcript",
    "zalacznik": "attachment",
    "aneks": "annex",
}

ZRODLO_TYPU = {
    "sufiks": "suffix",
    "prefiks": "prefix",
    "katalog": "directory",
    "domyslny": "default",
}

ROLA_DOKUMENTU = {
    "arkusz": "paper",
    "klucz": "marking_scheme",
    "karta": "answer_sheet",
    "transkrypcja": "transcript",
    "zalacznik": "attachment",
}


# Wariant arkusza z nazwy pliku — to on mówi, KTÓREJ formy dotyczy treść zadań
# w tym dokumencie. Nagłówek wymienia wszystkie obsługiwane formy (bywa ich
# sześć), ale zeszyt zadań istnieje tylko dla własnego wariantu.
RE_WLASNA_FORMA = re.compile(r"([A-Z]{4})-((?:[A-Z]\d-)?[A-Z0-9]{3})")


class Ladowarka:
    """Wstawia rekordy z `parser.Klucz` do bazy, pilnując wspólnych słowników.

    Reżimy, wymagania i formy są WSPÓLNE dla całego przebiegu, nie dla pliku:
    ta sama forma OMAP-200-2505 bywa zadeklarowana przez dwa różne klucze,
    a ta sama ścieżka podstawy programowej wraca w co drugim zadaniu.

    Get-or-create idzie przez `ON CONFLICT ... DO NOTHING RETURNING id`
    (a gdy nic nie wróci — `SELECT`), a nie przez samą pamięć procesu. Różnica
    jest istotna: pamięć chroni tylko w obrębie jednego przebiegu, więc drugi
    ingest na tej samej bazie zaczynał
    dublować słowniki. Do tego pamięć rozjeżdża się z bazą, gdy transakcja
    jednego klucza zostanie wycofana — a wycofujemy ją zawsze, gdy klucz padnie.
    Słowniki w polach `_rezimy` i spółka zostają wyłącznie jako oszczędność
    zapytań i wolno je w każdej chwili wyczyścić.
    """

    def __init__(self, con):
        self.con = con
        self._rezimy: dict[str, int] = {}
        self._formy: dict[tuple, int] = {}
        # (id, treść zapisana w bazie) — treść trzymamy, żeby dało się zauważyć,
        # że kolejny klucz cytuje to samo wymaganie inaczej.
        self._wymagania: dict[tuple, tuple[int, str]] = {}
        self.kolizje_form: dict[tuple, list] = {}
        # Ta sama ścieżka podstawy z inną treścią niż zapisana. Nie jest to błąd
        # parsera — dokumenty naprawdę cytują wymagania różnie — ale musi być
        # widoczne, bo do bazy wchodzi tylko jedna z tych treści.
        self.kolizje_wymagan: dict[tuple, set] = {}
        self.kolizje_rezimow: dict[str, list] = {}

    def zapomnij_slowniki(self) -> None:
        """Po wycofanej transakcji — identyfikatory z niej już nie istnieją."""
        self._rezimy.clear()
        self._formy.clear()
        self._wymagania.clear()

    # ── słowniki wspólne ────────────────────────────────────────────────────
    def rezim(self, cur, kod: str, nazwa: str = "", sesja: str = "2019-01-01",
              zrodlo: str | None = None) -> int:
        """Reżim wymagań; `zrodlo` to akt prawny z przypisu pod tabelą.

        Tożsamość reżimu niesie Dziennik Ustaw, a nie podpis tabeli — ten sam
        akt bywa podpisany „Wymagania egzaminacyjne 2023" i „…2023 i 2024".
        Kod idzie za dokumentem, żeby nic nie zgadywać, ale `zrodlo` pozwala
        te dwa scalić jednym UPDATE-em, gdy przyjdzie na to czas.
        """
        if kod in self._rezimy:
            return self._rezimy[kod]
        cur.execute(
            """INSERT INTO requirement_regime (code, name, session_from, source)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (code) DO NOTHING
               RETURNING id""",
            (kod, nazwa or kod, sesja, zrodlo),
        )
        wiersz = cur.fetchone()
        if wiersz is None:
            cur.execute("SELECT id, name FROM requirement_regime WHERE code = %s", (kod,))
            (rid, stara) = cur.fetchone()
            nowa = nazwa or kod
            if stara != nowa:
                self.kolizje_rezimow.setdefault(kod, []).append(nowa)
        else:
            (rid,) = wiersz
        self._rezimy[kod] = rid
        return rid

    def wymaganie(self, cur, rezim_id: int, rodzaj: str, etap: str | None,
                  sciezka: str, tresc: str) -> int:
        k = (rezim_id, rodzaj, etap, sciezka)
        if k in self._wymagania:
            # Porównanie MUSI być też tutaj, nie tylko na ścieżce z bazą:
            # pamięć procesu przechwytuje drugie i każde następne wystąpienie
            # tej samej ścieżki, więc licznik rozjazdów oparty wyłącznie na
            # `ON CONFLICT` nie zapaliłby się nigdy w jednym przebiegu.
            wid, zapisana = self._wymagania[k]
            if zapisana != tresc:
                self.kolizje_wymagan.setdefault((rodzaj, etap, sciezka), set()).add(tresc)
            return wid
        # DO NOTHING, nie DO UPDATE: ta sama ścieżka podstawy wraca w kilkudziesięciu
        # kluczach, a jej treść bywa różna (tabela raz łamie się na stronie, raz nie).
        # Nadpisywanie znaczyłoby, że w bazie zostaje treść z klucza, który akurat
        # wszedł ostatni — bez śladu po pozostałych. Pierwsza treść zostaje, każdy
        # rozjazd idzie do raportu.
        cur.execute(
            """INSERT INTO requirement (regime_id, kind, stage, path, content)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (regime_id, kind, stage, path) DO NOTHING
               RETURNING id""",
            (rezim_id, RODZAJ_WYMAGANIA[rodzaj], etap, sciezka, tresc),
        )
        wiersz = cur.fetchone()
        if wiersz is None:
            cur.execute(
                """SELECT id, content FROM requirement
                   WHERE regime_id = %s AND kind = %s AND stage IS NOT DISTINCT FROM %s
                     AND path = %s""",
                (rezim_id, RODZAJ_WYMAGANIA[rodzaj], etap, sciezka),
            )
            (wid, zapisana) = cur.fetchone()
            if zapisana != tresc:
                self.kolizje_wymagan.setdefault((rodzaj, etap, sciezka), set()).add(tresc)
        else:
            (wid,) = wiersz
            zapisana = tresc
        self._wymagania[k] = (wid, zapisana)
        return wid

    def forma(self, cur, rezim_id: int, egzamin: str, przedmiot: str, kod: str,
              wariant: str, wersja: str | None, sesja: str,
              zrodlo: str = "") -> int:
        k = (kod, wariant, wersja, sesja)
        if k in self._formy:
            if zrodlo:
                # Ta sama forma zadeklarowana przez drugi klucz. Nie jest to
                # błąd — OMAP-100-2505 obsługuje formę 200, która ma też własny
                # plik z zasadami — ale trzeba to widzieć w raporcie, bo znaczy
                # dwa komplety kryteriów dla jednego arkusza.
                self.kolizje_form.setdefault(k, []).append(zrodlo)
            return self._formy[k]
        cur.execute(
            """INSERT INTO exam_form
               (regime_id, exam, subject, code, variant, version, session)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (code, variant, version, session) DO NOTHING
               RETURNING id""",
            (rezim_id, egzamin, przedmiot, kod, wariant, wersja, sesja),
        )
        wiersz = cur.fetchone()
        if wiersz is None:
            # Forma zadeklarowana wcześniej — przez inny klucz albo przez
            # poprzedni przebieg. Kolizje między kluczami zbiera gałąź wyżej;
            # tutaj interesuje nas tylko identyfikator.
            cur.execute(
                """SELECT id FROM exam_form
                   WHERE code = %s AND variant = %s
                     AND version IS NOT DISTINCT FROM %s AND session = %s""",
                (kod, wariant, wersja, sesja),
            )
            (fid,) = cur.fetchone()
            if zrodlo:
                self.kolizje_form.setdefault(k, []).append(zrodlo)
        else:
            (fid,) = wiersz
        self._formy[k] = fid
        return fid

    # ── ładowanie jednego klucza ────────────────────────────────────────────
    def zaladuj(self, k, meta: dict, arkusze: dict | None = None) -> dict:
        """`parser.Klucz` + wiersz z urls.tsv → wiersze w tabelach.

        Cały klucz wchodzi w JEDNEJ transakcji. Klucz, który wywalił się
        w połowie, nie może zostawić połowy zadań w bazie — inaczej raport
        pokrycia kłamie, a to on jest tu jedynym sygnałem, że coś jest nie tak.

        `meta` niesie to, czego nie ma w PDF-ie: segment, rocznik strony,
        z której plik pochodzi, URL i ścieżkę lokalną. `arkusze` to wynik
        `parser.czytaj_arkusz()` per wersja — bez niego rekordy `task_version`
        powstają bez treści, co jest poprawne: klucz mówi, ILE jest wersji,
        a treść zadania mieszka w zeszycie zadań.
        """
        try:
            with self.con.transaction(), self.con.cursor() as cur:
                return self._zaladuj(cur, k, meta, arkusze)
        except Exception:
            # Transakcja wycofana → identyfikatory ze słowników wskazują
            # na wiersze, których już nie ma.
            self.zapomnij_slowniki()
            raise

    def _wyczysc_klucz(self, cur, url: str) -> None:
        """Kasuje to, co ten klucz zapisał poprzednim razem.

        Bez tego drugi przebieg pada na `UNIQUE (marking_scheme_id, number)`
        w `task` — a klucz ma się dać załadować ponownie, bo poprawka w parserze
        musi wchodzić bez czyszczenia całego korpusu. Kasujemy PO ZADANIACH,
        nie po dokumencie: `task.marking_scheme_id` celowo nie ma kaskady, żeby
        nie dało się usunąć dokumentu, którego zadania wciąż stoją w bazie.
        Wszystko pod zadaniem (wersje, kryteria, odpowiedzi, zasoby) leci
        kaskadą z `task`.
        """
        cur.execute("SELECT id FROM document WHERE url = %s", (url,))
        wiersz = cur.fetchone()
        if wiersz is None:
            return
        (doc_id,) = wiersz
        cur.execute("DELETE FROM task WHERE marking_scheme_id = %s", (doc_id,))
        cur.execute("DELETE FROM rule WHERE marking_scheme_id = %s", (doc_id,))
        cur.execute("DELETE FROM exam_form_document WHERE document_id = %s", (doc_id,))

    def _zaladuj(self, cur, k, meta: dict, arkusze: dict | None) -> dict:
        sesja = k.termin or meta.get("sesja_data") or "2019-01-01"
        self._wyczysc_klucz(cur, meta["url"])

        rezimy_id = {}
        for r in k.rezimy:
            rezimy_id[r["kod"]] = self.rezim(cur, r["kod"], r["nazwa"], sesja,
                                             r.get("zrodlo"))
        domyslny_rezim = (
            list(rezimy_id.values())
            or [self.rezim(cur, f"{k.egzamin}-nieznany", "reżim nierozpoznany", sesja)]
        )[0]

        cur.execute(
            # Dokument ma naturalny klucz — URL, i to on ma `UNIQUE` w schemacie.
            # Baza jest trwała, więc drugi przebieg trafia na własne wiersze
            # z pierwszego; goły INSERT (bezpieczny w SQLite tworzonym w pamięci)
            # kończyłby się tu `UniqueViolation` na każdym z 75 kluczy.
            """INSERT INTO document
               (segment, year, code, variants, session, kind, kind_source,
                url, path, pages)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (url) DO UPDATE SET path = EXCLUDED.path,
                                               pages = EXCLUDED.pages
               RETURNING id""",
            (meta["segment"], int(meta["rocznik"]), meta["kod"],
             meta.get("warianty"), sesja, "marking_scheme",
             ZRODLO_TYPU[meta.get("zrodlo_typu", "sufiks")], meta["url"],
             meta["sciezka"], k.stron),
        )
        (klucz_doc,) = cur.fetchone()

        # Forma własna pliku: ta, której dotyczą zeszyty zadań i wersje.
        m_wlasna = RE_WLASNA_FORMA.search(os.path.basename(meta["sciezka"]))
        wlasna = (m_wlasna.group(1), m_wlasna.group(2)) if m_wlasna else None

        # Wariant WŁASNY pliku — ten, którego dotyczą zeszyty zadań i wycinki.
        # Kolumna `warianty` bywa listą sześciu form, więc do ścieżki zasobu
        # bierzemy pierwszy człon, a nie całą listę.
        wlasny_wariant = (wlasna[1] if wlasna
                          else (meta.get("warianty") or "100").split(",")[0])

        forma_ids, wersje_wlasne = {}, []
        for f in k.formy:
            for wersja in f["wersje"]:
                fid = self.forma(cur, domyslny_rezim, k.egzamin,
                                 meta.get("przedmiot", "matematyka"),
                                 f["kod"], f["wariant"], wersja, sesja,
                                 zrodlo=os.path.basename(meta["sciezka"]))
                forma_ids[(f["kod"], f["wariant"], wersja)] = fid
                self._spnij_forme(cur, fid, klucz_doc, "klucz")
                if wlasna and (f["kod"], f["wariant"]) == wlasna:
                    wersje_wlasne.append((wersja, fid))

        if not wersje_wlasne:
            # Klucz bez nagłówka „Formy arkusza" (roczniki 2019 i 2020) albo
            # forma własna nieujęta w wykazie — forma i tak musi istnieć,
            # bo bez niej nie ma gdzie powiesić wersji zadania.
            kod = wlasna[0] if wlasna else meta["kod"]
            fid = self.forma(cur, domyslny_rezim, k.egzamin,
                             meta.get("przedmiot", "matematyka"), kod, wlasny_wariant,
                             None, sesja)
            self._spnij_forme(cur, fid, klucz_doc, "klucz")
            wersje_wlasne = [(None, fid)]

        arkusz_ids = self._wstaw_arkusze(cur, meta, sesja, arkusze, wersje_wlasne)

        stat = dict(zadan=0, wersji=0, wymagan=0, kryteriow=0, warunkow=0,
                    zapisow=0, odpowiedzi=0, rozwiazan=0, regul=0, zasobow=0,
                    form=len(forma_ids) or 1)

        for z in k.zadania:
            self._wstaw_zadanie(cur, z, klucz_doc, meta, rezimy_id,
                                domyslny_rezim, wersje_wlasne, arkusze,
                                arkusz_ids, stat, sesja, wlasny_wariant)

        for r in k.reguly:
            cur.execute(
                """INSERT INTO rule
                   (marking_scheme_id, kind, content, tasks_from, tasks_to, position)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (klucz_doc, RODZAJ_REGULY[r["rodzaj"]], r["tresc"],
                 r["zadania_od"], r["zadania_do"], r["kolejnosc"]),
            )
            stat["regul"] += 1

        return stat

    # ── kawałki, żeby `_zaladuj` dało się przeczytać ────────────────────────
    def _spnij_forme(self, cur, forma_id: int, dokument_id: int, rola: str) -> None:
        cur.execute(
            """INSERT INTO exam_form_document (exam_form_id, document_id, role)
               VALUES (%s, %s, %s) ON CONFLICT DO NOTHING""",
            (forma_id, dokument_id, ROLA_DOKUMENTU[rola]),
        )

    def _wstaw_arkusze(self, cur, meta, sesja, arkusze, wersje_wlasne) -> dict:
        arkusz_ids = {}
        for wersja, dane in (arkusze or {}).items():
            if not dane.get("sciezka"):
                continue
            cur.execute(
                """INSERT INTO document
                   (segment, year, code, variants, session, kind, kind_source, url, path)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (url) DO UPDATE SET path = EXCLUDED.path
                   RETURNING id""",
                (meta["segment"], int(meta["rocznik"]), meta["kod"],
                 meta.get("warianty"), sesja, "paper", "suffix",
                 dane.get("url", dane["sciezka"]), dane["sciezka"]),
            )
            (aid,) = cur.fetchone()
            arkusz_ids[wersja] = aid
            for w, fid in wersje_wlasne:
                if w == wersja:
                    self._spnij_forme(cur, fid, aid, "arkusz")
        return arkusz_ids

    def _wstaw_zadanie(self, cur, z, klucz_doc, meta, rezimy_id, domyslny_rezim,
                       wersje_wlasne, arkusze, arkusz_ids, stat,
                       sesja: str, wariant: str) -> None:
        cur.execute(
            """INSERT INTO task
               (marking_scheme_id, number, position, max_points, kind)
               VALUES (%s, %s, %s, %s, %s) RETURNING id""",
            (klucz_doc, z.numer, z.kolejnosc, z.punkty, TYP_ZADANIA[z.typ]),
        )
        (zid,) = cur.fetchone()
        stat["zadan"] += 1

        for o in z.ogolne:
            rid = rezimy_id.get(o.get("rezim"), domyslny_rezim)
            wid = self.wymaganie(cur, rid, "ogolne", None, o["sciezka"], o["tresc"])
            cur.execute(
                "INSERT INTO task_requirement VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (zid, wid))
            stat["wymagan"] += 1
        for sz in z.szczegolowe:
            rid = rezimy_id.get(sz.get("rezim"), domyslny_rezim)
            wid = self.wymaganie(cur, rid, "szczegolowe", sz["etap"],
                                 sz["sciezka"], sz["tresc"])
            cur.execute(
                "INSERT INTO task_requirement VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (zid, wid))
            stat["wymagan"] += 1

        # Wersje: bliźniaki dzielą kryteria, różnią się treścią i odpowiedzią.
        for wersja, fid in wersje_wlasne:
            tresc = (arkusze or {}).get(wersja, {}).get("zadania", {}).get(z.numer, {})
            cur.execute(
                """INSERT INTO task_version
                   (task_id, exam_form_id, paper_id, content, page)
                   VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                (zid, fid, arkusz_ids.get(wersja), tresc.get("tresc"),
                 tresc.get("strona", z.strona)),
            )
            (wid_wersji,) = cur.fetchone()
            stat["wersji"] += 1

            # Odpowiedź wzorcowa wisi na WERSJI, bo X i Y się różnią.
            pozycje = z.odpowiedzi.get(wersja)
            if pozycje is None and wersja is None and z.odpowiedzi:
                # Forma bez litery wersji w kluczu, który mimo to podaje dwie
                # kolumny odpowiedzi — tak wygląda KAŻDY klucz wariantu 200,
                # 400, C00 i K00 od 2023 r. Rozstrzyga przypis w samym
                # dokumencie: „Odpowiedzi w wersji Y dotyczą wyłącznie arkusza
                # OMAP-100-2505", czyli pozostałym formom przysługuje odpowiedź
                # pierwszej wersji. Bez tego 177 wersji zadań zamkniętych
                # wchodzi do korpusu bez odpowiedzi — i nikt tego nie zauważa,
                # bo samo zadanie odpowiedź ma.
                pozycje = next(iter(z.odpowiedzi.values()))
            for podpunkt, odp in (pozycje or []):
                cur.execute(
                    """INSERT INTO model_answer (task_version_id, part, answer)
                       VALUES (%s, %s, %s) ON CONFLICT DO NOTHING""",
                    (wid_wersji, podpunkt, odp))
                stat["odpowiedzi"] += 1

            for i, zas in enumerate(tresc.get("zasoby", [])):
                cur.execute(
                    """INSERT INTO asset (task_version_id, kind, path, page, bbox)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (wid_wersji, RODZAJ_ZASOBU[zas["rodzaj"]],
                     # Ścieżka WZGLĘDNA wobec korzenia blob storage, i musi
                     # zawierać WSZYSTKO, co odróżnia jeden wycinek od drugiego:
                     # sesję i wariant też. Bez nich zadanie 16 z maja 2025
                     # i zadanie 16 z maja 2024 wskazywały ten sam plik — tak
                     # samo jak wszystkie warianty dostosowane, bo 200, 400, 700
                     # i 800 mają ten sam kod arkusza.
                     f"{meta['kod']}/{sesja}/{wariant or '0'}"
                     f"/{wersja or '0'}/z{z.numer}-{i}.png",
                     zas["strona"], [float(x) for x in zas["bbox"]]),
                )
                stat["zasobow"] += 1

        for kr in z.kryteria:
            cur.execute(
                """INSERT INTO criterion (task_id, points, label, description, position)
                   VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                (zid, kr["punkty"], kr["etykieta"], kr.get("opis"), kr["kolejnosc"]),
            )
            (kid,) = cur.fetchone()
            stat["kryteriow"] += 1
            for w_i, w in enumerate(kr["warunki"], 1):
                cur.execute(
                    """INSERT INTO criterion_condition (criterion_id, description, position)
                       VALUES (%s, %s, %s) RETURNING id""",
                    (kid, w["opis"], w_i))
                (wid2,) = cur.fetchone()
                stat["warunkow"] += 1
                for z_i, zap in enumerate(w["zapisy"], 1):
                    cur.execute(
                        """INSERT INTO condition_expression
                           (condition_id, expression, position)
                           VALUES (%s, %s, %s)""",
                        (wid2, zap[:300], z_i))
                    stat["zapisow"] += 1

        for r in z.rozwiazania:
            cur.execute(
                """INSERT INTO example_solution
                   (task_id, points, method, content, position)
                   VALUES (%s, %s, %s, %s, %s)""",
                (zid, r["punkty"] if r["punkty"] is not None else z.punkty,
                 r["sposob"], r["tresc"], r["kolejnosc"]),
            )
            stat["rozwiazan"] += 1

        # Sekcja „Uwagi" pod zadaniem to reguła TEGO zadania („Brak jednostki
        # w wyniku końcowym traktujemy jako błąd rachunkowy"), a nie kolejny
        # warunek progu. Trafia więc do `rule` z zakresem zawężonym do jednego
        # numeru — inaczej parser czyta ją i gubi.
        for u_i, u in enumerate(z.uwagi, 1):
            cur.execute(
                """INSERT INTO rule
                   (marking_scheme_id, kind, content, tasks_from, tasks_to, position)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (klucz_doc, RODZAJ_REGULY[_rodzaj_reguly(u)], u, z.numer, z.numer,
                 1000 + z.kolejnosc * 10 + u_i),
            )
            stat["regul"] += 1


def _rodzaj_reguly(tresc: str) -> str:
    """Klasyfikacja reguły — JEDNA definicja, ta z parsera.

    Wcześniej stała tu druga kopia „tych samych przesłanek", która sprawdzała
    inne podciągi (`tylko poprawny` zamiast `tylko poprawny wynik`, `dyskalkuli`
    zamiast `dyskalkulią`). Reguły przekrojowe idą przez parser, a „Uwagi" przy
    zadaniu przez ładowarkę — więc ten sam zapis dostawał dwa różne typy zależnie
    od tego, w którym miejscu klucza stał.

    Zwraca nazwę w języku dokumentu; na angielski tłumaczy ją RODZAJ_REGULY.
    """
    return K.rodzaj_reguly(tresc)


TABELE = ("requirement_regime", "requirement", "document", "exam_form",
          "exam_form_document", "task", "task_requirement", "task_version",
          "model_answer", "criterion", "criterion_condition",
          "condition_expression", "example_solution", "rule", "asset")


def licz(con, tabele=TABELE) -> dict[str, int]:
    with con.cursor() as cur:
        return {t: cur.execute(f"SELECT count(*) FROM {t}").fetchone()[0]  # noqa: S608
                for t in tabele}
