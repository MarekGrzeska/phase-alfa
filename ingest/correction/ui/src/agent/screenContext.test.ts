import { describe, expect, test } from "vitest";

import { screenContextOf } from "./screenContext";

describe("kontekst ekranu z adresu", () => {
  test("formularz zadania ze stroną klucza", () => {
    expect(screenContextOf("/task/42", "?page=7&year=2025", "task")).toEqual({
      view: "task",
      path: "/task/42",
      query: "?page=7&year=2025",
      task_id: 42,
      page: 7,
    });
  });

  test("lista i wiersz inspektora", () => {
    expect(screenContextOf("/inspect/task", "?kind=closed", "inspectList")).toMatchObject({ table: "task" });
    expect(screenContextOf("/inspect/asset/9", "", "inspectRecord")).toMatchObject({ table: "asset", row_id: 9 });
  });

  test("kontrola zdrowia nie jest tabelą", () => {
    const ctx = screenContextOf("/inspect/health/asset_full_page", "", "inspectHealth");
    expect(ctx.health_key).toBe("asset_full_page");
    expect(ctx.table).toBeUndefined();
  });

  test("przegląd bez niczego", () => {
    expect(screenContextOf("/", "", "overview")).toEqual({ view: "overview", path: "/", query: "" });
  });
});
