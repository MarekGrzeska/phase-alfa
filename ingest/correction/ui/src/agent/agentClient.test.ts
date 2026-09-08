import { afterEach, describe, expect, test, vi } from "vitest";

import { parseSse, sendMessage } from "./agentClient";
import type { AgentEvent } from "./agentClient";

describe("ramki SSE", () => {
  test("komplet ramek daje zdarzenia, niedomknięta reszta wraca", () => {
    const buffer =
      'event: token\ndata: {"type":"token","text":"a"}\n\n' +
      'event: done\ndata: {"type":"done","state":"finished"}\n\nevent: tok';
    const { events, rest } = parseSse(buffer);
    expect(events.map((e) => e.type)).toEqual(["token", "done"]);
    expect(rest).toBe("event: tok");
  });

  test("ramka bez JSON-a jest błędem w rozmowie, nie wyjątkiem", () => {
    const { events } = parseSse("data: nie json\n\n");
    expect(events[0].type).toBe("error");
  });
});

describe("strumień odpowiedzi", () => {
  afterEach(() => vi.unstubAllGlobals());

  test("zdarzenia przychodzą w kolejności, także gdy ramka jest podzielona między kawałki", async () => {
    const frames =
      'event: token\ndata: {"type":"token","text":"Zad"}\n\n' +
      'event: token\ndata: {"type":"token","text":"anie"}\n\n' +
      'event: done\ndata: {"type":"done","state":"finished"}\n\n';
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode(frames.slice(0, 30)));
        controller.enqueue(encoder.encode(frames.slice(30)));
        controller.close();
      },
    });
    const fetchMock = vi.fn(async () => new Response(body, { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const seen: AgentEvent[] = [];
    await sendMessage(7, "pytanie", { view: "task", path: "/task/1", query: "" }, (e) => seen.push(e), new AbortController().signal);

    expect(seen.map((e) => e.type)).toEqual(["token", "token", "done"]);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/agent/sessions/7/messages");
    expect(JSON.parse(String(init.body))).toEqual({
      text: "pytanie",
      screen: { view: "task", path: "/task/1", query: "" },
    });
  });

  test("odpowiedź bez 200 kończy się błędem z treścią serwera", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ detail: "w tej rozmowie właśnie biegnie odpowiedź" }), { status: 409 })),
    );
    await expect(
      sendMessage(7, "x", { view: null, path: "/", query: "" }, () => undefined, new AbortController().signal),
    ).rejects.toThrow("biegnie odpowiedź");
  });
});
