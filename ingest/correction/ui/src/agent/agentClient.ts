/** Klient `/api/agent/*`: konfiguracja, sesje, strumień zdarzeń odpowiedzi.
 *
 * Strumień idzie po `fetch` + `ReadableStream`, nie po `EventSource`: ten drugi
 * nie umie POST-a, a wiadomość i kontekst ekranu jadą w treści żądania.
 */

import type { ScreenContext } from "./screenContext";

export interface ModelInfo {
  readonly id: string;
  readonly label: string;
  readonly input_usd: number;
  readonly output_usd: number;
  readonly unavailable: string | null;
}

export interface AgentConfig {
  readonly models: readonly ModelInfo[];
  readonly default: string;
  readonly mode: "live" | "mock";
  readonly reason: string | null;
}

export interface Confirmation {
  readonly id: number;
  readonly tool: string;
  readonly title: string;
  readonly preview: string | null;
  readonly cost_usd: number | null;
  readonly status?: string;
}

export interface UiAction {
  readonly action: "navigate" | "focus" | "open";
  readonly url?: string;
  readonly name?: string;
}

export type AgentEvent =
  | { readonly type: "token"; readonly text: string }
  | { readonly type: "tool_call"; readonly id: string; readonly name: string; readonly args: unknown }
  | {
      readonly type: "tool_result";
      readonly id: string;
      readonly name: string;
      readonly is_error: boolean;
      readonly text: string;
      readonly ui: UiAction | null;
    }
  | ({ readonly type: "ui" } & UiAction)
  | {
      readonly type: "confirm";
      readonly confirm: Confirmation;
      readonly tool: string;
      readonly args: unknown;
      readonly tool_call_id: string;
    }
  | {
      readonly type: "usage";
      readonly input_tokens: number;
      readonly output_tokens: number;
      readonly usd: number;
      readonly model: string;
    }
  | { readonly type: "done"; readonly state: "finished" | "waiting" }
  | { readonly type: "error"; readonly message: string };

export interface StoredMessage {
  readonly id: number;
  readonly role: "operator" | "agent" | "system";
  readonly content: string;
  readonly tool_calls: readonly { id: string; name: string; args: unknown }[] | null;
  readonly input_tokens: number;
  readonly output_tokens: number;
}

export interface StoredToolCall {
  readonly id: number;
  readonly message_id: number | null;
  readonly tool: string;
  readonly arguments: unknown;
  readonly result_summary: string | null;
  readonly is_error: boolean;
  readonly confirmation_id: number | null;
}

export interface SessionData {
  readonly session: { id: number; model: string; title: string | null };
  readonly messages: readonly StoredMessage[];
  readonly tool_calls: readonly StoredToolCall[];
  /** `usd` liczy serwer — cennik jest w Pythonie, a baza trzyma same tokeny. */
  readonly usage: { input_tokens: number; output_tokens: number; turns: number; usd: number };
  readonly pending: readonly Confirmation[];
  readonly running: boolean;
}

async function failure(response: Response): Promise<Error> {
  const detail = await response.json().catch(() => null);
  return new Error(detail?.detail ?? `serwer odpowiedział ${response.status}`);
}

export async function fetchConfig(): Promise<AgentConfig> {
  const response = await fetch("/api/agent/config");
  if (!response.ok) throw await failure(response);
  return (await response.json()) as AgentConfig;
}

export async function createSession(
  model: string,
  screen: ScreenContext,
): Promise<{ id: number; model: string }> {
  const response = await fetch("/api/agent/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model, screen }),
  });
  if (!response.ok) throw await failure(response);
  return (await response.json()) as { id: number; model: string };
}

export async function fetchSession(id: number): Promise<SessionData> {
  const response = await fetch(`/api/agent/sessions/${id}`);
  if (!response.ok) throw await failure(response);
  return (await response.json()) as SessionData;
}

/** Zdarzenia z bufora SSE: komplet ramek zamkniętych pustą linią, reszta wraca. */
export function parseSse(buffer: string): { events: AgentEvent[]; rest: string } {
  const events: AgentEvent[] = [];
  const frames = buffer.split("\n\n");
  const rest = frames.pop() ?? "";
  for (const frame of frames) {
    const data = frame
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n");
    if (data === "") continue;
    try {
      events.push(JSON.parse(data) as AgentEvent);
    } catch {
      events.push({ type: "error", message: `niezrozumiała ramka strumienia: ${data.slice(0, 80)}` });
    }
  }
  return { events, rest };
}

export type OnEvent = (event: AgentEvent) => void;

async function streamEvents(
  url: string,
  body: unknown,
  onEvent: OnEvent,
  signal: AbortSignal,
): Promise<void> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok) throw await failure(response);
  if (response.body === null) throw new Error("serwer nie oddał strumienia");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parsed = parseSse(buffer);
    buffer = parsed.rest;
    for (const event of parsed.events) onEvent(event);
  }
  const tail = parseSse(buffer + "\n\n");
  for (const event of tail.events) onEvent(event);
}

export function sendMessage(
  sessionId: number,
  text: string,
  screen: ScreenContext,
  onEvent: OnEvent,
  signal: AbortSignal,
): Promise<void> {
  return streamEvents(`/api/agent/sessions/${sessionId}/messages`, { text, screen }, onEvent, signal);
}

export function sendDecision(
  sessionId: number,
  confirmationId: number,
  decision: "accept" | "reject",
  onEvent: OnEvent,
  signal: AbortSignal,
): Promise<void> {
  return streamEvents(
    `/api/agent/sessions/${sessionId}/confirmations/${confirmationId}`,
    { decision },
    onEvent,
    signal,
  );
}
