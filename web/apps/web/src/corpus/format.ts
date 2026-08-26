import type { components } from "@klucz/api-client";

export type FormSummary = components["schemas"]["FormSummary"];
export type TaskSummary = components["schemas"]["TaskSummary"];
export type TaskDetail = components["schemas"]["TaskDetail"];
export type CorpusProgress = components["schemas"]["CorpusProgress"];

/**
 * Liczby całkowite przychodzą z kontraktu jako `number | string`: generator
 * OpenAPI .NET-a dopuszcza dla `int32` obie postacie. Konwersja w JEDNYM
 * miejscu, bo rozsypana po komponentach kończy się porównaniem `"12" === 12`.
 */
export function count(value: number | string): number {
  return typeof value === "number" ? value : Number.parseInt(value, 10);
}

/** Nazwa formy taka, jak stoi na arkuszu: `OMAP-100 X · 2025-05`. */
export function formName(form: FormSummary): string {
  const version = form.version === null ? "" : ` ${form.version}`;
  return `${form.code}-${form.variant}${version} · ${form.session.slice(0, 7)}`;
}

const KINDS: Record<string, string> = {
  closed: "zamknięte",
  open_short: "otwarte krótkie",
  open_extended: "otwarte rozszerzone",
  essay: "wypracowanie",
};

export function kindLabel(kind: string): string {
  return KINDS[kind] ?? kind;
}

const MATHJSON_STATUS: Record<string, string> = {
  none: "bez MathJSON-a",
  auto: "MathJSON z konwertera",
  approved: "MathJSON zatwierdzony",
  failed: "konwerter nie ugryzł",
};

export function mathJsonLabel(status: string): string {
  return MATHJSON_STATUS[status] ?? status;
}

/**
 * Bliźniaki X/Y obok siebie — po to powstał podział `task`/`task_version`.
 * Kolejność po wersji, a nie po identyfikatorze: X ma stać po lewej także
 * wtedy, gdy do bazy wszedł drugi.
 */
export function versionsInOrder(task: TaskDetail): TaskDetail["versions"] {
  return [...task.versions].sort((left, right) =>
    (left.version ?? "").localeCompare(right.version ?? ""),
  );
}

/** Ułamek też przychodzi jako `number | string` — ten sam powód co przy `count`. */
export function percent(share: number | string): string {
  const value = typeof share === "number" ? share : Number.parseFloat(share);
  return `${(100 * value).toFixed(1)}%`;
}

/** Ile z rocznika jest rozstrzygnięte — pasek postępu pulpitu W2.3. */
export function decidedShare(year: CorpusProgress["years"][number]): number {
  const total = count(year.total);
  if (total === 0) {
    return 0;
  }

  return (count(year.approved) + count(year.corrected) + count(year.rejected)) / total;
}
