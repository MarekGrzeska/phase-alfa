import { createApiClient } from "@klucz/api-client";

/**
 * `/api`, nie adres z portem: dev server proxy'uje ten prefiks na backend
 * (`vite.config.ts`), więc przeglądarka widzi jeden origin i nie trzeba
 * ani CORS-u, ani drugiego miejsca z numerem portu.
 */
export const corpus = createApiClient("/api");

export type Loaded<T> =
  | { readonly state: "loading" }
  | { readonly state: "error"; readonly message: string }
  | { readonly state: "ready"; readonly data: T };

export const LOADING: Loaded<never> = { state: "loading" };

/** Błąd HTTP ma dojść do ekranu z powodem — cichy pusty widok kłamie. */
export function failed(what: string, error: unknown): Loaded<never> {
  const detail = error instanceof Error ? error.message : String(error);
  return { state: "error", message: `${what}: ${detail}` };
}
