import { describe, expect, test } from "vitest";

import type { SessionData } from "./agentClient";
import { NO_USAGE, apply, itemsOf } from "./items";
import type { Turn } from "./items";

const EMPTY: Turn = { items: [], partial: null, navigateTo: null, usage: NO_USAGE, waiting: false };

describe("zdarzenia strumienia → elementy rozmowy", () => {
  test("tekst przed wywołaniem narzędzia staje się osobnym dymkiem", () => {
    let turn = apply(EMPTY, { type: "token", text: "Sprawdzę." });
    turn = apply(turn, { type: "tool_call", id: "c1", name: "db_health", args: {} });
    turn = apply(turn, { type: "tool_result", id: "c1", name: "db_health", is_error: false, text: "{}", ui: null });
    turn = apply(turn, { type: "token", text: "Wszystko gra." });
    turn = apply(turn, { type: "done", state: "finished" });

    expect(turn.items.map((i) => i.kind)).toEqual(["agent", "tool", "agent"]);
    const tool = turn.items[1];
    expect(tool.kind === "tool" && tool.result?.isError).toBe(false);
    expect(turn.partial).toBeNull();
  });

  test("nawigacja czeka do końca odpowiedzi, ostatnia wygrywa", () => {
    let turn = apply(EMPTY, { type: "ui", action: "navigate", url: "/inspect" });
    turn = apply(turn, { type: "ui", action: "navigate", url: "/task/42" });
    expect(turn.navigateTo).toBe("/task/42");
    expect(turn.items.filter((i) => i.kind === "ui").length).toBe(2);
  });

  test("zgoda zamyka tekst i zostawia turę w stanie oczekiwania", () => {
    let turn = apply(EMPTY, { type: "token", text: "Zatwierdzam." });
    turn = apply(turn, {
      type: "confirm",
      confirm: { id: 3, tool: "task_decide", title: "Rozstrzygnięcie", preview: null, cost_usd: null },
      tool: "task_decide",
      args: { id: 1 },
      tool_call_id: "c2",
    });
    turn = apply(turn, { type: "done", state: "waiting" });
    expect(turn.items.map((i) => i.kind)).toEqual(["agent", "confirm"]);
    expect(turn.waiting).toBe(true);
  });

  test("zużycie sumuje się przez tury", () => {
    let turn = apply(EMPTY, { type: "usage", input_tokens: 100, output_tokens: 10, usd: 0.001, model: "m" });
    turn = apply(turn, { type: "usage", input_tokens: 50, output_tokens: 5, usd: 0.0005, model: "m" });
    expect(turn.usage).toEqual({ input_tokens: 150, output_tokens: 15, usd: 0.0015 });
  });
});

describe("historia z serwera", () => {
  test("wiadomości, wywołania z wynikami i zaległe zgody w kolejności", () => {
    const data: SessionData = {
      session: { id: 1, model: "openai:gpt-5.6-terra", title: "t" },
      messages: [
        { id: 10, role: "operator", content: "co z danymi?", tool_calls: null, input_tokens: 0, output_tokens: 0 },
        {
          id: 11,
          role: "agent",
          content: "",
          tool_calls: [{ id: "c1", name: "db_health", args: {} }],
          input_tokens: 10,
          output_tokens: 1,
        },
        { id: 12, role: "agent", content: "Bez problemów.", tool_calls: null, input_tokens: 10, output_tokens: 3 },
      ],
      tool_calls: [
        { id: 1, message_id: 11, tool: "db_health", arguments: {}, result_summary: '{"checks":[]}', is_error: false, confirmation_id: null },
      ],
      usage: { input_tokens: 20, output_tokens: 4, turns: 2 },
      pending: [{ id: 5, tool: "db_execute", title: "Surowy zapis SQL", preview: "UPDATE …", cost_usd: null }],
      running: false,
    };
    const items = itemsOf(data);
    expect(items.map((i) => i.kind)).toEqual(["operator", "tool", "agent", "confirm"]);
    const tool = items[1];
    expect(tool.kind === "tool" && tool.result?.text).toBe('{"checks":[]}');
    const confirm = items[3];
    expect(confirm.kind === "confirm" && confirm.confirmation.id).toBe(5);
  });
});
