/** Kształt zadania z `/api/task/{id}` — to samo, co widział szablon `task.html`. */

export interface Expression {
  readonly id: number;
  readonly expression: string;
  readonly mathjson: unknown | null;
}

export interface Condition {
  readonly id: number;
  readonly description: string;
  readonly expressions: readonly Expression[];
}

export interface Criterion {
  readonly id: number;
  readonly points: number | null;
  readonly label: string | null;
  readonly description: string | null;
  readonly conditions: readonly Condition[];
}

export interface ModelAnswer {
  readonly id: number;
  readonly part: string | null;
  readonly answer: string;
}

export interface Version {
  readonly id: number;
  readonly code: string;
  readonly variant: string;
  readonly version: string | null;
  readonly content: string | null;
  readonly answers: readonly ModelAnswer[];
}

export interface Requirement {
  readonly id: number;
  readonly regime: string;
  readonly kind: string;
  readonly stage: string | null;
  readonly path: string;
  readonly content: string;
}

export interface Asset {
  readonly id: number;
  readonly kind: string;
  readonly path: string;
  readonly page: number;
  readonly variant: string;
  readonly version: string | null;
  readonly paper_path: string | null;
  readonly paper_pages: number | null;
  readonly box: Readonly<Record<"x0" | "top" | "x1" | "bottom", string>>;
  readonly cropped: boolean;
  readonly framed: boolean;
  readonly description: string | null;
  readonly description_status: string;
}

export interface Solution {
  readonly method: string | null;
  readonly points: number | null;
  readonly content: string;
}

export interface Rule {
  readonly kind: string;
  readonly content: string;
  readonly tasks_from: number | null;
  readonly tasks_to: number | null;
}

export interface Hint {
  readonly model: string;
  readonly kind: string;
  readonly points: number | null;
  readonly hint: string;
  readonly detail: readonly string[];
}

export interface ModelNotes {
  readonly model: string;
  readonly action: string;
  readonly when: string;
  readonly reasons: readonly string[];
}

export interface Task {
  readonly id: number;
  readonly number: string;
  readonly max_points: number | null;
  readonly kind: string;
  readonly page: number | null;
  readonly review_status: string;
  readonly code: string;
  readonly session: string;
  readonly year: number;
  readonly document_path: string;
  readonly criteria: readonly Criterion[];
  readonly closed_have_criteria: boolean;
  readonly requirements: readonly Requirement[];
  readonly solutions: readonly Solution[];
  readonly rules: readonly Rule[];
  readonly versions: readonly Version[];
  readonly assets: readonly Asset[];
  readonly hints: readonly Hint[];
  readonly model_notes: ModelNotes | null;
}

export interface TaskPayload {
  readonly task: Task;
  readonly nav: { readonly previous: number | null; readonly next: number | null };
  readonly requirements: readonly Requirement[];
  readonly started_at: string;
  readonly page: number | null;
  readonly document_pages: number | null;
  readonly status_labels: Readonly<Record<string, string>>;
  readonly task_kinds: readonly string[];
  /** Wraca tylko z zapisu: czy w tej rundzie były już poprawki. */
  readonly edited_before?: boolean;
}

/** Odpowiedź na zapis: albo dokąd iść, albo świeże zadanie, albo powody odmowy. */
export type SaveResult =
  | { readonly kind: "redirect"; readonly to: string }
  | { readonly kind: "task"; readonly payload: TaskPayload }
  | { readonly kind: "errors"; readonly messages: readonly string[] };
