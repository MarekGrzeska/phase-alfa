/** Na co patrzy korektor — z adresu i z `data-view` skorupy, bo panel i widok
 *  to osobne korzenie Reacta i nie dzielą stanu. Jedzie z każdą wiadomością. */

export interface ScreenContext {
  readonly view: string | null;
  readonly path: string;
  readonly query: string;
  readonly task_id?: number;
  readonly page?: number;
  readonly table?: string;
  readonly row_id?: number;
  readonly health_key?: string;
}

export function screenContextOf(
  path: string,
  query: string,
  view: string | null | undefined,
): ScreenContext {
  const out: {
    -readonly [K in keyof ScreenContext]: ScreenContext[K];
  } = { view: view ?? null, path, query };
  const params = new URLSearchParams(query);

  const task = /^\/task\/(\d+)/.exec(path);
  if (task) {
    out.task_id = Number(task[1]);
    const page = params.get("page");
    if (page !== null && /^\d+$/.test(page)) out.page = Number(page);
  }
  const health = /^\/inspect\/health\/([a-z_]+)/.exec(path);
  if (health) out.health_key = health[1];
  const record = /^\/inspect\/([a-z_]+)(?:\/(\d+))?/.exec(path);
  if (record && !health && record[1] !== "document") {
    out.table = record[1];
    if (record[2] !== undefined) out.row_id = Number(record[2]);
  }
  return out;
}

export function currentScreen(): ScreenContext {
  const root = document.getElementById("root");
  return screenContextOf(window.location.pathname, window.location.search, root?.dataset.view);
}
