/** Klient `/api/inspect/*`. Formatowanie wartości robi Python — tu tylko układ. */

export interface Cell {
  readonly text: string;
  readonly full: string;
  readonly link?: string | null;
}

export interface IndexData {
  readonly tables: readonly { name: string; count: number; note: string }[];
  readonly views: readonly string[];
  readonly health: readonly {
    key: string;
    title: string;
    why: string;
    severity: string;
    count: number;
  }[];
  readonly empty_columns: readonly {
    table: string;
    column: string;
    untouched: number;
    total: number;
  }[];
}

export interface HealthData {
  readonly check: {
    key: string;
    title: string;
    why: string;
    severity: string;
    table: string;
  };
  readonly columns: readonly string[];
  readonly rows: readonly (readonly Cell[])[];
}

export interface ColumnMeta {
  readonly name: string;
  readonly type: string;
  readonly nullable: boolean;
  readonly default: string | null;
  readonly source: string;
  readonly parent: string | null;
}

export interface ColumnFilterOffer {
  readonly column: string;
  readonly operators: readonly string[];
  readonly default: string;
  readonly is_enum: boolean;
  readonly options: readonly string[];
}

export interface ActiveFilter {
  readonly param: string;
  readonly label: string;
  readonly column: string;
  readonly op: string;
  readonly value: string | null;
}

export interface ListData {
  readonly table: {
    readonly name: string;
    readonly single_key: string | null;
    readonly note: string;
    readonly columns: readonly ColumnMeta[];
    readonly parents: Readonly<Record<string, string>>;
  };
  readonly visible: readonly string[];
  readonly rows: readonly {
    readonly key: number | string | null;
    readonly cells: Readonly<Record<string, Cell>>;
    readonly parents: readonly { table: string; id: number }[];
  }[];
  readonly total: number;
  readonly view: {
    readonly page: number;
    readonly per_page: number;
    readonly sort: string | null;
    readonly direction: string;
    readonly all_columns: boolean;
    readonly filters: readonly ActiveFilter[];
  };
  readonly links: {
    readonly canonical: string;
    readonly clear: string;
    readonly columns: string;
    readonly sort: Readonly<Record<string, string>>;
    readonly drop: Readonly<Record<string, string>>;
    readonly previous: string | null;
    readonly next: string | null;
    readonly per: Readonly<Record<string, string>>;
  };
  readonly described: Readonly<Record<string, ColumnFilterOffer>>;
  readonly operators: Readonly<Record<string, readonly string[]>>;
  readonly operator_prefix: string;
  readonly per_page_options: readonly number[];
  readonly summary_columns: readonly string[] | null;
  readonly errors: readonly string[];
}

export interface RecordColumn {
  readonly name: string;
  readonly kind: "null" | "parent" | "json" | "status" | "plain";
  readonly text: string;
  readonly parent: string | null;
  readonly value: string | number | null;
  readonly source: string;
}

export interface Provenance {
  readonly note: string | null;
  readonly document_id: number | null;
  readonly document_kind: string | null;
  readonly document_path: string | null;
  readonly document_pages: number | null;
  readonly page: number | null;
  readonly file_exists: boolean;
  readonly bbox: readonly number[] | null;
  readonly page_size: readonly number[] | null;
  readonly asset_id: number | null;
  readonly crop_path: string | null;
  readonly crop_exists: boolean;
  readonly related: readonly { id: number; role: string; path: string }[];
}

export interface RecordData {
  readonly table: { readonly name: string; readonly single_key: string; readonly note: string };
  readonly id: number;
  readonly row_notes: readonly string[];
  readonly columns: readonly RecordColumn[];
  readonly parents: readonly {
    column: string;
    table: string;
    value: number;
    url: string;
  }[];
  readonly children: readonly {
    table: string;
    column: string;
    count: number;
    url: string;
    rows: readonly { id: number | null; text: string; url: string | null }[];
  }[];
  readonly source: Provenance;
  readonly crop_name: string | null;
  readonly pdf_page: number;
}

async function ask<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail ?? `serwer odpowiedział ${response.status}`);
  }
  return (await response.json()) as T;
}

export const fetchIndex = () => ask<IndexData>("/api/inspect");
export const fetchHealth = (key: string) => ask<HealthData>(`/api/inspect/health/${key}`);
export const fetchList = (table: string, query: string) =>
  ask<ListData>(`/api/inspect/${table}${query}`);
export const fetchRecord = (table: string, id: string, query: string) =>
  ask<RecordData>(`/api/inspect/${table}/${id}${query}`);
