import { useCallback, useEffect, useRef, useState } from "react";
import type { KeyboardEvent, PointerEvent as ReactPointerEvent } from "react";

import { MessageBody } from "./MessageBody";
import { mockReply, streamMockReply } from "./mockAgent";
import type { MockStream } from "./mockAgent";

/**
 * Panel agenta — kolumna shellu, nie nakładka: rozwinięty ZWĘŻA treść korekty
 * zamiast ją zasłaniać, bo pytanie zadaje się o skan, który się właśnie ogląda.
 * Zwinięty jest szyną na całą wysokość — cały pasek jest przyciskiem, więc nie da
 * się go przeoczyć przy żadnej szerokości okna.
 *
 * Za panelem nie stoi jeszcze żaden agent: odpowiedzi są z `mockAgent`.
 */

const STATE_KEY = "correction.agentPanel.state.v1";
const WIDTH_KEY = "correction.agentPanel.width.v1";
const MIN_WIDTH = 280;
const DEFAULT_WIDTH = 384;

export interface Message {
  readonly id: number;
  readonly author: "operator" | "agent";
  readonly text: string;
}

// Pamięć, która rzuca wyjątkiem (tryb prywatny, zablokowane ciasteczka), nie ma
// prawa zatrzymać ekranu korekty — panel wtedy po prostu niczego nie pamięta.
function readStored(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStored(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
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

export function AgentPanel() {
  const [expanded, setExpandedState] = useState(() => readStored(STATE_KEY) === "expanded");
  const [width, setWidthState] = useState(loadWidth);
  const [messages, setMessages] = useState<readonly Message[]>([]);
  // Odpowiedź, która właśnie się pisze. Osobno od `messages`, bo dopóki leci,
  // renderuje się inaczej — `remend` domyka jej składnię w locie.
  const [streaming, setStreaming] = useState<string | null>(null);
  // Ten sam tekst w referencji: „Przerwij" musi go PRZECZYTAĆ, a czytanie stanu
  // wewnątrz funkcji aktualizującej to efekt uboczny — React w trybie ścisłym
  // woła ją dwa razy i urwana odpowiedź lądowała w rozmowie podwójnie.
  const partial = useRef<string | null>(null);
  const stream = useRef<MockStream | null>(null);
  const nextId = useRef(1);
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

  // Szerokość wybrana w szerokim oknie nie jest szerokością w wąskim — pytamy
  // o nią ponownie, zamiast ją przeliczać: ograniczenie zna aktualne okno.
  useEffect(() => {
    const reclamp = () => setWidthState((current) => clampWidth(current, window.innerWidth));
    window.addEventListener("resize", reclamp);
    return () => window.removeEventListener("resize", reclamp);
  }, []);

  // Strumień przeżyłby odmontowanie panelu i pisał do stanu, którego już nie ma.
  useEffect(() => () => stream.current?.stop(), []);

  // Rozmowa dopisuje się na dole, więc widok jedzie za nią — inaczej odpowiedź
  // rośnie poza ekranem i trzeba za nią przewijać ręcznie.
  useEffect(() => {
    const box = transcript.current;
    if (box) {
      box.scrollTop = box.scrollHeight;
    }
  }, [messages, streaming]);

  function send(text: string): void {
    const question = text.trim();
    if (question === "" || streaming !== null) {
      return;
    }
    const turn = messages.length;
    setMessages((current) => [
      ...current,
      { id: nextId.current++, author: "operator", text: question },
    ]);
    partial.current = "";
    setStreaming("");
    stream.current = streamMockReply(mockReply(question, turn), {
      onChunk: (soFar) => {
        partial.current = soFar;
        setStreaming(soFar);
      },
      onDone: (full) => {
        stream.current = null;
        partial.current = null;
        setStreaming(null);
        setMessages((current) => [
          ...current,
          { id: nextId.current++, author: "agent", text: full },
        ]);
      },
    });
  }

  function stop(): void {
    stream.current?.stop();
    stream.current = null;
    // To, co zdążyło przyjść, zostaje w rozmowie: urwana odpowiedź jest
    // odpowiedzią, a znikająca po naciśnięciu „Przerwij" wygląda na błąd.
    const said = partial.current;
    partial.current = null;
    setStreaming(null);
    if (said !== null && said !== "") {
      setMessages((current) => [...current, { id: nextId.current++, author: "agent", text: said }]);
    }
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

  return (
    <aside
      id="agent-panel"
      className="agent"
      data-state="expanded"
      aria-label="Agent"
      // Szerokość ze stanu, a nie z klasy: nie ma klasy na liczbę, którą wybrał
      // człowiek przeciągnięciem uchwytu.
      style={{ width }}
    >
      <ResizeHandle width={width} onResize={setWidth} />

      <div className="agent-head">
        <strong>Agent</strong>
        <span className="tag">makieta</span>
        <span className="spacer"></span>
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
        {messages.length === 0 && streaming === null && (
          <div className="agent-empty">
            <p>Tu pojawi się rozmowa z agentem.</p>
            <p>Odpowiedzi są na razie makietą — prawdziwego agenta jeszcze nie podłączono.</p>
          </div>
        )}
        {messages.map((message) => (
          <div key={message.id} className={`agent-turn ${message.author === "agent" ? "model" : "operator"}`}>
            {message.author === "agent" ? (
              <MessageBody text={message.text} />
            ) : (
              <p className="agent-said">{message.text}</p>
            )}
          </div>
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

      <Composer onSend={send} onStop={stop} busy={streaming !== null} />
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
    // Korektor napisze dziesięć pytań jednozdaniowych, zanim napisze akapit.
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
    // Przechwycony, żeby wskaźnik, który zaraz zjedzie z uchwytu — a zjedzie,
    // bo panel rusza się pod nim — dalej meldował ruchy tutaj.
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
    // jego szerokość JEST tą odległością, a przyrost dryfowałby o to, co przy
    // ostatniej klatce zjadło ograniczenie.
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
