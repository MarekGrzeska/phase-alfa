# web — warstwa TypeScript

Workspace pnpm, trzy pakiety:

| Pakiet | Co | DOM |
|---|---|---|
| `packages/core` | logika sesji: odpowiedzi, kolejność zadań, walidacja przed wysyłką | **nie** |
| `packages/api-client` | generowany klient OpenAPI | tak (`fetch`) |
| `apps/web` | Vite + React + PWA | tak |

```bash
pnpm -C web install
task dev                  # API + web z hot-reloadem
task test:web             # typecheck (w tym zero-DOM) + vitest
task openapi:generate     # regeneracja typów z backend/artifacts/openapi.json
```

## `packages/core` — bez DOM-u, od pierwszego dnia

To jedyna rzecz z fazy 2 (React Native), za którą alfa płaci z góry: pakiet ma
przejść do aplikacji mobilnej bez zmiany. Dlatego nie wolno mu dotknąć DOM-u ani
Reacta — a pilnują tego **trzy warstwy**, z których pierwsza jest właściwa:

1. **`tsconfig.json`** — `lib` bez `"DOM"` i `types: []`. `document` w `src/`
   **nie kompiluje się**: `error TS2584: Cannot find name 'document'`.
2. **`test/zero-dom.test.ts`** — zabronione zależności w `package.json`
   (`react`, `jsdom`, `mathlive`…) i sam kształt tsconfiga. Pakiet dopisany, ale
   jeszcze nie zawołany, jest dla kompilatora niewidoczny.
3. **skan źródeł** — `document.` / `window.` / `navigator.` w `src/`, z komunikatem
   po ludzku. Łapie obejście typów przez `any`.

Do tego vitest chodzi w środowisku `node`, nie `jsdom` — gdyby ktoś przeszedł
przez wszystkie trzy warstwy, `document` i tak nie istnieje w czasie wykonania.

Każdą z tych warstw widziano na czerwono (`CLAUDE.md`, „Testy, które nic nie
sprawdzają"). Sposób sprawdzenia:

```bash
# warstwa 1
echo 'document.querySelector("#root");' >> web/packages/core/src/session.ts
pnpm -C web --filter @klucz/core typecheck     # TS2584

# warstwa 2 — dopisz "react" do dependencies w packages/core/package.json
pnpm -C web --filter @klucz/core test          # „zabronione zależności"
```

`test/` ma własny `tsconfig.test.json` z `@types/node`, bo strażnik czyta pliki
z dysku. Produkt tych typów nie dostaje — `tsconfig.json` obejmuje wyłącznie `src`.

`pnpm --filter @klucz/core build` kompiluje pakiet **osobno**, bez Vite i bez
Reacta. To jest sprawdzian, że faza 2 weźmie go bez zmian.

## `packages/api-client`

| Plik | Skąd |
|---|---|
| `src/schema.d.ts` | **generowany** z `backend/artifacts/openapi.json` — nie edytować |
| `src/client.ts` | pisany ręcznie: adres bazowy i nagłówki, nic więcej |
| `src/index.ts` | co pakiet wystawia na zewnątrz |

Typy ścieżek, parametrów i odpowiedzi pochodzą wyłącznie ze schematu. Dopisanie
własnych typów DTO znaczyłoby, że kontrakt ma dwa źródła prawdy — a wtedy rozjazd
przestaje łamać build i zaczyna psuć działającą aplikację. `schema.d.ts` **wchodzi
do repozytorium** i pilnuje tego bramka `task openapi:check`.

## `apps/web`

Vite + React + TypeScript, PWA jako wtyczka. Service worker jest **wyłączony
w developmencie** i nie ma runtime cachingu: SW trzymający stary build to ostatnia
rzecz, jakiej trzeba przy iteracji co kilka minut.

Dev server proxuje `/api` na `http://localhost:${API_PORT}` — przeglądarka widzi
jeden origin, więc backend nie musi wystawiać CORS-u tylko dla dev servera. Port
czytany jest z `.env` w korzeniu repozytorium, tym samym, z którego bierze go Taskfile.

Ekran jest dziś szkieletem: kręci model sesji z `@klucz/core` na zadaniach wpisanych
na sztywno. Widok statusu bazy (ping API, wersja migracji, liczniki rekordów) dokłada
**W1**, korpus — **A2**.

## Nazewnictwo

Nazwy w kodzie po angielsku, komentarze po polsku — `CLAUDE.md`, zasady 2 i 4.
