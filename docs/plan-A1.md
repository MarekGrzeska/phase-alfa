# Plan implementacji A1 — Szkielet (G1.1 – G1.5)

Rozpisanie kamienia **A1** z [Planu Implementacji Alfy](../README.md#plany) na konkretne
pliki, komendy i sprawdziany. Zakres: tydzień 1. Wszystko lokalnie, zero kosztów stałych,
**bez deployu na Azure** — to świadome odstępstwo od K1 z `DECYZJE.md`.

> **Definicja „zrobione" dla A1**
> Zielony pipeline od commita do działającego localhosta: `git clone` → `task up` → `task dev`
> podnosi bazę, API i web; `task test` przechodzi lokalnie i w CI; **dryf kontraktu OpenAPI
> łamie build**; parser z `research/` działa na Postgresie z tym samym pokryciem co w sondzie.

---

## Spis treści

- [Kolejność i równoległość](#kolejność-i-równoległość)
- [G1.1 — Fundament repo](#g11--fundament-repo) · [1.1.1](#g111--struktura-monorepo) [1.1.2](#g112--docker-compose--migracje-schematu) [1.1.3](#g113--taskfile)
- [G1.2 — Awans researchu do `ingest/`](#g12--awans-researchu-do-ingest) · [1.2.1](#g121--warstwa-pozycyjna--testy-regresji) [1.2.2](#g122--parser-kluczy-na-postgresie) [1.2.3](#g123--mirror)
- [G1.3 — Szkielet C#](#g13--szkielet-c) · [1.3.1](#g131--solution--test-architektury) [1.3.2](#g132--openapi--generowany-klient-ts) [1.3.3](#g133--iblobstore--konfiguracja)
- [G1.4 — Szkielet web](#g14--szkielet-web) · [1.4.1](#g141--packagescore--appsweb) [1.4.2](#g142--test-zero-dom)
- [G1.5 — CI](#g15--ci)
- [W1 — Plac startowy](#w1--plac-startowy-jedzie-w-tym-samym-tygodniu)
- [Checklista domknięcia A1](#checklista-domknięcia-a1)
- [Pułapki i decyzje do zapisania](#pułapki-i-decyzje-do-zapisania)

---

## Kolejność i równoległość

```
dzień 1        G1.1.1 struktura ──┬─► G1.1.2 docker + migracje
                                  └─► G1.1.3 Taskfile
                                        │
dni 2–4    ┌────────────────────────────┼────────────────────────────┐
           ▼                            ▼                            ▼
        G1.2 Python                  G1.3 C#                      G1.4 web
        (layout, parser,             (solution, test arch.,       (core, apps/web,
         Postgres)                    OpenAPI, IBlobStore)         test zero-DOM)
           │                            │                            │
           └────────────────────────────┼────────────────────────────┘
                                        ▼
dzień 5                            G1.5 CI ═► [A1 zamknięte]
                                        └─► W1 plac startowy
```

**Jedyny szew między frontami:** `web/packages/api-client` potrzebuje `openapi.json`
z G1.3.2. Dlatego front web zaczyna od `packages/core` i `apps/web` ze stubem klienta,
a generację wpina, gdy API wystawi pierwszy endpoint.

**G1.1 blokuje wszystko** — nie da się go zrównoleglić i nie warto próbować. To jeden dzień.

---

## G1.1 — Fundament repo

### G1.1.1 — Struktura monorepo

**Czeka na:** G0.3 (odstępstwa alfy dopisane do `DECYZJE.md`) · **Blokuje:** wszystko

Granica warstw ma być widoczna w drzewie katalogów, zanim powstanie pierwszy plik z kodem.

```
phase-alfa/
├── ingest/                     # PYTHON — offline ETL, zero ruchu użytkownika
│   ├── mirror/                 #   cke_mirror.py (gotowe, idempotentne)
│   ├── pdf/                    #   layout.py + reconstruct.py (awans z research/)
│   ├── parsers/                #   omap_e8.py — parser per segment, nie uniwersalny
│   ├── correction/             #   ekran korekty (A2 — na razie pusty katalog)
│   ├── schema/                 #   migracje SQL + runner
│   ├── golden/                 #   golden set jako JSON — część kontraktu (A3)
│   ├── tests/                  #   pytest: regresja parsera, więzy schematu
│   └── pyproject.toml
├── backend/
│   ├── Klucz.sln
│   ├── src/
│   │   ├── Klucz.Api/          #   ASP.NET Core, OpenAPI, kompozycja modułów
│   │   ├── Klucz.Contracts/    #   DTO + porty współdzielone, ZERO zależności
│   │   ├── Klucz.Corpus/       #   odczyt korpusu
│   │   ├── Klucz.Grading/      #   pipeline + port IGradingModel (A3)
│   │   └── Klucz.Learning/     #   mapa braków (A4)
│   └── tests/
│       ├── Klucz.ArchitectureTests/
│       └── Klucz.IntegrationTests/
├── web/
│   ├── packages/api-client/    #   generowany z OpenAPI — dryf łamie build
│   ├── packages/core/          #   czysty TS, zero DOM (test w CI)
│   ├── apps/web/               #   React PWA (Vite)
│   ├── package.json            #   pnpm workspaces
│   └── pnpm-workspace.yaml
├── data/                       # mirror · blob · raporty [gitignore]
│   ├── raw/                    #   PDF-y z mirrora CKE
│   ├── blob/                   #   wycinki PNG — ścieżki względne w bazie
│   └── raporty/
├── docs/
│   └── plan-A1.md              #   ten plik
├── .github/workflows/ci.yml
├── docker-compose.yml
├── Taskfile.yml
└── README.md
```

**Kroki**

1. Utworzyć drzewo katalogów; w pustych `.gitkeep`.
2. `data/` w `.gitignore` — z wyjątkiem inwentarza (już jest w `.gitignore`).
3. `.editorconfig` w korzeniu: LF, UTF-8, wcięcia (4 dla C#/Python, 2 dla TS/YAML).
   Na Windowsie **koniecznie** `core.autocrlf=input` albo `.gitattributes` z `* text=auto eol=lf`
   — inaczej fixture'y parsera będą się różnić bajtowo między maszyną a CI.

**Zrobione, gdy:** `git status` czysty, drzewo zgodne z powyższym, `.gitattributes` wymusza LF.

---

### G1.1.2 — Docker Compose + migracje schematu

**Czeka na:** G1.1.1 · **Równolegle z:** G1.1.3

PostgreSQL jest jedyną zależnością infrastrukturalną alfy.

`docker-compose.yml`:

```yaml
services:
  db:
    image: postgres:17-alpine
    container_name: klucz-db
    environment:
      POSTGRES_DB: klucz
      POSTGRES_USER: klucz
      POSTGRES_PASSWORD: klucz_dev
      # C.UTF-8, NIE pl_PL.UTF-8 — patrz uwaga o locale niżej
      POSTGRES_INITDB_ARGS: "--encoding=UTF8 --locale=C.UTF-8"
    ports:
      # Port KONFIGUROWALNY, nie zaszyty — patrz uwaga niżej
      - "${DB_PORT:-55434}:5432"
    volumes:
      - klucz-pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U klucz -d klucz"]
      interval: 3s
      timeout: 3s
      retries: 20

volumes:
  klucz-pgdata:
```

> **Port hosta jest konfigurowalny.** `55432` wydaje się bezpiecznie wysoki i nie jest —
> na maszynie deweloperskiej stoi zwykle kilka innych Postgresów w kontenerach
> (przy pierwszym `task up` port zajmował inny projekt). Stąd `${DB_PORT:-55434}`
> w compose i `DB_PORT` w `.env`: kolizja to zmiana jednej liczby, nie edycja
> pliku wersjonowanego.

> **Locale: cluster w `C.UTF-8`, polskie sortowanie przez ICU tam, gdzie jest potrzebne.**
> Obraz alpine stoi na musl, które **nie ma `pl_PL.UTF-8`** — `initdb` z takim locale
> po prostu nie wstanie. Zamiast walczyć z obrazem, cluster zostaje w `C.UTF-8`
> (szybkie, przenośne, identyczne na każdej maszynie i w CI), a polskie porządkowanie
> wchodzi jawnie tam, gdzie ma znaczenie — czyli przy sortowaniu treści zadań:
>
> ```sql
> -- migrations/0001_corpus.sql
> CREATE COLLATION IF NOT EXISTS pl_icu (provider = icu, locale = 'pl-PL');
> -- ... tresc text COLLATE pl_icu
> ```
>
> PostgreSQL 15+ ma ICU wkompilowane także w wariancie alpine. Alternatywa —
> `--locale-provider=icu --icu-locale=pl-PL` przy `initdb` — działa, ale ustawia
> to globalnie i wraca jako różnica przy każdej zmianie obrazu. Kolacja per kolumna
> jest jawna i widoczna w schemacie, czyli w kontrakcie.

**Migracje — plain SQL, nie ORM.** Schemat jest kontraktem między warstwami, więc
ma być czytelny jako SQL, a nie wyprowadzalny z modelu w którymkolwiek języku.
Żadnej Alembiki, żadnego EF Migrations — C# ten schemat **tylko czyta**.

```
ingest/schema/
├── migrations/
│   ├── 0001_corpus.sql          # schema.sql z research/ pocięty na kroki
│   ├── 0002_indexes.sql
│   └── 0003_status_korekty.sql  # (A2 — status per rekord)
├── migrate.py                   # runner: ~50 linii, psycopg, tabela schema_migrations
└── README.md
```

`migrate.py` — mechanika:

```python
# 1. CREATE TABLE IF NOT EXISTS schema_migrations (wersja text primary key,
#    zastosowano timestamptz not null default now(), suma_sha256 text not null)
# 2. Lista plików migrations/*.sql posortowana po nazwie.
# 3. Dla każdego: jeśli wersji nie ma w tabeli — wykonaj W JEDNEJ TRANSAKCJI
#    razem z INSERT-em do schema_migrations.
# 4. Jeśli wersja JEST, ale sha256 pliku się nie zgadza — przerwij z błędem.
#    Migracja już zastosowana nie może zmieniać treści.
```

**Kroki**

1. Przenieść `research/schema/schema.sql` → `ingest/schema/migrations/0001_corpus.sql`.
   Sprawdzić, czy DDL jest czysto Postgresowe (research pisał je jako PG DDL, ale sonda
   ładowała do SQLite — patrz pułapki w G1.2.2).
2. **Więzy zostają ostre.** `UNIQUE (task_id, points)` w `criterion` złapał prawdziwy
   błąd przy pierwszym ładowaniu (sekcja reguł przekrojowych udawała drugi próg 0 pkt).
   Nic nie luzować „żeby przeszło" — od tego jest ekran korekty w A2.
3. Napisać `migrate.py` i test: podniesienie pustej bazy → migracje → `\d` pokazuje
   komplet tabel (`exam_form_document`, `task`, `task_version`, `criterion`,
   `criterion_condition`, `condition_expression`, `model_answer`, `example_solution`,
   `rule`, `asset`, `requirement`, `requirement_regime`, `task_requirement`).
   Nazwy po angielsku wg słownika z `CLAUDE.md`; model bez zmian wobec sondy.
4. Connection string wyłącznie z konfiguracji (`.env` + `.env.example` w repo).
   Żadnych haseł w kodzie — nawet dev-owych.

**Zrobione, gdy:** `task up` na czystej maszynie stawia bazę ze schematem, `task db:reset`
odtwarza ją od zera, a druga próba migracji nic nie robi (idempotencja).

---

### G1.1.3 — Taskfile

**Czeka na:** G1.1.1 · **Równolegle z:** G1.1.2

**Wymaganie: ta sama komenda działa na Windows, macOS i w CI (Linux).**

**Taskfile, nie Makefile** — i to jest dokładnie powód. `make` na Windows to osobna
instalacja i osobne źródło różnic wobec reszty maszyn. [go-task](https://taskfile.dev)
jest jednym binarium bez zależności, a kluczowe: **ma wbudowany interpreter POSIX sh**
([mvdan/sh](https://github.com/mvdan/sh), napisany w Go). Składnia `&&`, `||`, potoki
i podstawienia zmiennych działa identycznie na Windows **bez instalowania bash-a**.
To znaczy, że jeden `Taskfile.yml` obsługuje wszystkie trzy platformy — nie ma wariantu
„dla Windows" i „dla Maca".

#### Instalacja — jeden sposób dla obu maszyn

| Platforma | Komenda |
|---|---|
| Windows | `winget install Task.Task` (albo `scoop install task`) |
| macOS | `brew install go-task/tap/go-task` |
| **obie naraz** | `npm i -g @go-task/cli` — Node i tak jest wymagany, więc to jedna komenda na każdej maszynie |

Wariant npm jest utrzymywany przez społeczność, nie przez zespół Task, i potrafi być
o wersję z tyłu. Dla alfy bez znaczenia; gdyby zaczęło przeszkadzać, `winget`/`brew`
są zawsze aktualne. Wersję Taska przypiąć w README, żeby obie maszyny gadały tym samym.

```yaml
version: '3'

dotenv: ['.env']

tasks:
  up:
    desc: Postgres + migracje schematu
    cmds:
      - docker compose up -d --wait
      - uv run python ingest/schema/migrate.py

  down:
    cmds: [docker compose down]

  db:reset:
    desc: Baza od zera (UWAGA: kasuje wolumen)
    prompt: Skasować wolumen z korpusem?
    cmds:
      - docker compose down -v
      - task: up

  dev:
    desc: API + web z hot-reloadem
    deps: [up]
    cmds:
      - task: dev:api
      - task: dev:web

  test:
    desc: Wszystkie testy deterministyczne
    cmds:
      - task: test:arch
      - task: test:dotnet
      - task: test:web
      - task: test:python
      - task: test:contract

  test:contract:
    desc: Dryf OpenAPI - regeneracja i porownanie z repo
    cmds:
      - task: openapi:generate
      - git diff --exit-code -- web/packages/api-client/

  ingest:   { cmds: [uv run python ingest/parsers/omap_e8.py] }   # A2
  bench:    { cmds: [dotnet run --project backend/tests/Klucz.Bench]} # A3
```

#### Pięć rzeczy, które łamią wieloplatformowość — i reguła na każdą

Interpreter POSIX załatwia **składnię**. Nie załatwia tego, że po drugiej stronie
komendy musi istnieć program. Stąd pięć twardych reguł dla tego Taskfile'a:

| # | Pułapka | Reguła |
|---|---|---|
| 1 | **`rm`, `cp`, `mkdir -p`, `touch` nie istnieją na Windows.** Task ma interpreter shella, nie coreutils — a Windows nie ma tych plików wykonywalnych | **Zero operacji na plikach w Taskfile.** Sprzątanie delegować do narzędzi, które to umieją same: `docker compose down -v`, `dotnet clean`, `pnpm store prune`. Gdy naprawdę trzeba — `{{if eq OS "windows"}}` albo `platforms: [windows]` na osobnym wariancie zadania |
| 2 | **`python` vs `python3`.** Na Windows binarką jest `python`, na macOS `python3` (samo `python` bywa nieobecne) | Zawsze `uv run python ...`. `uv` normalizuje to na obu i przy okazji trzyma lockfile — jedna zależność mniej do ustalania per maszyna |
| 3 | **Wielkość liter w ścieżkach.** macOS (APFS) i Windows są domyślnie **case-insensitive**, Linux w CI **case-sensitive** | Import z literówką w wielkości liter przechodzi lokalnie na **obu** maszynach i wywala się dopiero w CI. To nie jest argument za ostrożnością — to argument za tym, żeby CI był jedynym źródłem prawdy o zielonym buildzie |
| 4 | **Zakończenia linii.** Windows dopisze CRLF, macOS/Linux nie | `.gitattributes` z `* text=auto eol=lf` (G1.1.1). Bez tego fixture'y parsera różnią się bajtowo i pół dnia idzie na szukanie regresji, której nie ma |
| 5 | **Szimy `.cmd` na Windows.** `pnpm`, `npx` i spółka to na Windows pliki `.cmd`, nie `.exe` | Task rozwiązuje je przez `PATHEXT` i zwykle działa. Gdyby któryś się postawił — `platforms:` z jawnym wariantem. Sprawdzić raz, na starcie, a nie w trakcie debugowania czegoś innego |

Docker jest bezpieczny na obu: obraz `postgres:17-alpine` ma wariant `linux/arm64`,
więc Apple Silicon nie wymaga emulacji. Wolumen jest **nazwany**, nie bind-mountem —
na macOS bind-mount do kontenera potrafi być dramatycznie wolny, a nazwany wolumen nie.

#### `task setup` — sprawdzian środowiska

Przy dwóch maszynach opłaca się jedno zadanie, które mówi, czego brakuje, zamiast
pozwalać temu wyjść w połowie `task up`:

```yaml
  setup:
    desc: Sprawdza, czy maszyna ma komplet narzędzi
    silent: true
    cmds:
      - cmd: docker --version  || (echo "BRAK: Docker"        && exit 1)
      - cmd: dotnet --version  || (echo "BRAK: .NET SDK"      && exit 1)
      - cmd: node --version    || (echo "BRAK: Node.js"       && exit 1)
      - cmd: pnpm --version    || (echo "BRAK: pnpm"          && exit 1)
      - cmd: uv --version      || (echo "BRAK: uv"            && exit 1)
      - echo "OS={{OS}} ARCH={{ARCH}} — komplet."
```

`{{OS}}` i `{{ARCH}}` to zmienne Taska — działają bez `uname`, którego na Windows nie ma.

**Zrobione, gdy:** `task --list` pokazuje komplet, `task setup` przechodzi na obu
maszynach, `task test` przechodzi (na razie na pustych projektach), a CI woła
dokładnie te same nazwy zadań co maszyna lokalna.

---

## G1.2 — Awans researchu do `ingest/`

Kod z `research/` jest sprawdzony pomiarem, ale mieszka poza produktem i ładował do SQLite.
Awans to trzy rzeczy: przeniesienie, **testy regresji** i przepięcie na Postgres.

### G1.2.1 — Warstwa pozycyjna + testy regresji

**Czeka na:** G1.1 · **Równolegle z:** G1.3, G1.4

`research/layout.py` + `research/reconstruct.py` → `ingest/pdf/`.

**Kroki**

1. Przenieść oba pliki bez zmian logiki. Zmiana logiki i zmiana lokalizacji w jednym
   commicie to gwarancja, że nie da się odróżnić regresji od przeprowadzki.
2. Zależności do `pyproject.toml` (`uv`): `pdfplumber` (MIT), `pypdf` (BSD),
   `cryptography` (jeden klucz w korpusie — `MMAP-R0-100-2605-zasady.pdf` — jest
   zaszyfrowany AES z pustym hasłem właściciela; **obsłużyć jako przypadek, nie jako błąd**).
3. **Testy regresji na utrwalonych fixture'ach.** `research/bakeoff-wynik.txt` z 24.08.2026
   jest punktem odniesienia. Minimum, co ma być zamrożone testem:

   | Test | Oczekiwanie | Skąd |
   |---|---|---|
   | ułamek piętrowy | `7/15-(1/5+1/6)` na zadaniu 16 | bakeoff |
   | potęga | `P = 5² = 25 (cm²)`, nie `P = 52 = 25 (cm)` | research §2 |
   | scalanie serii | `k⁻¹⁰` → jedna wartość, nie `k^-^1^0` | `_scal_indeksy()` |
   | NFKC | U+1D465 → `x` | research §3 |
   | przypis w kryterium | 70 → 8 wystąpień na 75 kluczach | research §4 |
   | filtr tabel | brak ułamków typu `' '/'Liczba'` i `Uwagi/1` | ślepe uliczki |
   | zasięg | 3330/4472 kresek → ułamków (74,5%) | bakeoff |

4. Fixture'y PDF: **nie kopiować arkuszy do repo** (prawa CKE nierozstrzygnięte — G0.1).
   Testy pracują na plikach z `data/raw/`, a gdy mirror nie jest pobrany, `pytest.skip`
   z czytelnym powodem. Do CI trafia wariant offline: **utrwalone wyjścia** warstwy
   pozycyjnej (JSON ze znakami, ramkami i kreskami dla kilku stron) jako `ingest/tests/fixtures/`.
   To pozwala testować `reconstruct.py` bez ani jednego PDF-a w repozytorium.

**Znane luki — bez zmian w A1.** Liczby mieszane (`1⅔ km` → `12/3`) i pierwiastki
zostają nienaprawione; decyzja per luka („naprawa w kodzie czy ręczna korekta")
należy do G2.3.2. Tu tylko **udokumentować je testem oznaczonym `xfail`**, żeby
w A2 było widać, kiedy przestaje być czerwony.

**Zrobione, gdy:** `task test:python` przechodzi, a wynik jest identyczny z pomiarem
z 24.08.2026 — co do znaku.

---

### G1.2.2 — Parser kluczy na Postgresie

**Czeka na:** G1.1.2, G1.2.1 · **Równolegle z:** G1.3, G1.4

`research/schema/klucz.py` + `korpus.py` + `ingest.py` → `ingest/parsers/omap_e8/`.
Cel: ten sam przebieg co w sondzie, ale zapisujący do Postgresa z Dockera.

**Kroki**

1. Przenieść parser i ładowarkę; sprawdzian modelu z `probe_load.py` zostaje jako
   test integracyjny — po awansie nazywa się `ingest/tests/test_corpus_load.py`
   i chodzi pod pytestem, zamiast być osobnym skryptem.
2. **Port sqlite3 → psycopg.** Lista różnic, na których to się wywróci:

   | sqlite3 | psycopg / PostgreSQL |
   |---|---|
   | `?` jako placeholder | `%s` |
   | `cursor.lastrowid` | `INSERT ... RETURNING id` |
   | `INSERT OR IGNORE` | `INSERT ... ON CONFLICT DO NOTHING` |
   | `INTEGER PRIMARY KEY AUTOINCREMENT` | `GENERATED BY DEFAULT AS IDENTITY` |
   | boolean jako 0/1 | prawdziwy `boolean` |
   | text affinity — wszystko wchodzi | typy egzekwowane, `NULL` vs `''` boli |
   | autocommit domyślnie | transakcja jawna; **jeden klucz = jedna transakcja** |

3. **Jeden klucz w jednej transakcji.** Klucz, który wywalił się w połowie, nie może
   zostawić połowy zadań w bazie — inaczej raport pokrycia kłamie.
4. Przebieg kontrolny: `uv run python ingest/parsers/omap_e8/ingest.py` na 75 kluczach E8.
   Wynik ma się zgadzać z sondą z 25.08.2026:

   ```
   kluczy 75 · ~114 s (1,5 s/klucz) · zadań 1436 (2062 punkty)
   pokrycie wymagań 100% · odpowiedzi 100% · kryteriów 100%

   task 1436 · task_version 1574 · task_requirement 3809
   criterion 3315 · criterion_condition 4379 · condition_expression 514
   example_solution 1227 · model_answer 1221 · rule 772
   ```

   **Rozbieżność w tych liczbach = regresja przeprowadzki, nie ciekawostka.** Zapisać
   wynik do `data/reports/` i porównać z sondą, zanim cokolwiek dalej. (Katalog po
   angielsku — `.gitignore` i mirror używają `data/reports/`, nazwy plików i katalogów
   są w tym repozytorium po angielsku.) Robi to `run.py` sam: raport idzie na ekran
   i do `data/reports/ingest-RRRR-MM-DD.txt`.
5. Sekcja `SPÓJNOŚĆ` z `ingest.py` zostaje bez zmian — pyta o rzeczy, o które CHECK
   zapytać nie może. Znane, wytłumaczone wyniki (nie naprawiać w A1):
   - 1 próg ponad pulą — literówka CKE w `OMAP-900-2105`, parser oddaje dokument wiernie
   - 90 zadań bez progu 0 pkt — rocznik 2019 nie ma sekcji kryteriów dla zamkniętych
6. Test integracyjny w CI: `tests/test_corpus_load.py` na **jednym** kluczu
   (`OMAP-100-2505`) przeciwko Postgresowi w usłudze GitHub Actions
   (`.github/workflows/ci.yml`). Sześć testów modelu ma przejść,
   a liczby zgodzić się z sondą:
   `form=7 zadan=21 wersji=42 wymagan=58 kryteriow=51 warunkow=73 zapisow=14 odpowiedzi=30 rozwiazan=20 regul=17 zasobow=14`

**Zrobione, gdy:** pełny zakres 75 kluczy ładuje się do Postgresa z włączonymi więzami,
przy pokryciu 100/100/100, a test integracyjny na jednym kluczu jedzie w CI.

---

### G1.2.3 — Mirror

**Czeka na:** G1.1.1 · **Równolegle z:** wszystkim w G1

`cke_mirror.py` → `ingest/mirror/`. Kopiuj-wklej — kod jest gotowy i idempotentny,
2508 plików leży na dysku (43 101 stron, ~2,6 GiB).

**Kroki**

1. Przenieść, wpiąć w Taskfile jako `task mirror`.
2. Test uruchomienia: `--filtr matematyka --dry-run` wypisuje plan bez pobierania
   (flaga jest aliasem `--tylko-raport`; pilnuje jej `tests/test_mirror.py`).
3. Udokumentować w README zasadę **„mirror raz, potem tylko kopia"** — parser iteruje
   na lokalnych plikach, nigdy nie odpytuje cke.gov.pl w pętli.

**Zrobione, gdy:** `task mirror -- --dry-run` przechodzi, `data/raw/` nie wchodzi do gita.

---

## G1.3 — Szkielet C#

### G1.3.1 — Solution + test architektury

**Czeka na:** G1.1.1 · **Równolegle z:** G1.2, G1.4

Granice modułów mają być egzekwowane testem **od pierwszego commita**. Dokładanie
kolejnych modułów w A2–A4 ma być dopisywaniem, nie przebudową.

**Kierunek zależności**

```
Klucz.Api ────────► Corpus · Grading · Learning        (kompozycja, DI)
      │
      └───────────► Contracts

Corpus ─┐
Grading ─┼────────► Klucz.Contracts                    (DTO + porty)
Learning ┘

Klucz.Contracts ──► (nic — zero zależności zewnętrznych)
```

Moduły **nie widzą się nawzajem**. Gdy `Grading` będzie potrzebował kryteriów z `Corpus`
(A3), dostanie port `ICriteriaSource` w `Contracts`, a `Api` wstrzyknie implementację.
Ten sam wzorzec co `IGradingModel` i `IBlobStore` — jeden nawyk, nie trzy.

**Kroki**

1. `dotnet new sln -n Klucz`; pięć projektów `src/`, dwa `tests/`.
   `Directory.Build.props` w korzeniu: `<Nullable>enable</Nullable>`,
   `<TreatWarningsAsErrors>true</TreatWarningsAsErrors>`, `<LangVersion>latest</LangVersion>`.
   Wersję SDK przypiąć w `global.json` — CI i maszyna mają budować tym samym.
2. Test architektury (`Klucz.ArchitectureTests`, NetArchTest.Rules + xUnit):

   ```csharp
   // Nazwy testów po angielsku, jak cały kod (CLAUDE.md, zasada 4).
   [Fact]
   public void Modules_do_not_see_each_other()
   {
       string[] modules = ["Klucz.Corpus", "Klucz.Grading", "Klucz.Learning"];
       foreach (var module in modules)
       {
           var others = modules.Where(m => m != module).ToArray();
           var result = Types.InAssembly(Assembly.Load(module))
               .Should().NotHaveDependencyOnAny(others)
               .GetResult();
           Assert.True(result.IsSuccessful,
               $"{module} sięga do: {string.Join(", ", result.FailingTypeNames ?? [])}");
       }
   }

   [Fact] public void Nothing_depends_on_Api() { /* moduły + Contracts ↛ Klucz.Api */ }

   [Fact] public void Contracts_has_no_external_dependencies() { /* tylko BCL */ }

   [Fact]
   public void No_module_touches_the_database_directly()
       => /* Corpus.Infrastructure wyjątkiem; Grading i Learning ↛ Npgsql */;

   [Fact]
   public void Backend_does_not_parse_PDF()
       => /* żaden projekt ↛ pakiet z „Pdf" w nazwie — granica z DECYZJE.md */;
   ```

   Ostatni test jest tani i pilnuje najważniejszej reguły całego projektu:
   **C# nigdy nie otwiera PDF-a.**
3. `Klucz.Api`: minimal API, health check (`/health` — gotowość + ping do bazy),
   Serilog albo wbudowany logger ze strukturą.
4. Moduły dostają po jednej metodzie rozszerzającej `AddCorpus(...)` / `AddGrading(...)`
   / `AddLearning(...)` — `Program.cs` ma wołać trzy linijki, nie znać wnętrza modułów.

**Zrobione, gdy:** `dotnet test` zielony, a **ręcznie dodany nielegalny import zapala
test na czerwono** (sprawdzić to raz, świadomie — test architektury, którego nikt nie
widział na czerwono, jest dekoracją).

---

### G1.3.2 — OpenAPI → generowany klient TS

**Czeka na:** G1.3.1 · **Równolegle z:** G1.2

Kontrakt między backendem a webem generowany z C#. **Dryf łamie build** — to ma być
mechanizm, nie konwencja i nie dobre chęci.

**Kroki**

1. `Microsoft.AspNetCore.OpenApi` — dokument generowany przy buildzie do
   `backend/artifacts/openapi.json`. Wersję dokumentu przypiąć jawnie.
2. Plik `openapi.json` **wchodzi do repozytorium**. Jest artefaktem, ale wersjonowanym —
   dzięki temu zmiana kontraktu jest widoczna w diffie PR-a, a nie dopiero w CI.
3. Klient TS: `openapi-typescript` (typy) + `openapi-fetch` (cienki runtime).
   Wynik: `web/packages/api-client/src/schema.d.ts` + ręcznie pisany, cienki
   `client.ts` z konfiguracją `baseUrl`.
   *Alternatywa:* NSwag/Kiota, gdyby potrzebny był klient obiektowy — dla alfy nadmiar.
4. Zadanie `openapi:generate` w Taskfile: build API → eksport dokumentu → generacja typów.
5. **Bramka dryfu** (`task test:contract`, wołane też w CI):

   ```bash
   task openapi:generate
   git diff --exit-code -- backend/artifacts/openapi.json web/packages/api-client/
   ```

   Zmieniłeś API i nie przegenerowałeś klienta → czerwony build. Dokładnie o to chodzi.

**Zrobione, gdy:** dodanie pola do DTO bez regeneracji łamie build — sprawdzone ręcznie.

---

### G1.3.3 — `IBlobStore` + konfiguracja

**Czeka na:** G1.3.1 · **Równolegle z:** G1.3.2

Przeniesienie na Azure po alfie ma być **zmianą configu, nie architektury**.

**Kroki**

1. Port w `Klucz.Contracts`:

   ```csharp
   public interface IBlobStore
   {
       Task<Stream> OpenAsync(string path, CancellationToken ct = default);
       Task<string> SaveAsync(string path, Stream content, CancellationToken ct = default);
       Task<bool> ExistsAsync(string path, CancellationToken ct = default);
   }
   ```

2. `DiskBlobStore` — korzeń z konfiguracji (`Blob:Root` → `data/blob/`).
   **W bazie stoją ścieżki względne** (`omap/2505/zad-16-x.png`), nigdy absolutne
   i nigdy z literą dysku — inaczej korpus przestaje być przenośny.
3. **Ochrona przed wyjściem poza korzeń:** ścieżka po normalizacji musi zostawać
   wewnątrz `Blob:Root`. `..` w nazwie pliku z parsera nie jest scenariuszem
   z bajki, gdy nazwy biorą się z tekstu PDF-a.
4. Konfiguracja: `appsettings.json` + `appsettings.Development.json` + zmienne
   środowiskowe. Connection string **wyłącznie** ze zmiennych. `.env.example` w repo,
   `.env` w `.gitignore`.
5. Docelowy `AzureBlobStore` — nie w alfie. Ale interfejs ma już teraz nie zdradzać,
   że pod spodem jest dysk (żadnych `FileInfo` w sygnaturach).

**Zrobione, gdy:** test integracyjny zapisuje i odczytuje plik przez port,
a próba wyjścia poza korzeń rzuca wyjątek.

---

## G1.4 — Szkielet web

### G1.4.1 — `packages/core` + `apps/web`

**Czeka na:** G1.1.1 · **Równolegle z:** G1.2, G1.3

**Kroki**

1. pnpm workspaces (`web/pnpm-workspace.yaml`): `packages/*` + `apps/*`.
   pnpm, nie npm — twarde linki i rygorystyczne `node_modules` wyłapują
   przypadkowe zależności, których nie ma w `package.json`.
2. `packages/core` — czysty TypeScript, biblioteka. Tu mieszka logika sesji:
   stan odpowiedzi, kolejność zadań, walidacja przed wysyłką. **Zero Reacta,
   zero DOM.** To jedyna rzecz z fazy 2 (React Native), za którą alfa płaci
   z góry — po fakcie jest nie do odrobienia.
3. `apps/web` — Vite + React + TypeScript, PWA jako plugin (na razie bez
   agresywnego cache'owania — service worker trzymający stary build to
   ostatnia rzecz, jakiej trzeba przy iteracji co kilka minut).
4. Vitest w obu paczkach. W `apps/web` środowisko `jsdom`, w `packages/core`
   **`node`** — to pierwsza z dwóch warstw ochrony przed DOM-em.
5. Proxy dev servera na API (`/api` → `localhost:5xxx`), żeby nie było CORS-u
   w developmencie.

**Zrobione, gdy:** `task dev` podnosi web z HMR, `packages/core` buduje się osobno.

---

### G1.4.2 — Test zero-DOM

**Czeka na:** G1.4.1 · **Równolegle z:** G1.3

Reguła „`packages/core` bez DOM od pierwszego dnia" ma być egzekwowana
**przez kompilator**, nie przez pamięć.

**Warstwa 1 — tsconfig (mechanizm właściwy).** `web/packages/core/tsconfig.json`:

```jsonc
{
  "compilerOptions": {
    "lib": ["ES2022"],          // BEZ "DOM" — `document` przestaje istnieć w typach
    "types": [],                // bez @types/node — żadnego `process`, `Buffer`
    "strict": true,
    "noEmit": true,             // emisja stoi osobno, w tsconfig.build.json
    "moduleResolution": "bundler"
  },
  "include": ["src"]            // sam produkt; testy mają tsconfig.test.json
}
```

Emisja `dist/` idzie przez osobny `tsconfig.build.json` (`noEmit: false`,
`declaration: true`) — dzięki temu testy da się typecheckować bez wrzucania ich
do zbudowanego pakietu.

Po tym `document.querySelector(...)` w `core` **nie kompiluje się**.
Nie „powinno się nie kompilować" — nie kompiluje się.

**Warstwa 2 — test zależności.** `packages/core/package.json` nie może mieć
w `dependencies` niczego DOM-owego. Test w CI:

```ts
// web/packages/core/test/zero-dom.test.ts
const FORBIDDEN = ["react", "react-dom", "mathlive", "@vitejs/plugin-react"];
// czyta package.json, sprawdza dependencies + peerDependencies + devDependencies
```

Do tego reguła odwrócona, która nie wymaga pilnowania listy: `dependencies`
i `peerDependencies` mają być **puste**.

**Warstwa 3 (opcjonalna) — skan źródeł** na `document.` / `window.` / `navigator.`
jako komunikat po ludzku („`packages/core` nie może dotykać DOM — przenieś do `apps/web`"),
bo błąd kompilatora bywa mniej wymowny niż zdanie.

**Zrobione, gdy:** `document` w `packages/core` łamie `task test:web` — sprawdzone
ręcznie na jednej linijce, którą się potem usuwa.

---

## G1.5 — CI

**Czeka na:** G1.2 – G1.4 · **Domyka kamień**

Na każdy push, za darmo, deterministycznie. **Benchmark LLM nie wchodzi do CI w A1** —
dochodzi jako przebieg nocny w A3.

> **Uwaga o limicie.** Repozytorium jest **prywatne**, więc minuty GitHub Actions
> liczą się do darmowego limitu konta (2000 min/mc na planie Free), inaczej niż
> w repo publicznym. To zmienia rachunek z Planu Alfy. Konsekwencje: cache'ować
> zależności (NuGet, pnpm, uv), nie odpalać macierzy systemów operacyjnych,
> a test integracyjny Postgresa robić na **jednym** kluczu, nie na 75.

`.github/workflows/ci.yml` — cztery zadania równoległe:

| Zadanie | Co robi | Czas |
|---|---|---|
| `dotnet` | build + testy architektury + testy jednostkowe | ~2 min |
| `web` | typecheck (w tym zero-DOM przez tsconfig) + vitest + build | ~1,5 min |
| `python` | ruff + pytest na utrwalonych fixture'ach warstwy pozycyjnej | ~1 min |
| `contract` | regeneracja OpenAPI + `git diff --exit-code` | ~1,5 min |

Zadanie `python` odpala usługę Postgresa i test integracyjny na jednym kluczu
(więzy schematu + sześć testów modelu z `probe_load.py`):

```yaml
  python:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:17-alpine
        env: { POSTGRES_DB: klucz, POSTGRES_USER: klucz, POSTGRES_PASSWORD: klucz_dev }
        options: >-
          --health-cmd "pg_isready -U klucz" --health-interval 3s
          --health-timeout 3s --health-retries 20
        ports: ['5432:5432']
```

**Kroki**

1. Cztery zadania, każde z cache'em; `concurrency` z `cancel-in-progress: true`,
   żeby kolejny push ubijał poprzedni przebieg (oszczędność minut).

   > **Poprawka z implementacji.** Wyzwalacz `push: ['**']` razem z `pull_request`
   > odpalał DWA przebiegi tego samego commita, gdy gałąź miała otwarty PR — czyli
   > podwójny rachunek za tę samą informację. Jest więc `push` tylko na `main`
   > plus `pull_request`. `cancel-in-progress` obowiązuje wyłącznie na PR-ach:
   > na `main` każdy przebieg opisuje stan, który zostaje, więc nie wolno go ubijać.
   > Do cache'u NuGeta dochodzą wersjonowane `packages.lock.json` i
   > `dotnet restore --locked-mode` — inaczej „cache" nie miałby stabilnego klucza,
   > a restore nie miałby czego pilnować.
2. `permissions: contents: read` — minimalne uprawnienia tokena.
3. Ochrona gałęzi `main`: wymagane przejście wszystkich czterech zadań.
4. **Sprawdzian klonu od zera** — raz, ręcznie, przed zamknięciem A1:
   świeży katalog → `git clone` → `task up` → `task dev` → `/health` odpowiada,
   web się otwiera. Jeśli po drodze potrzeba było kroku spoza README, README kłamie.

**Zrobione, gdy:** zielony pipeline od commita do działającego localhosta,
a każdy z czterech sprawdzianów widziało się raz na czerwono z właściwego powodu.

---

## W1 — Plac startowy (jedzie w tym samym tygodniu)

Formalnie tor W, ale mieści się w A1 i domyka pętlę „widzę postęp".

**Czeka na:** G1.3.2, G1.4.1

Widok statusu w `apps/web`: ping API, wersja zastosowanej migracji, liczniki rekordów
w bazie (na starcie same zera — i dobrze, bo w A2 zaczną rosnąć na oczach).

Wartość nie jest kosmetyczna: to **pierwszy realny konsument generowanego klienta OpenAPI**,
czyli smoke test całego kontraktu end-to-end w tygodniu 1, a nie w tygodniu 7.

---

## Checklista domknięcia A1

- [ ] `git clone` → `task setup` → `task up` → `task dev` działa **na Windows i na macOS**, bez kroków spoza README i bez wariantów Taskfile'a per platforma
- [ ] `task test` zielony lokalnie i w CI (4 zadania)
- [ ] Test architektury widziany na czerwono przy nielegalnym imporcie
- [ ] Test zero-DOM widziany na czerwono przy `document` w `packages/core`
- [ ] Bramka dryfu OpenAPI widziana na czerwono przy zmianie DTO bez regeneracji
- [ ] Regresja parsera zgodna z `bakeoff-wynik.txt` co do znaku
- [ ] 75 kluczy E8 ładuje się do Postgresa: 1436 zadań, pokrycie 100/100/100
- [ ] `/health` odpowiada, W1 pokazuje liczniki bazy w przeglądarce
- [ ] `data/` nie wchodzi do gita; `.env` nie wchodzi do gita
- [ ] **G0.1 (CKE) i G0.2 (PARP) wysłane** — nie są częścią kodu, ale są częścią tygodnia 1

---

## Pułapki i decyzje do zapisania

**Do `DECYZJE.md` przed startem (G0.3)** — trzy odstępstwa alfy z datą, żeby agenci
nie „naprawiali" braku deployu: K1 bez Azure, K5 w całości za alfą, benchmark bramką
merge dopiero po alfie.

**Do `DECYZJE.md` po A1** — rozstrzygnięcia podjęte tutaj, żeby nie wracały jako pytania:

| Decyzja | Uzasadnienie |
|---|---|
| Taskfile zamiast Makefile | wbudowany interpreter POSIX sh — **jeden plik obsługuje Windows, macOS i CI**, bez bash-a na Windows i bez wariantów per platforma |
| Zero operacji na plikach w Taskfile | `rm`/`cp`/`mkdir -p` nie istnieją na Windows; sprzątanie robią narzędzia same |
| Cluster w `C.UTF-8`, kolacja `pl_icu` per kolumna | musl w obrazie alpine nie ma `pl_PL.UTF-8`; polskie sortowanie jawne w schemacie, czyli w kontrakcie |
| Migracje plain SQL + własny runner | schemat jest kontraktem — ma być czytelny jako SQL; C# go tylko czyta |
| `openapi.json` wersjonowany w repo | zmiana kontraktu widoczna w diffie PR-a, nie dopiero w CI |
| pnpm zamiast npm | rygorystyczne `node_modules` wyłapuje niezadeklarowane zależności |
| Port hosta przez `${DB_PORT:-55434}`, nie zaszyty | wysoki numer nie gwarantuje wolnego portu — sprawdzone boleśnie: 55432 zajmował inny projekt w kontenerze |
| Zero-DOM przez `lib: ["ES2022"]` | egzekwuje kompilator, nie code review |

**Trzy rzeczy, które w A1 najłatwiej przeoczyć**

1. **Różnice między maszynami.** Komplet pułapek Windows ↔ macOS ↔ CI stoi w tabeli
   przy [G1.1.3](#g113--taskfile). Dwie najdroższe: brak `.gitattributes` (CRLF psuje
   fixture'y parsera) i wielkość liter w ścieżkach — literówka przechodzi lokalnie
   na **obu** maszynach, a wywala się dopiero na Linuksie w CI.
2. **Testy, których nikt nie widział na czerwono.** Test architektury, zero-DOM
   i bramka dryfu — każdy trzeba raz świadomie złamać. Test, który zawsze był zielony,
   jest nieodróżnialny od testu, który nic nie sprawdza.
3. **Cicha zmiana logiki przy przeprowadzce.** `research/` → `ingest/` ma być
   przeniesieniem, nie refaktorem. Liczby z sondy (1436 zadań, 100/100/100, 3330/4472)
   są jedynym sposobem, żeby to sprawdzić — i działają tylko wtedy, gdy nic po drodze
   nie „poprawiono przy okazji".

---

*Plan A1 · uszczegółowienie `plan-implementacji-alfa.html` (grupa G1) · przy sprzeczności
ustępuje `DECYZJE.md` w repozytorium `cke-mirror`.*
