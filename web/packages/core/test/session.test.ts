import { describe, expect, it } from "vitest";

import {
  answerOf,
  answerTask,
  checkBeforeSubmit,
  createSession,
  currentTask,
  goTo,
  next,
  previous,
  progress,
  unansweredTasks,
} from "../src/index";
import type { Task } from "../src/index";

const TASKS: readonly Task[] = [
  { id: "t16", number: "16", maxPoints: 2, kind: "open_short" },
  { id: "t17", number: "17", maxPoints: 3, kind: "open_extended" },
  { id: "t01", number: "1", maxPoints: 1, kind: "closed" },
];

describe("createSession", () => {
  it("zaczyna na pierwszym zadaniu i bez odpowiedzi", () => {
    const session = createSession(TASKS);

    expect(session.currentIndex).toBe(0);
    expect(session.answers.size).toBe(0);
    expect(currentTask(session)?.id).toBe("t16");
  });

  it("odrzuca dwa zadania o tym samym id", () => {
    const duplicated = [...TASKS, TASKS[0]!];

    expect(() => createSession(duplicated)).toThrowError(/t16/);
  });
});

describe("answerTask", () => {
  it("nie rusza poprzedniej sesji", () => {
    const before = createSession(TASKS);
    const after = answerTask(before, "t16", "105");

    expect(before.answers.size).toBe(0);
    expect(answerOf(after, "t16")).toBe("105");
  });

  it("pusta odpowiedź kasuje wpis, zamiast zapisywać pustkę", () => {
    const session = answerTask(answerTask(createSession(TASKS), "t16", "105"), "t16", "   ");

    expect(session.answers.has("t16")).toBe(false);
    expect(unansweredTasks(session).map((task) => task.id)).toContain("t16");
  });

  it("odrzuca zadanie spoza sesji", () => {
    expect(() => answerTask(createSession(TASKS), "t99", "x")).toThrowError(/t99/);
  });
});

describe("kolejność zadań", () => {
  it("next i previous nie wychodzą poza zakres", () => {
    const session = createSession(TASKS);

    expect(previous(session).currentIndex).toBe(0);
    expect(next(next(next(next(session)))).currentIndex).toBe(TASKS.length - 1);
  });

  it("goTo poza zakresem zostawia sesję bez zmian", () => {
    const session = createSession(TASKS);

    expect(goTo(session, 9)).toBe(session);
    expect(goTo(session, -1)).toBe(session);
    expect(goTo(session, 1.5)).toBe(session);
  });
});

describe("progress", () => {
  it("liczy odpowiedziane, nie odwiedzone", () => {
    const session = answerTask(next(createSession(TASKS)), "t01", "BD");

    expect(progress(session)).toEqual({ answered: 1, total: 3, ratio: 1 / 3 });
  });

  it("pusty arkusz nie dzieli przez zero", () => {
    expect(progress(createSession([]))).toEqual({ answered: 0, total: 0, ratio: 0 });
  });
});

describe("checkBeforeSubmit", () => {
  it("wskazuje KTÓRYCH zadań brakuje", () => {
    const check = checkBeforeSubmit(answerTask(createSession(TASKS), "t16", "105"));

    expect(check.ok).toBe(false);
    expect(check.ok === false && check.missing.map((task) => task.number)).toEqual(["17", "1"]);
  });

  it("komplet odpowiedzi przechodzi", () => {
    const session = TASKS.reduce(
      (acc, task) => answerTask(acc, task.id, "odpowiedź"),
      createSession(TASKS),
    );

    expect(checkBeforeSubmit(session)).toEqual({ ok: true });
  });

  it("pusta sesja nie jest gotowa do wysłania", () => {
    expect(checkBeforeSubmit(createSession([])).ok).toBe(false);
  });
});
