import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { mockReply, streamMockReply } from "./mockAgent";

describe("makieta odpowiedzi", () => {
  test("to samo pytanie w tej samej turze daje tę samą odpowiedź", () => {
    // Makieta, która przy każdym odświeżeniu mówi co innego, jest nie do pokazania.
    expect(mockReply("ile progów?", 0)).toBe(mockReply("ile progów?", 0));
  });

  test("kolejne tury dają różne odpowiedzi", () => {
    const rozne = new Set([0, 1, 2, 3].map((turn) => mockReply("pytanie", turn)));
    expect(rozne.size).toBeGreaterThan(1);
  });
});

describe("strumień", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  test("tekst przychodzi kawałkami, w kolejności, aż do całości", () => {
    const chunks: string[] = [];
    let done: string | null = null;
    streamMockReply("abcdefghij", {
      interval: 10,
      chunkSize: 3,
      onChunk: (soFar) => chunks.push(soFar),
      onDone: (full) => { done = full; },
    });

    vi.advanceTimersByTime(100);
    expect(chunks).toEqual(["abc", "abcdef", "abcdefghi", "abcdefghij"]);
    expect(done).toBe("abcdefghij");
  });

  test("po zatrzymaniu nie przychodzi już nic", () => {
    const chunks: string[] = [];
    const stream = streamMockReply("abcdefghij", {
      interval: 10,
      chunkSize: 3,
      onChunk: (soFar) => chunks.push(soFar),
      onDone: () => { throw new Error("strumien dokonczyl sie mimo zatrzymania"); },
    });

    vi.advanceTimersByTime(10);
    stream.stop();
    vi.advanceTimersByTime(1000);
    expect(chunks).toEqual(["abc"]);
  });
});
