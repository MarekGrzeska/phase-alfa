# backend — warstwa C#

Modularny monolit: jeden proces, moduły, które **nie widzą się nawzajem**.
Czyta gotową strukturę z bazy i ze składu blobów. **Nigdy nie otwiera PDF-a** —
to robi wyłącznie Python (patrz `DECYZJE.md` i `CLAUDE.md`).

```bash
task dev                  # API z hot-reloadem na http://localhost:$API_PORT (domyślnie 5014)
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
| `src/Klucz.Corpus` | korpus: port `ICorpusReader` i DTO odpowiedzi; `Infrastructure/` to JEDYNE miejsce z Npgsql — i jedyny csproj, któremu wolno go zadeklarować |
| `src/Klucz.Grading` | ocenianie (treść w A3) |
| `src/Klucz.Learning` | nauka i powtórki (treść w A4) |
| `src/Klucz.Api` | minimal API, kompozycja modułów, `/health`, trasy `/corpus/*` |
| `tests/Klucz.ArchitectureTests` | granice modułów — jedyny projekt referujący wszystko |
| `tests/Klucz.Tests` | zachowanie: health check, skład blobów, kompozycja DI, odczyt korpusu |

Nazwy w kodzie są po angielsku, komentarze po polsku — patrz `CLAUDE.md`, zasada 4.

## Testy architektury — widziane na czerwono

Test granicy, którego nikt nie widział czerwonego, jest dekoracją. Oba sprawdzone
świadomie przed scaleniem G1.3:

```
$ # 1. Grading sięga po typ z Corpusa
  Niepowodzenie Modules_do_not_see_each_other
   Klucz.Grading sięga do: Klucz.Grading.ProbaZlamaniaGranicy

$ # 2. do Klucz.Learning dopisany pakiet PdfPig
  Niepowodzenie Backend_does_not_parse_PDF
   Backend sięgnął po bibliotekę do PDF-ów: Klucz.Learning.csproj: PdfPig
```

Powtórzenie: dopisz `<PackageReference Include="PdfPig" />` i uruchom `task test:dotnet`.
Sam `<PackageVersion Include="PdfPig" />` w `Directory.Packages.props` też wystarczy —
sito czyta oba pliki.

Każda z pięciu reguł ma **trzy różne sita**, bo żadne nie widzi tego, co pozostałe:

| Sito | Widzi | Nie widzi |
|---|---|---|
| referencje assembly (NetArchTest, `GetReferencedAssemblies`) | to, czego kod **używa** | pakietu dopisanego, ale jeszcze nie zawołanego |
| deklaracje w `*.csproj` i `Directory.Packages.props` | **zamiar**, zanim ktoś go użyje | pakietu, który wszedł tranzytywnie |
| `obj/project.assets.json` | całe drzewo po `restore` | niczego z powyższych — dlatego stoją wszystkie trzy |

Kompilator nie emituje referencji do assembly, z którego nic nie wzięto. Samo sito
assembly zapalało się więc dopiero przy commicie, który pakietu **używa** — czyli
wtedy, gdy granica jest już przekroczona, a test przestaje być granicą i staje się
protokołem z wypadku.

## Wersje pakietów: `packages.lock.json`

Wersje stoją centralnie w `Directory.Packages.props`, a `RestorePackagesWithLockFile`
dokłada do każdego projektu **wersjonowany** `packages.lock.json` z pełnym drzewem
tranzytywnym. CI przywraca pakiety przez `dotnet restore --locked-mode`: przywraca
DOKŁADNIE to, co w lockfile'ach, i nic innego.

Dodałeś pakiet i nie zacommitowałeś lockfile'a → CI kończy się `NU1004`, zamiast
po cichu pobrać wersję inną niż na maszynie autora. Lokalnie lockfile'e aktualizują
się same przy pierwszym `dotnet build` po zmianie wersji — trzeba je tylko dodać
do commita. Te same pliki są kluczem cache'u NuGeta w CI.

## Kontrakt: OpenAPI → klient TS

Dokument powstaje **przy buildzie** (`Microsoft.Extensions.ApiDescription.Server`)
i ląduje w `backend/artifacts/openapi.json`. Plik jest artefaktem, ale **wersjonowanym**:
dzięki temu zmiana kontraktu widać w diffie PR-a, a nie dopiero w CI.

`task openapi:check` regeneruje dokument i typy, po czym porównuje z repozytorium.
Zmieniłeś DTO i nie przegenerowałeś klienta → czerwony build. To samo chodzi w CI
jako osobne zadanie `kontrakt`, które dodatkowo **kompiluje klienta TS** — bramka
dryfu pilnuje zgodności kontraktu z kodem, ale nie tego, czy ręcznie pisany
`client.ts` dalej się buduje.

Generacja idzie przez `dotnet build --no-incremental`. MSBuild jest przyrostowy:
przy aktualnym projekcie pomija cel generujący dokument, a bramka porównuje wtedy
plik, którego nikt nie odtworzył — sam ze sobą. Zaraz po buildzie stoi asercja, że
artefakt istnieje, bo „nie wygenerowano" wygląda tak samo jak „nie ma zmian".

## Konfiguracja

Adres bazy **wyłącznie ze zmiennych środowiskowych** (`DB_HOST`, `DB_PORT`, `DB_NAME`,
`DB_USER`, `DB_PASSWORD`; `DATABASE_URL` ma pierwszeństwo). Składany z części,
tak samo jak po stronie Pythona — numer portu stoi w `.env` raz.

`DATABASE_URL` jest rozkładany na części razem z **query stringiem**: `sslmode`
i reszta parametrów trafiają do connection stringa, a nie są zjadane. Nieznany
parametr zatrzymuje składanie adresu — cicha utrata parametru bezpieczeństwa jest
gorsza niż głośny błąd konfiguracji. Każdy błąd tej ścieżki (brak zmiennych, zły
`DB_PORT`, popsuty adres) wychodzi z `/health` jako `degraded`, nigdy jako 500.

Korzeń składu blobów: zmienna **`BLOB_ROOT`**, w drugiej kolejności `Blob:Root`
z `appsettings.json`, domyślnie `data/blob`. Kolejność jest istotna i pilnuje jej
test: `Blob:Root` stoi w pliku, więc zawsze coś zwraca — postawiony pierwszy
zjadałby `BLOB_ROOT` w całości, a korpus rozjeżdżałby się na dwie lokalizacje
(Python pisze w nowej, C# czyta ze starej). W bazie stoją ścieżki **względne**
wobec tego korzenia.

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
{ "status": "ok", "database": true, "version": "0.1.0" }
{ "status": "degraded", "database": false, "version": "0.1.0+3cf423e…" }
```

Kod odpowiedzi to zawsze 200: „API żyje" jest odpowiedzią, po którą się tu przychodzi.
Powód awarii bazy idzie do logu, nie do odpowiedzi HTTP — adres i nazwa użytkownika
nie są rzeczami, które wystawia się bez pytania.

`degraded` obejmuje też **błąd konfiguracji**, nie tylko leżącą bazę: literówka
w `DB_PORT` czy popsuty `DATABASE_URL` dają `degraded`, a nie HTTP 500 ze stack
trace. Monitoring widzący „API leży", gdy API stoi i zła jest wyłącznie
konfiguracja, jest gorszy niż jego brak.

Pole `version` to `InformationalVersion`, czyli `VersionPrefix`
z `Directory.Build.props`. CI dokłada do niego SHA commita
(`-p:SourceRevisionId=<sha>`), więc odpowiedź z wdrożenia mówi, który commit tam
stoi. Wersji assembly nikt nie ustawiał, więc wcześniej pole było stałą `1.0.0.0`
i nie odróżniało żadnych dwóch buildów.

## `/openapi/v1.json`

Wystawiane **tylko w `Development`**. Pełny opis API to mapa powierzchni ataku,
a poza deweloperką nikt go stąd nie czyta: klient TS bierze typy z wersjonowanego
`backend/artifacts/openapi.json`, a ten powstaje przy **buildzie** (GetDocument.Insider
woła generator z DI), nie przez ten endpoint.


## Corpus read API (W2.1)

| Endpoint | Zwraca |
|---|---|
| `GET /corpus/forms` | formy arkusza z liczbą zatwierdzonych zadań i pulą punktów |
| `GET /corpus/forms/{id}/tasks` | zadania formy: numer, pula, rodzaj, czy ma rysunek |
| `GET /corpus/tasks/{id}` | pełne drzewo: wersje X/Y, kryteria → warunki → zapisy z MathJSON-em, wymagania, rozwiązania, reguły |
| `GET /corpus/assets/{id}` | wycinek PNG strumieniem przez `IBlobStore` |
| `GET /corpus/progress` | postęp korekty per rocznik i statystyka półautomatu |

**Każde zapytanie idzie po widoku `corpus_task`, nigdy po `task`.** Definicja
„co jest korpusem" stoi w jednym miejscu schematu, zamiast być powtórzona w kodzie
trzech warstw; zadanie czekające na korektę to dla tego API 404. Pilnuje tego test
`Task_waiting_for_review_is_not_corpus` — widziany raz na czerwono po podmianie
widoku na tabelę.

Jedyny świadomy wyjątek: `GET /corpus/progress` liczy po całej tabeli zadań,
bo pulpit odpowiada na pytanie „ile jeszcze zostało".

`GET /corpus/assets/{id}` jest pierwszym prawdziwym konsumentem `IBlobStore` —
ścieżka względna z bazy plus ochrona przed wyjściem poza korzeń składu, która
istniała od G1.3 i nie miała dotąd kto użyć. **Brak pliku to 404, nie 500:** tak
wygląda korpus po `task db:reset` albo przed `task crops`.

### `Results<Ok<T>, NotFound>`, nie `Results.Ok(...)`

To pierwsze niesie TYP do dokumentu OpenAPI. Przy drugim `TaskDetail` w ogóle
nie trafiał do schematu, a klient TS dostawał `unknown` — **i bramka dryfu tego
nie łapie**, bo plik się zgadza, tylko jest pusty.
