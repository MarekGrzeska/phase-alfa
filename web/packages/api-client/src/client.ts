import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

/**
 * Klient API. Ręcznie napisane są TYLKO adres bazowy i nagłówki — własne DTO tutaj
 * znaczyłyby, że kontrakt ma dwa źródła prawdy.
 */
export function createApiClient(baseUrl: string) {
  return createClient<paths>({
    baseUrl,
    headers: { Accept: "application/json" },
  });
}

export type HealthStatus = components["schemas"]["HealthResponse"];

export type ApiClient = ReturnType<typeof createApiClient>;
