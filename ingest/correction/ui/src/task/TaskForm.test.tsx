import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { TaskForm } from "./TaskForm";
import type { Task, TaskPayload } from "./types";

/** Formularz korekty. Testy pilnują tego, na czym stoi pomiar S8: co idzie do
 *  zapisu, co zostaje na ekranie po odmowie i czego korektor nie traci. */

function task(overrides: Partial<Task> = {}): Task {
  return {
    id: 12,
    number: "20",
    max_points: 3,
    kind: "open_short",
    page: 7,
    review_status: "pending",
    code: "OMAP",
    session: "2025-05-01",
    year: 2025,
    document_path: "OMAP-100-2505-zasady.pdf",
    closed_have_criteria: false,
    criteria: [
      {
        id: 5,
        points: 3,
        label: "pełne rozwiązanie",
        description: null,
        conditions: [
          {
            id: 8,
            description: "poprawny sposób obliczenia pola",
            expressions: [{ id: 9, expression: "P = 15² − 3", mathjson: null }],
          },
        ],
      },
    ],
    requirements: [],
    solutions: [],
    rules: [],
    versions: [
      {
        id: 3,
        code: "OMAP",
        variant: "100",
        version: null,
        content: "Treść zadania 20",
        answers: [{ id: 4, part: null, answer: "105" }],
      },
    ],
    assets: [],
    hints: [],
    model_notes: null,
    ...overrides,
  };
}

function payload(overrides: Partial<TaskPayload> = {}): TaskPayload {
  return {
    task: task(),
    nav: { previous: null, next: 13 },
    requirements: [],
    started_at: "2026-09-08T10:00:00+00:00",
    page: 7,
    document_pages: 30,
    status_labels: {
      pending: "do zatwierdzenia",
      approved: "zatwierdzone",
      corrected: "poprawione",
      rejected: "odrzucone",
    },
    task_kinds: ["closed", "open_short", "open_extended", "essay"],
    ...overrides,
  };
}

/** Serwer, który na GET oddaje zadanie, a na POST — to, co mu podstawimy. */
function server(get: TaskPayload, post?: { status: number; body: unknown }) {
  return vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === "POST") {
      const answer = post ?? { status: 200, body: { redirect: "/next" } };
      return {
        ok: answer.status === 200,
        status: answer.status,
        json: async () => answer.body,
      } as Response;
    }
    return { ok: true, status: 200, json: async () => get } as Response;
  });
}

function sentBody(fetchMock: ReturnType<typeof server>) {
  const call = fetchMock.mock.calls.find((args) => (args[1] as RequestInit)?.method === "POST");
  return JSON.parse((call![1] as RequestInit).body as string);
}

beforeEach(() => {
  window.history.replaceState(null, "", "/task/12");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("pokazuje próg, warunek i zapis równoważny", async () => {
  vi.stubGlobal("fetch", server(payload()));
  render(<TaskForm />);

  expect(await screen.findByDisplayValue("pełne rozwiązanie")).toBeDefined();
  expect(screen.getByDisplayValue("poprawny sposób obliczenia pola")).toBeDefined();
  expect(screen.getByDisplayValue("P = 15² − 3")).toBeDefined();
});

test("zatwierdzenie wysyła pola pod nazwami, które rozstrzyga db.save", async () => {
  const fetchMock = server(payload());
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup();
  render(<TaskForm />);

  const label = await screen.findByDisplayValue("pełne rozwiązanie");
  await user.clear(label);
  await user.type(label, "pełne rozwiązanie zadania");
  await user.click(screen.getByRole("button", { name: /Zatwierdź/ }));

  await waitFor(() => expect(sentBody(fetchMock).action).toBe("approve"));
  const body = sentBody(fetchMock);
  expect(body.fields["criterion.5.label"]).toBe("pełne rozwiązanie zadania");
  expect(body.fields["answer.4.answer"]).toBe("105");
  // Znacznik wychodzi z serwera przy wydaniu zadania i wraca nietknięty:
  // pomiar S8 liczy czas pracy, a nie czas od ostatniego kliknięcia.
  expect(body.started_at).toBe("2026-09-08T10:00:00+00:00");
});

test("niezaznaczone „usuń” nie jedzie w zapisie — na jego BRAKU stoi kasowanie", async () => {
  const fetchMock = server(payload());
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup();
  render(<TaskForm />);

  await screen.findByDisplayValue("pełne rozwiązanie");
  await user.click(screen.getByRole("button", { name: /Zatwierdź/ }));

  await waitFor(() => expect(sentBody(fetchMock).fields).toBeDefined());
  expect(sentBody(fetchMock).fields["delete.criterion.5"]).toBeUndefined();

  const trash = screen.getAllByRole("checkbox")[0];
  await user.click(trash);
  await user.click(screen.getByRole("button", { name: /Zatwierdź/ }));

  await waitFor(() => {
    const calls = fetchMock.mock.calls.filter((args) => (args[1] as RequestInit)?.method === "POST");
    expect(calls.length).toBe(2);
  });
});

test("rozstrzygnięcie prowadzi tam, gdzie każe serwer", async () => {
  const fetchMock = server(payload(), { status: 200, body: { redirect: "/next?year=2025" } });
  vi.stubGlobal("fetch", fetchMock);
  const assign = vi.fn();
  vi.stubGlobal("location", { ...window.location, assign, search: "", pathname: "/task/12" });
  const user = userEvent.setup();
  render(<TaskForm />);

  await screen.findByDisplayValue("pełne rozwiązanie");
  await user.click(screen.getByRole("button", { name: /Zatwierdź/ }));

  await waitFor(() => expect(assign).toHaveBeenCalledWith("/next?year=2025"));
});

test("po odmowie zostaje POWÓD i to, co człowiek wpisał", async () => {
  // Odczyt czterech liczb z siatki kosztuje minutę; kasowanie go za literówkę
  // w innym polu jest karą bez związku z przewinieniem.
  const fetchMock = server(payload(), {
    status: 422,
    body: { errors: ["Opis warunku nie może być puste."] },
  });
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup();
  render(<TaskForm />);

  const label = await screen.findByDisplayValue("pełne rozwiązanie");
  await user.clear(label);
  await user.type(label, "napisane i niezapisane");
  await user.click(screen.getByRole("button", { name: /Zatwierdź/ }));

  expect(await screen.findByText("Opis warunku nie może być puste.")).toBeDefined();
  expect(screen.getByDisplayValue("napisane i niezapisane")).toBeDefined();
});

test("dołożenie progu zostawia korektora na zadaniu i pamięta poprawkę", async () => {
  const grown = payload({
    task: task({
      criteria: [
        ...task().criteria,
        { id: 6, points: 2, label: null, description: null, conditions: [] },
      ],
    }),
    edited_before: true,
  });
  const fetchMock = server(payload(), { status: 200, body: grown });
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup();
  render(<TaskForm />);

  await screen.findByDisplayValue("pełne rozwiązanie");
  await user.click(screen.getByRole("button", { name: "+ próg punktowy" }));

  // Formularz jest niekontrolowany, więc nowy próg musi go PRZEMONTOWAĆ —
  // inaczej pola pokazywałyby stan sprzed dołożenia.
  expect(await screen.findByDisplayValue("2")).toBeDefined();
  expect(screen.getByText(/W tej rundzie były już poprawki/)).toBeDefined();
});

test("zadanie zamknięte bez kryteriów: norma dokumentu kontra dziura", async () => {
  const closed = task({ kind: "closed", criteria: [], closed_have_criteria: false });
  vi.stubGlobal("fetch", server(payload({ task: closed })));
  const { unmount } = render(<TaskForm />);
  expect(await screen.findByText(/norma dokumentu/)).toBeDefined();
  unmount();

  vi.stubGlobal(
    "fetch",
    server(payload({ task: { ...closed, closed_have_criteria: true } })),
  );
  render(<TaskForm />);
  expect(await screen.findByText(/dziura/)).toBeDefined();
});

test("podgląd klucza chodzi po stronach, a strona zostaje w adresie", async () => {
  vi.stubGlobal("fetch", server(payload()));
  const user = userEvent.setup();
  render(<TaskForm />);

  const image = await screen.findByRole("img", { name: /strona 7 klucza/ });
  expect(image.getAttribute("src")).toBe("/task/12/page.png?n=7");

  await user.click(screen.getByRole("button", { name: /strona 8/ }));
  expect(window.location.search).toContain("page=8");
});

test("nawigacja po kluczu niesie zakres pracy", async () => {
  window.history.replaceState(null, "", "/task/12?year=2025&variant=100");
  vi.stubGlobal("fetch", server(payload()));
  render(<TaskForm />);

  const next = await screen.findByRole("link", { name: /następne/ });
  expect(next.getAttribute("href")).toBe("/task/13?year=2025&variant=100");
});

test("zakres jedzie z zapisem, bo po rozstrzygnięciu ekran skacze na /next", async () => {
  window.history.replaceState(null, "", "/task/12?year=2025&variant=100");
  const fetchMock = server(payload());
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup();
  render(<TaskForm />);

  await screen.findByDisplayValue("pełne rozwiązanie");
  await user.click(screen.getByRole("button", { name: /Zatwierdź/ }));

  await waitFor(() => expect(sentBody(fetchMock).scope).toBeDefined());
  expect(sentBody(fetchMock).scope).toEqual({ year: "2025", code: "", variant: "100" });
});

test("„Cofnij do korekty” pokazuje się dopiero po rozstrzygnięciu", async () => {
  vi.stubGlobal("fetch", server(payload()));
  const { unmount } = render(<TaskForm />);
  await screen.findByDisplayValue("pełne rozwiązanie");
  expect(screen.queryByRole("button", { name: /Cofnij do korekty/ })).toBeNull();
  unmount();

  vi.stubGlobal("fetch", server(payload({ task: task({ review_status: "approved" }) })));
  render(<TaskForm />);
  expect(await screen.findByRole("button", { name: /Cofnij do korekty/ })).toBeDefined();
});

test("próg ponad pulą zadania jest ostrzeżeniem, nie blokadą", async () => {
  // Taki zapis stoi w prawdziwym kluczu CKE (OMAP-900-2105, literówka komisji),
  // więc schemat go dopuszcza — chodzi o to, żeby człowiek nie powtórzył go przez pomyłkę.
  const over = task({
    max_points: 2,
    criteria: [{ id: 5, points: 3, label: "za dużo", description: null, conditions: [] }],
  });
  vi.stubGlobal("fetch", server(payload({ task: over })));
  render(<TaskForm />);

  expect(await screen.findByText("próg ponad pulą zadania")).toBeDefined();
  const decide = screen.getByRole("button", { name: /Zatwierdź/ });
  expect(decide.hasAttribute("disabled")).toBe(false);
});

test("wycinek: ramka, podgląd strony zeszytu i osobna decyzja o opisie", async () => {
  const withAsset = task({
    assets: [
      {
        id: 21,
        kind: "diagram",
        path: "TEST/z20-0.png",
        page: 3,
        variant: "100",
        version: null,
        paper_path: "raw/zeszyt.pdf",
        paper_pages: 20,
        box: { x0: "0.0", top: "0.0", x1: "595.0", bottom: "842.0" },
        cropped: false,
        framed: false,
        description: null,
        description_status: "none",
      },
    ],
  });
  const fetchMock = server(payload({ task: withAsset }));
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup();
  render(<TaskForm />);

  expect(await screen.findByText("ramka: cała strona")).toBeDefined();
  const page = screen.getByRole("img", { name: /strona 3 zeszytu zadań/ });
  expect(page.getAttribute("src")).toBe("/asset/21/page.png?n=3");

  const x0 = within(screen.getByText("ramka: cała strona").closest(".criterion")!)
    .getAllByRole("textbox")[1];
  await user.clear(x0);
  await user.type(x0, "100");
  await user.click(screen.getByRole("button", { name: "Wytnij" }));

  await waitFor(() => expect(sentBody(fetchMock).action).toBe("crop"));
  expect(sentBody(fetchMock).fields["asset.21.x0"]).toBe("100");
});
