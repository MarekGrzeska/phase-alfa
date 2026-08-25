# web — warstwa TypeScript

Workspace pnpm. Dziś stoi w nim jeden pakiet: **generowany klient API**.
Aplikacja (`apps/web`) i `packages/core` bez DOM wchodzą w G1.4.

```bash
pnpm -C web install
pnpm -C web -r typecheck
task openapi:generate     # regeneracja typów z backend/artifacts/openapi.json
```

## `packages/api-client`

| Plik | Skąd |
|---|---|
| `src/schema.d.ts` | **generowany** z `backend/artifacts/openapi.json` — nie edytować |
| `src/client.ts` | pisany ręcznie: adres bazowy i nagłówki, nic więcej |
| `src/index.ts` | co pakiet wystawia na zewnątrz |

Nazwy w kodzie po angielsku (`createApiClient`, `HealthStatus`, `ApiClient`), komentarze
po polsku — `CLAUDE.md`, zasada 4. Typy ścieżek, parametrów i odpowiedzi pochodzą
wyłącznie ze schematu. Dopisanie
własnych typów DTO znaczyłoby, że kontrakt ma dwa źródła prawdy — a wtedy rozjazd
przestaje łamać build i zaczyna psuć działającą aplikację.

`schema.d.ts` **wchodzi do repozytorium** i pilnuje tego bramka `task openapi:check`.
