import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { InspectRecord } from "./InspectRecord";
import type { Provenance, RecordData } from "./api";

/** Widok wiersza: wartości ze źródłem i podgląd strony, z której rekord wyszedł. */

function source(overrides: Partial<Provenance> = {}): Provenance {
  return {
    note: null,
    document_id: 3,
    document_kind: "marking_scheme",
    document_path: "OMAP-100-2505-zasady.pdf",
    document_pages: 30,
    page: 9,
    file_exists: true,
    bbox: null,
    page_size: null,
    asset_id: null,
    crop_path: null,
    crop_exists: false,
    related: [],
    ...overrides,
  };
}

function payload(overrides: Partial<RecordData> = {}): RecordData {
  return {
    table: { name: "task", single_key: "id", note: "Jednostka logiczna." },
    id: 7,
    row_notes: ["nierozstrzygnięte — poza korpusem"],
    columns: [
      { name: "id", kind: "plain", text: "7", parent: null, value: null, source: "baza" },
      {
        name: "review_status",
        kind: "status",
        text: "pending",
        parent: null,
        value: "pending",
        source: "ekran korekty",
      },
      {
        name: "marking_scheme_id",
        kind: "parent",
        text: "3",
        parent: "document",
        value: 3,
        source: "ingest",
      },
      { name: "review_model", kind: "null", text: "NULL", parent: null, value: null, source: "nikt" },
    ],
    parents: [{ column: "marking_scheme_id", table: "document", value: 3, url: "/inspect/document/3" }],
    children: [
      {
        table: "criterion",
        column: "task_id",
        count: 2,
        url: "/inspect/criterion?task_id=7",
        rows: [{ id: 11, text: "3 pkt", url: "/inspect/criterion/11" }],
      },
    ],
    source: source(),
    crop_name: null,
    pdf_page: 9,
    ...overrides,
  };
}

function server(body: RecordData) {
  return vi.fn(async () => ({ ok: true, status: 200, json: async () => body }) as Response);
}

beforeEach(() => {
  window.history.replaceState(null, "", "/inspect/task/7");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("wartość NULL, rodzic i status pokazują się każde po swojemu", async () => {
  vi.stubGlobal("fetch", server(payload()));
  render(<InspectRecord />);

  expect(await screen.findByText("NULL")).toBeDefined();
  // Odnośnik do rodzica jest i w wartości kolumny, i w opisie źródła — oba mają
  // prowadzić w to samo miejsce.
  for (const link of screen.getAllByRole("link", { name: "document #3" })) {
    expect(link.getAttribute("href")).toBe("/inspect/document/3");
  }
  expect(document.querySelector(".tag.pending")?.textContent).toBe("pending");
});

test("rodzice, dzieci i skok do korekty", async () => {
  vi.stubGlobal("fetch", server(payload()));
  render(<InspectRecord />);

  expect(await screen.findByRole("link", { name: "criterion" })).toBeDefined();
  expect(screen.getByRole("link", { name: "#11" }).getAttribute("href")).toBe(
    "/inspect/criterion/11",
  );
  expect(screen.getByRole("link", { name: /Otwórz w korekcie/ }).getAttribute("href")).toBe(
    "/task/7",
  );
});

test("ramka rysuje się WYŁĄCZNIE na swojej stronie", async () => {
  // Na cudzej wisiałaby w powietrzu i kłamała o położeniu zasobu.
  const framed = payload({
    source: source({ bbox: [10, 20, 110, 220], page_size: [595, 842] }),
    pdf_page: 9,
  });
  vi.stubGlobal("fetch", server(framed));
  const { unmount } = render(<InspectRecord />);

  await waitFor(() => expect(document.querySelector("svg rect")).not.toBeNull());
  expect(screen.getByText(/bbox = \[10.0, 20.0, 110.0, 220.0\] pt/)).toBeDefined();
  unmount();

  vi.stubGlobal("fetch", server({ ...framed, pdf_page: 3 }));
  render(<InspectRecord />);

  await waitFor(() => expect(screen.getByAltText("strona 3")).toBeDefined());
  expect(document.querySelector("svg rect")).toBeNull();
  expect(screen.getByText(/ramka jest na stronie 9/)).toBeDefined();
});

test("podgląd chodzi po stronach, a numer zostaje w adresie", async () => {
  vi.stubGlobal("fetch", server(payload()));
  const user = userEvent.setup();
  render(<InspectRecord />);

  await screen.findAllByText(/strona 9 z 30/);
  await user.click(screen.getByRole("button", { name: /następna/ }));
  expect(window.location.search).toContain("_pdfpage=10");
});

test("na krawędzi dokumentu przycisk przestaje prowadzić", async () => {
  vi.stubGlobal("fetch", server(payload({ pdf_page: 1 })));
  render(<InspectRecord />);

  const previous = await screen.findByRole("button", { name: /poprzednia/ });
  expect(previous.hasAttribute("disabled")).toBe(true);
  expect(screen.getByRole("button", { name: /wróć do strony rekordu \(9\)/ })).toBeDefined();
});

test("brakujący plik jest nazwany, a nie chowany", async () => {
  vi.stubGlobal("fetch", server(payload({ source: source({ file_exists: false }) })));
  render(<InspectRecord />);

  expect(await screen.findByText(/Pliku nie ma w mirrorze/)).toBeDefined();
  expect(screen.queryByRole("img")).toBeNull();
});
