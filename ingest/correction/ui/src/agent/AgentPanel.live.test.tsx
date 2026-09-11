import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { AgentPanel } from "./AgentPanel";
import type { AgentEvent } from "./agentClient";
import * as navigate from "./navigate";

/** Panel z prawdziwym agentem za atrapą `fetch`: konfiguracja, sesja, strumień SSE. */

vi.mock("./navigate", () => ({ assign: vi.fn(), open: vi.fn() }));

const CONFIG = {
  models: [
    { id: "openai:gpt-5.6-luna", label: "luna", input_usd: 0.2, output_usd: 1.2, unavailable: null },
    { id: "openai:gpt-5.6-terra", label: "terra", input_usd: 2, output_usd: 12, unavailable: null },
    { id: "openai:gpt-5.6-sol", label: "sol", input_usd: 4, output_usd: 20, unavailable: null },
  ],
  default: "openai:gpt-5.6-terra",
  mode: "live",
  reason: null,
};

function sse(events: AgentEvent[]): Response {
  const text = events.map((e) => `event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`).join("");
  return new Response(new TextEncoder().encode(text), {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

type Route = (url: string, init?: RequestInit) => Response | undefined;

function stubFetch(routes: Route[]) {
  const calls: { url: string; body: unknown }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : null });
    for (const route of routes) {
      const found = route(url, init);
      if (found) return found;
    }
    return json({ detail: `brak trasy w teście: ${url}` }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

const config: Route = (url) => (url === "/api/agent/config" ? json(CONFIG) : undefined);
const newSession: Route = (url, init) =>
  url === "/api/agent/sessions" && init?.method === "POST"
    ? json({ id: 7, model: JSON.parse(String(init.body)).model })
    : undefined;

function openPanel() {
  window.localStorage.setItem("correction.agentPanel.state.v1", "expanded");
}

async function ask(text: string) {
  const user = userEvent.setup();
  const box = await screen.findByLabelText("Wiadomość do agenta");
  await waitFor(() => expect(box.hasAttribute("disabled")).toBe(false));
  await user.type(box, text);
  await user.click(screen.getByRole("button", { name: "Wyślij" }));
  return user;
}

describe("panel na żywo", () => {
  beforeEach(openPanel);
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  test("wybór modelu ma dokładnie trzy pozycje, a wybrany jedzie w nowej sesji", async () => {
    const calls = stubFetch([
      config,
      newSession,
      (url) => (url.endsWith("/messages") ? sse([{ type: "done", state: "finished" }]) : undefined),
    ]);
    render(<AgentPanel />);

    const picker = (await screen.findByLabelText("Model agenta")) as HTMLSelectElement;
    expect(picker.options.length).toBe(3);
    expect(picker.value).toBe("openai:gpt-5.6-terra");
    const user = userEvent.setup();
    await user.selectOptions(picker, "openai:gpt-5.6-luna");
    await ask("hej");

    await waitFor(() =>
      expect(window.localStorage.getItem("correction.agentPanel.session.v1")).toBe("7"),
    );
    const created = calls.find((c) => c.url === "/api/agent/sessions");
    expect(created?.body).toMatchObject({ model: "openai:gpt-5.6-luna", screen: { path: "/" } });
  });

  test("wywołanie narzędzia to chip, tekst dopisuje się, przejście dopiero po done", async () => {
    stubFetch([
      config,
      newSession,
      (url) =>
        url.endsWith("/messages")
          ? sse([
              { type: "tool_call", id: "c1", name: "ui_navigate", args: { target: { view: "inspect" } } },
              { type: "tool_result", id: "c1", name: "ui_navigate", is_error: false, text: "{}", ui: { action: "navigate", url: "/inspect" } },
              { type: "ui", action: "navigate", url: "/inspect" },
              { type: "token", text: "Otwieram **inspektor**." },
              { type: "usage", input_tokens: 900, output_tokens: 20, usd: 0.002, model: "openai:gpt-5.6-terra" },
              { type: "done", state: "finished" },
            ])
          : undefined,
    ]);
    render(<AgentPanel />);
    await ask("pokaż inspektor");

    await waitFor(() => expect(document.querySelector('[data-tool="ui_navigate"]')).not.toBeNull());
    await waitFor(() => expect(screen.getByText("inspektor")).toBeDefined());
    expect(document.querySelector(".agent-ui")?.getAttribute("href")).toBe("/inspect");
    await waitFor(() => expect(navigate.assign).toHaveBeenCalledWith("/inspect"));
    expect(navigate.assign).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/920 tok/)).toBeDefined();
  });

  test("zgoda: karta z podglądem, „Wykonaj” wysyła decyzję i wznawia odpowiedź", async () => {
    const calls = stubFetch([
      config,
      newSession,
      (url) =>
        url.endsWith("/messages")
          ? sse([
              { type: "tool_call", id: "c2", name: "task_decide", args: { id: 1, action: "approve" } },
              {
                type: "confirm",
                confirm: { id: 3, tool: "task_decide", title: "Rozstrzygnięcie zadania #1", preview: "pending → approve", cost_usd: null },
                tool: "task_decide",
                args: { id: 1, action: "approve" },
                tool_call_id: "c2",
              },
              { type: "done", state: "waiting" },
            ])
          : undefined,
      (url) =>
        url.endsWith("/confirmations/3")
          ? sse([
              { type: "tool_result", id: "c2", name: "task_decide", is_error: false, text: '{"review_status":"approved"}', ui: null },
              { type: "token", text: "Zatwierdzone." },
              { type: "done", state: "finished" },
            ])
          : undefined,
    ]);
    render(<AgentPanel />);
    const user = await ask("zatwierdź");

    const card = await screen.findByText("Rozstrzygnięcie zadania #1");
    const box = card.closest(".agent-confirm") as HTMLElement;
    expect(within(box).getByText("pending → approve")).toBeDefined();
    // Do decyzji pole pisania jest wolne: człowiek może zapytać, zanim kliknie.
    expect(screen.getByRole("button", { name: "Wyślij" })).toBeDefined();

    await user.click(within(box).getByRole("button", { name: "Wykonaj" }));
    await waitFor(() => expect(screen.getByText("Zatwierdzone.")).toBeDefined());
    expect(calls.find((c) => c.url.endsWith("/confirmations/3"))?.body).toEqual({ decision: "accept" });
    expect(within(box).getByText("Wykonane za zgodą.")).toBeDefined();
    expect(document.querySelector('[data-tool="task_decide"]')?.classList.contains("done")).toBe(true);
  });

  test("po wczytaniu strony rozmowa wraca z serwera", async () => {
    window.localStorage.setItem("correction.agentPanel.session.v1", "7");
    stubFetch([
      config,
      (url) =>
        url === "/api/agent/sessions/7"
          ? json({
              session: { id: 7, model: "openai:gpt-5.6-luna", title: "co z danymi?" },
              messages: [
                { id: 1, role: "operator", content: "co z danymi?", tool_calls: null, input_tokens: 0, output_tokens: 0 },
                { id: 2, role: "agent", content: "Wszystko gra.", tool_calls: null, input_tokens: 500, output_tokens: 20 },
              ],
              tool_calls: [],
              usage: { input_tokens: 500, output_tokens: 20, turns: 1 },
              pending: [],
              running: false,
            })
          : undefined,
    ]);
    render(<AgentPanel />);

    await waitFor(() => expect(screen.getByText("co z danymi?")).toBeDefined());
    expect(screen.getByText("Wszystko gra.")).toBeDefined();
    expect((screen.getByLabelText("Model agenta") as HTMLSelectElement).value).toBe("openai:gpt-5.6-luna");
    expect(screen.getByText(/520 tok/)).toBeDefined();
  });

  test("sesja, której serwer nie zna, znika z pamięci", async () => {
    window.localStorage.setItem("correction.agentPanel.session.v1", "99");
    stubFetch([config, (url) => (url === "/api/agent/sessions/99" ? json({ detail: "nie ma" }, 404) : undefined)]);
    render(<AgentPanel />);
    await waitFor(() => expect(window.localStorage.getItem("correction.agentPanel.session.v1")).toBeNull());
  });
});

describe("panel bez serwera agenta", () => {
  beforeEach(openPanel);
  afterEach(() => vi.unstubAllGlobals());

  test("brak konfiguracji znaczy makietę, nie pusty panel", async () => {
    stubFetch([]);
    render(<AgentPanel />);
    await waitFor(() => expect(screen.getByText("makieta")).toBeDefined());
    expect(screen.queryByLabelText("Model agenta")).toBeNull();
  });
});
