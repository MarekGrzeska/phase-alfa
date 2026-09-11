/** Elementy rozmowy i to, jak zdarzenia strumienia je zmieniają — bez Reacta,
 *  żeby dało się sprawdzić kolejność i sklejanie bez renderowania panelu. */

import type { AgentEvent, Confirmation, SessionData, UiAction } from "./agentClient";

export type Item =
  | { readonly kind: "operator"; readonly id: number; readonly text: string }
  | { readonly kind: "agent"; readonly id: number; readonly text: string }
  | {
      readonly kind: "tool";
      readonly id: number;
      readonly callId: string;
      readonly name: string;
      readonly args: unknown;
      readonly result: { readonly text: string; readonly isError: boolean } | null;
    }
  | {
      readonly kind: "confirm";
      readonly id: number;
      readonly confirmation: Confirmation;
      readonly tool: string;
      readonly args: unknown;
      readonly state: "pending" | "deciding" | "accepted" | "rejected";
    }
  | { readonly kind: "ui"; readonly id: number; readonly action: UiAction }
  | { readonly kind: "error"; readonly id: number; readonly text: string };

export interface Usage {
  readonly input_tokens: number;
  readonly output_tokens: number;
  readonly usd: number;
}

export const NO_USAGE: Usage = { input_tokens: 0, output_tokens: 0, usd: 0 };

let counter = 1;
export function nextId(): number {
  return counter++;
}

/** Stan tury w trakcie strumienia: elementy, tekst, który się pisze, i zaległa nawigacja. */
export interface Turn {
  readonly items: readonly Item[];
  readonly partial: string | null;
  readonly navigateTo: string | null;
  readonly usage: Usage;
  readonly waiting: boolean;
}

export function flush(turn: Turn): Turn {
  if (turn.partial === null || turn.partial === "") {
    return { ...turn, partial: null };
  }
  return {
    ...turn,
    items: [...turn.items, { kind: "agent", id: nextId(), text: turn.partial }],
    partial: null,
  };
}

/** Jedno zdarzenie → nowy stan tury. Tekst przed wywołaniem narzędzia staje się
 *  osobnym dymkiem: odpowiedź „sprawdzę to" i odpowiedź po sprawdzeniu to dwie rzeczy. */
export function apply(turn: Turn, event: AgentEvent): Turn {
  switch (event.type) {
    case "token":
      return { ...turn, partial: (turn.partial ?? "") + event.text };
    case "tool_call": {
      const flushed = flush(turn);
      return {
        ...flushed,
        partial: "",
        items: [
          ...flushed.items,
          { kind: "tool", id: nextId(), callId: event.id, name: event.name, args: event.args, result: null },
        ],
      };
    }
    case "tool_result":
      return {
        ...turn,
        items: turn.items.map((item) =>
          item.kind === "tool" && item.callId === event.id
            ? { ...item, result: { text: event.text, isError: event.is_error } }
            : item,
        ),
      };
    case "ui": {
      const { type: _type, ...action } = event;
      return {
        ...turn,
        items: [...turn.items, { kind: "ui", id: nextId(), action }],
        navigateTo: action.action === "navigate" && action.url ? action.url : turn.navigateTo,
      };
    }
    case "confirm": {
      const flushed = flush(turn);
      return {
        ...flushed,
        partial: "",
        items: [
          ...flushed.items,
          {
            kind: "confirm",
            id: nextId(),
            confirmation: event.confirm,
            tool: event.tool,
            args: event.args,
            state: "pending",
          },
        ],
      };
    }
    case "usage":
      return {
        ...turn,
        usage: {
          input_tokens: turn.usage.input_tokens + event.input_tokens,
          output_tokens: turn.usage.output_tokens + event.output_tokens,
          usd: turn.usage.usd + event.usd,
        },
      };
    case "done":
      return { ...flush(turn), waiting: event.state === "waiting" };
    case "error":
      return {
        ...flush(turn),
        items: [...flush(turn).items, { kind: "error", id: nextId(), text: event.message }],
      };
    default:
      return turn;
  }
}

export function decide(items: readonly Item[], confirmationId: number, state: "deciding" | "accepted" | "rejected"): Item[] {
  return items.map((item) =>
    item.kind === "confirm" && item.confirmation.id === confirmationId ? { ...item, state } : item,
  );
}

/** Historia z serwera → elementy. Wynik narzędzia dopina się po wierszu wiadomości
 *  i kolejności wywołań — dziennik nie zna id wywołania po stronie modelu. */
export function itemsOf(data: SessionData): Item[] {
  const out: Item[] = [];
  const results = new Map<number, typeof data.tool_calls[number][]>();
  for (const call of data.tool_calls) {
    if (call.message_id === null) continue;
    const list = results.get(call.message_id) ?? [];
    list.push(call);
    results.set(call.message_id, list);
  }
  for (const message of data.messages) {
    if (message.role === "operator") {
      out.push({ kind: "operator", id: nextId(), text: message.content });
      continue;
    }
    if (message.role !== "agent") continue;
    if (message.content !== "") {
      out.push({ kind: "agent", id: nextId(), text: message.content });
    }
    const logged = results.get(message.id) ?? [];
    (message.tool_calls ?? []).forEach((call, index) => {
      const row = logged[index];
      out.push({
        kind: "tool",
        id: nextId(),
        callId: call.id,
        name: call.name,
        args: call.args,
        result: row ? { text: row.result_summary ?? "", isError: row.is_error } : null,
      });
    });
  }
  for (const pending of data.pending) {
    out.push({
      kind: "confirm",
      id: nextId(),
      confirmation: pending,
      tool: pending.tool,
      args: null,
      state: "pending",
    });
  }
  return out;
}

export function shortArgs(args: unknown): string {
  if (args === null || args === undefined) return "";
  const text = typeof args === "string" ? args : JSON.stringify(args);
  return text.length > 120 ? text.slice(0, 117) + "…" : text;
}

export function formatUsd(usd: number): string {
  return usd < 0.0001 && usd > 0 ? "<0,0001 $" : `${usd.toFixed(4).replace(".", ",")} $`;
}
