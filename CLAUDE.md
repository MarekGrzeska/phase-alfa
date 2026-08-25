# CLAUDE.md

Zasady pracy nad tym repozytorium. Plik żywy — rozwijamy go na bieżąco, w miarę
jak zapadają kolejne rozstrzygnięcia.

Przy sprzeczności obowiązuje kolejność: `DECYZJE.md` (w repozytorium `cke-mirror`)
→ ten plik → plany w `docs/`.

---

## Język: nazwy po angielsku, komentarze po polsku

Dwie zasady, bez wyjątków.

### 1. Nazwy katalogów i plików — **wyłącznie po angielsku**

```
docs/review/            code-review/            template.html
0001_corpus.sql         0002_indexes.sql        migrate.py
```

Nie:

```
docs/przeglad/          przeglad-kodu/          szablon.html
0001_korpus.sql         0002_indeksy.sql        migruj.py
```

Dotyczy wszystkiego, co ma ścieżkę: katalogów, plików źródłowych, migracji,
zasobów, plików konfiguracyjnych. Także nazw gałęzi w gicie.

### 2. Komentarze w kodzie — **wyłącznie po polsku**

Każdy komentarz, docstring i tekst wyjaśniający pisze się po polsku. Angielski
komentarz jest w tym repozytorium błędem tak samo jak polska nazwa pliku.

```python
def suma(sciezka: Path) -> str:
    """SHA-256 treści, po normalizacji zakończeń linii i BOM-u.

    Suma ma reagować na zmianę TREŚCI, a nie na to, czym plik był zapisany.
    """
```

Dotyczy też komunikatów dla człowieka: `echo` w Taskfile, komunikaty błędów,
teksty w dokumentach HTML. Odbiorcą jest autor, który mówi po polsku.

**Wyjątek — komunikaty commitów.** Pisane po polsku, ale **bez polskich znaków
diakrytycznych**: `poprawka`, nie `poprawka` z ogonkami. Powód jest praktyczny —
konsole i narzędzia gitowe na Windows potrafią je rozjechać.

### 3. Nazwy tabel i kolumn — **po angielsku**

Cały schemat bazy jest po angielsku, mimo że dziedzina jest polska. Decyzja
z 25.08.2026; wcześniej schemat był po polsku i został przetłumaczony w całości.

Ponieważ pojęcia biorą się z dokumentów CKE, tłumaczenie **musi być jedno i to samo
wszędzie** — inaczej parser, schemat i moduł C# zaczną nazywać tę samą rzecz na trzy
sposoby. Stąd słownik obowiązujący:

| Polski (dokumenty CKE) | Angielski (kod i baza) |
|---|---|
| reżim wymagań | `requirement_regime` |
| wymaganie (podstawy programowej) | `requirement` |
| dokument (plik PDF) | `document` |
| forma arkusza | `exam_form` |
| zadanie | `task` |
| wersja zadania (bliźniak X/Y) | `task_version` |
| odpowiedź wzorcowa | `model_answer` |
| kryterium (próg punktowy) | `criterion` |
| warunek kryterium | `criterion_condition` |
| zapis równoważny | `condition_expression` |
| rozwiązanie przykładowe | `example_solution` |
| przykład odpowiedzi | `answer_example` |
| reguła przekrojowa („Uwagi ogólne") | `rule` |
| zasób graficzny (wycinek) | `asset` |
| zasady oceniania (klucz) | `marking_scheme` |
| arkusz (zeszyt zadań) | `paper` |
| treść | `content` · | opis | `description` |
| kolejność | `position` · | rodzaj/typ | `kind` |
| ścieżka | `path` · | punkty | `points` |

Wartości w więzach `CHECK` też są po angielsku (`'marking_scheme'`, `'open_short'`,
`'approved'`), bo należą do schematu, a nie do danych. Dane pozostają, jakie są —
`subject` trzyma `'matematyka'`, bo tak nazywa to CKE.

**Komentarze w tym schemacie zostają po polsku** i to jest zamierzone: nazwa mówi,
*co* to jest, komentarz mówi, *dlaczego tak* — i to drugie jest po polsku, jak wszystko
inne w tym repozytorium.

### 4. Cały kod — **po angielsku**. Bez wyjątków

Rozstrzygnięcie z 25.08.2026. Dotyczy **wszystkiego, co jest identyfikatorem**:
klasy, interfejsy, metody, funkcje, zmienne, parametry, pola, właściwości, stałe,
nazwy testów, klucze konfiguracji, komunikaty wyjątków przeznaczone dla kodu.

```csharp
Task<Stream> OpenAsync(string path, CancellationToken ct = default);   // dobrze
Task<Stream> OtworzAsync(string sciezka, CancellationToken ct = default);  // źle
```

```python
def read_key(path: str) -> Key: ...      # dobrze
def czytaj_klucz(sciezka: str): ...      # źle
```

**Komentarze, docstringi i teksty dla człowieka zostają po polsku** (zasada 2).
Nazwa mówi *co* to jest — po angielsku, jak schemat bazy i jak nazwy plików.
Komentarz mówi *dlaczego tak* — po polsku, bo czyta go autor.

Polskie pojęcia z dokumentów CKE tłumaczy słownik z zasady 3
(`zasady_oceniania` → `marking_scheme`, `zadanie` → `task`). Ten sam przekład
obowiązuje w kodzie, nie tylko w bazie — inaczej parser, schemat i moduł C#
nazywają tę samą rzecz na trzy sposoby.

**Dług do spłacenia:** `ingest/` powstał przed tym rozstrzygnięciem i ma nazwy
po polsku (`czytaj_klucz`, `polaczenie`, `Ladowarka`). Przemianowanie to osobne
zadanie — nie robi się go w commicie, który zmienia zachowanie, bo wtedy nie da
się odróżnić regresji od zmiany nazwy.

---

## Granica warstw — najważniejsza reguła projektu

```
PDF z cke.gov.pl
  → [Python] mirror + parser pdfplumber + rekonstrukcja + wycinki stron
  → [zapis] PostgreSQL + blob storage
  → [C#] czyta gotową strukturę; NIGDY nie parsuje PDF-a
```

- **C# nie otwiera PDF-a.** Pilnuje tego test architektury (G1.3).
- **Python nie obsługuje ruchu użytkownika.** Uruchamiany ręcznie, jego wynikiem są dane.
- Kontraktem między warstwami jest **schemat bazy plus pliki JSON golden setu**, nie API.

Wyjątek świadomy: ekran korekty (`ingest/correction/`) to lokalne narzędzie na
localhost, obsługiwane przez Pythona — edytuje rekordy, **zanim** staną się korpusem.

---

## Więzy bazy zostają ostre

`UNIQUE (zadanie_id, punkty)` w tabeli `kryterium` złapał prawdziwy błąd przy
pierwszym ładowaniu w sondzie. **Gdy parser łamie więz — naprawia się parser albo
poprawia rekord w ekranie korekty. Nigdy nie luzuje się więzu.**

Testy schematu sprawdzają, czy więzy **odrzucają złe dane**, a nie czy istnieją.
Test, który tylko wylicza tabele, przechodzi zawsze i nie mówi nic.

---

## Wieloplatformowość: Windows i macOS wołają to samo

Jeden `Taskfile.yml` na oba systemy — go-task ma wbudowany interpreter POSIX sh,
więc działa na Windows bez bash-a. Konsekwencje, o których trzeba pamiętać:

| Pułapka | Reguła |
|---|---|
| `rm`, `cp`, `mkdir` **nie istnieją na Windows** | Zero operacji na plikach w Taskfile — sprzątanie robią narzędzia same |
| `python` vs `python3` | Zawsze `uv run python` |
| Wielkość liter w ścieżkach | macOS i Windows nie rozróżniają, Linux w CI tak — **CI jest jedynym źródłem prawdy o zielonym buildzie** |
| Zakończenia linii | `.gitattributes` wymusza LF |
| Zaszyte porty | Port hosta z konfiguracji (`DB_PORT`), nigdy w pliku wersjonowanym |
| PowerShell 5.1 | `Set-Content -Encoding utf8` dopisuje BOM, `Get-Content -Raw` czyta jako ANSI — para tych komend psuje polskie znaki. Pliki edytować w edytorze, nie w konsoli |
| Proces potomny z przechwyconym wyjściem | Na Windows pisze w kodowaniu konsoli (cp1250), nie UTF-8. Uruchamiając Pythona z Pythona, przekazać `PYTHONIOENCODING=utf-8` — inaczej polskie znaki w komunikatach rozsypią dekodowanie, a `stdout` wyjdzie jako `None` |

Cudzysłowy proste w komunikacie commita rozbijają argument, gdy `git commit -m`
wywołuje się z PowerShella. Komunikaty wieloliniowe pisać przez `git commit -F -`
z narzędzia Bash, nie z PowerShella.

---

## Testy, które nic nie sprawdzają

**Każdy test i każdą bramkę trzeba raz zobaczyć na czerwono.** Test, który zawsze
był zielony, jest nieodróżnialny od testu, który nic nie sprawdza.

Wzorce, które to psują i są w tym repozytorium zakazane:

```bash
polecenie || echo "pomijam"      # połknie też prawdziwą porażkę
polecenie || true
```

Zamiast tego rozdzielać przypadki jawnie przez `if`.

---

## Polecenia

```bash
task setup     # sprawdza, czy maszyna ma komplet narzędzi
task up        # Postgres + Azurite (emulator Azure Blob) + migracje schematu
task dev       # dotnet watch + vite (od G1.3/G1.4)
task test      # architektura, zero-DOM, regresja parsera, więzy schematu
task db:reset  # baza od zera (kasuje wolumen)
task ingest    # przebieg parsera (od A2)
task bench     # benchmark golden setu (od A3)
```

---

## Gdzie co leży

| Ścieżka | Co |
|---|---|
| `ingest/` | Python: mirror, parser PDF, migracje schematu, ekran korekty |
| `backend/` | C#: modularny monolit, moduły nie widzą się nawzajem |
| `web/` | TypeScript: `packages/core` bez DOM, `apps/web`, generowany klient OpenAPI |
| `docs/` | plany implementacji i przeglądy kodu |
| `docs/review/` | przeglądy kodu — tworzy je skill `code-review` |
| `.claude/skills/` | skille projektowe |
| `data/` | mirror, blob, raporty — poza gitem |

Dokumenty nadrzędne (`DECYZJE.md`, `LICZBY.md`, plany fazy alfa, know-how parsera)
leżą w repozytorium `cke-mirror`.
