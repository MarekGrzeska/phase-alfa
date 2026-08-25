import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

/**
 * Klient API — cienka warstwa nad `openapi-fetch`.
 *
 * Ręcznie napisane jest TYLKO to: adres bazowy i domyślne nagłówki. Typy ścieżek,
 * parametrów i odpowiedzi pochodzą z `schema.d.ts`, który jest generowany
 * z `backend/artifacts/openapi.json`. Dopisanie tu własnych typów DTO znaczyłoby, że
 * kontrakt ma dwa źródła prawdy — a wtedy rozjazd między nimi przestaje łamać build
 * i zaczyna psuć działającą aplikację.
 */
export function createApiClient(baseUrl: string) {
  return createClient<paths>({
    baseUrl,
    headers: { Accept: "application/json" },
  });
}

/** Odpowiedź `/health` — gotowość procesu i stan bazy, osobno. */
export type HealthStatus = components["schemas"]["HealthResponse"];

export type ApiClient = ReturnType<typeof createApiClient>;
