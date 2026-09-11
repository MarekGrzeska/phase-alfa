import { useCallback, useEffect, useRef, useState } from "react";
import type { KeyboardEvent, PointerEvent as ReactPointerEvent } from "react";

import { MessageBody } from "./MessageBody";
import { ModelPicker } from "./ModelPicker";
import { TranscriptItem } from "./Transcript";
import { createSession, fetchConfig, fetchSession, sendDecision, sendMessage } from "./agentClient";
import type { AgentConfig, AgentEvent } from "./agentClient";
import { NO_USAGE, apply, decide, flush, itemsOf, nextId } from "./items";
import type { Item, Turn, Usage } from "./items";
import { mockReply, streamMockReply } from "./mockAgent";
import type { MockStream } from "./mockAgent";
import * as navigate from "./navigate";
import { currentScreen } from "./screenContext";

/**
 * Panel agenta — kolumna shellu, nie nakładka: rozwinięty ZWĘŻA treść korekty
 * zamiast ją zasłaniać, bo pytanie zadaje się o skan, który się właśnie ogląda.
 * Zwinięty jest szyną na całą wysokość — cały pasek jest przyciskiem.
 *
 * Rozmowa żyje na serwerze (`/api/agent/sessions`): nawigacja przeładowuje
 * stronę, więc panel pamięta tylko id sesji i po wczytaniu odtwarza historię.
 * Bez klucza API (albo z `AGENT_MODEL=mock`) wraca makieta z `mockAgent`.
 */

const STATE_KEY = "correction.agentPanel.state.v1";
const WIDTH_KEY = "correction.agentPanel.width.v1";
const SESSION_KEY = "correction.agentPanel.session.v1";
const MODEL_KEY = "correction.agentPanel.model.v1";
const MIN_WIDTH = 280;
const DEFAULT_WIDTH = 384;
const FOCUS_CLASS = "agent-focus";

// Pamięć, która rzuca wyjątkiem (tryb prywatny, zablokowane ciasteczka), nie ma
// prawa zatrzymać ekranu korekty — panel wtedy po prostu niczego nie pamięta.
function readStored(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStored(key: string, value: string | null): void {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    /* trudno */
  }
}

export function maxWidth(windowWidth: number): number {
  return Math.max(MIN_WIDTH, Math.round(windowWidth * 0.6));
}

export function clampWidth(width: number, windowWidth: number): number {
  return Math.min(Math.max(width, MIN_WIDTH), maxWidth(windowWidth));
}

function loadWidth(): number {
  const raw = Number(readStored(WIDTH_KEY));
  if (!Number.isFinite(raw) || raw <= 0) {
    return DEFAULT_WIDTH;
  }
  return clampWidth(raw, window.innerWidth);
}

/** Pole formularza na otwartej stronie: przewiń, zaznacz na chwilę, ustaw kursor. */
export function focusField(name: string): boolean {
  const field = document.querySelector<HTMLElement>(`[name="${CSS.escape(name)}"]`);
  if (field === null) return false;
  field.scrollIntoView?.({ block: "center" });
  field.classList.add(FOCUS_CLASS);
  window.setTimeout(() => field.classList.remove(FOCUS_CLASS), 2500);
  field.focus?.();
  return true;
}

const EMPTY_TURN: Turn = { items: [], partial: null, navigateTo: null, usage: NO_USAGE, waiting: false };

type Mode = "loading" | "live" | "mock";

export function AgentPanel() {
  const [expanded, setExpandedState] = useState(() => readStored(STATE_KEY) === "expanded");
  const [width, setWidthState] = useState(loadWidth);
  const [mode, setMode] = useState<Mode>("loading");
  const [config, setConfig] = useState<AgentConfig | null>(null);
  const [model, setModelState] = useState<string>(() => readStored(MODEL_KEY) ?? "");
  const [sessionId, setSessionIdState] = useState<number | null>(() => {
    const raw = Number(readStored(SESSION_KEY));
    return Number.isInteger(raw) && raw > 0 ? raw : null;
  });
  const [items, setItems] = useState<readonly Item[]>([]);
  // Odpowiedź, która właśnie się pisze. Osobno od `items`, bo dopóki leci,
  // renderuje się inaczej — `remend` domyka jej składnię w locie.
  const [streaming, setStreaming] = useState<string | null>(null);
  const [usage, setUsage] = useState<Usage>(NO_USAGE);
  // Stan tury w referencji: zdarzenia przychodzą szybciej niż React renderuje,
  // a każde ma widzieć skutek poprzedniego.
  const turn = useRef<Turn>(EMPTY_TURN);
  const abort = useRef<AbortController | null>(null);
  const mockStream = useRef<MockStream | null>(null);
  const partial = useRef<string | null>(null);
  const transcript = useRef<HTMLDivElement | null>(null);

  const setWidth = useCallback((next: number) => {
    const clamped = clampWidth(next, window.innerWidth);
    setWidthState(clamped);
    writeStored(WIDTH_KEY, String(clamped));
  }, []);

  const setExpanded = useCallback((next: boolean) => {
    setExpandedState(next);
    writeStored(STATE_KEY, next ? "expanded" : "collapsed");
  }, []);

  const setSessionId = useCallback((next: number | null) => {
    setSessionIdState(next);
    writeStored(SESSION_KEY, next === null ? null : String(next));
  }, []);

  const setModel = useCallback((next: string) => {
    setModelState(next);
    writeStored(MODEL_KEY, next);
  }, []);

  // Konfiguracja raz na wczytanie strony; porażka (serwer bez agenta, strona
  // testowa) znaczy makietę, nie pusty panel. Obietnica w referencji: pytanie
  // zadane, zanim odpowiedź przyszła, czeka na nią, zamiast trafić w wyłączone pole.
  const ready = useRef<Promise<Mode> | null>(null);
  useEffect(() => {
    let current = true;
    ready.current = fetchConfig()
      .then((next): Mode => {
        if (!current) return next.mode;
        setConfig(next);
        setMode(next.mode);
        setModelState((chosen) =>
          next.models.some((m) => m.id === chosen && m.unavailable === null) ? chosen : next.default,
        );
        return next.mode;
      })
      .catch((): Mode => {
        if (current) setMode("mock");
        return "mock";
      });
    return () => {
      current = false;
    };
  }, []);

  // Historia z serwera po każdym wczytaniu strony — także po nawigacji, którą
  // wywołał sam agent. Tylko dla sesji zapamiętanej PRZED wczytaniem: tę założoną
  // na tej stronie panel już ma w całości. Sesja, której serwer nie zna
  // (skasowana baza), po prostu znika.
  const restore = useRef(sessionId);
  useEffect(() => {
    const wanted = restore.current;
    if (mode !== "live" || wanted === null) return;
    let current = true;
    fetchSession(wanted)
      .then((data) => {
        if (!current) return;
        setItems(itemsOf(data));
        setModelState(data.session.model);
        setUsage({
          input_tokens: data.usage.input_tokens,
          output_tokens: data.usage.output_tokens,
          // Kwotę liczy serwer z cennika; panel jej nie zeruje, bo rozmowa za
          // cztery centy wyglądała po odświeżeniu na darmową.
          usd: data.usage.usd ?? 0,
        });
      })
      .catch(() => {
        if (current) setSessionId(null);
      });
    return () => {
      current = false;
    };
  }, [mode, setSessionId]);

  useEffect(() => {
    const reclamp = () => setWidthState((current) => clampWidth(current, window.innerWidth));
    window.addEventListener("resize", reclamp);
    return () => window.removeEventListener("resize", reclamp);
  }, []);

  useEffect(
    () => () => {
      abort.current?.abort();
      mockStream.current?.stop();
    },
    [],
  );

  useEffect(() => {
    const box = transcript.current;
    if (box) {
      box.scrollTop = box.scrollHeight;
    }
  }, [items, streaming]);

  const busy = streaming !== null;

  function render(next: Turn): void {
    turn.current = next;
    setItems(next.items);
    setStreaming(next.partial);
  }

  function onEvent(event: AgentEvent): void {
    const next = apply(turn.current, event);
    render(next);
    if (event.type === "ui" && event.action === "focus" && event.name) {
      focusField(event.name);
    }
    if (event.type === "ui" && event.action === "open" && event.url) {
      navigate.open(event.url);
    }
    if (event.type === "usage") {
      setUsage((total) => ({
        input_tokens: total.input_tokens + event.input_tokens,
        output_tokens: total.output_tokens + event.output_tokens,
        usd: total.usd + event.usd,
      }));
    }
  }

  function finish(): void {
    const done = flush(turn.current);
    turn.current = { ...done, navigateTo: null, waiting: false };
    setItems(done.items);
    setStreaming(null);
    abort.current = null;
    // Przejście dopiero teraz: przeładowanie w połowie odpowiedzi urwałoby ją,
    // a rozmowa i tak jest na serwerze — po wczytaniu strony panel ją odtworzy.
    if (done.navigateTo !== null) {
      navigate.assign(done.navigateTo);
    }
  }

  async function runLive(start: (signal: AbortSignal) => Promise<void>): Promise<void> {
    const controller = new AbortController();
    abort.current = controller;
    setStreaming("");
    try {
      await start(controller.signal);
    } catch (error) {
      if (!controller.signal.aborted) {
        const message = error instanceof Error ? error.message : String(error);
        render(apply(turn.current, { type: "error", message }));
      }
    } finally {
      finish();
    }
  }

  async function sendLive(question: string): Promise<void> {
    const screen = currentScreen();
    turn.current = {
      ...turn.current,
      items: [...turn.current.items, { kind: "operator", id: nextId(), text: question }],
      partial: "",
      navigateTo: null,
      waiting: false,
    };
    render(turn.current);
    await runLive(async (signal) => {
      let id = sessionId;
      if (id === null) {
        const created = await createSession(model, screen);
        id = created.id;
        setSessionId(id);
      }
      await sendMessage(id, question, screen, onEvent, signal);
    });
  }

  function sendMock(question: string): void {
    const ordinal = turn.current.items.length;
    turn.current = {
      ...turn.current,
      items: [...turn.current.items, { kind: "operator", id: nextId(), text: question }],
      partial: "",
    };
    render(turn.current);
    partial.current = "";
    mockStream.current = streamMockReply(mockReply(question, ordinal), {
      onChunk: (soFar) => {
        partial.current = soFar;
        turn.current = { ...turn.current, partial: soFar };
        setStreaming(soFar);
      },
      onDone: () => {
        mockStream.current = null;
        partial.current = null;
        finish();
      },
    });
  }

  function dispatch(how: Mode, question: string): void {
    if (how === "live") {
      void sendLive(question);
    } else {
      sendMock(question);
    }
  }

  function send(text: string): void {
    const question = text.trim();
    if (question === "" || busy) {
      return;
    }
    if (mode === "loading") {
      setStreaming("");
      void (ready.current ?? Promise.resolve<Mode>("mock")).then((how) => dispatch(how, question));
      return;
    }
    dispatch(mode, question);
  }

  function stop(): void {
    if (mode === "live") {
      abort.current?.abort();
      return;
    }
    mockStream.current?.stop();
    mockStream.current = null;
    // To, co zdążyło przyjść, zostaje w rozmowie: urwana odpowiedź jest
    // odpowiedzią, a znikająca po naciśnięciu „Przerwij" wygląda na błąd.
    turn.current = { ...turn.current, partial: partial.current };
    partial.current = null;
    finish();
  }

  function onDecide(confirmationId: number, decision: "accept" | "reject"): void {
    if (busy || sessionId === null) return;
    turn.current = { ...turn.current, items: decide(turn.current.items, confirmationId, "deciding") };
    render(turn.current);
    void runLive(async (signal) => {
      await sendDecision(sessionId, confirmationId, decision, onEvent, signal);
      turn.current = {
        ...turn.current,
        items: decide(turn.current.items, confirmationId, decision === "accept" ? "accepted" : "rejected"),
      };
    });
  }

  function newConversation(): void {
    if (busy) return;
    abort.current?.abort();
    turn.current = EMPTY_TURN;
    setItems([]);
    setStreaming(null);
    setUsage(NO_USAGE);
    setSessionId(null);
  }

  function changeModel(next: string): void {
    if (next === model) return;
    // Model jest cechą sesji: zmiana zakłada nową rozmowę, żeby koszt i historia
    // nie mieszały dwóch cenników.
    if (items.length > 0 && !window.confirm(`Zacząć nową rozmowę z modelem ${next}?`)) {
      return;
    }
    setModel(next);
    newConversation();
  }

  if (!expanded) {
    return (
      <aside className="agent" data-state="collapsed" aria-label="Agent">
        <button
          type="button"
          className="agent-rail"
          onClick={() => setExpanded(true)}
          aria-label="Otwórz panel agenta"
          aria-expanded={false}
          aria-controls="agent-panel"
        >
          <span className="label">Agent</span>
          <span aria-hidden="true">‹</span>
        </button>
      </aside>
    );
  }

  const tokens = usage.input_tokens + usage.output_tokens;

  return (
    <aside id="agent-panel" className="agent" data-state="expanded" data-mode={mode} aria-label="Agent" style={{ width }}>
      <ResizeHandle width={width} onResize={setWidth} />

      <div className="agent-head">
        <strong>Agent</strong>
        {mode === "live" && config !== null ? (
          <ModelPicker models={config.models} value={model} onChange={changeModel} disabled={busy} />
        ) : mode === "mock" ? (
          <span className="tag" title={config?.reason ?? "brak połączenia z serwerem agenta"}>
            makieta
          </span>
        ) : null}
        <span className="spacer"></span>
        {mode === "live" && (
          <>
            {tokens > 0 && (
              <span className="small agent-usage" title="tokeny wejścia + wyjścia w tej rozmowie">
                {tokens.toLocaleString("pl-PL")} tok
                {usage.usd > 0 ? ` · ${usage.usd.toFixed(4).replace(".", ",")} $` : ""}
              </span>
            )}
            <button type="button" onClick={newConversation} disabled={busy} title="Nowa rozmowa">
              +
            </button>
          </>
        )}
        <button
          type="button"
          onClick={() => setExpanded(false)}
          aria-label="Zwiń panel agenta"
          aria-expanded
          aria-controls="agent-panel"
        >
          ›
        </button>
      </div>

      <div className="agent-transcript" ref={transcript}>
        {items.length === 0 && streaming === null && (
          <div className="agent-empty">
            <p>Tu pojawi się rozmowa z agentem.</p>
            {mode === "mock" ? (
              <p>Odpowiedzi są makietą — {config?.reason ?? "serwer agenta nie odpowiada"}.</p>
            ) : (
              <p>Agent widzi, na co patrzysz, czyta bazę i dokumentację; zmiany w korpusie wykonuje dopiero po Twojej zgodzie.</p>
            )}
          </div>
        )}
        {items.map((item) => (
          <TranscriptItem key={item.id} item={item} onDecide={onDecide} busy={busy} />
        ))}
        {streaming !== null && (
          <div className="agent-turn model" aria-busy="true">
            {streaming === "" ? (
              <p className="agent-waiting">Agent pisze…</p>
            ) : (
              <MessageBody text={streaming} streaming />
            )}
          </div>
        )}
      </div>

      <Composer onSend={send} onStop={stop} busy={busy} />
    </aside>
  );
}

function Composer({
  onSend,
  onStop,
  busy,
}: {
  onSend: (text: string) => void;
  onStop: () => void;
  busy: boolean;
}) {
  const [draft, setDraft] = useState("");

  function submit(): void {
    if (busy || draft.trim() === "") {
      return;
    }
    onSend(draft);
    setDraft("");
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    // Enter wysyła, Shift+Enter łamie linię: to okno czatu, nie pole formularza.
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }

  return (
    <form
      className="agent-composer"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <textarea
        rows={2}
        value={draft}
        disabled={busy}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={onKeyDown}
        placeholder={busy ? "Agent odpowiada…" : "Zapytaj agenta…"}
        aria-label="Wiadomość do agenta"
      />
      <div className="row">
        <span className="small">Enter wysyła · Shift+Enter nowa linia</span>
        {busy ? (
          <button type="button" className="danger" onClick={onStop}>
            Przerwij
          </button>
        ) : (
          <button type="submit" className="primary" disabled={draft.trim() === ""}>
            Wyślij
          </button>
        )}
      </div>
    </form>
  );
}

/**
 * Lewa krawędź panelu, do przeciągania. `separator`, bo to jedyny tutejszy element
 * sterujący bez etykiety. Pozycjonowany absolutnie NA krawędzi: gdyby zajmował
 * miejsce w układzie, przesuwałby kolumnę, której szerokość mierzy.
 */
function ResizeHandle({ width, onResize }: { width: number; onResize: (width: number) => void }) {
  const dragging = useRef(false);

  function onPointerDown(event: ReactPointerEvent<HTMLDivElement>): void {
    dragging.current = true;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    event.preventDefault();
  }

  function stopDragging(): void {
    dragging.current = false;
  }

  function onPointerMove(event: ReactPointerEvent<HTMLDivElement>): void {
    if (!dragging.current) {
      return;
    }
    // Od prawej krawędzi okna, nie z przyrostu: panel jest ostatnią kolumną, więc
    // jego szerokość JEST tą odległością.
    onResize(window.innerWidth - event.clientX);
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>): void {
    const step = event.shiftKey ? 64 : 16;
    if (event.key === "ArrowLeft") onResize(width + step);
    else if (event.key === "ArrowRight") onResize(width - step);
    else if (event.key === "Home") onResize(MIN_WIDTH);
    else if (event.key === "End") onResize(maxWidth(window.innerWidth));
    else return;
    event.preventDefault();
  }

  return (
    <div
      className="agent-resize"
      role="separator"
      aria-orientation="vertical"
      aria-label="Zmien szerokosc panelu agenta"
      aria-valuenow={width}
      aria-valuemin={MIN_WIDTH}
      aria-valuemax={maxWidth(typeof window === "undefined" ? width : window.innerWidth)}
      tabIndex={0}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={stopDragging}
      onPointerCancel={stopDragging}
      onKeyDown={onKeyDown}
    />
  );
}
