# ingest — warstwa Pythona

Offline ETL: PDF-y z mirrora CKE → rekordy w PostgreSQL i wycinki stron.
**Nie obsługuje żadnego ruchu użytkownika.** Uruchamiany ręcznie, jego wynikiem
są dane. C# czyta gotową strukturę i nigdy nie otwiera PDF-a.

```bash
task mirror -- --filtr matematyka   # zwózka (idempotentna, dosypuje brakujące)
task mirror -- --dry-run            # nic nie pobiera: raport z tego, co leży na dysku
task ingest -- --limit 8            # szybki przebieg parsera
task ingest -- --wipe               # cały zakres od zera (~2,5 min)
task ingest -- --year 2025 --variant 100 --with-papers   # pilot G2.2: jeden klucz z treściami
task correction                     # ekran korekty na localhoście (G2.1)
task correction:report              # pomiary S6, S7, S8 do data/reports/
task crops                          # dotnij brakujące wycinki PNG (G2.4)
task crops -- --prune               # skasuj pliki, do których nie prowadzi żaden zasób
task mathjson                       # zapisy równoważne → MathJSON (G2.6)
task prefill -- --year 2025 --limit 20    # podpowiedzi LLM, próbka S6 (płatne)
task describe -- --year 2025 --batch      # opisy rysunków, S7 (płatne)
task verify -- --year 2025 --variant 100          # drugi czytelnik: raport na sucho (płatne)
task verify -- --year 2025 --variant 100 --apply  # …i rozstrzyga w bazie (plan A2-auto)
task frame -- --variant 100 --apply               # ramki „cała strona” → ramka z siatki przez model (X3)
task corpus:report                  # kompletność korpusu — domknięcie A2 (G2.7)
task parser:snapshot -- --baseline ../data/reports/parser-przed.json
task test:python                    # ruff + pytest
```

Flagi runnera są po angielsku (`--wipe`, `--with-papers`, `--engine`, `--verbose`,
`--report`, `--code`, `--year`, `--variant`) — zasada 4 z `CLAUDE.md`. **Mirror ich
jeszcze nie ma** (`--filtr`, `--rocznik`, `--tylko-spis`, `--cicho`): ten sam plik
stoi w repozytorium `cke-mirror`, więc przemianowanie wymaga zmiany w obu miejscach
naraz i schodzi osobno.

## Mirror raz, potem tylko kopia

Parser iteruje po **lokalnych plikach** i nigdy nie odpytuje `cke.gov.pl` w pętli.
Zwózka jest osobnym, ręcznym krokiem: raz pobrane 2508 plików (43 101 stron, ~2,6 GiB)
zostaje na dysku, a kolejne uruchomienie `task mirror` dosypuje tylko to, czego brakuje.

Korzeń mirrora wskazuje `MIRROR_ROOT` z `.env` — ta sama wartość dla mirrora, parsera
i testów (reguła stoi w [`sciezki.py`](sciezki.py), w jednym miejscu). Gdy mirror masz
już pobrany obok, ustaw `MIRROR_ROOT=../cke-mirror` zamiast pobierać go drugi raz.

## Układ

| Katalog | Co |
|---|---|
| `mirror/` | `cke_mirror.py` — zwózka z cke.gov.pl, buduje `data/index/urls.tsv` |
| `pdf/` | warstwa pozycyjna: `layout.py` (znaki, ramki, kreski, kształty; dwa silniki za jednym API) + `reconstruct.py` (ułamki, potęgi, NFKC, przypisy) + `regions.py` (region grafiki) + `crop.py` (wycinek PNG) |
| `parsers/omap_e8/` | parser matematyki E8: `parser.py` → `loader.py` → `run.py`; obok `crops.py` (wycinki) i `snapshot.py` (regresja bez bazy) |
| `mathjson/` | konwerter zapisów równoważnych: `normalize.py` (Python) → `convert.mjs` (Node) → `fill.py` |
| `schema/` | migracje SQL + runner — patrz [`schema/README.md`](schema/README.md) |
| `correction/` | ekran korekty: `app.py` (FastAPI) → `db.py` (SQL) → `stats.py` (S6/S7/S8); `prefill.py` i `describe.py` to warstwa LLM |
| `reports/` | `corpus.py` — raport kompletności korpusu, liczony po widoku `corpus_task` |
| `golden/` | golden set jako JSON (A3, jeszcze pusty) |
| `tests/` | regresja warstwy pozycyjnej, więzy schematu, ładowanie korpusu, mirror |
| `tests/fixtures/` | zrzuty stron (JSON) — regresja rekonstrukcji bez ani jednego PDF-a |
| `sciezki.py` | korzeń repo i korzeń mirrora — jedno miejsce dla runnera, mirrora i testów |

## Podział ról w `parsers/omap_e8/`

**`parser.py`** czyta PDF i zwraca obiekty `Klucz`. Nie dotyka bazy — ani jednego
`INSERT`. Awansował z `research/` **bez zmian logiki**, bo tylko wtedy liczby
z sondy mogą cokolwiek udowodnić.

**`loader.py`** zamienia te obiekty na wiersze. Jest zarazem **tłumaczem
słownika**: parser mówi językiem dokumentu (`zamkniete`, `zasady_oceniania`),
bo czyta polskie klucze CKE, a schemat mówi po angielsku (`closed`,
`marking_scheme`). Przekład stoi w jednym miejscu, w postaci słowników na górze
pliku — nie rozsypany po kodzie parsera.

**`run.py`** to punkt wejścia: czyta spis, woła parser, ładuje, drukuje raport
pokrycia i **zwraca kod 1**, gdy którykolwiek klucz spadł poniżej progów.
To jest test regresji parsera, nie tylko raport. Raport ląduje też na dysku
(`data/reports/ingest-RRRR-MM-DD.txt`, inne miejsce przez `--report`) — porównanie
z sondą „z pamięci" nie jest porównaniem.

Ponowne uruchomienie jest bezpieczne: klucz zastępuje to, co sam zapisał poprzednio
(kasowane są jego zadania i reguły, dokument wchodzi przez `ON CONFLICT (url)`).
`--wipe` jest do czyszczenia CAŁEGO korpusu, nie do powtórki jednego przebiegu.

## Ekran korekty — bramka między parserem a korpusem

Parser produkuje **kandydatów**, nie korpus. Rekord wchodzi do korpusu dopiero wtedy,
gdy człowiek go rozstrzygnie w ekranie (`task correction`, domyślnie
`http://localhost:8600`). Kolejność z `DECYZJE.md`: najpierw ekran korekty, potem parser.

| Status `task.review_status` | Znaczy |
|---|---|
| `pending` | parser zapisał, nikt nie patrzył — **poza korpusem** |
| `approved` | człowiek zatwierdził **bez zmian** — trafienie parsera |
| `corrected` | człowiek poprawił i zatwierdził |
| `rejected` | rekord nie do uratowania — **poza korpusem**, dziura do zaraportowania |

Konsumenci korpusu (moduł `Corpus` w C#, pipeline w A3) czytają widok **`corpus_task`**,
nigdy wprost z `task`. Dzięki temu definicja „co jest korpusem" stoi w jednym miejscu
schematu, zamiast być powtórzona w kodzie trzech warstw.

**`approved` i `corrected` to dwa stany, bo różnica między nimi jest wynikiem badawczym.**
Odsetek zadań, które parser trafił sam, to pomiar S8 (koszt półautomatu) i liczba do
wniosku grantowego. Statusu nie da się przekłamać: ekran ma jeden przycisk „Zatwierdź",
a o tym, który stan zapisać, decyduje **porównanie formularza z bazą**, nie deklaracja
człowieka.

`task correction:report` zrzuca te liczby do `data/reports/correction-RRRR-MM-DD.txt`:
stan, mediana czasu na zadanie, prognozę reszty. Prognoza mnoży medianę, a nie średnią —
formularz zostawiony otwarty na noc wchodzi do dziennika jako praca.

### Ponowny ingest nie kasuje korekty

`loader` przy powtórce klucza kasuje jego zadania i wstawia od nowa — i to jest poprawne,
dopóki nikt tych rekordów nie tknął. Po pierwszej ręcznej poprawce ta sama linijka kasuje
**pracę człowieka**, czyli najdroższy zasób całego A2. Dlatego:

```bash
task ingest                                  # klucze po korekcie POMIJA, wypisuje które
task ingest -- --overwrite-reviewed          # przeładowuje je, KASUJĄC rozstrzygnięcia
task ingest -- --wipe                     # odmawia, gdy w korpusie jest korekta
```

Pominięcie nie jest błędem: im dalej w A2, tym więcej kluczy przebieg omija, a raport
wypisuje je wprost — cicho pominięty klucz wyglądałby w raporcie tak samo jak załadowany.
Bramka siedzi w `loader._wyczysc_klucz`, tuż przed `DELETE`, więc obowiązuje każdą drogę
do niego: runner, testy i ekran. Runner dokłada do tego zapytanie wstępne, żeby pominięty
klucz nie kosztował 1,5 s parsowania.

Dziennik `correction_event` przeżywa przeładowanie (`ON DELETE SET NULL`): pomiar S8 jest
wynikiem alfy i nie ma znikać razem z zadaniami, bo wiersz bez zadania wciąż niesie czas
i rodzaj decyzji.

**Czego bramka NIE łapie: `--with-papers` pominięte w powtórce.** Zadania `pending`
przeładowują się bez pytania — i jeśli poprzedni przebieg czytał zeszyty, a ten nie,
klucz zostaje bez `task_version.content` i bez ani jednego `asset`. Widać to dopiero
w ekranie, po pustej treści zadania. Klucz raz wczytany z arkuszami wczytuje się z nimi
zawsze.

### Wycinki graficzne — ręczna ramka (G2.4.2)

Zadanie z rysunkiem ma w widoku kartę „Wycinki graficzne": po lewej strona **zeszytu
zadań** z siatką współrzędnych (kreska co 50 pt, podpis co 100), po prawej wycinek.
Ramkę wpisuje się w cztery pola — `x0`, `top`, `x1`, `bottom` w punktach PDF, liczone
od **lewego górnego** rogu strony — i klika „Wytnij".

```
data/blob/OMAP/2025-05-14/100/X/z1-0.png     # ścieżka z asset.path, względna
```

Cięcie robi `pdf/crop.py` (200 DPI) i to ta sama funkcja, której użyje automat
wykrywania regionu z G2.4.1: automat i ręczna ramka różnią się wyłącznie tym, skąd
bierze się `bbox`. „Wytnij" nie rozstrzyga zadania — ramkę dociąga się na raty,
a wpis w dzienniku S8 powstaje dopiero przy zatwierdzeniu. Zmiana ramki liczy się
jako poprawka, więc nie zasili S6 jako trafienie parsera.

Licznik „wycinków w blobie" na stronie głównej mówi, ile zostało: definicja „zrobione"
dla G2.4.2 to **zero zadań z rysunkiem bez wycinka**.

### Numery stron są liczone od 1

`task.page`, `task_version.page` i `asset.page` trzymają numer strony taki, jaki stoi
w stopce PDF-a. Warstwa pozycyjna (`pdf/layout.py`) indeksuje strony **od zera** i ten
indeks szedł kiedyś wprost do bazy — podgląd pokazywał wtedy stronę wcześniejszą niż
rekord, co wygląda wiarygodnie i dlatego długo nie rzucało się w oczy. Korpus wczytany
przed tą poprawką trzeba przeładować.

### Zakres pracy w ekranie

Rocznik, kod i wariant filtrują listę **oraz** przycisk „Następne do korekty" —
i jadą dalej w adresie (`/next?year=2025&variant=100`). Bez zakresu przycisk bierze
pierwsze czekające zadanie z całego korpusu, więc pilot jednego rocznika kończyłby się
na pierwszym zapisie.

## Uruchamianie modułami, nie ścieżkami

```bash
uv run python -m parsers.omap_e8.run     # dobrze
uv run python parsers/omap_e8/run.py     # źle
```

Korzeniem pakietu jest `ingest/`, więc `pdf.layout`, `parsers.omap_e8.parser`
i `schema.migrate` widzą się nawzajem. Uruchomienie przez ścieżkę ustawia
`sys.path` na katalog pliku i importy między pakietami się sypią.

## Przebieg kontrolny — liczby, które mają się zgadzać

Ten sam wynik co sonda z 25.08.2026. **Rozjazd znaczy regresję, nie „inny wynik".**

```
kluczy 75 · zadań 1436 (2062 punkty)
pokrycie wymagań 100% · odpowiedzi 100% · kryteriów 100%

task 1436 · task_version 1574 · task_requirement 3809
criterion 3315 · criterion_condition 4379 · condition_expression 514
example_solution 1227 · model_answer 1221 · rule 772
```

Przebieg trwa ~2,5 min zamiast 114 s z sondy — bo baza stoi w kontenerze
i chodzi po TCP, zamiast siedzieć w pamięci procesu jak SQLite.

## Znane wyniki, które NIE są błędami

Sekcja `SPÓJNOŚĆ` w raporcie zadaje pytania, których `CHECK` zadać nie może.
Dwa niezerowe wyniki mają wytłumaczenie w dokumentach, nie w parserze:

- **1 próg ponad pulą** — literówka CKE w `OMAP-900-2105`: nagłówek `(0–2)`,
  a kryterium za 3 punkty. Parser oddaje dokument wiernie; gdyby to naprawiał,
  błąd zniknąłby z pola widzenia.
- **90 zadań zamkniętych bez kryteriów** — rocznik 2019 (6 kluczy × 15 zadań).
  Ten układ dokumentu nie ma dla zadań zamkniętych sekcji kryteriów w ogóle,
  więc od G2.3.1 stoi to w raporcie w **osobnym wierszu, bez progu alarmu**,
  a liczniki „bez progu 0 pkt" pytają wyłącznie o zadania, które jakieś kryteria
  mają. Ekran korekty mówi to samo przy pustej liście: „norma dokumentu" kontra
  „dziura". Rozstrzyga POMIAR z dokumentu, nie rocznik wpisany w kod — w 2019 r.
  warianty 800 i Q00 te sekcje mają.

## Ograniczenia i to, co z nich zostało

- **Liczby mieszane** — naprawione w G2.3.2. `1⅔ km` to jedna wartość, więc
  ułamek stojący tuż za cyfrą dostaje odstęp; sklejone `12/3` wyglądało jak
  poprawny ułamek o innej wartości, czyli było błędem CICHYM. `xfail` zgasł.
- **Pierwiastki** — **świadomie zostają ręcznej korekcie** (decyzja G2.3.2).
  Zasięg „daszka" jest niejednoznaczny, wystąpień mało, a brak domknięcia widać
  w ekranie przy zapisie. `xfail` zostaje z powodem „ŚWIADOMIE: korekta ręczna",
  a konwerter MathJSON odmawia takich zapisów wprost, zamiast zgadywać zasięg.
- **`bbox` zasobu** — od G2.4.1 to ramka wokół rysunku, nie cała strona.
  Zmierzone na całym korpusie: 558 z 607 zasobów ma ramkę z automatu, 49 (8%)
  czeka na ręczne dociągnięcie w ekranie.
- **`mathjson`** — od G2.6 wypełnione dla 414 z 514 zapisów; 100 pozostałych ma
  status `failed` z powodem po polsku, widoczny w ekranie korekty jako robota
  do zrobienia.
- **Fixture'y testowe nie zawierają arkuszy CKE.** Testy oznaczone `mirror`
  pomijają się bez mirrora; PDF-y wejdą do repo najwcześniej po odpowiedzi
  na zapytanie o komercyjne użycie (G0.1). Regresję rekonstrukcji trzyma
  zamiast nich zrzut trzech stron (`tests/fixtures/strony-omap-100-2505.json`):
  znaki, kreski i tabele, z których `reconstruct` odtwarza ten sam tekst.
  Test `test_zrzut_zgadza_sie_z_plikiem` (oznaczony `mirror`) pilnuje, żeby
  zrzut nie rozjechał się z plikiem źródłowym. Wykrywanie regionu ma własny
  zrzut trzech stron ZESZYTU (`arkusz-omap-100-x-2505.json`) — z kształtami,
  bo pułapki tego kroku są geometryczne i nie da się ich wymyślić.
- **Wywołań LLM nie ma w CI.** `task prefill` i `task describe` są ręczne
  i płatne; testy chodzą na utrwalonych odpowiedziach.

## Wykrywanie regionu graficznego (G2.4.1)

Automat czyta obiekty graficzne z warstwy pozycyjnej, ogranicza je do **pionowego
pasa zadania** i klastruje do skutku — diagram to zwykle kilkadziesiąt kresek,
które mają zostać JEDNYM zasobem. Trzy filtry śmieci, każdy zmierzony na arkuszu:

| Śmieć | Jak wygląda | Reguła |
|---|---|---|
| kreska pod odpowiedź ucznia | prostokąt 13,7 × 0,5 pt, 4479 sztuk na stronie | krótki i cienki naraz |
| pasek pod nagłówkiem zadania | 456,6 × 14,6 pt | **dokładnie** szerokość kolumny tekstu |
| tabela „Prawda / Fałsz" | siatka na pełną szerokość kolumny | klaster ≥ 0,97 kolumny |

Filtrowania po wykrytych tabelach **nie ma świadomie**: pdfplumber widzi w wykresie
słupkowym tabelę o dziewięciu wierszach, więc odsiewanie po nich skasowałoby właśnie
tę grafikę, o którą chodzi. Wykres z 2025 r. zajmuje 0,86 szerokości kolumny, tabela
odpowiedzi 0,99 — próg rozdziela je z zapasem.

Gdy automat nie domknie, zasób zostaje z ramką całej strony i przejmuje go ręczne
dociągnięcie z G2.4.2. To zawór, nie awaria.

Cięcie PNG stoi **poza transakcją ładowania** (`parsers/omap_e8/crops.py`): dysk nie
cofa się razem z transakcją, więc plik wycięty przed nieudanym zapisem zostawałby
z ramką, której w bazie nie ma. To samo narzędzie sprząta bloba po `task db:reset` —
reset kasuje wolumen Postgresa, a pliki PNG zostawia:

```bash
task crops              # dotnij brakujące
task crops -- --prune   # skasuj osierocone pliki
```

## MathJSON (G2.6)

```bash
task mathjson:setup                  # jedyna zależność: @cortex-js/compute-engine
task mathjson -- --year 2025         # pilot na jednym roczniku
task mathjson                        # całe 514 zapisów
```

Bez MathJSON-a Compute Engine w A3 porównuje **stringi**, więc `2(x+1)` i `2x+2`
są dla niego dwiema różnymi odpowiedziami. Podział ról nie jest wygodą:

- **normalizacja tekstu CKE na LaTeX stoi w Pythonie** (`mathjson/normalize.py`),
  bo to tam rodzą się pomyłki — `∶` (U+2236) znaczy dzielenie, przecinek jest
  dziesiętny, ułamek z rekonstrukcji jest liniowy — i tam da się je przetestować
  bez Node'a, czyli także w CI;
- **parsowanie w Node** (`convert.mjs`), bo `@cortex-js/compute-engine` jest
  referencyjną implementacją MathJSON i tym samym silnikiem, którego użyje A3.

Trzy sita przed konwersją istnieją po to, żeby NIE powstał błąd cichy: ucięcie
polskiego ogona („lub zapisy równoważne"), odmowa dla zdania („zapisanie P=15"
weszłoby jako iloczyn dziewięciu symboli — MathJSON poprawny i bezwartościowy)
i odmowa przy pierwiastku.

| Status | Znaczy |
|---|---|
| `none` | jeszcze nie próbowano |
| `auto` | konwerter przerobił, nikt nie sprawdzał |
| `approved` | człowiek potwierdził w ekranie korekty |
| `failed` | konwerter nie ugryzł — **jawny stan**, z powodem w `mathjson_error` |

## LLM w ingeście (G2.5) — ręcznie i za pieniądze

**Model proponuje, człowiek zatwierdza.** Nic stąd nie wchodzi do korpusu bez bramki
ekranu korekty, a provenance niesie schemat (`prefill_suggestion`,
`description_status='auto'`), nie pamięć autora.

```bash
task prefill -- --year 2025 --variant 100 --limit 20            # próbka S6
task describe -- --year 2025 --variant 100 --batch              # opisy, S7
task prefill -- --model openai:gpt-5.6-luna --limit 20          # porównanie modeli
task describe -- --model anthropic:claude-opus-5 --limit 5      # inny dostawca
```

Wywołania idą przez **LangChain** (`init_chat_model`), więc `prefill.py` i `describe.py`
nie wiedzą, czyje API jest pod spodem. **Dostawca i model to jeden parametr przebiegu**
(`--model dostawca:nazwa`), a ta sama wartość jest kluczem cennika:

| `--model` | rola | za MTok (wejście/wyjście) | klucz w `.env` |
|---|---|---|---|
| `openai:gpt-5.6-terra` *(domyślny)* | mocniejszy | $2 / $12 | `OPENAI_API_KEY` |
| `openai:gpt-5.6-luna` | słabszy | $0,20 / $1,20 | `OPENAI_API_KEY` |
| `anthropic:claude-opus-5` | inny dostawca | $5 / $25 | `ANTHROPIC_API_KEY` |
| `anthropic:claude-haiku-4-5` | inny dostawca | $1 / $5 | `ANTHROPIC_API_KEY` |

Para pomiarowa to **terra kontra luna**: dziesięciokrotna różnica ceny przy tej samej
rodzinie modeli. Czy słabszy wystarczy do prefillu i opisów, rozstrzygają S6 i S7,
a nie założenie. Klucz stoi wyłącznie w `.env`, wzór w `.env.example`.

**Batch API jest wyjątkiem od LangChaina.** `Runnable.batch()` to zrównoleglenie po
stronie klienta — te same żądania i **ta sama cena**. Prawdziwy wsad (−50%, okno 24 h)
to osobny endpoint dostawcy, więc `--batch` schodzi do surowego SDK (`llm.py`, sekcja
„przebieg wsadowy") i na dziś ma adapter dla `openai`. Inny dostawca z `--batch`
dostaje jawną odmowę z instrukcją, zamiast po cichu zapłacić pełną stawkę.
Przebiegi masowe i tak czyta się następnego dnia w ekranie, więc wsad jest tu domyślnym
wyborem dla całego rocznika.

Pomiar S6 nie potrzebuje pamiętania, kiedy prefill był włączony: **ramię wyznacza
istnienie wiersza w `prefill_suggestion`**, a odsetek zatwierdzeń bez poprawki i czas
na zadanie liczy `task correction:report` z dziennika korekty.

### Drugi czytelnik rozstrzyga — `task verify` (plan A2-auto)

Decyzja MVP z 4.09.2026 (`docs/plan-A2-auto.md`): **model rozstrzyga rekordy,
człowiek sprawdza próbkę.** Model dostaje rekord zadania w kształcie formularza
ekranu korekty i obrazy stron klucza (od strony zadania do początku następnego,
najwyżej pięć), oddaje werdykt:

| werdykt | co się dzieje |
|---|---|
| `match` | `db.decide("approve")` jak „Zatwierdź" człowieka → `approved` |
| `fix` | pełny rekord po poprawce → `db.save` + `db.decide` → `corrected` |
| `unsure` | zadanie zostaje `pending`; powody w dzienniku i nad formularzem w ekranie |

Zapis idzie **tą samą drogą co u człowieka**, więc status wynika z porównania z bazą,
a więzy schematu odrzucają śmieci modelu tak samo jak śmieci parsera — rekord
odrzucony przez więz ląduje w `unsure`, więzów nie luzujemy. Kto rozstrzygnął, niesie
schemat (migracja 0009): `task.reviewed_by`, `task.review_model`,
`correction_event.actor`. Powrót do korekty ręcznej:

```sql
UPDATE task SET review_status = 'pending' WHERE reviewed_by = 'model';
```

```bash
task verify -- --year 2025 --variant 100                 # raport + JSON, bez zapisu
task verify -- --year 2025 --variant 100 --apply         # rozstrzyga
task verify -- --variant 100 --apply --batch --limit 200 # cały wariant, Batch API
task verify -- --retry-unsure --apply                    # drugie podejście do unsure
```

Wymagania podstawy programowej są dla modelu kontekstem, nie przedmiotem edycji —
różnicę zgłasza w `reasons`. Odpowiedzi wzorcowych nie dokłada (formularz tego nie umie),
poprawia albo kasuje istniejące. `task corpus:report` rozbija korpus na człowieka i model.

Pierwszy przebieg na sucho (2025/100, $0,46) wykrył błąd systematyczny **parsera**, nie
modelu: blok „Rozwiązanie – wersja X/Y" wchodził do warunku za 0 pkt w każdym zadaniu
zamkniętym 2020+. Naprawione w parserze, nie 1346 razy modelem — reguła z G2.3.2.

## Raport kompletności korpusu (G2.7)

```bash
task corpus:report                    # do data/reports/
task corpus:report -- --copy-to-docs  # kopia zbiorcza do repozytorium
```

Trzynaście liczników „co jest" i sześć pytań o BRAK, każdy liczony **dwa razy**:
po widoku `corpus_task` i po całej tabeli `task`. Druga kolumna nie jest ozdobnikiem —
bez niej raport z pustego korpusu wygląda dokładnie tak samo jak raport z korpusu,
którego nikt nie sparsował, a **różnica między kolumnami JEST pracą, która została
do zrobienia w ekranie korekty**.

## Regresja parsera bez bazy

```bash
task parser:snapshot -- --out ../data/reports/parser-przed.json
# ...poprawka w parserze...
task parser:snapshot -- --baseline ../data/reports/parser-przed.json
```

Reguła z G2.3.1: po każdej poprawce parsera idzie przebieg kontrolny wszystkich
75 kluczy. Poprawka dla rocznika 2019 nie ma prawa ruszyć liczb 2020–2026, a zrzut
łapie to w dwie minuty — w ekranie korekty ta sama regresja kosztuje dzień. Zrzut
trzyma liczniki **i skróty treści**, bo sama liczba kryteriów nie odróżnia „tyle samo
progów" od „tyle samo progów o innym tekście".
