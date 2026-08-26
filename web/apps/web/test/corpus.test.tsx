import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { readRoute, writeRoute } from "../src/App";
import { ProgressView } from "../src/corpus/ProgressDashboard";
import { TaskDetailView } from "../src/corpus/TaskDetailView";
import { count, decidedShare, formName, versionsInOrder } from "../src/corpus/format";
import type { CorpusProgress, TaskDetail } from "../src/corpus/format";

afterEach(cleanup);

// Kształt odpowiedzi API jest tu wpisany ręcznie CELOWO: komponenty dostają
// dane, a nie pobierają je, więc test nie potrzebuje ani sieci, ani bazy.
// Liczby jako STRINGI w części pól — tak wygląda `int32` z generatora OpenAPI
// .NET-a i to jest pułapka, którą `count` ma gasić.
const TASK: TaskDetail = {
  id: 7,
  number: "16",
  maxPoints: "2",
  kind: "open_short",
  reviewStatus: "corrected",
  page: 9,
  versions: [
    {
      id: 2,
      code: "OMAP",
      variant: "100",
      version: "Y",
      content: "Treść wersji Y",
      page: 9,
      answers: [{ id: 11, part: null, answer: "30%" }],
      assets: [],
    },
    {
      id: 1,
      code: "OMAP",
      variant: "100",
      version: "X",
      content: "Treść wersji X",
      page: 9,
      answers: [],
      assets: [
        { id: 5, kind: "chart", description: "Wykres słupkowy wydatków.", descriptionStatus: "approved" },
      ],
    },
  ],
  criteria: [
    {
      id: 3,
      points: 2,
      label: "pełne rozwiązanie",
      description: null,
      conditions: [
        {
          id: 4,
          description: "obliczenie liczby przegranych meczów (12)",
          expressions: [
            { id: 6, expression: "100% - (25% + 45%)", mathJson: null, mathJsonStatus: "failed" },
          ],
        },
      ],
    },
  ],
  requirements: [
    { id: 8, regime: "e8-pp2017", kind: "specific", stage: "VII-VIII", path: "XIII.2", content: "oblicza liczbę a" },
  ],
  solutions: [],
  rules: [{ id: 9, kind: "result_only", content: "Sam wynik to 0 punktów.", tasksFrom: "16", tasksTo: "21" }],
};

const PROGRESS: CorpusProgress = {
  years: [
    { year: 2025, total: 222, pending: 200, approved: 15, corrected: 5, rejected: 2 },
    { year: 2026, total: "194", pending: "194", approved: 0, corrected: 0, rejected: 0 },
  ],
  totals: {
    tasks: 1436,
    decided: 22,
    approved: 15,
    corrected: 5,
    rejected: 2,
    pending: 1414,
    hitShare: 0.75,
    assets: 607,
    assetsDescribed: 12,
    expressions: 514,
    expressionsWithMathJson: 414,
  },
};

describe("format", () => {
  it("liczba z kontraktu bywa stringiem i ma zostać liczbą", () => {
    expect(count("194")).toBe(194);
    expect(count(194)).toBe(194);
  });

  it("nazwa formy czyta się jak na arkuszu", () => {
    expect(
      formName({ id: 1, code: "OMAP", variant: "100", version: "X", session: "2025-05-01", tasks: 21, points: 30 }),
    ).toBe("OMAP-100 X · 2025-05");
  });

  it("wersje ustawiają się X przed Y niezależnie od kolejności z bazy", () => {
    expect(versionsInOrder(TASK).map((version) => version.version)).toEqual(["X", "Y"]);
  });

  it("postęp rocznika liczy rozstrzygnięte, nie zatwierdzone", () => {
    // 15 + 5 + 2 z 222: odrzucone też są rozstrzygnięte — praca została wykonana.
    expect(decidedShare(PROGRESS.years[0]!)).toBeCloseTo(22 / 222, 5);
  });
});

describe("routing w adresie", () => {
  it("czyta widok i zaznaczenie z query stringa", () => {
    expect(readRoute("?view=progress&form=3&task=42")).toEqual({
      view: "progress",
      form: 3,
      task: 42,
    });
  });

  it("nieznany widok wraca do korpusu zamiast pustego ekranu", () => {
    expect(readRoute("?view=czegos-takiego-nie-ma").view).toBe("corpus");
  });

  it("adres da się złożyć z powrotem", () => {
    expect(writeRoute({ view: "corpus", form: 3, task: null })).toBe("?view=corpus&form=3");
  });
});

describe("podgląd zadania", () => {
  it("pokazuje obie wersje bliźniaka obok siebie", () => {
    render(<TaskDetailView task={TASK} />);

    expect(screen.getByText("Treść wersji X")).toBeDefined();
    expect(screen.getByText("Treść wersji Y")).toBeDefined();
  });

  it("nie spłaszcza trzech poziomów dysjunkcji", () => {
    render(<TaskDetailView task={TASK} />);

    const criterion = screen.getByText("obliczenie liczby przegranych meczów (12)").closest("li");
    expect(criterion).not.toBeNull();
    expect(within(criterion!).getByText("100% - (25% + 45%)")).toBeDefined();
  });

  it("wycinek dostaje alt-text z korpusu, nie pustą ramkę", () => {
    render(<TaskDetailView task={TASK} />);

    const image = screen.getByAltText("Wykres słupkowy wydatków.") as HTMLImageElement;
    expect(image.getAttribute("src")).toBe("/api/corpus/assets/5");
  });

  it("mówi wprost, że zapis nie ma MathJSON-a", () => {
    render(<TaskDetailView task={TASK} />);

    expect(screen.getByText("konwerter nie ugryzł")).toBeDefined();
  });
});

describe("pulpit postępu", () => {
  it("pokazuje S8 i pokrycie, a nie samą liczbę zadań", () => {
    render(<ProgressView progress={PROGRESS} />);

    expect(screen.getByText("22/1436")).toBeDefined();
    expect(screen.getByText("75.0%")).toBeDefined();
    expect(screen.getByText("414/514")).toBeDefined();
  });

  it("rocznik bez ani jednego rozstrzygnięcia ma zerowy pasek", () => {
    render(<ProgressView progress={PROGRESS} />);

    const bars = screen.getAllByRole("progressbar") as HTMLProgressElement[];
    expect(bars[1]!.value).toBe(0);
  });
});
