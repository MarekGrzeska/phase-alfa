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
| **A1** | Szkielet: monorepo, Postgres w Dockerze, monolit C# z granicami modułów, OpenAPI → klient TS, CI | G1.1 ✓ · G1.2 ✓ · G1.3 ✓ |
| A2 | Korpus: ekran korekty → parser OMAP E8 2019–2026 → zatwierdzone rekordy w bazie | |
| A3 | Grading: pipeline 5 kroków, golden set, benchmark, macierz eksperymentów | |
| A4 / W4 | Sesja zadań, mapa braków, telemetria, sprawdzian od zera | |

Tory równoległe: **F** (formalności — CKE, PARP), **G** (mini golden set),
**W** (web przyrostowo — po każdym feature silnika powstaje jego obsługa na FE).

## Plany i przeglądy

- [`docs/plan-A1.md`](docs/plan-A1.md) — szczegółowy plan implementacji **G1.1–G1.5** (kamień A1)
- [`ingest/README.md`](ingest/README.md) · [`backend/README.md`](backend/README.md) · [`web/README.md`](web/README.md) — jak uruchomić i czego pilnują bramki w każdej z warstw
- [`docs/g1.2-ingest.html`](docs/g1.2-ingest.html) — **G1.2** ingest: co powstało, co osiąga, jak podłączyć się do bazy DBeaverem
- [`docs/review/`](docs/review/) — przeglądy kodu (G1.1, G1.2, G1.3); plan mówi, co miało powstać, przegląd — co z tego wyszło

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
task bench     # benchmark golden setu (po A3)
```

## Licencje zależności

`pdfplumber` (MIT) w rdzeniu ekstrakcji, `pypdf` (BSD) do inwentaryzacji.
**PyMuPDF odrzucony** — AGPL-3.0 uruchamia obowiązek udostępnienia źródeł w modelu SaaS.
Decyzja odwracalna: `layout.py` ukrywa oba silniki za jednym interfejsem.
