# Plan implementacji A2 — Korpus (G2.1 – G2.7 + W2)

Rozpisanie kamienia **A2** z [Planu Implementacji Alfy](../README.md#plany-i-przeglądy) na
konkretne pliki, migracje, komendy i sprawdziany. Zakres: tygodnie 2–4, największy kamień
alfy i jedyny z prawdziwą niewiadomą (tempo ręcznej korekty). Kolejność z `DECYZJE.md`:
**najpierw ekran korekty, potem parser**.

> **Definicja „zrobione" dla A2**
> Komplet E8 2019–2026 **wariantu bazowego (100)** w Postgresie, **każdy rekord
> zatwierdzony** — żaden nie ominął bramki korekty. Zadania z rysunkiem mają wycinek PNG
> (nie całą stronę), zapisy równoważne mają MathJSON, raport kompletności per rocznik
> leży w `data/reports/`, a statystyka półautomatu (S8) ma liczby do wniosku grantowego.

---

## Spis treści

- [Kolejność i równoległość](#kolejność-i-równoległość)
- [Stan wyjściowy po A1](#stan-wyjściowy-po-a1)
- [G2.1 — Ekran korekty](#g21--ekran-korekty) · [2.1.1](#g211--przepływ-rekordu-migracja-0004) [2.1.2](#g212--ui-lokalne) [2.1.3](#g213--statystyka-korekty-s8)
- [G2.2 — Pilot: rocznik 2025](#g22--pilot-rocznik-2025-end-to-end) · [2.2.1](#g221--pełny-przebieg) [2.2.2](#g222--decyzja-po-pilocie-zawór)
- [G2.3 — Parser: pełny zasięg 2019–2026](#g23--parser-pełny-zasięg-20192026) · [2.3.1](#g231--dialekt-e8-2019-w-pełni) [2.3.2](#g232--znane-luki-rekonstrukcji) [2.3.3](#g233--dosypywanie-roczników-partiami)
- [G2.4 — Wycinki graficzne](#g24--wycinki-graficzne) · [2.4.1](#g241--wykrywanie-regionu--eksport-png) [2.4.2](#g242--fallback-ręczna-ramka)
- [G2.5 — LLM w ingeście](#g25--llm-w-ingeście) · [2.5.1](#g251--wstępne-wypełnianie-ekranu-s6) [2.5.2](#g252--opisy-rysunków-s7)
- [G2.6 — Konwerter MathJSON](#g26--konwerter-mathjson)
- [G2.7 — Domknięcie kamienia](#g27--domknięcie-kamienia)
- [W2 — Przeglądarka korpusu (tor W)](#w2--przeglądarka-korpusu-tor-w)
- [Tor G — golden set startuje razem z A2](#tor-g--golden-set-startuje-razem-z-a2)
- [Checklista domknięcia A2](#checklista-domknięcia-a2)
- [Pułapki i decyzje do zapisania](#pułapki-i-decyzje-do-zapisania)

---

## Kolejność i równoległość

```
tydz. 2      G2.1 ekran korekty ── 0004 → UI → statystyki      [blokuje wszystko]
                     │
tydz. 2–3    G2.2 pilot 2025: parser → korekta → zatwierdzenie ═► DECYZJA (zawór)
                     │
tydz. 3–4  ┌─────────┼──────────────┬───────────────┬───────────────┐
           ▼         ▼              ▼               ▼               ▼
        G2.3       G2.4           G2.5            G2.6            W2 przeglądarka
        roczniki   wycinki PNG    LLM: prefill    MathJSON        korpusu (czyta
        2019–2026  (region+       + alt-text      (Node CLI)      zatwierdzone
        partiami   fallback)      (S6, S7)                        przez C#/OpenAPI)
           │         │              │               │               │
           └─────────┴──────────────┴───────────────┴───────────────┘
                                    ▼
tydz. 4–5                     G2.7 komplet + raporty ═► [A2 zamknięte]

TOR G        G3.0 golden set — od tygodnia 2, rytm 2 roczniki/tydzień, równolegle z całym A2
```

**G2.1 blokuje wszystko** — bez bramki statusów żaden rekord nie ma jak zostać
„zatwierdzony", więc pilot nie ma czego mierzyć. To samo zdanie co przy G1.1 w A1:
jeden tydzień, nie zrównoleglać.

**G2.2 jest punktem decyzyjnym, nie formalnością.** Po pilocie znane jest tempo korekty
na rocznik; decyzja z G2.2.2 rozstrzyga, czy A3 czeka na komplet, czy startuje na pilocie
(zawór z Planu Implementacji). G2.3–G2.6 i W2 zaczynają się dopiero PO pilocie —
wszystkie iterują na przepływie, który pilot dopiero utwardza.

**Jedyne szwy między frontami po pilocie:** G2.5.2 (opisy rysunków) czeka na wycinki
z G2.4.1, a W2 czyta wyłącznie rekordy zatwierdzone w G2.1. Poza tym cztery fronty
nie dzielą żadnego pliku.

---

## Stan wyjściowy po A1

Co już istnieje i czego A2 **nie** buduje od nowa:

| Jest | Gdzie | Konsekwencja dla A2 |
|---|---|---|
| 75 kluczy E8 ładuje się do Postgresa, pokrycie 100/100/100 | `ingest/parsers/omap_e8/` | A2 nie pisze parsera — dociska dialekt 2019 i luki |
| Statusy w schemacie: `document.ingest_status`, `task_version.content_status`, `asset.description_status` | `0001_corpus.sql` | brakuje statusu na **zadaniu** — to jest migracja 0004 |
| `condition_expression.mathjson jsonb` — kolumna pusta | `0001_corpus.sql` | G2.6 ją wypełnia; migracja dokłada tylko status konwersji |
| `asset.bbox` = cała strona; `--z-arkuszami` dokłada treść i zasoby | `run.py` | G2.4 zawęża bbox i tnie PNG |
| Luki rekonstrukcji zamrożone testami `xfail` (liczby mieszane, pierwiastki) | `ingest/tests/` | G2.3.2 gasi je świadomą decyzją per luka |
| Ponowny przebieg klucza kasuje i wstawia jego zadania od nowa | `loader.py` | **koliduje z korektą** — ochrona w G2.1.1, zanim powstanie pierwsza poprawka |
| `IBlobStore` + `DiskBlobStore`, korzeń `data/blob/`, ścieżki względne | `backend/` | wycinki z G2.4 lądują tam, gdzie C# już umie czytać |
| Kontrakt OpenAPI + bramka dryfu | `task openapi:check` | endpointy W2.1 przechodzą przez tę samą bramkę |

Uwaga porządkowa: plan A1 zapowiadał migrację `0003_status_korekty.sql`, ale numer 0003
zajęło `0003_nulls_not_distinct.sql`. Migracje A2 zaczynają się więc od **0004**.
Zastosowanych migracji nie wolno ruszać (runner liczy SHA-256) — każda zmiana schematu
to nowy plik.

---

## G2.1 — Ekran korekty

### G2.1.1 — Przepływ rekordu, migracja 0004

**Czeka na:** [A1] · **Równolegle z:** G2.1.2

Przepływ: parser → **do zatwierdzenia** → **zatwierdzony / poprawiony / odrzucony**.
Do korpusu wchodzi tylko zatwierdzone i poprawione — to jest definicja „zrobione" ingestu.

`ingest/schema/migrations/0004_review_status.sql`:

```sql
-- Status korekty wisi na ZADANIU, nie na dokumencie i nie na wersji.
-- Zadanie jest jednostką pracy w ekranie: człowiek patrzy na zadanie
-- z kompletem kryteriów, warunków, zapisów, wersji i wymagań naraz
-- i zatwierdza całość. Statusy drobniejsze już istnieją i zostają:
-- content_status na wersji (treść z arkusza), description_status na
-- zasobie (alt-text) — domykają się osobno, bo powstają w innym czasie.
ALTER TABLE task
    ADD COLUMN review_status text NOT NULL DEFAULT 'pending'
        CHECK (review_status IN ('pending', 'approved', 'corrected', 'rejected')),
    ADD COLUMN reviewed_at timestamptz;

-- Dziennik korekty: surowiec dla S8 (czas na zadanie, odsetek trafień
-- parsera). Liczby liczy się z dziennika, nie z liczników w kolumnach —
-- licznik nadpisany traci historię, dziennik nie.
CREATE TABLE correction_event (
    id             serial      PRIMARY KEY,
    task_id        integer     NOT NULL REFERENCES task(id) ON DELETE CASCADE,
    action         text        NOT NULL CHECK (action IN
                     ('approve', 'correct', 'reject', 'reopen')),
    started_at     timestamptz NOT NULL,
    finished_at    timestamptz NOT NULL DEFAULT now(),
    fields_changed jsonb                -- {"criterion": 2, "condition_expression": 1}
);

-- Kontrakt dla konsumentów korpusu (C# w W2.1, pipeline w A3):
-- czytają przez ten widok, nigdy wprost z task. Definicja "co jest
-- korpusem" stoi wtedy w JEDNYM miejscu schematu.
CREATE VIEW corpus_task AS
SELECT * FROM task WHERE review_status IN ('approved', 'corrected');
```

Rozróżnienie `approved`/`corrected` jest celowe: **`approved` = parser trafił sam,
`corrected` = człowiek poprawiał**. Odsetek `approved` w kompletach to wprost S6/S8 —
bez osobnego statusu trzeba by go rekonstruować z dziennika.

**Ochrona przed ponownym ingestem.** `loader.py` przy powtórce klucza kasuje jego
zadania i wstawia od nowa — po pierwszej poprawce ręcznej to jest **utrata pracy
człowieka**, najdroższego zasobu tego kamienia. Zanim powstanie UI:

1. `run.py` przed ładowaniem klucza sprawdza, czy którekolwiek jego zadanie ma
   `review_status != 'pending'`. Jeśli tak — **pomija klucz** z komunikatem
   (`POMIJAM OMAP-100-2505: 21 zadan po korekcie`).
2. Flaga `--nadpisz-korekte` wymusza przeładowanie ze skasowaniem statusów —
   do świadomego użycia, gdy poprawka parsera ma unieważnić starą korektę.
3. Test na to zachowanie w `ingest/tests/` — i raz zobaczyć go na czerwono.

**Zrobione, gdy:** migracja wchodzi na czystą bazę i na bazę z danymi z A1;
`corpus_task` zwraca zero wierszy przed pierwszym zatwierdzeniem; ponowny
`task ingest` nie rusza klucza z korektą — sprawdzone świadomie.

> **Poprawki z implementacji (G2.1.1).**
> **(1)** `correction_event.task_id` jest **NULL-owalne, z `ON DELETE SET NULL`**,
> a nie `NOT NULL` z kaskadą jak wyżej w planie. Kaskada kasowała pomiar S8 razem
> z zadaniami przy `--overwrite-reviewed`, a S8 jest wynikiem alfy i liczbą do wniosku;
> wiersz bez zadania wciąż niesie czas i rodzaj decyzji, czyli wszystko, czego pomiar
> potrzebuje.
> **(2)** Flaga nazywa się `--overwrite-reviewed`, nie `--nadpisz-korekte`: nowe
> identyfikatory w tym repozytorium są po angielsku (CLAUDE.md, zasada 4), a polskie
> flagi obok są długiem z G1.2 i schodzą osobnym commitem.
> **(3)** Doszła kolumna `task.page` — strona w KLUCZU. `task_version.page` po wczytaniu
> z `--z-arkuszami` trzyma stronę w ARKUSZU i wtedy numeru strony klucza nie ma nigdzie,
> a ekran korekty renderuje właśnie ją. Migracja uzupełnia ją dla korpusu wczytanego
> bez arkuszy; reszta domaga się przeładowania i mówi to wprost.
> **(4)** Bramka `--wyczysc` (TRUNCATE) jest osobna od bramki w ładowarce — ten SQL
> omija ładowarkę z definicji, więc ochrona przed skasowaniem całego korpusu musi stać
> w runnerze.

---

### G2.1.2 — UI lokalne

**Czeka na:** [A1] · **Równolegle z:** G2.1.1

Strona Pythona na localhost: rekord obok wycinka strony PDF; zatwierdź / popraw / odrzuć;
edycja kryteriów, warunków, zapisów, wymagań, treści wersji. Świadomy wyjątek od granicy
warstw (zapisany w `CLAUDE.md`): ekran korekty edytuje rekordy, **zanim** staną się
korpusem.

**Stos: FastAPI + Jinja2 + htmx, render stron przez pypdfium2.**

| Wybór | Powód |
|---|---|
| FastAPI + Uvicorn (MIT) | jeden proces, zero ruchu użytkownika; walidacja formularzy Pydantikiem, który i tak jest w zależnościach FastAPI |
| Jinja2 + htmx (BSD, jeden plik `.js` wendorowany do repo) | zero build stepu, zero Node w warstwie ingest; wymiana fragmentów HTML wystarcza na formularz z listą kryteriów |
| pypdfium2 (Apache-2.0 / BSD-3) | render strony PDF → PNG bez ImageMagicka i bez poppler-a; **PyMuPDF pozostaje zakazany** (AGPL, decyzja w `DECYZJE.md`) |

React tu nie wchodzi celowo: przeglądarka korpusu (W2) jest po stronie web i czyta
tylko zatwierdzone; ekran korekty jest narzędziem jednorazowego użytku na 3 tygodnie
pracy jednej osoby. Reguła stopu z Planu Implementacji obowiązuje podwójnie:
**zero stylowania ponad czytelność**.

Układ:

```
ingest/correction/
├── app.py            # FastAPI: trasy, wybór zadania, akcje zatwierdź/popraw/odrzuć
├── pages.py          # render strony PDF → PNG (pypdfium2), cache w data/reports/pages/
├── templates/        # Jinja2: lista zadań, formularz zadania, fragmenty htmx
└── static/htmx.min.js
```

**Kroki**

1. Zależności do `pyproject.toml`: `fastapi`, `uvicorn`, `jinja2`, `pypdfium2`.
2. Widok listy: klucze i zadania z filtrem po `review_status` i roczniku; „następne
   do korekty" jako domyślne wejście — zero klikania w poszukiwaniu pracy.
3. Widok zadania: po lewej render strony PDF (z `task_version.page` + `bbox`),
   po prawej formularz — treść wersji, kryteria → warunki → zapisy (edycja inline,
   dodaj/usuń), wymagania, odpowiedzi wzorcowe. Przy zapisie: `correct` do dziennika
   z listą zmienionych pól; przy zatwierdzeniu bez zmian: `approve`.
4. Akcje piszą w JEDNEJ transakcji: zmiany + status + `correction_event` +
   aktualizacja `document.ingest_status` (klucz z kompletem rozstrzygnięć →
   `approved`).
5. `Taskfile.yml`: `task correction` (uvicorn na `${CORRECTION_PORT:-8600}`);
   `CORRECTION_PORT` do `.env.example`. Port konfigurowalny — ta sama lekcja
   co `DB_PORT` w A1.
6. Czas startu pracy nad zadaniem (`started_at`) łapie moment otwarcia formularza —
   inaczej S8 zmierzy czas „między zapisami", nie czas pracy.

**Zrobione, gdy:** pełny cykl na jednym zadaniu przechodzi z przeglądarki:
otwórz → popraw kryterium → zatwierdź → rekord widoczny w `corpus_task`,
wpis w dzienniku, status dokumentu zaktualizowany.

> **Poprawki z implementacji (G2.1.2).**
> **(1) htmx nie wszedł — ekran nie ma ani linijki JavaScriptu.** Wymiana fragmentów
> okazała się niepotrzebna: dodawanie progu, warunku i zapisu to zwykłe `submit`
> tego samego formularza (zapisz edycje → wstaw pusty wiersz → przekierowanie), więc
> jedyne, co htmx by wniósł, to wendorowany plik zewnętrzny do przeglądu i utrzymania.
> **(2) Jeden przycisk „Zatwierdź", dwa stany.** Plan zakładał rozdzielenie
> `approve`/`correct` w interfejsie; w implementacji o statusie decyduje **porównanie
> formularza z bazą**. Dzięki temu S6/S8 nie da się przekłamać kliknięciem — a przy
> okazji `fields_changed` powstaje za darmo, z tego samego porównania.
> **(3) Status `corrected` wymusza uczciwość również przy pustych wierszach:** nowy
> warunek wchodzi z pustym opisem (`NOT NULL` pozwala na `''`), a walidacja nie puści
> zapisu, dopóki człowiek go nie wypełni albo nie usunie.

---

### G2.1.3 — Statystyka korekty (S8)

**Czeka na:** G2.1.1 · **Równolegle z:** G2.1.2

Licznik na stronie głównej ekranu + zrzut do raportu:

- odsetek rekordów zatwierdzonych **bez poprawki** (`approved` / wszystkie rozstrzygnięte),
- czas korekty na zadanie (mediana i suma, z `correction_event`),
- prognoza: tempo × pozostałe zadania = ile jeszcze godzin.

To jest <span title="S8">pomiar S8</span> — koszt półautomatu, wejście do kalkulacji K6
(matura, angielski) i do wniosku grantowego. Prognoza jest po to, żeby decyzja G2.2.2
była rachunkiem, nie wrażeniem.

**Zrobione, gdy:** po pilocie liczby S8 są na ekranie i w `data/reports/`.

---

## G2.2 — Pilot: rocznik 2025 end-to-end

### G2.2.1 — Pełny przebieg

**Czeka na:** G2.1 · **Równolegle z:** — (pilot robi się w skupieniu)

Rocznik 2025, wariant bazowy: `OMAP-100-2505` (X/Y) + termin dodatkowy `OMAP-100-2506`.
Pełny przebieg: parser z arkuszami → korekta całości w ekranie → zatwierdzenie do
Postgresa. Wycinki PNG dla zadań z rysunkiem — na etapie pilotu **fallbackiem ręcznym**
(bbox dociągnięty w ekranie, G2.4.2), bo automat z G2.4.1 jeszcze nie istnieje.

**Kroki**

1. `task ingest -- --z-arkuszami` na roczniku 2025 (`--limit`/filtr sesji wg potrzeby).
   Liczby kontrolne z sondy: `OMAP-100-2505` = 21 zadań, 42 wersje, 51 kryteriów,
   73 warunki, 14 zapisów, 30 odpowiedzi, 17 reguł, 14 zasobów.
2. Korekta wszystkich zadań rocznika w ekranie — **mierząc czas** (dziennik robi to sam).
3. Zadania z rysunkiem: ramka ręcznie w ekranie, wycinek do `data/blob/`, ścieżka
   względna w `asset.path`.
4. Na koniec: rocznik w 100% rozstrzygnięty, raport S8 z pilotu do `data/reports/`.

**Zrobione, gdy:** pierwszy rocznik w bazie w 100% zatwierdzony; czas korekty
na rocznik zmierzony i zapisany.

> **Poprawki z implementacji (G2.2.1).**
> **(1) Terminu dodatkowego `OMAP-100-2506` nie ma w mirrorze** — spis zna dla 2025 r.
> jedną sesję (`2025-05`), i tak samo dla każdego rocznika 2019–2026. Pilot to jeden
> klucz `OMAP-100-2505` z dwoma zeszytami (X/Y), nie dwa klucze.
> **(2) Runner dostał `--year` i `--variant`.** Zawężenie przebiegu umiały wcześniej
> tylko `--kod` i `--segment`, więc pilot z arkuszami brał cały korpus: kwadrans
> zamiast minuty i 74 klucze przeładowane bez powodu. Wariant porównuje się po
> **pierwszym członie** kolumny `warianty`, bo zeszyty trzymają tam także wersję
> („100,X") — filtr na całość nie znalazłby ani jednego arkusza.
> **(3) Ekran korekty dostał zakres pracy** (rocznik + kod + wariant). „Następne do
> korekty" brało pierwsze czekające zadanie z **całego** korpusu, czyli z 2019 r.:
> pilot kończył się na pierwszym zapisie. Zakres jedzie w adresie i w ukrytych polach
> formularza, więc przeżywa przekierowanie po zapisie.
> **(4) Pułapka: przebieg BEZ `--z-arkuszami` kasuje treści i zasoby** wczytane
> wcześniej z arkuszami. Bramka z G2.1.1 chroni tylko zadania po korekcie, a te
> `pending` ładowarka kasuje i wstawia od nowa — bez zeszytów, czyli bez `content`
> i bez `asset`. W pilocie każdy kolejny przebieg tego klucza musi mieć tę flagę.
> Liczby kontrolne z sondy zgadzają się co do jednego: 21 / 42 / 51 / 73 / 14 / 30 /
> 17 / 14, pokrycie wymagań, odpowiedzi i kryteriów 100%.

---

### G2.2.2 — Decyzja po pilocie (zawór)

**Czeka na:** G2.2.1

Rachunek: tempo z pilotu × 7 pozostałych roczników. Mieści się w ~2 tygodniach?

- **Tak** → A2 jedzie do końca sekwencyjnie, A3 czeka na komplet.
- **Nie** → zawór: **pilot 2025 staje się „wystarczającym A2"** i odblokowuje A3;
  G2.3–G2.7 schodzą na tor równoległy do A3. Wpis do `DECYZJE.md` z datą i liczbą,
  która o tym rozstrzygnęła.

Druga decyzja przy okazji: czy prefill LLM (G2.5.1) wchodzi do przepływu korekty
pozostałych roczników od razu, czy po własnym pomiarze na próbce. Jeśli pilot pokaże
tempo dużo gorsze od planu — prefill przesuwa się z „eksperyment" na „narzędzie".

**Zrobione, gdy:** decyzja zapisana (w `DECYZJE.md`, jeśli zawór uruchomiony).

---

## G2.3 — Parser: pełny zasięg 2019–2026

### G2.3.1 — Dialekt `e8-2019` w pełni

**Czeka na:** G2.2 · **Równolegle z:** G2.4, G2.5, G2.6

Parser już rozpoznaje dialekt 2019 (żywa pagina, nie separator) i ładuje te klucze
z pokryciem 100% — „w pełni" znaczy tutaj: **rocznik 2019 przechodzi przez KOREKTĘ
bez błędów strukturalnych**, a znane osobliwości są obsłużone jako przypadki, nie jako szum:

- brak wersji X/Y (jedna wersja arkusza),
- brak sekcji kryteriów dla zadań zamkniętych (90 zadań bez progu 0 pkt — to cecha
  dokumentu, w ekranie korekty ma być widoczna jako norma rocznika, nie jako brak),
- separator warunków `lub` (małe litery),
- **podwójne mapowanie na podstawy 2012+2017** — cztery kolumny tabeli wymagań,
  każda para z własnym reżimem; w ekranie korekty oba mapowania widoczne obok siebie.

**Kroki**

1. Przebieg rocznika 2019 przez parser, potem korekta pierwszego klucza w ekranie —
   lista błędów strukturalnych z tej korekty jest backlogiem poprawek parsera.
2. Poprawki parsera zawsze przed masową korektą rocznika: godzina w parserze,
   która oszczędza minutę na zadaniu × 90 zadań, wygrywa; odwrotnie — nie
   (reguła z Planu Alfy: przy 219 zadaniach korekta zwykle wygrywa — stosować per błąd).
3. Po każdej poprawce parsera: przebieg kontrolny 75 kluczy i porównanie liczb
   z `data/reports/` — poprawka dla 2019 nie może ruszyć wyników 2020–2026.

**Zrobione, gdy:** rocznik 2019 przechodzi przez korektę bez błędów strukturalnych,
a liczby pozostałych roczników są niezmienione.

---

### G2.3.2 — Znane luki rekonstrukcji

**Czeka na:** G2.2 · **Równolegle z:** G2.3.1

Dwie luki zamrożone w A1 testami `xfail` — teraz rozstrzygnięcie **per luka**:
naprawa w kodzie albo ręczna korekta.

| Luka | Objaw | Rekomendacja |
|---|---|---|
| liczby mieszane | `1⅔ km` → `12/3` | **naprawa w kodzie** — wzorzec jest regularny (glif ułamka po cyfrze), a błąd jest CICHY: `12/3` wygląda jak poprawny ułamek i przejdzie korektę niezauważony |
| pierwiastki | znak √ jest glifem, „daszek" linią; zasięg nieodtwarzany | **ręczna korekta** — wystąpień mało, geometria daszka niejednoznaczna, a błąd jest WIDOCZNY w ekranie (brak domknięcia zasięgu rzuca się w oczy przy zapisie) |

Kryterium rozstrzygnięcia zapisać razem z decyzją: **cichy błąd naprawia się w kodzie,
widoczny wolno zostawić korekcie.** Naprawa liczb mieszanych gasi test `xfail`
(zapala się na zielono — dokładnie po to tam jest); pierwiastki dostają wpis
w `DECYZJE.md` i `xfail` zostaje z komentarzem „świadomie: korekta ręczna".

**Zrobione, gdy:** obie decyzje zapisane; `xfail` liczb mieszanych zielony;
zero cicho błędnych rekordów w zatwierdzonym korpusie.

---

### G2.3.3 — Dosypywanie roczników partiami

**Czeka na:** G2.3.1 · **Równolegle z:** G2.4, G2.5

Pozostałe roczniki (2020–2024, 2026 + terminy dodatkowe) partiami przez korektę.
Partia = rocznik. Po każdej partii raport pokrycia (sekcja `SPÓJNOŚĆ` z `run.py`
robi to sama) — porównany z poprzednim przebiegiem, ZANIM zacznie się korekta partii:
regresję parsera taniej złapać na raporcie niż na 20 zadaniach ręcznie.

Kolejność roczników: od najnowszych wstecz (2026 → 2020) — dialekt 2020+ jest
przetarty pilotem, rocznik 2019 domknięty osobno w G2.3.1.

**Zrobione, gdy:** 8 roczników wariantu 100 rozstrzygniętych w korekcie;
pokrycie wymagań / odpowiedzi / kryteriów = 100% na zatwierdzonym korpusie.

---

## G2.4 — Wycinki graficzne

### G2.4.1 — Wykrywanie regionu → eksport PNG

**Czeka na:** G2.2 · **Równolegle z:** G2.3, G2.5

Stan zastany: 84 z 219 zadań wariantu bazowego (38%) odwołuje się do grafiki,
587 obiektów graficznych w arkuszach, a `asset.bbox` to **cała strona**. Cel: każdy
zasób ma ramkę wokół rysunku i wycinek PNG przypięty do `task_version`.

**Mechanika** (`ingest/pdf/regions.py` + zapis w przebiegu parsera):

1. Kandydaci: obiekty graficzne strony (`images`, `curves`, `rects`, `lines`
   z warstwy pozycyjnej) przycięte do pionowego zakresu zadania
   (`task_version.bbox` z cięcia arkusza).
2. Klastrowanie po odległości (sąsiedztwo ramek z marginesem) — diagram to zwykle
   dziesiątki kresek, które mają zostać JEDNYM zasobem, nie 40 wycinkami.
3. Filtr śmieci: linie tabel i obramowań stron odpadają po proporcjach i położeniu
   (pełna szerokość kolumny = tabela, nie rysunek) — ta sama lekcja co filtr
   fałszywych ułamków w rekonstrukcji.
4. Bounding box klastra + margines → render fragmentu przez **pypdfium2**
   w stałej skali (≈200 DPI) → PNG.
5. Zapis: `data/blob/omap/<sesja>/<forma>/task-<nr>-<wersja>.png`; w bazie
   **ścieżka względna** (`omap/2505/100-x/task-1.png`) — nigdy absolutna, nigdy
   z literą dysku; `asset.bbox` dostaje ramkę wycinka (do ponownego renderu).
6. Idempotencja jak w całym ingeście: ponowny przebieg nadpisuje własne pliki
   po tej samej ścieżce, nie mnoży wersji.

**Sprawdzian skuteczności, nie „działa u mnie":** przebieg na pilocie 2025 →
w ekranie korekty każdy wycinek obok strony źródłowej; licznik „ramka poprawna /
do dociągnięcia" mówi, czy automat domknął temat, czy G2.4.2 przejmuje resztę.

**Zrobione, gdy:** zadania z rysunkiem w pilocie mają wycinek zamiast całej strony,
a odsetek ramek wymagających ręcznego dociągnięcia jest zmierzony.

---

### G2.4.2 — Fallback: ręczna ramka

**Czeka na:** G2.1.2 · **Równolegle z:** G2.4.1

W widoku zadania: obrazek strony + przeciągnięcie prostokąta (canvas albo zwykłe
`<input>` na współrzędne — czytelność przed wygodą) → zapis bbox → wycinek tnie się
tym samym kodem co w G2.4.1 (jedna funkcja `crop(page, bbox) → path`; automat
i fallback różnią się tylko źródłem ramki).

To jest **zawór nr 3** z Planu Implementacji: jeśli automat nie domyka, ręczne
dociągnięcie ramki jest akceptowalnym zamknięciem tematu. 84 zadania × minuta
to półtorej godziny — automat, który zjada dzień strojenia, przegrywa ten rachunek.

**Zrobione, gdy:** 0 zadań z rysunkiem bez wycinka — niezależnie od drogi.

---

## G2.5 — LLM w ingeście

Budżet badawczy alfy. Obie pozycje mają tę samą regułę twardą:
**LLM proponuje, człowiek zatwierdza w ekranie korekty — nic z modelu nie wchodzi
do korpusu bez bramki.** Provenance w statusach (`auto` → `approved`), nie w pamięci.

Wspólna mechanika:

- SDK `anthropic` (Python) w `pyproject.toml`; `ANTHROPIC_API_KEY` wyłącznie
  z `.env` (wpis w `.env.example`, wartość nigdy w repo).
- Structured output (`client.messages.parse()` ze schematem Pydantica) — werdykt
  ma być rekordem, nie prozą do parsowania.
- Model jako **parametr przebiegu**, nie stała w kodzie: domyślnie `claude-opus-5`
  ($5/$25 za MTok), porównawczo `claude-haiku-4-5` ($1/$5) — różnica jakości
  przy 5× różnicy ceny to część pomiaru S6/S7, nie decyzja z góry.
- Przebiegi masowe (cały rocznik naraz) przez **Batch API** — −50% kosztu,
  wynik i tak czyta się następnego dnia w ekranie korekty.
- Licznik tokenów i kosztu per przebieg do `data/reports/` — ta sama dyscyplina,
  którą A3 wymusi w porcie `IGradingModel` (G3.2.2), zaczęta wcześniej.
- **Wywołania LLM nie wchodzą do CI.** Testy jednostkowe pracują na utrwalonych
  odpowiedziach (fixture JSON); przebieg z żywym modelem jest ręczny.

### G2.5.1 — Wstępne wypełnianie ekranu (S6)

**Czeka na:** G2.1, G2.2 · **Równolegle z:** G2.3

Strukturalna ekstrakcja kryteriów z surowego tekstu klucza: model dostaje tekst
sekcji zasad oceniania jednego zadania, oddaje strukturę progi → warunki → zapisy
w tym samym kształcie, który produkuje parser.

**Kroki**

1. `ingest/correction/prefill.py`: wejście — tekst zadania po rekonstrukcji;
   wyjście — struktura kryteriów (schemat Pydantica identyczny z modelem parsera).
2. Ekran korekty pokazuje **różnice** parser vs LLM jako podpowiedź przy polach,
   których dotyczą — nie drugi formularz do czytania w całości.
3. Pomiar na próbce rocznika (≥20 zadań otwartych, te same zadania w obu wariantach):
   korekta z podpowiedzią vs bez. Metryki: odsetek zatwierdzeń bez poprawki,
   czas na zadanie, koszt tokenów.
4. Wynik <span title="S6">S6</span> do `data/reports/` — rozstrzyga, jak tanie
   będzie K6 (matura, angielski: tam parser trzeba napisać od zera, prefill LLM
   może go częściowo zastąpić).

**Zrobione, gdy:** liczba S6 zapisana; decyzja „prefill w przepływie czy nie"
podjęta na jej podstawie (patrz G2.2.2).

---

### G2.5.2 — Opisy rysunków (S7)

**Czeka na:** G2.4.1 · **Równolegle z:** G2.3

Alt-text dla wszystkich zasobów graficznych: wycinek PNG → opis po polsku →
`asset.description` + `description_status='auto'` → walidacja ręczna w ekranie
korekty → `approved`.

**Kroki**

1. `ingest/correction/describe.py`: obraz + treść zadania jako kontekst → opis,
   który pozwala rozwiązać zadanie bez patrzenia na rysunek (to jest test jakości,
   nie „ładny opis"). Batch API, całe roczniki naraz.
2. Walidacja w ekranie: opis pod wycinkiem, akcje zatwierdź / popraw — te same,
   co dla rekordów.
3. Miara <span title="S7">S7</span>: odsetek opisów zatwierdzonych bez poprawki.
   To wejście do A/B „obraz vs opis" w A3 (G3.4.1, pytanie S1) **i** do WCAG —
   opisy zostają w produkcie niezależnie od wyniku A/B.

**Zrobione, gdy:** każdy `asset` wariantu bazowego ma `description_status='approved'`;
S7 zmierzone i zapisane.

---

## G2.6 — Konwerter MathJSON

**Czeka na:** G2.2 · **Równolegle z:** G2.3, G2.4, G2.5 · **Blokuje:** G3.1.3 (EvaluateClosed)

Konwersja `condition_expression.expression` (tekst: `P = 1/2⋅15·2⋅(15∶5)`) na MathJSON
w kolumnie `mathjson` (jsonb, po researchu pusta; 514 zapisów w korpusie). Bez tego
Compute Engine porównuje stringi, a `2(x+1) ≡ 2x+2` nigdy nie zadziała — decyzja
z `DECYZJE.md`, sekcja 2.

**Świadome zawężenie wobec Planu Implementacji:** `model_answer` (odpowiedzi wzorcowe
zamkniętych) to litery `BD`/`FP` — MathJSON nic tam nie wnosi, `EvaluateClosed`
porówna litery. Konwersji podlegają **zapisy równoważne zadań otwartych**. Gdyby A3
wykazał potrzebę (np. zadania z odpowiedzią liczbową), kolumna `model_answer.mathjson`
wejdzie osobną migracją — nie „na zapas" teraz.

**Narzędzie: mały CLI w Node z `@cortex-js/compute-engine` (MIT), wołany z Pythona.**
Powód, nie wygoda: Compute Engine jest referencyjną implementacją MathJSON i **tym
samym silnikiem, którego użyje EvaluateClosed w A3** — parsowanie tą samą biblioteką
eliminuje dryf dialektu między ingestem a silnikiem. Node i tak jest wymaganiem repo.
Granica warstw nietknięta: to nadal offline ETL uruchamiany ręcznie, wynikiem są dane.

```
ingest/mathjson/
├── convert.mjs    # stdin: NDJSON {id, expression} → stdout: {id, mathjson | error}
├── fill.py        # czyta zapisy z bazy, woła convert.mjs, zapisuje wynik + status
└── package.json   # jedyna zależność: @cortex-js/compute-engine
```

`0005_mathjson_status.sql`:

```sql
-- Status konwersji per zapis: 'failed' jest jawnym stanem, nie NULL-em —
-- zapis, którego konwerter nie ugryzł, ma być widoczny w ekranie korekty
-- jako robota do zrobienia, a nie znikać w tle.
ALTER TABLE condition_expression
    ADD COLUMN mathjson_status text NOT NULL DEFAULT 'none'
        CHECK (mathjson_status IN ('none', 'auto', 'approved', 'failed'));
```

**Kroki**

1. Normalizacja przed parsowaniem: NFKC (jest w rekonstrukcji) + mapowanie
   operatorów CKE na wejście Compute Engine (`∶` → `:`, `⋅`/`∙` → `*`,
   `−` → `-`, ułamki piętrowe już są liniowe po rekonstrukcji).
2. `fill.py` na pilocie 2025 → przegląd wyników w ekranie korekty: zapis, jego
   MathJSON wyrenderowany z powrotem do postaci czytelnej, akcje zatwierdź / popraw /
   oznacz `failed`.
3. Pełny przebieg na 514 zapisach; `failed` schodzi ręcznie w ekranie —
   **zawór z Planu Implementacji:** jeśli konwerter utknie, pilotem jest podzbiór
   przekonwertowany ręcznie, nie tydzień walki z parserem wyrażeń.
4. Testy: utrwalone pary tekst → MathJSON dla znanych pułapek (potęgi po scaleniu
   indeksów, `15∶5`, jednostki w nawiasach); test idzie w CI **bez Node'a w pętli** —
   fixture'y z zapisanym wyjściem konwertera + osobny test uruchamiający
   `convert.mjs`, oznaczony do pominięcia, gdy Node niedostępny.

**Zrobione, gdy:** każdy zapis wariantu bazowego ma `mathjson_status`
w {`auto`, `approved`} albo świadome `failed` z ręczną decyzją; fixture'y konwersji w CI.

---

## G2.7 — Domknięcie kamienia

### G2.7.1 — Komplet w bazie

**Czeka na:** G2.3–G2.6

Sprawdzenie definicji „zrobione" z Planu Alfy — zapytaniami, nie wrażeniem:

- zadania z wersjami X/Y (bliźniaki widoczne w widoku `twins`),
- kryteria z progami i alternatywami — trzy poziomy dysjunkcji niespłaszczone,
- reguły przekrojowe z zakresem zadań,
- mapowanie na podstawę programową (widok `tasks_per_requirement` bez dziur),
- wycinki PNG dla wszystkich zadań z grafiką,
- MathJSON w zapisach, opisy przy zasobach,
- **wszystko powyższe liczone po `corpus_task`** — rekordy `pending`/`rejected`
  nie są korpusem.

### G2.7.2 — Raport kompletności i statystyka półautomatu

**Czeka na:** G2.7.1

Raport per rocznik do `data/reports/corpus-A2-<data>.txt` + sekcja zbiorcza:

- liczby rekordów per tabela, per rocznik (wzór: sekcja `SPÓJNOŚĆ`),
- **statystyka półautomatu:** ile rekordów parser trafił sam (`approved`),
  ile poprawiono (`corrected`), ile odrzucono; czas korekty łącznie i per zadanie,
- S6, S7, S8 zebrane w jednym miejscu — **liczby do wniosku grantowego**.

**Zrobione, gdy:** raport w repo (`data/` jest poza gitem — raport zbiorczy
skopiować do `docs/`), **[A2 zamknięte]**.

---

## W2 — Przeglądarka korpusu (tor W)

**Czeka na:** G2.2.1 (pilot w bazie) · **Równolegle z:** G2.3–G2.6

Tor W, tygodnie 3–4. **Przeglądarka ≠ ekran korekty:** ekran korekty (Python) edytuje
rekordy, zanim staną się korpusem; przeglądarka czyta **wyłącznie zatwierdzone**,
przez C# i OpenAPI. Granica warstw bez zmian. Wartość: wizualna weryfikacja ingestu
drugą parą oczu — każdy dosypany rocznik natychmiast widoczny — i kontrakt
zadanie/kryterium ustalony tygodnie przed pipeline'em A3.

### W2.1 — Corpus read API (C#)

Moduł `Klucz.Corpus` dostaje pierwszą prawdziwą treść (powstaje TU, nie w A3):

| Endpoint | Zwraca |
|---|---|
| `GET /corpus/forms` | lista form: kod, wariant, wersja, sesja, liczba zadań zatwierdzonych |
| `GET /corpus/forms/{id}/tasks` | zadania formy: numer, pula punktów, rodzaj, czy ma rysunek |
| `GET /corpus/tasks/{id}` | pełne drzewo: wersje z treścią, kryteria → warunki → zapisy (z MathJSON), wymagania, rozwiązania przykładowe, odpowiedzi wzorcowe, reguły arkusza z zakresem |
| `GET /corpus/assets/{id}` | wycinek PNG strumieniem przez `IBlobStore` |
| `GET /corpus/progress` | dla W2.3: statusy korekty per rocznik, pokrycie, statystyka półautomatu |

**Kroki**

1. Odczyt przez Npgsql w `Klucz.Corpus.Infrastructure` — plain SQL po widoku
   **`corpus_task`**, nie po `task` (definicja korpusu zostaje w schemacie; test
   architektury już pilnuje, że tylko Corpus dotyka Npgsql). Żadnego EF — C#
   ten schemat tylko czyta.
2. DTO odpowiedzi jako rekordy C# w `Klucz.Corpus` (Api je widzi; Contracts
   zostaje dla portów współdzielonych między modułami).
3. `GET /corpus/assets/{id}`: ścieżka względna z bazy → `IBlobStore.OpenAsync` —
   ochrona przed wyjściem poza korzeń już istnieje i jest tu pierwszym realnym
   konsumentem.
4. Po dodaniu endpointów: `task openapi:generate` + commit artefaktów — bramka
   dryfu (`test:contract`) pilnuje reszty.

### W2.2 — FE: przeglądarka korpusu

Lista arkuszy i zadań; podgląd zadania: treść, wycinek PNG, kryteria z progami
i alternatywami, wymagania; **obie wersje X/Y obok siebie** (do tego był podział
`task`/`task_version` — tu widać go pierwszy raz na ekranie). Konsument generowanego
`api-client`; narzędzie badawcze — zero stylowania ponad czytelność, routing
najprostszy możliwy (stan w URL wystarczy).

### W2.3 — FE: pulpit postępu ingestu

Pokrycie per rocznik, statusy korekty (pending / approved / corrected / rejected),
statystyka półautomatu na żywo z `GET /corpus/progress` — wykres do S8.
Progres A2 widoczny w przeglądarce na bieżąco.

**Zrobione, gdy:** zatwierdzone zadanie z pilotu da się obejrzeć w przeglądarce
z kryteriami i wycinkiem; pulpit pokazuje postęp korekty; bramka dryfu zielona.

---

## Tor G — golden set startuje razem z A2

Nie jest częścią bramki A2, ale **startuje w tygodniu 2** i pilnuje go rytm,
nie termin: po 2–3 własne odpowiedzi (poprawna, częściowa, błędna) na każde z 56
zadań otwartych — ~150 odpowiedzi, **2 roczniki tygodniowo**, ocena wg klucza
kryterium po kryterium, zapis jako JSON w `ingest/golden/` (część kontraktu
między warstwami). Wymaga wyłącznie klucza w PDF — nie czeka na korpus w bazie.
Golden set opóźniony o tydzień = A3 opóźnione o tydzień (G3.3 na niego czeka);
to jedyny zasób, którego nie da się kupić tokenami.

---

## Checklista domknięcia A2

- [ ] Każde zadanie wariantu 100 roczników 2019–2026 rozstrzygnięte:
      `review_status ≠ 'pending'`; korpus = `corpus_task`
- [ ] Rocznik 2019 przeszedł przez korektę bez błędów strukturalnych
      (dialekt, podwójne mapowanie 2012+2017)
- [ ] Ponowny `task ingest` nie nadpisuje skorygowanych kluczy — **zobaczone raz
      świadomie**, jak odmawia
- [ ] 84 zadania z rysunkiem mają wycinek PNG zamiast całej strony — automatem
      albo ręczną ramką, odsetek dróg zmierzony
- [ ] Zapisy równoważne mają MathJSON (`auto`/`approved`) albo świadome `failed`
- [ ] Opisy rysunków: każdy `asset` z `description_status='approved'` (S7 zmierzone)
- [ ] S6 zmierzone: zatwierdzenia bez poprawki, parser sam vs parser + LLM
- [ ] S8 zmierzone: czas korekty na zadanie i na rocznik, odsetek trafień parsera
- [ ] Decyzje zapisane: zawór po pilocie (G2.2.2), luki rekonstrukcji per luka
      (G2.3.2), zawężenie MathJSON do zapisów (G2.6)
- [ ] Raport kompletności per rocznik w `data/reports/` + kopia zbiorcza w `docs/`
- [ ] W2: zatwierdzone zadanie widoczne w przeglądarce (treść, kryteria, wycinek,
      X/Y obok siebie); pulpit postępu działa; bramka dryfu OpenAPI zielona
- [ ] Golden set (tor G) trzyma rytm 2 roczniki/tydzień — sprawdzone przy domykaniu,
      bo A3 na nim stoi

---

## Pułapki i decyzje do zapisania

**Do `DECYZJE.md` w trakcie A2** — rozstrzygnięcia, które mają nie wracać jako pytania:

| Decyzja | Uzasadnienie |
|---|---|
| Status korekty na `task`, konsumenci czytają widok `corpus_task` | zadanie jest jednostką pracy w ekranie; definicja „co jest korpusem" stoi w jednym miejscu schematu, nie w kodzie trzech warstw |
| `approved` ≠ `corrected` | odsetek trafień parsera (S6/S8) wprost ze statusów, bez rekonstrukcji z dziennika |
| Ekran korekty: FastAPI + Jinja2, zero build stepu i zero JavaScriptu | narzędzie na 3 tygodnie dla jednej osoby; React zostaje w `web/`, gdzie jest kontrakt OpenAPI. htmx z planu okazał się zbędny — dodawanie wierszy to `submit` tego samego formularza |
| Render PDF przez pypdfium2 | licencja Apache-2.0/BSD; PyMuPDF (AGPL) pozostaje zakazany |
| Ochrona rerunu: ingest pomija klucze po korekcie, `--nadpisz-korekte` wymusza | praca człowieka jest najdroższym zasobem A2; utrata cicha = najgorsza |
| MathJSON: Node CLI z `@cortex-js/compute-engine` | ten sam silnik co EvaluateClosed w A3 — zero dryfu dialektu; zawężenie do `condition_expression` (odpowiedzi zamkniętych to litery) |
| LLM proponuje, człowiek zatwierdza; model i koszt to parametry przebiegu | S6/S7 są pomiarami, nie wiarą; przebiegi masowe przez Batch API (−50%) |
| Cichy błąd naprawia się w parserze, widoczny wolno zostawić korekcie | kryterium z G2.3.2 — obowiązuje też dla przyszłych luk |

**Pięć rzeczy, które w A2 najłatwiej zepsuć**

1. **Rerun parsera kasujący korektę.** `loader.py` z założenia zastępuje własne
   zapisy — po pierwszej ręcznej poprawce to już nie jest idempotencja, tylko utrata
   danych. Ochrona wchodzi w G2.1.1, **przed** pierwszą poprawką, i raz się ją łamie
   świadomie, żeby zobaczyć odmowę.
2. **Migracje.** Zastosowanych plików nie wolno ruszać (SHA-256 w runnerze) — każda
   zmiana schematu to nowy plik; A2 zaczyna od 0004, bo 0003 zajęte.
3. **Ekran korekty puchnący w produkt.** Reguła stopu: widok jest zrobiony, gdy
   odpowiada na pytanie, dla którego powstał. Każda godzina w stylach ekranu korekty
   to godzina zdjęta z korekty właściwej — a to korekta jest ścieżką krytyczną alfy.
4. **LLM z ręką w bazie.** Prefill i opisy piszą wyłącznie stany `auto`; do korpusu
   wchodzi tylko to, co przeszło przez ekran. Wywołań LLM nie ma w CI — testy chodzą
   na utrwalonych odpowiedziach.
5. **`db:reset` a blob.** Reset bazy kasuje wolumeny Postgresa, ale **zostawia PNG
   w `data/blob/`** — po resecie ścieżki w świeżej bazie i pliki na dysku rozjeżdżają
   się po cichu. Czyszczenie blob robi narzędzie (komenda w ekranie korekty albo
   skrypt Pythona), nie `rm` w Taskfile — reguła z A1 obowiązuje.

---

*Plan A2 · uszczegółowienie `plan-implementacji-alfa.html` (grupa G2 + W2) · przy
sprzeczności ustępuje `DECYZJE.md` w repozytorium `cke-mirror`.*
