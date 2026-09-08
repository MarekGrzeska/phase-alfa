/** Klient `/api/*` ekranu korekty.
 *
 * Bez biblioteki do pobierania danych: widoków jest kilka, a każda zależność
 * w tym narzędziu to godzina zdjęta z korekty — a korekta jest ścieżką krytyczną.
 */

export interface StatusCounts {
  readonly pending: number;
  readonly approved: number;
  readonly corrected: number;
  readonly rejected: number;
}

export interface Numbers {
  readonly status: {
    readonly counts: StatusCounts;
    readonly total: number;
    readonly decided: number;
    readonly pending: number;
    readonly done_share: number;
    readonly hit_share: number;
    readonly rejected: number;
  };
  readonly durations: {
    readonly events: number;
    readonly median: number;
    readonly total: number;
    readonly long: number;
  };
  readonly forecast: { readonly tasks: number; readonly seconds: number; readonly hours: number };
  readonly years: readonly YearRow[];
  readonly assets: { readonly total: number; readonly cropped: number; readonly framed: number };
}

export interface YearRow {
  readonly year: number;
  readonly total: number;
  readonly pending: number;
  readonly approved: number;
  readonly corrected: number;
  readonly rejected: number;
}

export interface TaskRow {
  readonly id: number;
  readonly number: string;
  readonly max_points: number | null;
  readonly kind: string;
  readonly review_status: string;
  readonly code: string;
  readonly session: string;
  readonly year: number;
  readonly variants: string | null;
}

export interface Scope {
  readonly status: string | null;
  readonly year: number | null;
  readonly code: string | null;
  readonly variant: string | null;
}

export interface Overview {
  readonly numbers: Numbers;
  readonly tasks: readonly TaskRow[];
  readonly options: {
    readonly years: readonly number[];
    readonly codes: readonly string[];
    readonly variants: readonly string[];
  };
  readonly selected: Scope;
  readonly next_id: number | null;
  readonly status_labels: Readonly<Record<string, string>>;
}

/** Parametry zakresu w adresie — puste pole znaczy „wszystkie" i nie jedzie wcale. */
export function scopeQuery(scope: Partial<Record<string, string>>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(scope)) {
    if (value !== undefined && value !== "") {
      params.set(key, value);
    }
  }
  const query = params.toString();
  return query === "" ? "" : `?${query}`;
}

export async function fetchOverview(query: string): Promise<Overview> {
  const response = await fetch(`/api/overview${query}`);
  if (!response.ok) {
    // Treść błędu z FastAPI (`detail`) jest zdaniem dla człowieka — warto ją
    // pokazać, zamiast zamieniać każdą porażkę w „coś poszło nie tak".
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail ?? `serwer odpowiedział ${response.status}`);
  }
  return (await response.json()) as Overview;
}
