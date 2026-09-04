# Plan A2-auto — korekta korpusu modelem, człowiek wyrywkowo

Stan na 4.09.2026. Decyzja autora: **w fazie MVP model rozstrzyga rekordy, człowiek
sprawdza próbkę.** Podstawa: podpowiedzi `task prefill` na roczniku 2025 (6 zadań otwartych,
$0,07) obejrzane ręcznie w wielu miejscach zgadzały się z kluczem. Niedoskonałość
korpusu na tym etapie jest akceptowana świadomie.

To odwraca dwa zdania z `DECYZJE.md` i `CLAUDE.md`: „nic z modelu nie wchodzi do korpusu
z pominięciem bramki" oraz „LLM proponuje, człowiek zatwierdza". Plan robi to tak, żeby
decyzja była **odwracalna** i **widoczna w schemacie**: każdy rekord niesie, kto go
rozstrzygnął. Powrót do korekty ręcznej to jedno zapytanie, nie archeologia.

> **Definicja „zrobione" dla A2-auto**
> Wariant 100 roczników 2019–2026 w `corpus_task` (159 zadań), każdy z `reviewed_by`
> równym `model` albo `human`; kolejka `unsure` pusta albo rozstrzygnięta ręcznie; zasoby
> z ramką i opisem `auto`; golden set wygenerowany z oznaczonym autorem i oceniającym;
> raport kompletności rozbity na człowieka i model; wpis w `DECYZJE.md`.

---

## Co zostaje ręką, a co idzie do modelu

| Praca ręczna z planu A2 | Po zmianie | Człowiek |
|---|---|---|
| Korekta 159 zadań (odpowiedzi, kryteria, wymagania) | `task verify` — model porównuje rekord ze stroną klucza i rozstrzyga | próbka 10% (16 zadań) + kolejka `unsure` |
| 49 ramek „cała strona" | `task frame` — model czyta siatkę i oddaje bbox | rzut oka na wycinki w przeglądarce W2 |
| 607 opisów rysunków | `task describe` już istnieje; konsumenci przyjmują status `auto` | próbka 20 opisów, żeby S7 miało liczbę |
| 100 odmów MathJSON | bez zmian w MVP — A3 traktuje `failed` jak warunek tekstowy | nic |
| Golden set ~150 odpowiedzi | model A pisze odpowiedzi, model B ocenia wg kryteriów | próbka 10 zadań oceniona ręcznie |
| Decyzja z zaworu G2.2.2 | bezprzedmiotowa — A2 zamyka się w dwa dni | wpis w `DECYZJE.md` |

Golden set ma zastrzeżenie, którego automat nie zdejmie: jeśli ten sam model pisze,
ocenia i potem jest oceniany w A3, benchmark mierzy zgodność modelu z samym sobą. Stąd
**dwie różne rodziny modeli** (autor ≠ oceniający ≠ oceniany w A3) i próbka ludzka, na której
liczy się rozrzut. W MVP benchmark odpowiada na pytanie „czy silnik jest spójny
z niezależną oceną modelu", nie „czy ocenia jak nauczyciel". To wraca przy golden secie
nauczycielskim (próg beta).

---

## Klocki

### X1 — Migracja `0009_review_actor.sql`

```sql
ALTER TABLE task
    ADD COLUMN reviewed_by text NOT NULL DEFAULT 'human'
        CHECK (reviewed_by IN ('human', 'model')),
    ADD COLUMN review_model text;          -- np. 'openai:gpt-5.6-terra', NULL dla człowieka

ALTER TABLE correction_event
    ADD COLUMN actor text NOT NULL DEFAULT 'human'
        CHECK (actor IN ('human', 'model')),
    ADD COLUMN model text,
    ADD COLUMN verdict text                -- 'match' | 'fix' | 'unsure', tylko dla modelu
        CHECK (verdict IS NULL OR verdict IN ('match', 'fix', 'unsure'));
```

Widok `corpus_task` **bez zmian**: `approved` i `corrected` wchodzą do korpusu niezależnie
od tego, kto rozstrzygnął. Statystyka S8 filtruje `actor = 'human'`, więc dotychczasowe
liczby nie mieszają się z automatem. `db.decide` dostaje parametr `actor` i `model`.

**Zrobione, gdy:** migracja wchodzi na bazę z danymi; test więzu odrzuca `reviewed_by = 'llm'`.

### X2 — `correction/verify.py` — drugi czytelnik, który rozstrzyga

Wejście dla jednego zadania: rekord w tym samym kształcie co formularz ekranu (numer,
pula, rodzaj, treść, odpowiedzi, progi → warunki → zapisy, wymagania) plus **obraz strony
klucza** z `pages.render(task.document_path, task.page)` (i strony następnej, gdy zadanie
kończy się na krawędzi). Wyjście ze structured output:

```python
class Verdict(BaseModel):
    verdict: Literal["match", "fix", "unsure"]
    reasons: list[str]                  # po polsku, do dziennika i do raportu
    record: TaskRecord | None           # pełny rekord po poprawce, tylko przy "fix"
```

`TaskRecord` rozszerza schemat z `prefill.py` (progi → warunki → zapisy) o odpowiedzi
wzorcowe i wymagania. Zasada: **model oddaje cały rekord, nie diff** — różnicę liczy
`db.save`, tak samo jak dla człowieka, więc status `approved`/`corrected` wychodzi
z porównania z bazą, a nie z deklaracji modelu.

Przebieg:

1. `match` → `db.decide(..., "approve", actor="model")`. Status `approved`.
2. `fix` → rekord przepisany na słownik formularza (`task.number`, `answer.<id>.answer`,
   `criterion.<id>.points`, wiersze nowe przez `add_criterion`/`add_condition`/
   `add_expression`, kasowanie przez `delete.<tabela>.<id>`), potem `db.save` + `decide`.
   Status `corrected`. `ValidationError` albo więz bazy → transakcja cofnięta, zadanie
   ląduje w `unsure` z powodem. **Więzów nie luzujemy** — rekord, którego baza nie
   przyjmuje, jest robotą dla człowieka, nie dla `--force`.
3. `unsure` → zadanie zostaje `pending`, wpis w `correction_event` z `verdict = 'unsure'`
   i powodem. Ekran korekty pokazuje te powody nad kryteriami (ten sam pasek co `hints`).

Polecenie:

```bash
task verify -- --year 2025 --variant 100              # raport, bez zapisu
task verify -- --year 2025 --variant 100 --apply      # rozstrzyga
task verify -- --variant 100 --apply --batch          # cały wariant, Batch API
```

Raport (`data/reports/verify-RRRR-MM-DD.txt`): match / fix / unsure per rocznik,
najczęstsze powody `fix` i `unsure`, tokeny i koszt. Wywołań LLM **nie ma w CI**; testy
chodzą na utrwalonych odpowiedziach w `tests/fixtures/`, jak dla prefillu.

**Zrobione, gdy:** dry-run na 2025/100 pokrywa się z tym, co autor obejrzał przy 6
podpowiedziach prefillu; `--apply` na 2025/100 zostawia zero `pending` poza `unsure`.

### X3 — `correction/frame.py` — ramka z siatki

Dla zasobów z `framed = false`: obraz strony z siatką (`pages.render(..., grid=True)`),
prośba o cztery liczby (`x0`, `top`, `x1`, `bottom`) w punktach PDF, walidacja
`assets.BOX_FIELDS` jak w formularzu, cięcie tą samą funkcją co „Wytnij". Zasób dostaje
`bbox`, wycinek trafia do bloba. 49 sztuk, jeden przebieg.

**Zrobione, gdy:** `corpus:report` pokazuje 0 zasobów z ramką „cała strona".

### X4 — Opisy rysunków: `auto` jest dobre dla konsumentów

`task describe -- --variant 100 --batch` już działa. Zmiana jest po stronie odbiorców:
C# (`CorpusContracts.Asset.DescriptionStatus`) i przeglądarka W2 traktują `auto` jak
opis użyteczny, z etykietą „opis modelu". `approved`/`corrected` zostają jako stany
wyższe dla próbki ludzkiej.

**Zrobione, gdy:** 607 zasobów ma opis; 20 z wariantu 100 sprawdzonych ręcznie
w ekranie — to jedyna liczba S7, jaka zostaje.

### X5 — Golden set generowany: `golden/generate.py` + `golden/grade.py`

`generate.py`: dla każdego zadania otwartego wariantu 100 (56) model **A** pisze trzy
odpowiedzi ucznia: pełną, częściową, błędną. Wejście: treść zadania z `task_version`,
wycinek rysunku albo jego opis, bez klucza. `grade.py`: model **B** (inna rodzina) ocenia
każdą wg kryteriów z `corpus_task`, próg po progu, z cytatem. Zapis:

```
ingest/golden/2025/task-18.json
{ "exam_form": "OMAP-100-2505", "task": 18,
  "answers": [ { "kind": "full", "text": "...", "author": "model:openai:gpt-5.6-terra",
                 "points": 3, "grader": "model:anthropic:claude-opus-5",
                 "criteria": [ {"criterion": "3 pkt", "met": true, "quote": "..."} ] } ] }
```

Pola `author` i `grader` są obowiązkowe; wartość `human` oznacza ręczną pracę. Próbka:
10 zadań ocenionych ręcznie przez autora obok oceny modelu B — z tego wychodzi
rozrzut, który A3 raportuje przy każdej liczbie zgodności.

**Zrobione, gdy:** 56 plików, każdy z trzema odpowiedziami i oceną; 10 z nich ma
drugą ocenę `human`.

### X6 — Raporty i pomiary po nowemu

`corpus:report` i `correction:report` dostają rozbicie `human` / `model`. Pytania
badawcze zmieniają treść, nie numer:

| Było | Jest w MVP |
|---|---|
| S6 — czy podpowiedź przyspiesza człowieka | **S6′** — zgodność modelu z człowiekiem na próbce 16 zadań (odsetek `match` potwierdzonych, `fix` przyjętych bez zmiany) |
| S7 — opisy zatwierdzone bez poprawki | bez zmian, na próbce 20 zasobów |
| S8 — koszt półautomatu (mediana czasu × zadania) | **S8′** — koszt automatu: dolary na zadanie, odsetek `unsure`, czas człowieka na próbkę |

To są liczby do wniosku: „model rozstrzyga 159 zadań za ~$3 przy zgodności X% z próbką
ludzką" jest mocniejszym zdaniem niż mediana czasu klikania.

### X7 — Higiena decyzji

Wpis w `DECYZJE.md` z datą 4.09.2026: co odwrócono, dlaczego (tempo MVP), czym się to
kończy (kolumna `reviewed_by`, powrót do korekty ręcznej = `UPDATE ... WHERE reviewed_by
= 'model'`), i co zostaje bez zmian (więzy ostre, `corpus_task` jako jedyna definicja
korpusu, model jako parametr przebiegu). Poprawka w `CLAUDE.md`, sekcja „Granica warstw":
LLM w ingeście rozstrzyga, ale wyłącznie przez `db.save`/`db.decide`, nigdy SQL-em obok.

---

## Kolejność — trzy dni

| Dzień | Co | Wynik |
|---|---|---|
| 1 | X1 migracja · X2 `verify.py` · dry-run 2025/100 · porównanie z 6 podpowiedziami prefillu | raport `verify`, decyzja „jedziemy" |
| 2 | X2 `--apply` na wariancie 100 · X3 ramki · X4 opisy · X6 raporty · próbka 16 zadań w ekranie | **A2 zamknięte dla MVP** |
| 3 | X5 golden set · próbka 10 zadań · X7 `DECYZJE.md` | **A3 startuje** (G3.1) |

Pozostałe warianty (1277 zadań) — jeden przebieg nocny `--batch` po zamknięciu A2, gdy
przeglądarka i A3 potwierdzą, że korpus wariantu 100 się trzyma. Nie wcześniej: błąd
systematyczny w promptcie na 159 zadaniach naprawia się w godzinę, na 1436 w dzień.

## Koszt

| Przebieg | Sztuk | Szacunek |
|---|---|---|
| `verify` wariant 100 (obraz strony + rekord, ~4k tok. wejścia, ~1,5k wyjścia) | 159 | ~$3 |
| `frame` | 49 | <$1 |
| `describe --batch` | 607 | ~$3 |
| golden `generate` + `grade` | 56 × 3 | ~$2 |
| `verify` wszystkie warianty, `--batch` | 1277 | ~$12 |

Miara z prefillu: $0,012 na zadanie otwarte bez obrazu. Z obrazem strony 2–3× więcej.

## Dziennik wykonania

| Data | Co | Wynik |
|---|---|---|
| 4.09 | X1 migracja 0009, X2 `task verify`, X6 raport (gałąź `feat/a2-auto`) | 96 testów zielonych |
| 4.09 | dry-run #1 na 2025/100 ($0,46) | 18 `fix`, w tym 15 to **błąd parsera**: blok „Rozwiązanie – wersja X/Y" w warunku 0 pkt, 1346/1346 zadań zamkniętych 2020+ |
| 4.09 | naprawa w parserze (G2.3.2: cichy błąd → kod), przeładowanie korpusu | liczby zadań/kryteriów/warunków/odpowiedzi bez zmian; `notes` 444→397 (reguły ogólne przestały być uwagą ostatniego zadania) |
| 4.09 | dry-run #3 po przeładowaniu ($0,42) | 17 `match`, 4 `fix`, 0 `unsure` — cztery prawdziwe usterki w otwartych |
| 4.09 | `--apply` 2025/100 ($0,40) | 18 `approved`, 3 `corrected`, `reviewed_by = model` |
| 4.09 | `--apply` reszta wariantu 100 (138 zadań, $2,54) | 118 `approved`, 20 `corrected`, 0 `unsure` |
| 4.09 | **wariant 100 w korpusie** | 159 zadań: 136 `approved`, 23 `corrected`; `reviewed_by = model` 100%; koszt $2,94, ~$0,018 na zadanie |

Wniosek z pierwszego dnia: dry-run na jednym roczniku przed `--apply` jest obowiązkowy.
Błąd systematyczny widać po powtarzalnym powodzie w `reasons`; naprawia się go w parserze,
nie płaci modelowi 1436 razy.

X4 (opisy `auto`) nie wymaga zmian w C# ani w webie: przeglądarka W2 pokazuje
`asset.description` niezależnie od statusu, a licznik „opisów zatwierdzonych" zostaje
liczbą S7 z próbki ludzkiej.

## Ryzyka, które zostają

- **Błąd cichy.** Reguła z G2.3.2 („cichy naprawia się w kodzie") zakładała, że człowiek
  zobaczy głośny. Teraz oba typy przechodzą przez model. Zawór: A3 na golden secie wyłapie
  kryteria, przy których silnik systematycznie się myli — to wskazuje rekordy do ręki.
- **Model ocenia własną robotę.** Prefill i verify tym samym modelem to ta sama para oczu
  dwa razy. `verify` domyślnie bierze inny model niż prefill (`--model` jest parametrem).
- **Więzy bazy jako ostatnia bramka.** `UNIQUE (task_id, points)` i reszta odrzucają
  śmieci modelu tak samo jak śmieci parsera. Rekord odrzucony przez więz idzie do `unsure`,
  nie jest wymuszany.
- **Liczby do wniosku.** S6/S7/S8 w pierwotnym kształcie przepadają. S6′/S8′ są do obrony,
  jeśli próbka ludzka istnieje. Bez próbki nie ma żadnej liczby — próbka nie jest opcją.
