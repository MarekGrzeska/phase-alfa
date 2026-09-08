import type { SaveResult, TaskPayload } from "./types";

/** Wywołania `/api/task/*`. Front trzyma się nazw pól, które rozstrzyga `db.save`. */

export async function fetchTask(taskId: number, page: number | null): Promise<TaskPayload> {
  const query = page === null ? "" : `?page=${page}`;
  const response = await fetch(`/api/task/${taskId}${query}`);
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail ?? `serwer odpowiedział ${response.status}`);
  }
  return (await response.json()) as TaskPayload;
}

export interface SaveRequest {
  readonly taskId: number;
  readonly action: string;
  readonly startedAt: string;
  readonly page: number | null;
  readonly editedBefore: boolean;
  readonly scope: { readonly year: string; readonly code: string; readonly variant: string };
  /** Płaskie pary nazwa→wartość — to samo, co wysyłał formularz HTML. */
  readonly fields: Record<string, string>;
}

export async function saveTask(request: SaveRequest): Promise<SaveResult> {
  const response = await fetch(`/api/task/${request.taskId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      action: request.action,
      started_at: request.startedAt,
      page: request.page,
      edited_before: request.editedBefore,
      scope: request.scope,
      fields: request.fields,
    }),
  });

  if (response.status === 422) {
    const body = (await response.json()) as { errors?: string[] };
    return { kind: "errors", messages: body.errors ?? ["Zapis odrzucony bez podania powodu."] };
  }
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    return { kind: "errors", messages: [detail?.detail ?? `serwer odpowiedział ${response.status}`] };
  }

  const body = (await response.json()) as { redirect?: string } & TaskPayload;
  if (body.redirect !== undefined) {
    return { kind: "redirect", to: body.redirect };
  }
  return { kind: "task", payload: body };
}

/** Wartości formularza w postaci, jakiej oczekuje `db.save`.
 *
 * `FormData` daje dokładnie to, co dawała przeglądarka przy `method="post"`:
 * niezaznaczonych pól wyboru nie ma wcale, a to na ich BRAKU stoi kasowanie
 * wierszy. Stąd formularz jest niekontrolowany — stan trzyma DOM, tak jak
 * trzymał go przez cały pilotaż.
 */
export function fieldsOf(form: HTMLFormElement): Record<string, string> {
  const fields: Record<string, string> = {};
  for (const [name, value] of new FormData(form).entries()) {
    if (typeof value === "string") {
      fields[name] = value;
    }
  }
  return fields;
}
