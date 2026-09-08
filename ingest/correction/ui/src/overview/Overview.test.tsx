import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { Overview } from "./Overview";
import type { Overview as OverviewData } from "../app/api";

/** Przegląd korekty: liczby S8 i lista zadań. Testy pilnują tego, co ekran MÓWI
 *  korektorowi — udziału trafień, prognozy i zakresu, w którym pracuje. */

function payload(overrides: Partial<OverviewData> = {}): OverviewData {
  return {
    numbers: {
      status: {
        counts: { pending: 4, approved: 3, corrected: 1, rejected: 2 },
        total: 10,
        decided: 6,
        pending: 4,
        done_share: 0.6,
        hit_share: 0.75,
        rejected: 2,
      },
      durations: { events: 6, median: 92.4, total: 700, long: 1 },
      forecast: { tasks: 4, seconds: 369.6, hours: 0.1026 },
      years: [
        { year: 2025, total: 6, pending: 2, approved: 2, corrected: 1, rejected: 1 },
        { year: 2019, total: 4, pending: 2, approved: 1, corrected: 0, rejected: 1 },
      ],
      assets: { total: 9, cropped: 7, framed: 8 },
    },
    tasks: [
      {
        id: 12,
        number: "20",
        max_points: 3,
        kind: "open_short",
        review_status: "pending",
        code: "OMAP",
        session: "2025-05-01",
        year: 2025,
        variants: "100",
      },
    ],
    options: { years: [2019, 2025], codes: ["OMAP"], variants: ["100", "700"] },
    selected: { status: null, year: null, code: null, variant: null },
    next_id: 12,
    status_labels: {
      pending: "do zatwierdzenia",
      approved: "zatwierdzone",
      corrected: "poprawione",
      rejected: "odrzucone",
    },
    ...overrides,
  };
}

function answerWith(body: OverviewData, status = 200) {
  return vi.fn().mockResolvedValue({
    ok: status === 200,
    status,
    json: async () => body,
  } as Response);
}

beforeEach(() => {
  window.history.replaceState(null, "", "/");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("pokazuje liczby S8 tak, jak liczy je serwer", async () => {
  vi.stubGlobal("fetch", answerWith(payload()));
  render(<Overview />);

  // Udziały są ułamkami w API, a procentami na ekranie — zaokrąglenie jest
  // tutaj, więc to tutaj może się zepsuć.
  expect(await screen.findByText("60%")).toBeDefined();
  expect(screen.getByText("75%")).toBeDefined();
  expect(screen.getByText("92 s")).toBeDefined();
  expect(screen.getByText("0.1 h")).toBeDefined();
  expect(screen.getByText("7/9")).toBeDefined();
  expect(screen.getByText("6/10 rozstrzygniętych")).toBeDefined();
});

test("pokrycie per rocznik idzie wierszami z bazy", async () => {
  vi.stubGlobal("fetch", answerWith(payload()));
  render(<Overview />);

  const table = (await screen.findAllByRole("table"))[0];
  const rows = within(table).getAllByRole("row").slice(1) as HTMLTableRowElement[];
  expect(rows.map((row) => row.cells[0].textContent)).toEqual(["2025", "2019"]);
});

test("zadanie prowadzi do formularza, a status ma etykietę ze słownika", async () => {
  vi.stubGlobal("fetch", answerWith(payload()));
  render(<Overview />);

  const link = await screen.findByRole("link", { name: "otwórz" });
  expect(link.getAttribute("href")).toBe("/task/12");
  // Po znaczniku statusu, nie po tekście: „do zatwierdzenia" stoi też w liście
  // wyboru filtra, a to jest inna rzecz na tym samym ekranie.
  expect(document.querySelector(".tag.pending")?.textContent).toBe("do zatwierdzenia");
});

test("filtr wchodzi do adresu i do zapytania", async () => {
  const fetchMock = answerWith(payload());
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup();
  render(<Overview />);

  await screen.findByText("Zadania");
  await user.selectOptions(screen.getByRole("combobox", { name: /rocznik/ }), "2025");
  await user.click(screen.getByRole("button", { name: "Filtruj" }));

  await waitFor(() => expect(fetchMock).toHaveBeenLastCalledWith("/api/overview?year=2025"));
  // Adres jest stanem tego ekranu: link do zakresu ma się dać wkleić w notatce.
  expect(window.location.search).toBe("?year=2025");
});

test("zakres jedzie dalej w odnośnikach — pilot zostaje w swoim roczniku", async () => {
  const chosen = payload({ selected: { status: null, year: 2025, code: null, variant: "100" } });
  vi.stubGlobal("fetch", answerWith(chosen));
  render(<Overview />);

  const next = await screen.findByRole("link", { name: /Następne do korekty/ });
  expect(next.getAttribute("href")).toBe("/next?year=2025&variant=100");
  expect(screen.getByRole("link", { name: "otwórz" }).getAttribute("href")).toBe(
    "/task/12?year=2025&variant=100",
  );
});

test("gdy w zakresie nie ma już nic, przycisk ustępuje miejsca zdaniu", async () => {
  vi.stubGlobal("fetch", answerWith(payload({ next_id: null })));
  render(<Overview />);

  expect(await screen.findByText("wszystko rozstrzygnięte")).toBeDefined();
  expect(screen.queryByRole("link", { name: /Następne do korekty/ })).toBeNull();
});

test("pusty korpus mówi, co zrobić, zamiast pokazać pustą tabelę", async () => {
  const empty = payload();
  vi.stubGlobal(
    "fetch",
    answerWith({
      ...empty,
      tasks: [],
      numbers: { ...empty.numbers, years: [] },
    }),
  );
  render(<Overview />);

  expect(await screen.findByText(/Korpus pusty/)).toBeDefined();
  expect(screen.getByText("Nic nie pasuje do filtra.")).toBeDefined();
});

test("błąd serwera pokazuje POWÓD, a nie samą porażkę", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: false,
      status: 400,
      json: async () => ({ detail: "nieznany status: zatwierdzone" }),
    } as Response),
  );
  render(<Overview />);

  expect(await screen.findByText("nieznany status: zatwierdzone")).toBeDefined();
});
