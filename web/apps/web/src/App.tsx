import { useState } from "react";

import {
  answerOf,
  answerTask,
  checkBeforeSubmit,
  createSession,
  currentTask,
  next,
  previous,
  progress,
} from "@klucz/core";
import type { Task } from "@klucz/core";

/**
 * Zadania na sztywno: to szkielet z G1.4, a nie ekran ucznia. Korpus wchodzi
 * w A2, widok statusu bazy — w W1. Sens tego ekranu jest jeden: model sesji
 * z `@klucz/core` ma się kręcić w Reakcie, zanim ktokolwiek dołoży do niego dane.
 */
const DEMO_TASKS: readonly Task[] = [
  { id: "t01", number: "1", maxPoints: 1, kind: "closed" },
  { id: "t16", number: "16", maxPoints: 2, kind: "open_short" },
  { id: "t20", number: "20", maxPoints: 3, kind: "open_extended" },
];

export function App() {
  const [session, setSession] = useState(() => createSession(DEMO_TASKS));

  const task = currentTask(session);
  const { answered, total } = progress(session);
  const check = checkBeforeSubmit(session);

  return (
    <main>
      <h1>Klucz</h1>
      <p className="lead">
        Szkielet weba (G1.4). Widok statusu bazy dokłada W1, korpus — A2.
      </p>

      {task === undefined ? (
        <p>Arkusz bez zadań.</p>
      ) : (
        <section aria-labelledby="zadanie">
          <h2 id="zadanie">
            Zadanie {task.number} <small>({task.maxPoints} pkt)</small>
          </h2>

          <label>
            Odpowiedź
            <input
              value={answerOf(session, task.id) ?? ""}
              onChange={(event) => setSession(answerTask(session, task.id, event.target.value))}
            />
          </label>

          <nav>
            <button type="button" onClick={() => setSession(previous(session))}>
              Poprzednie
            </button>
            <button type="button" onClick={() => setSession(next(session))}>
              Następne
            </button>
          </nav>
        </section>
      )}

      <footer>
        <p>
          Odpowiedzi: {answered} z {total}
        </p>
        <p>
          {check.ok
            ? "Komplet — arkusz gotowy do wysłania."
            : `Bez odpowiedzi: ${check.missing.map((missing) => missing.number).join(", ") || "—"}`}
        </p>
      </footer>
    </main>
  );
}
