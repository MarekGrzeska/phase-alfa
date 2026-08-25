# backend — warstwa C#

Modularny monolit: jeden proces, moduły, które **nie widzą się nawzajem**.
Czyta gotową strukturę z bazy i ze składu blobów. **Nigdy nie otwiera PDF-a** —
to robi wyłącznie Python (patrz `DECYZJE.md` i `CLAUDE.md`).

```bash
task dev                  # API z hot-reloadem na http://localhost:5014
task test:dotnet          # build + testy architektury i zachowania
task openapi:generate     # dokument OpenAPI + typy klienta TS
task openapi:check        # bramka dryfu kontraktu
```

## Kierunek zależności

```
Klucz.Api ────────► Corpus · Grading · Learning        (kompozycja, DI)
      │
      └───────────► Contracts

Corpus ─┐
Grading ─┼────────► Klucz.Contracts                    (DTO + porty)
Learning ┘

Klucz.Contracts ──► (nic — zero zależności zewnętrznych)
```

Moduły nie widzą się nawzajem. Gdy `Grading` będzie potrzebował kryteriów z `Corpus`
(A3), dostanie port w `Contracts`, a `Api` wstrzyknie implementację — ten sam wzorzec
co `IBlobStore` i `IDatabaseProbe`. Jeden nawyk, nie trzy.

| Projekt | Co |
|---|---|
| `src/Klucz.Contracts` | DTO i porty. Zero pakietów — także tranzytywnie |
| `src/Klucz.Corpus` | korpus; `Infrastructure/` to JEDYNE miejsce z Npgsql |
| `src/Klucz.Grading` | ocenianie (treść w A3) |
| `src/Klucz.Learning` | nauka i powtórki (treść w A4) |
| `src/Klucz.Api` | minimal API, kompozycja modułów, `/health` |
| `tests/Klucz.ArchitectureTests` | granice modułów — jedyny projekt referujący wszystko |
| `tests/Klucz.Tests` | zachowanie: health check, skład blobów, kompozycja DI |

Nazwy w kodzie są po angielsku, komentarze po polsku — patrz `CLAUDE.md`, zasada 4.

## Testy architektury — widziane na czerwono

Test granicy, którego nikt nie widział czerwonego, jest dekoracją. Oba sprawdzone
świadomie przed scaleniem G1.3:

```
$ # 1. Grading sięga po typ z Corpusa
  Niepowodzenie Moduly_nie_widza_sie_nawzajem
   Klucz.Grading sięga do: Klucz.Grading.ProbaZlamaniaGranicy

$ # 2. do Klucz.Learning dopisany pakiet PdfPig
  Niepowodzenie Backend_nie_parsuje_PDF
   Backend sięgnął po bibliotekę do PDF-ów: Klucz.Learning.csproj: <PackageReference Include="PdfPig" />
```

Powtórzenie: dopisz `<PackageReference Include="PdfPig" />` (plus `PackageVersion`
w `Directory.Packages.props`) i uruchom `task test:dotnet`.

## Kontrakt: OpenAPI → klient TS

Dokument powstaje **przy buildzie** (`Microsoft.Extensions.ApiDescription.Server`)
i ląduje w `backend/artifacts/openapi.json`. Plik jest artefaktem, ale **wersjonowanym**:
dzięki temu zmiana kontraktu widać w diffie PR-a, a nie dopiero w CI.

`task openapi:check` regeneruje dokument i typy, po czym porównuje z repozytorium.
Zmieniłeś DTO i nie przegenerowałeś klienta → czerwony build. To samo chodzi w CI
jako osobne zadanie `kontrakt`.

## Konfiguracja

Adres bazy **wyłącznie ze zmiennych środowiskowych** (`DB_HOST`, `DB_PORT`, `DB_NAME`,
`DB_USER`, `DB_PASSWORD`; `DATABASE_URL` ma pierwszeństwo). Składany z części,
tak samo jak po stronie Pythona — numer portu stoi w `.env` raz.

Korzeń składu blobów: `Blob:Root` z `appsettings.json`, nadpisywalny zmienną
`BLOB_ROOT`. W bazie stoją ścieżki **względne** wobec tego korzenia.

### Azurite — emulator Azure Blob Storage

`task up` podnosi obok Postgresa kontener `klucz-blob` (Azurite) na porcie z `BLOB_PORT`.
Backend pisze dziś na dysk przez `DiskBlobStore` i emulatora nie dotyka — stoi tu po to,
żeby zdanie *„przeniesienie na Azure to zmiana konfiguracji, nie architektury"* dało się
**sprawdzić lokalnie**, zanim zapadnie decyzja o chmurze. Bez emulatora zostaje deklaracją.

Dane logowania (`devstoreaccount1` i klucz w `.env.example`) są wbudowane w Azurite,
publiczne i takie same u wszystkich — nie są sekretem. Prawdziwy connection string do
Azure wejdzie wyłącznie przez zmienną środowiskową.

`AzureBlobStore` wchodzi wtedy, gdy będzie na czym go sprawdzić — czyli razem
z wycinkami stron (G2.4). Port `IBlobStore` jest już przygotowany: żadnego `FileInfo`
w sygnaturach.

**Adres bazy jest rozwiązywany leniwie, przy pierwszym pytaniu.** Powód: dokument
OpenAPI powstaje przy buildzie, a generator startuje w tym celu całą aplikację.
Sprawdzanie zmiennych przy rejestracji usług znaczyłoby, że `dotnet build` wymaga
postawionego Postgresa.

## `/health`

Gotowość procesu i stan bazy **osobno** — proces potrafi stać, gdy baza leży:

```json
{ "status": "ok", "database": true, "version": "1.0.0.0" }
{ "status": "degraded", "database": false, "version": "1.0.0.0" }
```

Kod odpowiedzi to zawsze 200: „API żyje" jest odpowiedzią, po którą się tu przychodzi.
Powód awarii bazy idzie do logu, nie do odpowiedzi HTTP — adres i nazwa użytkownika
nie są rzeczami, które wystawia się bez pytania.
