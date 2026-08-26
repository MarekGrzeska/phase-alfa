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
 * Zadania na sztywno: to szkielet z G1.4, a nie ekran ucznia. Sens tego widoku
 * jest jeden — model sesji z `@klucz/core` ma się kręcić w Reakcie, zanim
 * ktokolwiek dołoży do niego dane. Prawdziwe zadania wchodzą w A3, przez
 * pipeline oceniania; korpus ogląda się w przeglądarce (W2).
 */
const DEMO_TASKS: readonly Task[] = [
  { id: "t01", number: "1", maxPoints: 1, kind: "closed" },
  { id: "t16", number: "16", maxPoints: 2, kind: "open_short" },
  { id: "t20", number: "20", maxPoints: 3, kind: "open_extended" },
];

export function SessionDemo() {
  const [session, setSession] = useState(() => createSession(DEMO_TASKS));
  // Surowy tekst pól, osobno od modelu: `answerTask` KASUJE odpowiedź z samych
  // białych znaków, więc wpisana spacja znikałaby użytkownikowi spod palców.
  const [drafts, setDrafts] = useState<ReadonlyMap<string, string>>(() => new Map());

  const task = currentTask(session);
  const { answered, total } = progress(session);
  const check = checkBeforeSubmit(session);

  return (
    <>
      <p className="lead">
        Szkielet modelu sesji (G1.4) na zadaniach wpisanych na sztywno.
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
              value={drafts.get(task.id) ?? answerOf(session, task.id) ?? ""}
              onChange={(event) => {
                const text = event.target.value;
                setDrafts((previousDrafts) => new Map(previousDrafts).set(task.id, text));
                setSession(answerTask(session, task.id, text));
              }}
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
    </>
  );
}
