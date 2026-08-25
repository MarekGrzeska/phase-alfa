# ingest — warstwa Pythona

Offline ETL: PDF-y z mirrora CKE → rekordy w PostgreSQL i wycinki stron.
**Nie obsługuje żadnego ruchu użytkownika.** Uruchamiany ręcznie, jego wynikiem
są dane. C# czyta gotową strukturę i nigdy nie otwiera PDF-a.

```bash
task mirror -- --filtr matematyka   # zwózka (idempotentna, dosypuje brakujące)
task ingest -- --limit 8            # szybki przebieg parsera
task ingest -- --wyczysc            # cały zakres od zera (~2,5 min)
task test:python                    # ruff + pytest
```

## Układ

| Katalog | Co |
|---|---|
| `mirror/` | `cke_mirror.py` — zwózka z cke.gov.pl, buduje `data/index/urls.tsv` |
| `pdf/` | warstwa pozycyjna: `layout.py` (znaki, ramki, kreski; dwa silniki za jednym API) + `reconstruct.py` (ułamki, potęgi, NFKC, przypisy) |
| `parsers/omap_e8/` | parser matematyki E8: `parser.py` → `loader.py` → `run.py` |
| `schema/` | migracje SQL + runner — patrz [`schema/README.md`](schema/README.md) |
| `correction/` | ekran korekty (A2, jeszcze pusty) |
| `golden/` | golden set jako JSON (A3, jeszcze pusty) |
| `tests/` | regresja warstwy pozycyjnej, więzy schematu, ładowanie korpusu |

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
To jest test regresji parsera, nie tylko raport.

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
  czy ręczna korekta) należy do G2.3.2.
- **Pierwiastki** — znak jest glifem, ale „daszek" bywa linią; zasięg nie jest
  odtwarzany.
- **`bbox` zasobu to cała strona**, nie wycinek wokół rysunku — wykrywanie
  regionu grafiki to G2.4.
- **`mathjson` w `condition_expression` jest puste** — konwerter to G2.6.
- **Fixture'y testowe nie zawierają arkuszy CKE.** Testy oznaczone `mirror`
  pomijają się bez mirrora; PDF-y wejdą do repo najwcześniej po odpowiedzi
  na zapytanie o komercyjne użycie (G0.1).
