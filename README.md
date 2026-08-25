# Projekt Klucz — Faza Alfa

Repozytorium implementacyjne fazy alfa: POC lokalny dla jednej osoby (autora).
Cała pętla **zadanie → ocena wg klucza CKE → mapa braków** ma zamknąć się na jednym
komputerze, bez środowiska produkcyjnego i bez stałych kosztów infrastruktury.

Dwie warstwy o twardej granicy:

- **`ingest/`** — Python, offline ETL. Wynik: rekordy w PostgreSQL i wycinki stron.
  Nie obsługuje żadnego ruchu użytkownika.
- **`backend/`** — C#, modularny monolit. Czyta gotową strukturę, **nigdy nie parsuje PDF-a**.
- **`web/`** — React PWA + TypeScript, monorepo z generowanym klientem OpenAPI.

Kontraktem między warstwami jest **schemat bazy plus pliki JSON golden setu**, nie API.

## Stan

| Kamień | Zakres | Status |
|---|---|---|
| **A1** | Szkielet: monorepo, Postgres w Dockerze, monolit C# z granicami modułów, OpenAPI → klient TS, CI | G1.1 ✓ · G1.2 ✓ · G1.3 ✓ · G1.4 ✓ · G1.5 ✓ |
| **A2** | Korpus: ekran korekty → parser OMAP E8 2019–2026 → zatwierdzone rekordy w bazie | G2.1 ✓ |
| A3 | Grading: pipeline 5 kroków, golden set, benchmark, macierz eksperymentów | |
| A4 / W4 | Sesja zadań, mapa braków, telemetria, sprawdzian od zera | |

Tory równoległe: **F** (formalności — CKE, PARP), **G** (mini golden set),
**W** (web przyrostowo — po każdym feature silnika powstaje jego obsługa na FE).

## Plany i przeglądy

- [`docs/plan-A1.md`](docs/plan-A1.md) — szczegółowy plan implementacji **G1.1–G1.5** (kamień A1)
- [`docs/plan-A2.md`](docs/plan-A2.md) — szczegółowy plan implementacji **G2.1–G2.7 + W2** (kamień A2)
- [`ingest/README.md`](ingest/README.md) · [`backend/README.md`](backend/README.md) · [`web/README.md`](web/README.md) — jak uruchomić i czego pilnują bramki w każdej z warstw
- [`docs/g1.2-ingest.html`](docs/g1.2-ingest.html) — **G1.2** ingest: co powstało, co osiąga, jak podłączyć się do bazy DBeaverem
- [`docs/review/`](docs/review/) — przeglądy kodu (G1.1–G1.4); plan mówi, co miało powstać, przegląd — co z tego wyszło

Przeglądy tworzy skill [`.claude/skills/code-review`](.claude/skills/code-review/SKILL.md)
na podstawie diffa brancha i zrealizowanego planu.

Dokumenty nadrzędne leżą w repozytorium `cke-mirror`:

| Dokument | Rola |
|---|---|
| `docs/DECYZJE.md` | jedno źródło prawdy — przy sprzeczności obowiązuje ten plik |
| `docs/LICZBY.md` | wszystkie kwoty, terminy i pomiary korpusu |
| `docs/projekt-klucz/plan-alfa.html` | Plan Alfy — cel, ramy, zasady, kamienie A1–A4 |
| `docs/projekt-klucz/plan-implementacji-alfa.html` | rozpisanie na grupy, podgrupy i 58 zadań z zależnościami |
| `research/README.md` | know-how parsera PDF: cztery pułapki i ślepe uliczki |
| `research/schema/README.md` | model korpusu N:M, słownik dialektów, wyniki na 75 kluczach |

## Wymagania

Repozytorium jest **wieloplatformowe: Windows, macOS i Linux (CI) wołają identyczne komendy.**
Żadnych wariantów per system — `Taskfile.yml` ma wbudowany interpreter POSIX sh,
więc działa na Windows bez instalowania bash-a.

- Docker (PostgreSQL — jedyna zależność infrastrukturalna)
- .NET SDK (wersja przypięta w `global.json`)
- Node.js LTS + pnpm
- Python 3.10+ przez [`uv`](https://docs.astral.sh/uv/)
- [go-task](https://taskfile.dev) — `task` jako jedno wejście do wszystkich pętli

Instalacja `task`:

| Platforma | Komenda |
|---|---|
| Windows | `winget install Task.Task` |
| macOS | `brew install go-task/tap/go-task` |
| obie | `npm i -g @go-task/cli` |

## Uruchomienie

```bash
task setup     # sprawdza, czy maszyna ma komplet narzędzi
task up        # docker compose up -d + migracje schematu
task dev       # dotnet watch + vite dev server
task test      # testy: architektura, zero-DOM, regresja parsera, więzy schematu
task ingest    # przebieg parsera (po A2)
task correction        # ekran korekty — bramka między parserem a korpusem (G2.1)
task correction:report # pomiar S8: stan korekty, czasy, prognoza
task bench     # benchmark golden setu (po A3)
```

Cały stos jednym poleceniem — `.env` z `.env.example`, sprawdzenie narzędzi,
kontenery, migracje i oba serwery:

| Platforma | Komenda |
|---|---|
| Windows | `powershell -File scripts\dev-stack.ps1` |
| macOS / Linux | `./scripts/dev-stack.sh` |

Skrypty nie powtarzają logiki z `Taskfile.yml` — wołają `task`. Dokładają to,
czego Taskfile z założenia nie robi: operacje na plikach (`.env` nie istnieje przy
pierwszym klonie) i sprawdzenie, czy silnik Dockera **odpowiada**, a nie tylko jest
zainstalowany.

## CI

`.github/workflows/ci.yml` — cztery zadania równoległe, każde odpowiada jednemu
`task test:*`, więc to samo da się uruchomić lokalnie:

| Zadanie | Co sprawdza | Lokalnie |
|---|---|---|
| `python` | ruff + pytest + migracje na świeżym Postgresie | `task test:python` |
| `dotnet` | build + granice modułów + testy jednostkowe | `task test:dotnet` |
| `web` | typecheck (w tym zero-DOM) + vitest + build | `task test:web` |
| `contract` | regeneracja OpenAPI + `git diff --exit-code` | `task test:contract` |

Bieg **na pull requestach i na pushu do `main`**, nie na każdej gałęzi: push do
gałęzi z otwartym PR-em odpalał dwa przebiegi tego samego commita, a repozytorium
jest prywatne — minuty Actions liczą się do limitu konta. Kolejny push do PR-a ubija
poprzedni przebieg (`concurrency`), na `main` przebiegi dochodzą do końca.

Zależności są cache'owane w każdej z trzech warstw i wszystkie trzy przywracają je
w trybie zamkniętym: `uv sync --frozen`, `pnpm install --frozen-lockfile`,
`dotnet restore --locked-mode`. To ostatnie wymaga wersjonowanych
`packages.lock.json` — pakiet dodany bez zacommitowania lockfile'a kończy się
błędem `NU1004`, a nie cichym pobraniem innej wersji niż na maszynie autora.

Ochrony gałęzi `main` **nie ma i na tym planie GitHuba być nie może** — repozytorium
jest prywatne, a ochrona wymaga planu Pro (API odpowiada `403: Upgrade to GitHub Pro`).
Bramką jest więc dyscyplina, nie ustawienie: scalamy przez pull request i dopiero
z czterema zielonymi checkami.

## Licencje zależności

`pdfplumber` (MIT) w rdzeniu ekstrakcji, `pypdf` (BSD) do inwentaryzacji.
**PyMuPDF odrzucony** — AGPL-3.0 uruchamia obowiązek udostępnienia źródeł w modelu SaaS.
Decyzja odwracalna: `layout.py` ukrywa oba silniki za jednym interfejsem.
