import { useEffect, useState } from "react";

import { CorpusBrowser } from "./corpus/CorpusBrowser";
import { ProgressDashboard } from "./corpus/ProgressDashboard";
import { SessionDemo } from "./SessionDemo";

const VIEWS = ["corpus", "progress", "session"] as const;
export type View = (typeof VIEWS)[number];

export interface Route {
  readonly view: View;
  readonly form: number | null;
  readonly task: number | null;
}

/**
 * Routing to ADRES i nic więcej — biblioteka routingu byłaby tu zależnością
 * na jeden ekran narzędzia badawczego. Odświeżenie strony wraca w to samo
 * miejsce, a link do zadania da się wkleić w notatce.
 */
export function readRoute(search: string): Route {
  const params = new URLSearchParams(search);
  const view = params.get("view");
  return {
    view: VIEWS.includes(view as View) ? (view as View) : "corpus",
    form: numberOrNull(params.get("form")),
    task: numberOrNull(params.get("task")),
  };
}

export function writeRoute(route: Route): string {
  const params = new URLSearchParams();
  params.set("view", route.view);
  if (route.form !== null) {
    params.set("form", String(route.form));
  }
  if (route.task !== null) {
    params.set("task", String(route.task));
  }
  return `?${params.toString()}`;
}

function numberOrNull(raw: string | null): number | null {
  if (raw === null || !/^\d+$/.test(raw)) {
    return null;
  }
  return Number.parseInt(raw, 10);
}

export function App() {
  const [route, setRoute] = useState<Route>(() => readRoute(window.location.search));

  useEffect(() => {
    // `popstate`, bo przycisk „wstecz" ma działać — bez tego adres się zmienia,
    // a widok zostaje ten sam i wygląda to na zawieszenie aplikacji.
    const onPop = () => setRoute(readRoute(window.location.search));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const go = (next: Partial<Route>) => {
    const merged = { ...route, ...next };
    window.history.pushState(null, "", writeRoute(merged));
    setRoute(merged);
  };

  return (
    <main className={route.view === "corpus" ? "wide" : undefined}>
      <h1>Klucz</h1>
      <nav className="views">
        <button type="button" aria-current={route.view === "corpus"}
                onClick={() => go({ view: "corpus" })}>Korpus</button>
        <button type="button" aria-current={route.view === "progress"}
                onClick={() => go({ view: "progress" })}>Postęp ingestu</button>
        <button type="button" aria-current={route.view === "session"}
                onClick={() => go({ view: "session" })}>Model sesji</button>
      </nav>

      {route.view === "corpus" && (
        <CorpusBrowser
          formId={route.form}
          taskId={route.task}
          onSelect={(next) => go(next)}
        />
      )}
      {route.view === "progress" && <ProgressDashboard />}
      {route.view === "session" && <SessionDemo />}
    </main>
  );
}
