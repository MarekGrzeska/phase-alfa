/**
 * Stan sesji rozwiązywania arkusza: odpowiedzi, kolejność zadań, walidacja
 * przed wysyłką.
 *
 * Wszystkie operacje zwracają NOWĄ sesję zamiast mutować starą — React
 * rozpoznaje zmianę po tożsamości obiektu, a faza 2 dostaje ten sam model
 * bez przepisywania.
 */

/** Rodzaje zadań ze schematu bazy (`task.kind`) — jeden słownik w całym produkcie. */
export type TaskKind = "closed" | "open_short" | "open_extended" | "essay";

export interface Task {
  readonly id: string;
  /** Numer w arkuszu: `'16'`, `'4.1'`. Nie kolejność — tę niesie pozycja na liście. */
  readonly number: string;
  readonly maxPoints: number;
  readonly kind: TaskKind;
}

export interface Session {
  readonly tasks: readonly Task[];
  readonly answers: ReadonlyMap<string, string>;
  readonly currentIndex: number;
}

export function createSession(tasks: readonly Task[]): Session {
  const duplicate = firstDuplicateId(tasks);
  if (duplicate !== null) {
    throw new Error(`Dwa zadania o tym samym id: ${duplicate}`);
  }

  return { tasks, answers: new Map(), currentIndex: 0 };
}

/**
 * Zapisuje odpowiedź. Pusta (same białe znaki) KASUJE wpis zamiast zapisywać
 * pustkę — inaczej „odpowiedziane" znaczyłoby dwie różne rzeczy zależnie
 * od tego, czy uczeń kliknął w pole, czy nie.
 */
export function answerTask(session: Session, taskId: string, answer: string): Session {
  requireTask(session, taskId);

  const answers = new Map(session.answers);
  if (answer.trim() === "") {
    answers.delete(taskId);
  } else {
    answers.set(taskId, answer);
  }

  return { ...session, answers };
}

export function answerOf(session: Session, taskId: string): string | undefined {
  return session.answers.get(taskId);
}

export function currentTask(session: Session): Task | undefined {
  return session.tasks[session.currentIndex];
}

/** Skok pod wskazany indeks; poza zakresem zostawia sesję bez zmian. */
export function goTo(session: Session, index: number): Session {
  if (!Number.isInteger(index) || index < 0 || index >= session.tasks.length) {
    return session;
  }

  return { ...session, currentIndex: index };
}

export function next(session: Session): Session {
  return goTo(session, session.currentIndex + 1);
}

export function previous(session: Session): Session {
  return goTo(session, session.currentIndex - 1);
}

export function unansweredTasks(session: Session): readonly Task[] {
  return session.tasks.filter((task) => !session.answers.has(task.id));
}

export interface Progress {
  readonly answered: number;
  readonly total: number;
  /** Ułamek 0–1; pusty arkusz daje 0, a nie dzielenie przez zero. */
  readonly ratio: number;
}

export function progress(session: Session): Progress {
  const total = session.tasks.length;
  const answered = total - unansweredTasks(session).length;

  return { answered, total, ratio: total === 0 ? 0 : answered / total };
}

export type SubmitCheck =
  | { readonly ok: true }
  | { readonly ok: false; readonly missing: readonly Task[] };

/**
 * Walidacja przed wysyłką. Zwraca listę zadań bez odpowiedzi zamiast samego
 * `false` — ekran ma pokazać KTÓRYCH brakuje, a nie tylko że czegoś brakuje.
 *
 * Arkusz bez zadań jest niekompletny: pusta sesja nie jest gotowa do wysłania.
 */
export function checkBeforeSubmit(session: Session): SubmitCheck {
  if (session.tasks.length === 0) {
    return { ok: false, missing: [] };
  }

  const missing = unansweredTasks(session);
  return missing.length === 0 ? { ok: true } : { ok: false, missing };
}

function requireTask(session: Session, taskId: string): void {
  if (!session.tasks.some((task) => task.id === taskId)) {
    throw new Error(`Zadanie spoza sesji: ${taskId}`);
  }
}

function firstDuplicateId(tasks: readonly Task[]): string | null {
  const seen = new Set<string>();

  for (const task of tasks) {
    if (seen.has(task.id)) {
      return task.id;
    }
    seen.add(task.id);
  }

  return null;
}
