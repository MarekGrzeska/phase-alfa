import { render, screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { InspectHealth, InspectIndex } from "./InspectIndex";
import type { HealthData, IndexData } from "./api";

/** Spis tabel i zdrowie danych: każda liczba ma prowadzić do wierszy, a wiersz
 *  — do swojego źródła. To jest cała racja bytu tego ekranu. */

const INDEX: IndexData = {
  tables: [
    { name: "task", count: 42, note: "Jednostka logiczna." },
    { name: "rule", count: 0, note: "Reguła przekrojowa." },
  ],
  views: ["corpus_task"],
  health: [
    { key: "asset_full_page", title: "wycinki na całą stronę", why: "ramka nieprzycięta",
      severity: "problem", count: 3 },
    { key: "expression_failed", title: "zapisy bez MathJSON", why: "konwerter odmówił",
      severity: "info", count: 0 },
  ],
  empty_columns: [{ table: "document", column: "sha256", untouched: 12, total: 12 }],
};

afterEach(() => vi.unstubAllGlobals());

function answer(body: unknown) {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, status: 200, json: async () => body }) as Response));
}

test("tabela pusta jest widoczna jako pusta, nie ukryta", async () => {
  answer(INDEX);
  render(<InspectIndex />);

  const empty = (await screen.findByRole("link", { name: "rule" })).closest("tr");
  expect(empty?.className).toBe("empty");
  expect(screen.getByRole("link", { name: "task" }).getAttribute("href")).toBe("/inspect/task");
});

test("każda kontrola zdrowia prowadzi do swoich wierszy", async () => {
  answer(INDEX);
  render(<InspectIndex />);

  const check = await screen.findByRole("link", { name: "wycinki na całą stronę" });
  expect(check.getAttribute("href")).toBe("/inspect/health/asset_full_page");
  // Zero to nie problem — licznik przestaje krzyczeć.
  const clean = screen.getByRole("link", { name: "zapisy bez MathJSON" }).closest("li");
  expect(within(clean!).getByText("0").className).toContain("zero");
});

test("kontrola listuje wiersze z odnośnikiem do źródła", async () => {
  const health: HealthData = {
    check: { key: "asset_full_page", title: "wycinki na całą stronę",
             why: "ramka nieprzycięta", severity: "problem", table: "asset" },
    columns: ["id", "path"],
    rows: [[{ text: "5", full: "5", link: "/inspect/asset/5" },
            { text: "TEST/z20-0.png", full: "TEST/z20-0.png", link: null }]],
  };
  window.history.replaceState(null, "", "/inspect/health/asset_full_page");
  answer(health);
  render(<InspectHealth />);

  const link = await screen.findByRole("link", { name: "#5" });
  expect(link.getAttribute("href")).toBe("/inspect/asset/5");
  expect(screen.getByText("TEST/z20-0.png")).toBeDefined();
});
