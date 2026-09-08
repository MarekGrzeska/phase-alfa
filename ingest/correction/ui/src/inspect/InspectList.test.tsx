import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { InspectList } from "./InspectList";
import type { ListData } from "./api";

/** Lista inspektora. Testy pilnują tego, co zeszło z serwera na front:
 *  wiersz filtrów, adres kanoniczny w pasku i pamięć rozmiaru strony. */

function payload(overrides: Partial<ListData> = {}): ListData {
  return {
    table: {
      name: "task",
      single_key: "id",
      note: "Jednostka logiczna.",
      columns: [
        { name: "id", type: "integer", nullable: false, default: null, source: "baza", parent: null },
        { name: "number", type: "text", nullable: false, default: null, source: "parser", parent: null },
        {
          name: "review_status",
          type: "text",
          nullable: false,
          default: "'pending'",
          source: "ekran korekty",
          parent: null,
        },
        {
          name: "position",
          type: "integer",
          nullable: false,
          default: null,
          source: "parser",
          parent: null,
        },
        {
          name: "marking_scheme_id",
          type: "integer",
          nullable: false,
          default: null,
          source: "ingest",
          parent: "document",
        },
      ],
      parents: { marking_scheme_id: "document" },
    },
    visible: ["id", "number", "review_status"],
    rows: [
      {
        key: 7,
        cells: {
          id: { text: "7", full: "7" },
          number: { text: "20", full: "20" },
          review_status: { text: "pending", full: "pending" },
        },
        parents: [{ table: "document", id: 3 }],
      },
    ],
    total: 1,
    view: {
      page: 1,
      per_page: 50,
      sort: null,
      direction: "asc",
      all_columns: false,
      filters: [],
    },
    links: {
      canonical: "/inspect/task",
      clear: "/inspect/task",
      columns: "/inspect/task?_cols=all",
      sort: { id: "/inspect/task?_sort=id&_dir=asc", number: "/inspect/task?_sort=number&_dir=asc" },
      drop: {},
      previous: null,
      next: null,
      per: { "25": "/inspect/task?_per=25", "50": "/inspect/task", "100": "/inspect/task?_per=100" },
    },
    described: {
      id: { column: "id", operators: ["eq", "ne", "gt", "gte", "lt", "lte"], default: "eq", is_enum: false, options: [] },
      number: { column: "number", operators: ["eq", "ne", "contains"], default: "contains", is_enum: false, options: [] },
      review_status: {
        column: "review_status",
        operators: ["eq", "ne", "null", "notnull"],
        default: "eq",
        is_enum: true,
        options: ["pending", "approved", "corrected", "rejected"],
      },
    },
    operators: {
      eq: ["=", "równe"],
      ne: ["≠", "różne"],
      contains: ["≈", "zawiera"],
      gt: [">", "większe"],
      gte: ["≥", "większe lub równe"],
      lt: ["<", "mniejsze"],
      lte: ["≤", "mniejsze lub równe"],
      null: ["∅", "puste"],
      notnull: ["!∅", "niepuste"],
    },
    operator_prefix: "op.",
    per_page_options: [25, 50, 100],
    summary_columns: ["number", "review_status"],
    errors: [],
    ...overrides,
  };
}

function server(body: ListData) {
  return vi.fn(async (url: string) => {
    void url;
    return { ok: true, status: 200, json: async () => body } as Response;
  });
}

beforeEach(() => {
  window.history.replaceState(null, "", "/inspect/task");
  window.localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("kolumna słownikowa daje wybór z listy, nie pole tekstowe", async () => {
  // Literówka w statusie dawałaby pustą listę i wyglądała jak brak danych.
  vi.stubGlobal("fetch", server(payload()));
  render(<InspectList />);

  const filter = await screen.findByRole("combobox", { name: "wartość filtru dla review_status" });
  expect(within(filter).getAllByRole("option").map((o) => o.textContent)).toEqual([
    "—",
    "pending",
    "approved",
    "corrected",
    "rejected",
  ]);
  expect(screen.queryByRole("textbox", { name: "filtr dla review_status" })).toBeNull();
  // Operatory zawężone: po statusie nie szuka się fragmentu.
  const operator = screen.getByRole("combobox", { name: "operator dla review_status" });
  expect(within(operator).queryByTitle("zawiera")).toBeNull();
});

test("zmiana pola filtruje sama — bez przycisku", async () => {
  const fetchMock = server(payload());
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup();
  render(<InspectList />);

  await screen.findByRole("combobox", { name: "wartość filtru dla review_status" });
  await user.selectOptions(
    screen.getByRole("combobox", { name: "wartość filtru dla review_status" }),
    "approved",
  );

  await waitFor(() => {
    const last = fetchMock.mock.calls.at(-1)?.[0] as string;
    expect(last).toContain("review_status=approved");
    expect(last).toContain("op.review_status=eq");
  });
});

test("filtr po kolumnie spoza widoku jedzie dalej ukryty", async () => {
  // Inaczej znikałby po pierwszym użyciu wiersza filtrów.
  const filtered = payload({
    view: {
      page: 1,
      per_page: 50,
      sort: null,
      direction: "asc",
      all_columns: false,
      filters: [
        { param: "position__gte", label: "position ≥ 1", column: "position", op: "gte", value: "1" },
      ],
    },
    links: { ...payload().links, drop: { position__gte: "/inspect/task" } },
  });
  const fetchMock = server(filtered);
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup();
  render(<InspectList />);

  await screen.findByRole("combobox", { name: "wartość filtru dla review_status" });
  await user.selectOptions(
    screen.getByRole("combobox", { name: "wartość filtru dla review_status" }),
    "approved",
  );

  await waitFor(() => {
    expect(fetchMock.mock.calls.at(-1)?.[0] as string).toContain("position__gte=1");
  });
});

test("adres w pasku staje się kanoniczny", async () => {
  // Wiersz filtrów wysyła `op.kolumna` osobno od wartości; w pasku ma zostać
  // postać, którą da się wkleić w notatce.
  window.history.replaceState(null, "", "/inspect/task?op.review_status=eq&review_status=pending");
  vi.stubGlobal(
    "fetch",
    server(payload({ links: { ...payload().links, canonical: "/inspect/task?review_status=pending" } })),
  );
  render(<InspectList />);

  await screen.findByText("Kolumny tej tabeli i kto je pisze");
  expect(window.location.pathname + window.location.search).toBe(
    "/inspect/task?review_status=pending",
  );
});

test("rozmiar strony pamięta się między tabelami", async () => {
  const fetchMock = server(payload());
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup();
  const view = render(<InspectList />);

  await screen.findByText("na stronie:");
  await user.click(screen.getByRole("link", { name: "25" }));
  view.unmount();

  // Inna tabela, ten sam wybór człowieka — wcześniej pamiętało go ciasteczko.
  window.history.replaceState(null, "", "/inspect/document");
  render(<InspectList />);
  await waitFor(() => {
    expect(fetchMock.mock.calls.at(-1)?.[0] as string).toContain("_per=25");
  });
});

test("zdjęcie filtru i sortowanie idą po adresach z serwera", async () => {
  const filtered = payload({
    view: {
      page: 1,
      per_page: 50,
      sort: "number",
      direction: "asc",
      all_columns: false,
      filters: [
        { param: "kind", label: "kind = closed", column: "kind", op: "eq", value: "closed" },
      ],
    },
    links: {
      ...payload().links,
      drop: { kind: "/inspect/task?_sort=number&_dir=asc" },
      sort: { number: "/inspect/task?kind=closed&_sort=number&_dir=desc" },
    },
  });
  const fetchMock = server(filtered);
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup();
  render(<InspectList />);

  const chip = await screen.findByTitle("zdejmij");
  expect(chip.getAttribute("href")).toBe("/inspect/task?_sort=number&_dir=asc");

  await user.click(screen.getByRole("link", { name: /number/ }));
  await waitFor(() => {
    expect(fetchMock.mock.calls.at(-1)?.[0] as string).toContain("_dir=desc");
  });
});

test("odrzucony filtr jest nazwany, a nie po cichu pominięty", async () => {
  vi.stubGlobal(
    "fetch",
    server(payload({ rows: [], errors: ["Filtr po nieznanej kolumnie albo operatorze, pominięty: nope"] })),
  );
  render(<InspectList />);

  expect(await screen.findByText(/pominięty: nope/)).toBeDefined();
  expect(screen.getByText("Nie wykonano zapytania.")).toBeDefined();
});
