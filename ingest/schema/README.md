# Schemat korpusu — migracje

Schemat bazy jest **kontraktem** między warstwą Pythona (ingest) a warstwą C#
(aplikacja). Dlatego stoi tu jako plain SQL, a nie jako model wyprowadzany
z kodu w którymkolwiek języku. **C# ten schemat wyłącznie czyta i nigdy go nie zmienia.**

```bash
task up               # postawienie bazy + zastosowanie brakujących migracji
task migrate          # same migracje (baza już stoi)
task migrate:status   # które weszły, których brakuje
task db:reset         # od zera — UWAGA: kasuje wolumen
task db:psql          # konsola SQL
```

## Zasady

| Zasada | Dlaczego |
|---|---|
| Jeden plik = jeden krok, nazwa `NNNN_opis.sql` | kolejność wynika z nazwy, nie z tabeli konfiguracyjnej |
| Migracja wykonywana w **jednej transakcji** razem z wpisem do `schema_migrations` | migracja przerwana w połowie nie zostawia bazy w stanie, którego nie da się nazwać |
| **Zastosowanej migracji się nie edytuje** — suma SHA-256 jest sprawdzana przy każdym uruchomieniu | dwie maszyny z tą samą wersją schematu muszą mieć tę samą bazę |
| Brak `BEGIN`/`COMMIT` w plikach | transakcję otwiera runner; zagnieżdżona dałaby ostrzeżenie i zamazała granicę |
| Więzy zostają **ostre** | patrz niżej |

## Więzy nie są dekoracją

`UNIQUE (task_id, points)` w tabeli `criterion` złapał prawdziwy błąd przy
pierwszym ładowaniu w sondzie: sekcja reguł przekrojowych stoi *między* zadaniami,
więc podział tekstu po nagłówkach `Zadanie N.` doklejał ją do zadania poprzedzającego,
a jej zdanie „…to otrzymuje 0 punktów" udawało drugi próg 0 pkt. **Bez tego więzu
błąd wszedłby do korpusu po cichu.**

Dlatego `tests/test_schema.py` nie sprawdza, czy więzy *istnieją* — sprawdza,
czy **odrzucają złe dane**. Test, który tylko wylicza tabele, przechodzi zawsze
i nie mówi nic.

Gdy parser zaczyna łamać więz: naprawia się parser albo poprawia rekord w ekranie
korekty (A2). Nigdy nie luzuje się więzu.

## Locale i sortowanie

Cluster stoi w **`C.UTF-8`**, nie w `pl_PL.UTF-8`. Obraz `postgres:*-alpine`
opiera się na musl, które polskich locale nie ma — `initdb` z `pl_PL.UTF-8`
w ogóle by nie wstał.

Polskie porządkowanie wchodzi przez kolację ICU zadeklarowaną w migracji `0001`:

```sql
CREATE COLLATION pl_icu (provider = icu, locale = 'pl-PL');
-- użycie:
SELECT ... ORDER BY tresc COLLATE pl_icu;
```

Test `test_kolacja_pl_icu_sortuje_po_polsku` pilnuje, że `ł` stoi między `l` a `m`,
a nie na końcu alfabetu jak w `C.UTF-8`.

## Kodowanie plików

Migracje są **UTF-8 bez BOM, z LF**. Wymusza to `.gitattributes` w korzeniu repo.

Runner normalizuje BOM i CRLF przed liczeniem sumy, więc niewinne otwarcie pliku
w edytorze, który dopisze znacznik, nie wygląda jak podmiana migracji. Czego
**nie** normalizuje: samych znaków — plik przepuszczony przez złe kodowanie
(`·` → `Â·`) ma zerwać sumę, bo to uszkodzona migracja, nie kosmetyka.

> Na Windows uwaga na PowerShell 5.1: `Set-Content -Encoding utf8` dopisuje BOM,
> a `Get-Content -Raw` czyta plik jako ANSI. Para tych komend na pliku z polskimi
> znakami robi mojibake. Migracje edytować w edytorze, nie w konsoli.

## Pliki

| Plik | Co robi |
|---|---|
| `migrate.py` | runner: transakcja per migracja, tabela `schema_migrations`, kontrola sum |
| `migrations/0001_corpus.sql` | model korpusu N:M — awans z `research/schema/schema.sql` bez zmian |
| `migrations/0002_indexes.sql` | indeksy na kluczach obcych (PostgreSQL nie robi ich sam) |

Uzasadnienie modelu — dlaczego klucz → arkusz jest N:M, dlaczego kryteria wiszą
na `task`, a odpowiedzi na `task_version`, i skąd trzy poziomy dysjunkcji
w kryteriach — leży w `research/schema/README.md` w repozytorium `cke-mirror`.
Tamten dokument używa jeszcze polskich nazw; przekład stoi w `CLAUDE.md`.
