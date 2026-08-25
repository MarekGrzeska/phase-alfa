# ingest — warstwa Pythona

Offline ETL: PDF-y z mirrora CKE → rekordy w PostgreSQL i wycinki stron.
**Nie obsługuje żadnego ruchu użytkownika.** Uruchamiany ręcznie, jego wynikiem
są dane. C# czyta gotową strukturę i nigdy nie otwiera PDF-a.

```bash
task mirror -- --filtr matematyka   # zwózka (idempotentna, dosypuje brakujące)
task mirror -- --dry-run            # nic nie pobiera: raport z tego, co leży na dysku
task ingest -- --limit 8            # szybki przebieg parsera
task ingest -- --wyczysc            # cały zakres od zera (~2,5 min)
task correction                     # ekran korekty na localhoście (G2.1)
task correction:report              # pomiar S8 do data/reports/
task test:python                    # ruff + pytest
```

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
| `pdf/` | warstwa pozycyjna: `layout.py` (znaki, ramki, kreski; dwa silniki za jednym API) + `reconstruct.py` (ułamki, potęgi, NFKC, przypisy) |
| `parsers/omap_e8/` | parser matematyki E8: `parser.py` → `loader.py` → `run.py` |
| `schema/` | migracje SQL + runner — patrz [`schema/README.md`](schema/README.md) |
| `correction/` | ekran korekty: `app.py` (FastAPI) → `db.py` (SQL) → `stats.py` (S8) |
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
(`data/reports/ingest-RRRR-MM-DD.txt`, inne miejsce przez `--raport`) — porównanie
z sondą „z pamięci" nie jest porównaniem.

Ponowne uruchomienie jest bezpieczne: klucz zastępuje to, co sam zapisał poprzednio
(kasowane są jego zadania i reguły, dokument wchodzi przez `ON CONFLICT (url)`).
`--wyczysc` jest do czyszczenia CAŁEGO korpusu, nie do powtórki jednego przebiegu.

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
task ingest -- --wyczysc                     # odmawia, gdy w korpusie jest korekta
```

Pominięcie nie jest błędem: im dalej w A2, tym więcej kluczy przebieg omija, a raport
wypisuje je wprost — cicho pominięty klucz wyglądałby w raporcie tak samo jak załadowany.
Bramka siedzi w `loader._wyczysc_klucz`, tuż przed `DELETE`, więc obowiązuje każdą drogę
do niego: runner, testy i ekran. Runner dokłada do tego zapytanie wstępne, żeby pominięty
klucz nie kosztował 1,5 s parsowania.

Dziennik `correction_event` przeżywa przeładowanie (`ON DELETE SET NULL`): pomiar S8 jest
wynikiem alfy i nie ma znikać razem z zadaniami, bo wiersz bez zadania wciąż niesie czas
i rodzaj decyzji.

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
- **90 zadań bez progu 0 pkt** — rocznik 2019 (6 kluczy × 15 zadań zamkniętych).
  Ten układ dokumentu nie ma dla zadań zamkniętych sekcji kryteriów w ogóle.

## Ograniczenia, które zostają po G1.2

- **Liczby mieszane** — `1⅔ km` wychodzi jako `12/3`. Decyzja (naprawa w kodzie
  czy ręczna korekta) należy do G2.3.2. Zamrożone testem `xfail` — zapali się
  na zielono w dniu naprawy.
- **Pierwiastki** — znak jest glifem, ale „daszek" bywa linią; zasięg nie jest
  odtwarzany. Też `xfail`.
- **`bbox` zasobu to cała strona**, nie wycinek wokół rysunku — wykrywanie
  regionu grafiki to G2.4.
- **`mathjson` w `condition_expression` jest puste** — konwerter to G2.6.
- **Fixture'y testowe nie zawierają arkuszy CKE.** Testy oznaczone `mirror`
  pomijają się bez mirrora; PDF-y wejdą do repo najwcześniej po odpowiedzi
  na zapytanie o komercyjne użycie (G0.1). Regresję rekonstrukcji trzyma
  zamiast nich zrzut trzech stron (`tests/fixtures/strony-omap-100-2505.json`):
  znaki, kreski i tabele, z których `reconstruct` odtwarza ten sam tekst.
  Test `test_zrzut_zgadza_sie_z_plikiem` (oznaczony `mirror`) pilnuje, żeby
  zrzut nie rozjechał się z plikiem źródłowym.
